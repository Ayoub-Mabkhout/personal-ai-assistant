"""Prepare pinned Vosk/JNA Android runtime with a frozen evaluated contrast policy.

Model assets are generic, Apache-2.0; personal audio never belongs in a runtime.
Generated native/jar/model files stay outside tracked paths. A diagnostic build
cannot be published until independent native quality/lifecycle checks pass.
"""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

from fetch_wake_runtime import download, sha

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
MODEL_SHA = "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"
DEPENDENCIES = {
    "vosk-android-0.3.75.aar": ("https://repo.maven.apache.org/maven2/com/alphacephei/vosk-android/0.3.75/vosk-android-0.3.75.aar", "ab2f8b91ac8051561aa325546b35fed9a68b36b8121bac5c6fb927525c4adfad"),
    "jna-5.18.1.aar": ("https://repo.maven.apache.org/maven2/net/java/dev/jna/jna/5.18.1/jna-5.18.1.aar", "7f053e3ec99e14dd71259c82c1c8a02738d64a13c31226b2acc170f3060951e0"),
}
GRAMMAR = ["hey chat", "hey cat", "hey chad", "hey jack", "hey pat", "hey charles", "hate chatting", "[unk]"]


def prepare(cache, abis, diagnostic=True):
    cache = Path(cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    files, jars, sources = [], [], [MODEL_URL]
    licenses = cache / "assets/voice/licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    for name, (url, checksum) in DEPENDENCIES.items():
        path = cache / name
        download(url, path, checksum)
        sources.append(url)
        with zipfile.ZipFile(path) as archive:
            jar = cache / (name + "-classes.jar")
            jar.write_bytes(archive.read("classes.jar"))
            jars.append({"path": str(jar), "sha256": sha(jar)})
            with zipfile.ZipFile(jar) as classes:
                for notice in classes.namelist():
                    if notice.startswith("META-INF/") and Path(notice).name.upper() in ("AL2.0", "LGPL2.1", "LICENSE", "NOTICE", "COPYING"):
                        target = licenses / (name + "-" + Path(notice).name)
                        target.write_bytes(classes.read(notice))
                        files.append({"path": str(target), "entry": "assets/voice/licenses/" + target.name, "sha256": sha(target)})
            for abi in abis:
                native = [name for name in archive.namelist() if name.startswith("jni/" + abi + "/") and name.endswith(".so")]
                if not native: raise ValueError("Missing pinned Vosk/JNA ABI " + abi)
                for entry in native:
                    target = cache / "native" / abi / Path(entry).name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(entry))
                    files.append({"path": str(target), "entry": "lib/" + abi + "/" + target.name, "sha256": sha(target)})
    model = cache / "model.zip"
    download(MODEL_URL, model, MODEL_SHA)
    assets = cache / "assets/voice/vosk"
    assets.mkdir(parents=True, exist_ok=True)
    model_files = []
    with zipfile.ZipFile(model) as archive:
        for item in archive.infolist():
            if item.is_dir(): continue
            parts = Path(item.filename).parts
            if parts[0] != "vosk-model-small-en-us-0.15" or ".." in parts: raise ValueError("Unexpected model archive path")
            relative = Path(*parts[1:])
            target = assets / "model" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
            digest = sha(target)
            model_files.append({"path": relative.as_posix(), "sha256": digest})
            files.append({"path": str(target), "entry": "assets/voice/vosk/model/" + relative.as_posix(), "sha256": digest})
    model_files.sort(key=lambda item: item["path"])
    identity = hashlib.sha256(json.dumps(model_files, sort_keys=True).encode()).hexdigest()
    settings = {"schema_version": 1, "sample_rate": 16000, "frame_samples": 320, "stable_samples": 1280,
                "grammar": GRAMMAR, "partial_words": False, "model_identity": identity, "model_files": model_files,
                "model_archive_sha256": MODEL_SHA, "diagnostic_only": diagnostic, "diagnostic_no_activation": diagnostic}
    path = assets / "settings.json"
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    files.append({"path": str(path), "entry": "assets/voice/vosk/settings.json", "sha256": sha(path)})
    # Vosk code/model and JNA may be redistributed under Apache-2.0. Include
    # upstream authors/source attribution plus the complete chosen license.
    license_file = licenses / "Apache-2.0.txt"
    if not license_file.exists():
        with urllib.request.urlopen("https://www.apache.org/licenses/LICENSE-2.0.txt", timeout=30) as response: license_file.write_bytes(response.read())
    upstream = licenses / "vosk-upstream-COPYING.txt"
    if not upstream.exists():
        with urllib.request.urlopen("https://raw.githubusercontent.com/alphacep/vosk-api/v0.3.45/COPYING", timeout=30) as response: upstream.write_bytes(response.read())
    notice = licenses / "vosk-jna-NOTICE.txt"
    notice.write_text("Vosk model and API: Copyright Alpha Cephei Inc., Apache-2.0.\nhttps://alphacephei.com/vosk/models\nhttps://github.com/alphacep/vosk-api\nJNA: Copyright JNA Development Team. Chosen distribution license Apache-2.0 (dual license with LGPL-2.1).\nhttps://github.com/java-native-access/jna\nPinned runtime dependencies and hashes appear in the builder runtime manifest.\n", encoding="utf-8")
    for path in (license_file, upstream, notice): files.append({"path": str(path), "entry": "assets/voice/licenses/" + path.name, "sha256": sha(path)})
    runtime = {"schema_version": 1, "engine": "vosk", "vosk_android_version": "0.3.75", "jna_version": "5.18.1",
               "source_urls": sources, "diagnostic_only": diagnostic, "jars": jars, "files": files,
               "model_archive_sha256": MODEL_SHA, "dependency_sha256": {key: value[1] for key, value in DEPENDENCIES.items()}}
    output = cache / "runtime.json"
    output.write_text(json.dumps(runtime, indent=2), encoding="utf-8")
    return {"runtime": str(output), "abis": abis, "diagnostic_only": diagnostic, "model_identity": identity}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path.home() / ".personal-assistant/android-vosk")
    parser.add_argument("--abis", nargs="+", choices=("arm64-v8a", "x86_64"), default=["arm64-v8a"])
    parser.add_argument("--release", action="store_true", help="Only after independent Android/negative-stream quality checks pass")
    args = parser.parse_args()
    print(json.dumps(prepare(args.cache, args.abis, not args.release)))
