"""Bounded offline wake replay using official Vosk small English streaming ASR.

Install vosk==0.3.45 in a separate workbench venv. The official 0.15 archive
SHA256 is 30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498
(https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip, Apache-2.0).
All audio and reports remain private. No paid API, retraining or handset claim.
Grammar policies are declared before replay, rather than selected on holdouts.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import statistics
import time
import wave

from vosk import KaldiRecognizer, Model, SetLogLevel


GRAMMARS = {
    "narrow-unknown": ["hey chat", "[unk]"],
    "contrasts-unknown": ["hey chat", "hey cat", "hey chad", "hey jack", "hey pat", "hey charles", "hate chatting", "[unk]"],
}


def is_wake(text):
    words = text.lower().split()
    return any(words[index:index + 2] == ["hey", "chat"] for index in range(len(words) - 1))


def run_clip(model, path, grammar, partial_word_timestamps=False):
    with wave.open(str(path), "rb") as source:
        assert (source.getnchannels(), source.getsampwidth(), source.getframerate()) == (1, 2, 16000)
        raw = source.readframes(source.getnframes())
    padded = bytes(32000) + raw + bytes(32000)
    recognizer = KaldiRecognizer(model, 16000, json.dumps(grammar))
    recognizer.SetWords(True)
    # Timestamped partial words use a delayed committed-word subset; normal
    # partial text exposes the current hypothesis and is the relevant wake path.
    recognizer.SetPartialWords(partial_word_timestamps)
    events, durations = [], []
    raw_first = stable_first = final_first = None
    stable_frames = 0
    last = None
    started = time.perf_counter()
    for offset in range(0, len(padded), 640):
        frame = padded[offset:offset + 640]
        begin = time.perf_counter()
        final = recognizer.AcceptWaveform(frame)
        value = json.loads(recognizer.Result() if final else recognizer.PartialResult())
        durations.append((time.perf_counter() - begin) * 1000)
        text = value.get("text" if final else "partial", "")
        at = (offset + len(frame)) / 32000 - 1
        if text != last or final:
            events.append({"type": "final" if final else "partial", "at_seconds": round(at, 3), "value": value})
            last = text
        if is_wake(text):
            if final:
                if final_first is None: final_first = at
            else:
                if raw_first is None: raw_first = at
                stable_frames += 1
                if stable_frames >= 4 and stable_first is None: stable_first = at
        else:
            stable_frames = 0
    value = json.loads(recognizer.FinalResult())
    if value.get("text"):
        at = len(padded) / 32000 - 1
        events.append({"type": "flush_final", "at_seconds": round(at, 3), "value": value})
        if is_wake(value["text"]) and final_first is None: final_first = at
    elapsed = time.perf_counter() - started
    sorted_times = sorted(durations)
    return {"raw_partial_wake_seconds": raw_first, "stable_80ms_partial_wake_seconds": stable_first,
            "final_wake_seconds": final_first, "events": events, "audio_seconds": len(raw) / 32000,
            "processing_seconds": elapsed, "frame_p95_ms": sorted_times[int(len(sorted_times) * .95)],
            "frame_max_ms": max(durations)}


def summarize(rows):
    sections = {}
    for split, kind in sorted({(row["split"], row["kind"]) for row in rows}):
        group = [row for row in rows if (row["split"], row["kind"]) == (split, kind)]
        if kind == "original": group = list({row["source_group"]: row for row in group}.values())
        positive, negative = [r for r in group if r["wake_expected"]], [r for r in group if not r["wake_expected"]]
        policies = {}
        for field in ("raw_partial_wake_seconds", "stable_80ms_partial_wake_seconds", "final_wake_seconds"):
            policies[field] = {"positives": len(positive), "negatives": len(negative),
                              "misses": sum(row[field] is None for row in positive),
                              "false_wakes": sum(row[field] is not None for row in negative)}
        sections[split + "/" + kind] = policies
    return sections


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--tts-manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--partial-word-timestamps", action="store_true")
    args = parser.parse_args()
    SetLogLevel(-1)
    loaded = time.perf_counter()
    model = Model(str(args.model))
    load_seconds = time.perf_counter() - loaded
    corpus = json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))
    clips = [dict(row, full_path=args.corpus / row["path"]) for row in corpus["clips"]]
    if args.tts_manifest:
        clips.extend(dict(row, full_path=Path(row["path"])) for row in json.loads(args.tts_manifest.read_text(encoding="utf-8"))["clips"])
    report = {"engine": "vosk", "version": importlib.metadata.version("vosk"), "model": args.model.name,
              "model_license": "Apache-2.0", "model_archive_sha256": "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498",
              "frame_samples": 320, "model_load_seconds": load_seconds, "policies_declared_before_replay": True,
              "partial_word_timestamps": args.partial_word_timestamps,
              "grammars": {}, "limitations": ["Existing personal clips are regression samples, not fresh blind acceptance data", "No hours-long natural negative stream or physical phone CPU/battery measurement", "Partial hypotheses may retract; 80ms stability alone does not prove safe wake acceptance"]}
    for name, grammar in GRAMMARS.items():
        rows = []
        for index, item in enumerate(clips):
            path = item["full_path"]
            result = run_clip(model, path, grammar, args.partial_word_timestamps)
            row = {key: value for key, value in item.items() if key != "full_path"}
            row.update(result, pcm_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            rows.append(row)
            if index % 20 == 0: print(json.dumps({"grammar": name, "completed": index + 1, "total": len(clips)}), flush=True)
        report["grammars"][name] = {"grammar": grammar, "sections": summarize(rows), "clips": rows,
                                  "frame_p95_ms_median": statistics.median(row["frame_p95_ms"] for row in rows),
                                  "frame_max_ms": max(row["frame_max_ms"] for row in rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(args.output), "load_seconds": load_seconds, "sections": {key: value["sections"] for key, value in report["grammars"].items()}}), flush=True)


if __name__ == "__main__": main()
