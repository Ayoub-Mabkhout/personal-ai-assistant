"""Compile real Android transport/buffer classes against minimal JVM framework shims.

No cloud calls or microphone use. Pass an existing org.json JAR; all generated
classes and evidence belong in an ignored/private workbench.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def evaluate(root: Path, json_jar: Path):
    with tempfile.TemporaryDirectory(prefix="voice-transport-") as folder:
        work = Path(folder)
        shims = {
            "android/content/Context.java": "package android.content; public class Context {public Context getApplicationContext(){return this;}}",
            "android/util/Base64.java": "package android.util; public class Base64 {public static final int NO_WRAP=2, DEFAULT=0; public static String encodeToString(byte[] data,int flags){return java.util.Base64.getEncoder().encodeToString(data);}public static byte[] decode(String data,int flags){return java.util.Base64.getDecoder().decode(data);}}",
            "com/personalassistant/companion/Cloud.java": "package com.personalassistant.companion; import android.content.Context; final class Cloud {static String origin(String s){return s;}static Prefs prefs(Context c){return new Prefs();}static class Prefs {String getString(String k,String d){return d;}}}",
        }
        for name, body in shims.items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        app = root / "apps/android/src/com/personalassistant/companion"
        sources = [app / (name + ".java") for name in ("VoiceSocket", "BufferedCapture", "PcmRingBuffer")]
        sources += [root / "tests/jvm/VoiceTransportHarness.java", *[work / name for name in shims]]
        subprocess.run(["javac", "-cp", str(json_jar), "-d", str(work), *map(str, sources)], check=True, capture_output=True, text=True)
        result = subprocess.run(["java", "-cp", str(work) + ";" + str(json_jar), "com.personalassistant.companion.VoiceTransportHarness"], check=True, capture_output=True, text=True)
        return json.loads(result.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-jar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(Path(__file__).resolve().parents[1], args.json_jar.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
