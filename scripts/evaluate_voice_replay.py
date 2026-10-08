"""Report acoustic replay results without treating template relatives as held-out."""
import argparse
import json
from pathlib import Path


def report(root, replay, threshold):
    manifest = json.loads((root / "manifest.json").read_text())
    clips = {item["path"]: item for item in manifest["clips"]}
    rows = []
    for line in replay.read_text(encoding="utf-8-sig").splitlines():
        path, score, trigger, seconds = line.split("\t")
        key = path.replace("\\", "/")
        if key not in clips: continue
        item = dict(clips[key], score=float(score),
                    first_trigger_sample=int(trigger), replay_seconds=float(seconds))
        item["predicted_wake"] = item["score"] < threshold
        rows.append(item)
    sections = {}
    for split in ("template", "held-out-real", "synthetic-evaluation"):
        for kind in ("original", "synthetic", "augmented"):
            subset = [r for r in rows if r["split"] == split and r["kind"] == kind]
            if not subset: continue
            # Reuploaded byte-identical originals do not add independent evidence.
            if kind == "original":
                subset = list({r["source_group"]: r for r in subset}.values())
            positives = [r for r in subset if r["wake_expected"]]
            negatives = [r for r in subset if not r["wake_expected"]]
            sections[split + "/" + kind] = {
                "clips": len(subset), "positives": len(positives), "negatives": len(negatives),
                "missed_wakes": sum(not r["predicted_wake"] for r in positives),
                "false_wakes": sum(r["predicted_wake"] for r in negatives),
                "positive_scores": [r["score"] for r in positives],
                "negative_scores": [r["score"] for r in negatives],
            }
    return {"threshold": threshold, "lower_score_means_closer": True,
            "sections": sections, "samples": rows,
            "limitations": manifest["limitations"] + [
                "Threshold comparison on these clips is calibration, not independent final acceptance",
                "No hours-long negative audio or actual S22 microphone/battery/lock-screen testing",
                "JVM replay and synthetic delays prove PCM ordering, not Android hardware lifecycle",
                "Generated TTS speaker is deliberately different from personal templates"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--threshold", type=float, default=.15)
    args = parser.parse_args()
    result = report(args.root, args.replay or args.root / "replay.tsv", args.threshold)
    (args.root / "evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["sections"], indent=2))
