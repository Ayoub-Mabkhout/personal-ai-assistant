"""Build a private same-signed Vosk/JNA instrumentation APK; never publish."""
import argparse
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(command): subprocess.run(list(map(str, command)), check=True)


def build(sdk, fixtures, signing):
    tools = sdk / "build-tools/35.0.0"
    platform = sdk / "platforms/android-35/android.jar"
    work = ROOT / "state/android-vosk-tests"
    classes, dex = work / "classes", work / "dex"
    classes.mkdir(parents=True, exist_ok=True)
    dex.mkdir(exist_ok=True)
    run([tools / "aapt2.exe", "link", "-I", platform, "--manifest", ROOT / "tests/android/VoskManifest.xml", "-A", fixtures, "-o", work / "resources.apk"])
    run(["javac", "-encoding", "UTF-8", "--release", "8", "-classpath", str(platform) + os.pathsep + str(ROOT / "state/android-build/classes"), "-d", classes, ROOT / "tests/android/VoskInstrumentation.java", ROOT / "tests/android/VoskGainInstrumentation.java"])
    run([tools / "d8.bat", "--lib", platform, "--classpath", ROOT / "state/android-build/classes", "--min-api", "26", "--output", dex, *classes.glob("**/*.class")])
    unsigned = work / "unsigned.apk"
    unsigned.write_bytes((work / "resources.apk").read_bytes())
    with zipfile.ZipFile(unsigned, "a") as archive:
        for file in dex.glob("*.dex"): archive.write(file, file.name)
    run([tools / "zipalign.exe", "-f", "4", unsigned, work / "aligned.apk"])
    output = work / "vosk-tests.apk"
    run([tools / "apksigner.bat", "sign", "--ks", signing / "companion.p12", "--ks-key-alias", "companion", "--ks-pass", "file:" + str(signing / "password.txt"), "--out", output, work / "aligned.apk"])
    run([tools / "apksigner.bat", "verify", output])
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=Path.home() / ".personal-assistant/android-sdk")
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--signing", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "PersonalAssistant/secrets/android-signing")
    args = parser.parse_args()
    build(args.sdk, args.fixtures, args.signing)
