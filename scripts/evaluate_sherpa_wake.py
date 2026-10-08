"""Replay private PCM fixtures through the official English Sherpa KWS model.

Install sherpa-onnx==1.13.8, sentencepiece and numpy in a separate evaluation
environment. Model downloads/runtime are outside the public repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import wave

import numpy as np
import sentencepiece as spm
import sherpa_onnx


def evaluate(corpus, model, threshold=.25, score=1., all_clips=False, chunk=8):
    manifest = json.loads((corpus / "manifest.json").read_text())
    if (model / "bpe.model").exists():
        processor = spm.SentencePieceProcessor(model_file=str(model / "bpe.model"))
        tokens = processor.encode("HEY CHAT", out_type=str)
        suffix = "epoch-12-avg-2-chunk-16-left-64.int8.onnx"
        paths = {part: model / (part + "-" + suffix) for part in ("encoder", "decoder", "joiner")}
    else:
        lexicon = {}
        for line in (model / "en.phone").read_text().splitlines():
            pieces = line.split()
            if pieces: lexicon.setdefault(pieces[0].upper(), pieces[1:])
        tokens = lexicon["HEY"] + lexicon["CHAT"]
        suffix = f"epoch-13-avg-2-chunk-{chunk}-left-64"
        paths = {part: model / (part + "-" + suffix + (".onnx" if part == "decoder" else ".int8.onnx"))
                 for part in ("encoder", "decoder", "joiner")}
    keywords = corpus / "sherpa-keywords.txt"
    keywords.write_text(" ".join(tokens) + f" :{score} #{threshold} @HEY_CHAT\n", encoding="utf-8")
    kws = sherpa_onnx.KeywordSpotter(**{key: str(value) for key, value in paths.items()},
        tokens=str(model / "tokens.txt"), keywords_file=str(keywords), num_threads=1,
        keywords_score=score, keywords_threshold=threshold, num_trailing_blanks=1)
    rows = []
    for item in manifest["clips"]:
        if not all_clips and item["kind"] == "augmented": continue
        with wave.open(str(corpus / item["path"]), "rb") as wav:
            assert wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == 16000
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.
        # One-second lead in and 800ms flush; use exactly phone's 20ms frames.
        padded = np.concatenate([np.zeros(16000, np.float32), pcm, np.zeros(12800, np.float32)])
        stream = kws.create_stream(); detections = []; started = time.monotonic()
        for start in range(0, len(padded), 320):
            stream.accept_waveform(16000, padded[start:start + 320])
            while kws.is_ready(stream):
                kws.decode_stream(stream)
                result = kws.keyword_spotter.get_result(stream)
                found = result.keyword.strip()
                if found:
                    detections.append({"keyword": found, "activation_seconds": (start + 320) / 16000 - 1,
                                       "token_timestamps": [round(t - 1, 3) for t in result.timestamps]})
                    kws.reset_stream(stream)
        stream.input_finished()
        row = dict(item, detections=detections, predicted_wake=bool(detections),
                   replay_seconds=round(time.monotonic() - started, 4))
        rows.append(row)
        print(json.dumps({"id": item["id"], "expected": item["wake_expected"],
                          "detected": bool(detections), "seconds": row["replay_seconds"]}), flush=True)
    sections = {}
    for split in ("template", "held-out-real", "synthetic-evaluation"):
        for kind in ("original", "synthetic", "augmented"):
            subset = [r for r in rows if r["split"] == split and r["kind"] == kind]
            if kind == "original": subset = list({r["source_group"]: r for r in subset}.values())
            if not subset: continue
            positives = [r for r in subset if r["wake_expected"]]
            negatives = [r for r in subset if not r["wake_expected"]]
            sections[split + "/" + kind] = {"positives": len(positives), "negatives": len(negatives),
                "missed_wakes": sum(not r["predicted_wake"] for r in positives),
                "false_wakes": sum(r["predicted_wake"] for r in negatives)}
    report = {"engine": "sherpa-onnx", "version": sherpa_onnx.__version__,
        "model": model.name, "keyword": "HEY CHAT", "bpe_tokens": tokens,
        "keywords_threshold": threshold, "keywords_score": score, "num_trailing_blanks": 1,
        "max_active_paths": 4, "frame_samples": 320, "sample_rate": 16000,
        "model_files": {key: {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                        for key, path in paths.items()}, "sections": sections, "samples": rows,
        "limitations": manifest["limitations"] + ["No hours-long false-wake test", "No handset lifecycle or battery test",
            "Parameter tuning on this corpus is calibration; new held-out recordings required for acceptance"]}
    destination = corpus / f"sherpa-evaluation-{model.name}-{threshold}-{score}{'-all' if all_clips else ''}.json"
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(destination), "sections": sections}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("--threshold", type=float, default=.25)
    parser.add_argument("--score", type=float, default=1.)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--chunk", type=int, choices=(8, 16), default=8,
                        help="2025 phoneme model chunk size; English 2024 BPE is fixed at 16")
    args = parser.parse_args()
    evaluate(args.corpus, args.model, args.threshold, args.score, args.all, args.chunk)
