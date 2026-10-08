"""Check the Git publication boundary without printing matched private values.

The default checks every index blob, exactly as it would be committed. Use
--staged for changed index blobs, or --include-untracked to also preview new
nonignored source files. Optional owner identifiers belong in an ignored local
JSON file with {"identifiers": ["..."]}, or a protected file outside the checkout.
This guard complements review; it cannot recognize every form of personal data.
"""

import argparse
import io
import json
import re
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
PRIVATE_ROOTS = {
    "private", "state", "data", "secrets", ".venv", ".tools", ".codex",
    ".codex-remote-attachments", "config/local", "node_modules", "build", "dist",
}
PRIVATE_COMPONENTS = {".ssh", ".aws", ".azure", ".oci", "node_modules", ".gradle"}
PRIVATE_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".db", ".sqlite",
    ".sqlite3", ".apk", ".aab", ".idsig", ".pcm", ".wav", ".m4a", ".mp3",
    ".pdf", ".docx", ".csv", ".xlsx", ".log",
}
PRIVATE_NAMES = {
    "credentials.json", "token.json", "tokens.json", "google-services.json",
    "application_default_credentials.json", "local.properties", "firebase-debug.log",
}
EXAMPLE_USER_NAMES = {"you", "user", "username", "owner", "assistant", "public", "default"}
EXAMPLE_DOMAINS = {"example.com", "example.net", "example.org", "localhost"}
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
WINDOWS_HOME = re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"'<>]+)", re.I)
POSIX_HOME = re.compile(r"(?<![\w/])/(?:Users|home)/([^/\s\"'<>]+)")
RULES = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    ("openai-key", re.compile(r"\bsk-(?:(?:proj|svcacct)-)?[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("stripe-key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b")),
    ("google-oauth-token", re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}\b")),
    ("azure-storage-key", re.compile(r"\bAccountKey=[A-Za-z0-9+/]{40,}={0,2}", re.I)),
    ("jwt-literal", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("whatsapp-identity", re.compile(r"\b[0-9]{7,}(?::[0-9]+)?@(?:s\.whatsapp\.net|lid)\b")),
    ("phone-contact", re.compile(r"(?:tel:|[\"']?(?:phone|mobile|telephone)[\"']?\s*[:=]\s*[\"'])\+?[0-9][0-9 ()-]{8,}[0-9]", re.I)),
)
# Byte-adjacent high characters must not hide ASCII token boundaries in binary
# source assets or compiled archive members.
RULES = tuple((rule, re.compile(pattern.pattern, (pattern.flags & ~re.UNICODE) | re.ASCII))
              for rule, pattern in RULES)
SECRET_LITERAL = re.compile(
    r"\b[\"']?[\w.-]*(?:api[_-]?key|client[_-]?secret|refresh[_-]?token|access[_-]?token|password|secret|token)"
    r"[\"']?\s*[:=]\s*(?:b)?([\"'])([^\r\n\"']{20,})\1", re.I)
SECRET_ENV_LITERAL = re.compile(
    r"^[\w.-]*(?:api[_-]?key|client[_-]?secret|refresh[_-]?token|access[_-]?token|password|secret|token)"
    r"\s*=\s*([A-Za-z0-9/+_=.-]{20,})\s*(?:#.*)?$", re.I | re.M)


@dataclass(frozen=True, order=True)
class Finding:
    file: str
    line: int
    rule: str


class GuardError(Exception):
    """An incomplete check must fail closed, with no credential-bearing details."""


def git(root, *args, input_bytes=None):
    result = subprocess.run(["git", *args], cwd=root, input=input_bytes,
                            capture_output=True, check=False)
    if result.returncode:
        raise GuardError("git-operation-failed")
    return result.stdout


def path_rule(name):
    path = PurePosixPath(name.replace("\\", "/"))
    lower = path.as_posix().lower()
    parts = [part.lower() for part in path.parts]
    if not parts or path.is_absolute() or ".." in parts:
        return "invalid-path"
    if any(lower == root or lower.startswith(root + "/") for root in PRIVATE_ROOTS):
        return "private-path"
    if PRIVATE_COMPONENTS.intersection(parts) or ".generated" in parts:
        return "private-path"
    filename = path.name.lower()
    if filename == ".env" or filename.startswith(".env.") and filename != ".env.example":
        return "environment-file"
    if (filename in PRIVATE_NAMES or "service-account" in filename
            or filename.startswith("client_secret") and filename.endswith(".json")):
        return "credential-file"
    if path.suffix.lower() in PRIVATE_SUFFIXES:
        return "private-artifact"
    return None


def example_domain(domain):
    domain = domain.lower().rstrip(".")
    return (any(domain == example or domain.endswith("." + example) for example in EXAMPLE_DOMAINS)
            or domain.endswith((".invalid", ".test", ".example")))


def content_findings(name, text, identifiers=()):
    findings = set()

    def add(rule, start):
        findings.add(Finding(name, text.count("\n", 0, start) + 1, rule))

    for rule, pattern in RULES:
        for match in pattern.finditer(text):
            add(rule, match.start())
    for match in EMAIL.finditer(text):
        if not example_domain(match.group(1)):
            add("nonexample-email", match.start())
    for pattern in (WINDOWS_HOME, POSIX_HOME):
        for match in pattern.finditer(text):
            if match.group(1).lower() not in EXAMPLE_USER_NAMES:
                add("owner-home-path", match.start())
    for pattern, group in ((SECRET_LITERAL, 2), (SECRET_ENV_LITERAL, 1)):
        for match in pattern.finditer(text):
            value = match.group(group)
            # Obvious prose/placeholders and runtime-generated keys are reusable.
            # Provider-shaped literals are checked above and never exempted here.
            placeholder = re.search(r"example|placeholder|replace|changeme|fixture|dummy|test|demo|\$\{|<|\s", value, re.I)
            classes = sum(bool(re.search(character_class, value)) for character_class in (
                r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
            mixed_alphanumeric = (bool(re.search(r"[0-9]", value))
                                  or bool(re.search(r"[a-z]", value)) and bool(re.search(r"[A-Z]", value)))
            if not placeholder and (classes >= 3 or classes >= 2 and mixed_alphanumeric and len(set(value)) >= 10):
                add("credential-literal", match.start())
    folded = text.casefold()
    for identifier in identifiers:
        start = 0
        while (start := folded.find(identifier.casefold(), start)) != -1:
            add("configured-private-identifier", start)
            start += len(identifier)
    return findings


def scan_blob(name, data, identifiers=(), *, archive_member=False):
    rule = path_rule(name)
    if rule:
        return {Finding(name, 1, rule)}
    if len(data) > MAX_FILE_BYTES:
        return {Finding(name, 1, "file-too-large")}
    # ASCII credential patterns remain visible in binary data and metadata.
    findings = content_findings(name, data.decode("latin1"), identifiers)
    suffix = PurePosixPath(name).suffix.lower()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            findings.update(content_findings(name, data.decode("utf-16"), identifiers))
        except UnicodeError:
            findings.add(Finding(name, 1, "unreadable-content"))
        return findings
    try:
        decoded = data.decode("utf-8-sig")
        if "\x00" not in decoded:
            findings.update(content_findings(name, decoded, identifiers))
            return findings
    except UnicodeError:
        pass
    if not archive_member and suffix == ".jar" and data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = archive.infolist()
                if sum(member.file_size for member in members) > MAX_ARCHIVE_BYTES:
                    return findings | {Finding(name, 1, "archive-too-large")}
                for member in members:
                    if member.is_dir():
                        continue
                    member_name = name + "!/" + member.filename
                    rule = path_rule(member.filename)
                    if rule or member.file_size > MAX_FILE_BYTES:
                        findings.add(Finding(member_name, 1, rule or "file-too-large"))
                        continue
                    content = archive.read(member)
                    if PurePosixPath(member.filename).suffix.lower() == ".class":
                        findings.update(content_findings(member_name, content.decode("latin1"), identifiers))
                    else:
                        findings.update(scan_blob(member_name, content, identifiers, archive_member=True))
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
            findings.add(Finding(name, 1, "unreadable-archive"))
        return findings
    if ((suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
            or (suffix in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8\xff"))
            or (suffix == ".ico" and data.startswith(b"\x00\x00\x01\x00"))):
        return findings
    findings.add(Finding(name, 1, "unsupported-binary"))
    return findings


def load_identifiers(root, filename):
    if filename is None:
        return ()
    filename = filename.resolve()
    try:
        relative = filename.relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = None
    if relative is not None:
        tracked = git(root, "ls-files", "-z", "--", relative)
        result = subprocess.run(["git", "check-ignore", "--no-index", "-q", "--", relative],
                                cwd=root, capture_output=True, check=False)
        if tracked or result.returncode != 0:
            raise GuardError("identifier-config-must-be-ignored")
    try:
        value = json.loads(filename.read_text(encoding="utf-8"))
        identifiers = value["identifiers"]
        if (not isinstance(identifiers, list) or not identifiers
                or any(not isinstance(item, str) or len(item.strip()) < 3 for item in identifiers)):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise GuardError("invalid-identifier-config") from None
    return tuple(item.strip() for item in identifiers)


def scan_repository(root, *, staged=False, include_untracked=False, identifiers=()):
    raw = git(root, "ls-files", "--stage", "-z")
    selected = None
    if staged:
        selected = set(git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0"))
    entries, findings = [], set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        mode, oid, stage = metadata.split()
        if selected is not None and raw_name not in selected:
            continue
        name = raw_name.decode("utf-8", errors="surrogateescape")
        rule = path_rule(name)
        if stage != b"0":
            rule = "unmerged-index"
        elif mode not in {b"100644", b"100755"}:
            rule = "unsupported-index-mode"
        if rule:
            findings.add(Finding(name, 1, rule))
        else:
            entries.append((name, oid))
    checked = len(entries) + len({finding.file for finding in findings})
    if entries:
        requests = b"".join(oid + b"\n" for _, oid in entries)
        headers = git(root, "cat-file", "--batch-check", input_bytes=requests).splitlines()
        if len(headers) != len(entries):
            raise GuardError("incomplete-index-check")
        readable = []
        for (name, oid), header in zip(entries, headers):
            values = header.split()
            if len(values) != 3 or values[1] != b"blob" or not values[2].isdigit():
                raise GuardError("unreadable-index-object")
            if int(values[2]) > MAX_FILE_BYTES:
                findings.add(Finding(name, 1, "file-too-large"))
            else:
                readable.append((name, oid))
        if readable:
            output = git(root, "cat-file", "--batch", input_bytes=b"".join(oid + b"\n" for _, oid in readable))
            offset = 0
            for name, oid in readable:
                end = output.index(b"\n", offset)
                header = output[offset:end].split()
                if len(header) != 3 or header[0] != oid or header[1] != b"blob":
                    raise GuardError("unreadable-index-object")
                size = int(header[2])
                offset = end + 1
                data = output[offset:offset + size]
                if len(data) != size or output[offset + size:offset + size + 1] != b"\n":
                    raise GuardError("incomplete-index-check")
                offset += size + 1
                findings.update(scan_blob(name, data, identifiers))
    if include_untracked:
        for raw_name in git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
            if not raw_name:
                continue
            name = raw_name.decode("utf-8", errors="surrogateescape")
            checked += 1
            path = root / name
            rule = path_rule(name)
            if path.is_symlink():
                rule = "unsupported-index-mode"
            if rule:
                findings.add(Finding(name, 1, rule))
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    findings.add(Finding(name, 1, "file-too-large"))
                else:
                    findings.update(scan_blob(name, path.read_bytes(), identifiers))
            except OSError:
                findings.add(Finding(name, 1, "unreadable-content"))
    return checked, sorted(findings)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="check only changed Git index blobs")
    parser.add_argument("--include-untracked", action="store_true", help="also preview nonignored new source files")
    parser.add_argument("--identifiers-file", type=Path, help="ignored/protected JSON owner-identifier configuration")
    args = parser.parse_args(argv)
    try:
        identifiers = load_identifiers(ROOT, args.identifiers_file)
        checked, findings = scan_repository(ROOT, staged=args.staged,
                                           include_untracked=args.include_untracked, identifiers=identifiers)
        report = {"ok": not findings, "files_checked": checked,
                  "findings": [asdict(finding) for finding in findings]}
    except (GuardError, OSError, ValueError) as error:
        rule = str(error) if isinstance(error, GuardError) else "publication-check-incomplete"
        report = {"ok": False, "findings": [], "errors": [rule]}
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return int(not report["ok"])


if __name__ == "__main__":
    sys.exit(main())
