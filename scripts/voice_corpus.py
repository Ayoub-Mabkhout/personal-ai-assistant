"""Prepare private, source-grouped voice fixtures inside the Wyoming container.

Requires its existing numpy/faster_whisper/wyoming packages. Never executes an
intent. Inputs are mono PCM16 WAVs with an input.json sidecar. Generated speech
uses the existing Piper service, not a paid speech API.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time
import wave

import numpy as np
from faster_whisper import WhisperModel
from wyoming.audio import AudioChunk, AudioStart
from wyoming.client import AsyncTcpClient
from wyoming.event import Event

RATE = 16000
SYNTHETIC = [
    ("Hey chat", True),
    ("Hey chat, add bananas and sparkling water to my shopping list.", True),
    ("Hey chat, set an alarm for seven thirty tomorrow morning.", True),
    ("Hey chat, find my latest electricity invoice.", True),
    ("Add bananas and sparkling water to my shopping list.", False),
    ("The cashier said have a great day.", False),
    ("Hey Jack, did you check the shopping list?", False),
    ("I hate chatting when the train is noisy.", False),
    ("Hey cat, come here.", False),
    ("Could you check that contract for me?", False),
]


def read(path):
    with wave.open(str(path), "rb") as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2:
            raise ValueError("Expected mono PCM16 WAV.")
        values = np.frombuffer(stream.readframes(stream.getnframes()), "<i2").astype(np.float32)
        rate = stream.getframerate()
    if rate != RATE:
        values = np.interp(np.arange(round(len(values) * RATE / rate)) * rate / RATE,
                           np.arange(len(values)), values)
    return values


def write(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(values, -32768, 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(RATE)
        stream.writeframes(pcm)
    return hashlib.sha256(pcm).hexdigest()


def trim(values):
    """Energy crop with 100ms margins; does not assert speech/wake alignment."""
    frame = 160
    energy = np.array([np.sqrt(np.mean(values[i:i+frame] ** 2))
                       for i in range(0, len(values), frame)])
    active = np.flatnonzero(energy > max(100, float(energy.max()) * .08))
    if not len(active):
        return values
    return values[max(0, int(active[0]) * frame - 1600):
                  min(len(values), (int(active[-1]) + 1) * frame + 1600)]


def augment(values, variant, seed):
    rng = np.random.default_rng(seed)
    if variant == "gain_minus6db": return values * .501187
    if variant.startswith("speed"):
        factor = 0.90 if variant == "speed090" else 1.10
        return np.interp(np.arange(round(len(values) / factor)) * factor,
                         np.arange(len(values)), values)
    if variant == "room_echo":
        result = values.copy()
        for delay, gain in [(640, .20), (1280, .10), (2080, .05)]:
            result[delay:] += values[:-delay] * gain
        return result * .75
    if variant.startswith("noise"):
        snr = 18 if variant == "noise18db" else 10
        noise = rng.normal(size=len(values))
        # Filtered noise + quiet low-frequency rumble. Synthetic, not crowd proof.
        noise = np.convolve(noise, np.array([.15, .25, .25, .20, .15]), "same")
        noise += .15 * np.sin(np.arange(len(values)) * 2 * np.pi * 120 / RATE)
        rms = np.sqrt(np.mean(values ** 2))
        return values + noise * rms / max(np.sqrt(np.mean(noise ** 2)), 1e-9) / 10 ** (snr / 20)
    raise ValueError(variant)


async def synthesize(text):
    async with AsyncTcpClient("piper", 10200) as client:
        await client.write_event(Event(type="synthesize", data={"text": text}))
        chunks = []; settings = None
        while True:
            event = await asyncio.wait_for(client.read_event(), 45)
            if event is None: raise RuntimeError("Piper closed before audio-stop.")
            if event.type == "audio-start": settings = AudioStart.from_event(event)
            elif event.type == "audio-chunk": chunks.append(AudioChunk.from_event(event).audio)
            elif event.type == "audio-stop": break
        if settings.width != 2 or settings.channels != 1: raise ValueError("Piper PCM format.")
        values = np.frombuffer(b"".join(chunks), "<i2").astype(np.float32)
        return np.interp(np.arange(round(len(values) * RATE / settings.rate)) * settings.rate / RATE,
                         np.arange(len(values)), values)


async def build(root):
    inputs = json.loads((root / "input.json").read_text())
    groups = {}
    for item in inputs:
        item["source_group"] = groups.setdefault(item["source_sha256"], item["source_group"])
    records = []
    model = WhisperModel("rhasspy/faster-whisper-base-int8", download_root="/data",
                         device="cpu", compute_type="int8", cpu_threads=2)
    for item in inputs:
        path = root / item["path"]; started = time.monotonic()
        segments, info = model.transcribe(str(path), language="en", beam_size=5,
                                          vad_filter=True)
        item["transcript"] = " ".join(s.text for s in segments).strip()
        item["transcription_seconds"] = round(time.monotonic() - started, 3)
        item["transcript_source"] = "faster-whisper-base-int8, beam5, no phrase prompt"
        values = read(path)
        records.append(dict(item, samples=len(values), pcm_sha256=write(path, values), kind="original"))
        if item["split"] == "template":
            clipped = trim(values)
            template = root / "wake-model" / "templates" / (item["id"] + ".wav")
            write(template, clipped)
            template.with_suffix(".pcm").write_bytes(np.clip(clipped, -32768, 32767).astype("<i2").tobytes())
    del model
    for index, (text, positive) in enumerate(SYNTHETIC):
        values = await synthesize(text)
        item = {"id": f"tts-{index:02d}", "path": f"synthetic/tts-{index:02d}.wav",
                "source_group": f"piper-lessac-{index:02d}", "split": "synthetic-evaluation",
                "wake_expected": positive, "transcript": text, "kind": "synthetic",
                "synthesis": "existing en_US-lessac-medium Piper; one voice"}
        records.append(dict(item, samples=len(values), pcm_sha256=write(root/item["path"], values)))
    originals = list(records)
    for index, item in enumerate(originals):
        values = read(root/item["path"])
        for offset, variant in enumerate(("gain_minus6db", "speed090", "speed110", "noise18db", "noise10db", "room_echo")):
            path = f"augmented/{item['id']}-{variant}.wav"; result = augment(values, variant, 7100+index*10+offset)
            records.append(dict(item, id=item["id"]+"-"+variant, path=path, kind="augmented",
                                parent_id=item["id"], variant=variant, seed=7100+index*10+offset,
                                samples=len(result), pcm_sha256=write(root/path, result)))
    silence = np.zeros(RATE * 10)
    records.append({"id": "silence", "path": "synthetic/silence.wav", "kind": "synthetic",
                    "split": "synthetic-evaluation", "wake_expected": False,
                    "source_group": "silence", "samples": len(silence),
                    "pcm_sha256": write(root/"synthetic/silence.wav", silence)})
    report = {"sample_rate": RATE, "channels": 1, "sample_width": 2,
              "seed_policy": "7100 + source index * 10 + augmentation index",
              "limitations": ["Only nine real clips and one negative original",
                  "Byte-identical reuploads count as one source family",
                  "Template-source augmentations remain template split; never held-out evidence",
                  "One synthetic speaker; generated noise/echo are not real crowd/wind tests",
                  "ASR output is not manually verified ground truth"], "clips": records}
    (root/"manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"clips": len(records), "originals": len(inputs), "tts": len(SYNTHETIC)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    asyncio.run(build(parser.parse_args().root))
