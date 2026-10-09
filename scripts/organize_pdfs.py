"""Plan and verify non-destructive PDF copies from a private JSONL inventory.

Inventory sources are never deleted or rewritten. Explicit allowed roots and
exclusions constrain document reads; cloud placeholders and application files
are skipped. Reports may contain personal paths and must be stored privately.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata


RULES = [
    ("academic/thesis", r"thesis|masterarbeit|bachelorarbeit|dissertation"),
    ("career/cvs", r"\bcv\b|curriculum|lebenslauf|resume"),
    ("career/cover-letters", r"cover.?letter|anschreiben|motivation.?letter"),
    ("career/applications", r"bewerbung|job.?application"),
    ("tax", r"steuer|tax.?return|tax.?assessment|finanzamt"),
    ("banking/statements", r"kontoauszug|bank.?statement|account.?statement"),
    ("insurance", r"versicherung|insurance|police d.assurance"),
    ("housing", r"mietvertrag|miete|wohnung|tenant|tenancy|rental.?agreement|nebenkosten"),
    ("identity", r"reisepass|passport|aufenthalt|residence.?permit|personalausweis"),
    ("health", r"arzt|medical|kranken|prescription|befund"),
    ("contracts", r"vertrag|contract|agreement"),
    ("receipts", r"rechnung|invoice|receipt|quittung|facture"),
    ("academic/coursework", r"assignments|lecture|vorlesung|university|universit|hochschule|klausur|studium|exercise|ubung|semester|transcript|zeugnis|certificate|zertifikat"),
]


def under(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:105] or "document"


def classify(source: Path, text: str) -> tuple[str, str]:
    location = source.as_posix().lower()
    filename = unicodedata.normalize("NFKD", source.stem.lower())
    for category, pattern in RULES:
        if re.search(pattern, filename):
            return category, "filename"
    for category, pattern in RULES:
        if re.search(pattern, location):
            return category, "source-folder"
    for category, pattern in RULES:
        if re.search(pattern, text.lower()):
            return category, "bounded-text"
    return "inbox", "needs-review"


def read_text(source: Path) -> tuple[str, str, int | None]:
    # Do not persist document text, metadata, passwords, or parser diagnostics.
    try:
        from pypdf import PdfReader
        reader = PdfReader(source, strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            return "", "encrypted", None
        total = len(reader.pages)
        text = "\n".join((page.extract_text() or "")[:10000] for page in reader.pages[:3])
        return text, "ok" if text.strip() else "no-text-scanned-or-empty", total
    except Exception as error:
        return "", "failed-" + type(error).__name__, None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--allow-root", action="append", required=True, type=Path)
    parser.add_argument("--exclude-root", action="append", default=[], type=Path)
    parser.add_argument("--metadata-only", action="store_true", help="Classify from paths and names without extracting PDF text")
    parser.add_argument("--apply", action="store_true", help="Copy bytes and verify; originals stay intact")
    args = parser.parse_args()
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    allowed = [p.resolve() for p in args.allow_root]
    excluded = [p.resolve() for p in args.exclude_root]
    vault = args.vault.resolve()
    args.report.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in args.inventory.read_text(encoding="utf-8").splitlines() if line]
    result = []
    seen: dict[str, Path] = {}
    # Already organized identical objects are reusable, regardless of their names.
    if vault.exists():
        for existing in vault.rglob("*.pdf"):
            try:
                if under(existing.resolve(), excluded) or "work" in existing.relative_to(vault).parts:
                    continue
                attrs = getattr(existing.stat(), "st_file_attributes", 0)
                if not attrs & (0x1000 | 0x40000 | 0x400000):
                    seen.setdefault(digest(existing), existing)
            except OSError:
                pass
    for record in rows:
        source = Path(record["source"]).resolve()
        item = {**record, "destination": None, "status": "skipped"}
        result.append(item)
        if not under(source, allowed) or under(source, excluded):
            item["reason"] = "outside-authorized-scope"
            continue
        if under(source, [vault]):
            item["reason"] = "already-in-vault"
            continue
        if record.get("bucket") in {"application-system", "suspected-work"} or record.get("cloud_not_local"):
            item["reason"] = "application-work-or-cloud-placeholder"
            continue
        try:
            before = source.stat()
            attrs = getattr(before, "st_file_attributes", 0)
            if attrs & (0x1000 | 0x40000 | 0x400000):
                item["reason"] = "became-cloud-placeholder"
                continue
            sha = digest(source)
            item["sha256"] = sha
            item["hash_status"] = "ok"
            text, extraction, pages = ("", "not-extracted-metadata-only", None) if args.metadata_only else read_text(source)
            category, basis = classify(source, text)
            if record.get("category_hint") in {c for c, _ in RULES} | {"inbox", "archive"}:
                category, basis = record["category_hint"], "inventory-category-hint"
            item.update(category=category, classification_basis=basis, extraction_status=extraction, pages=pages)
            date = dt.datetime.fromtimestamp(before.st_mtime).strftime("%Y-%m-%d")
            item["date_basis"] = "filesystem-modification-date-not-verified-document-date"
            destination = seen.get(sha) or vault / category / date[:4] / f"{date}__{slug(source.stem)}__{sha[:16]}.pdf"
            item["destination"] = str(destination)
            if sha in seen:
                item["status"] = "duplicate-existing" if destination.exists() else "duplicate-planned"
                item["reason"] = "identical-sha256"
            else:
                item["status"] = "planned"
                if args.apply:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists():
                        if digest(destination) != sha:
                            raise ValueError("destination-conflict")
                    else:
                        fd, tempname = tempfile.mkstemp(prefix=".copy-", dir=destination.parent)
                        os.close(fd)
                        temp = Path(tempname)
                        try:
                            shutil.copy2(source, temp)
                            if digest(temp) != sha:
                                raise ValueError("copy-hash-mismatch")
                            if destination.exists():
                                raise ValueError("destination-appeared-during-copy")
                            temp.rename(destination)
                        finally:
                            temp.unlink(missing_ok=True)
                    item["status"] = "copied-verified"
                seen[sha] = destination
            after = source.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or digest(source) != sha:
                raise ValueError("source-changed-during-operation")
            if args.apply and digest(destination) != sha:
                raise ValueError("destination-verification-failed")
            item["source_preserved"] = True
        except Exception as error:
            item["status"] = "failed"
            item["error_type"] = type(error).__name__
    manifest = args.report / ("copy-manifest.json" if args.apply else "sorting-plan.json")
    manifest.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    summary = {"statuses": dict(Counter(r["status"] for r in result)), "categories": dict(Counter(r.get("category") for r in result if r.get("category"))), "originals_deleted": 0, "originals_modified": 0, "manifest": str(manifest.resolve())}
    (args.report / "sorting-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
