"""Prepare ignored same-corpus PCM fixtures for actual Android Vosk replay."""
import argparse
import hashlib
import json
from pathlib import Path
import wave


def pcm(path):
    with wave.open(str(path), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2): raise ValueError("Expected PCM16 mono16kHz")
        return source.readframes(source.getnframes())


def main(args):
    report = json.loads(args.report.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    cases = []
    for index, item in enumerate(report["grammars"]["contrasts-unknown"]["clips"]):
        path = Path(item["path"])
        if not path.is_absolute(): path = args.corpus / path
        raw = bytes(32000) + pcm(path) + bytes(32000)
        target = args.output / f"clip-{index:03}.pcm"
        target.write_bytes(raw)
        first = item["stable_80ms_partial_wake_seconds"]
        cases.append({"id": item["id"], "path": target.name, "sha256": hashlib.sha256(raw).hexdigest(),
                      "wake_expected": item["wake_expected"], "host_detected": first is not None,
                      "host_activation_samples": None if first is None else round((first + 1) * 16000),
                      "split": item["split"], "kind": item["kind"], "source_group": item["source_group"]})
    if args.natural_streams:
        manifest = json.loads((args.natural_streams / "streams.json").read_text())
        pieces = []
        for item in manifest["clips"]:
            if item["split"] != "natural-test": continue
            path = Path(item["path"])
            pieces.append(pcm(path if path.is_absolute() else args.natural_streams / path))
        raw = b"".join(pieces)
        if len(raw) < 32000 * 900: raise ValueError("Need at least15minutes natural negative audio")
        target = args.output / "natural-continuous.pcm"
        target.write_bytes(raw)
        cases.append({"id": "natural-continuous", "path": target.name, "sha256": hashlib.sha256(raw).hexdigest(),
                      "wake_expected": False, "host_detected": False, "host_activation_samples": None,
                      "split": "natural-test", "kind": "continuous", "source_group": "natural-continuous"})
    (args.output / "reference.json").write_text(json.dumps({"sample_rate": 16000, "frame_samples": 320, "cases": cases}, indent=2))
    print(json.dumps({"fixtures": str(args.output), "cases": len(cases)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--natural-streams", type=Path)
    main(parser.parse_args())
