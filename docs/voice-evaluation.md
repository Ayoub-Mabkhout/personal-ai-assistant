# Voice fixtures and replay

Recordings and generated media belong under ignored `state/voice/`, not Git.
`scripts/voice_corpus.py` runs inside the existing Wyoming Whisper container,
using its installed numpy, faster-whisper and Wyoming packages. Piper synthesis
uses the existing speech service; it does not spend OpenAI credits or execute
commands. Input `input.json` records source hashes, expected wake presence,
relative WAV paths and source-group split. Convert originals with ffmpeg to
16 kHz mono PCM16 first; preserve original M4A files.

The script transcribes originals with base-int8/beam5 and no wake phrase prompt,
generates positive and confusable negative phrases with Piper, and produces
seeded gain, speed, filtered-noise and simple echo variants. Its manifest retains
parent/source identifiers, hashes, transformation and seed. A transformed training
clip remains training data. Byte-identical reuploads count as one source family.
An ASR transcript is provisional, not manually checked reference text.

Only isolated wake clips become experimental personal templates. Energy cropping
keeps 100 ms margins; inspect crops before replacing the detector with a trained
neural model. A single TTS speaker and simulated noise are useful regression
fixtures, but do not establish accuracy in shops or streets.

Compile `tests/java/VoiceReplay.java` together with the companion's actual
`PcmRingBuffer`, `BufferedCapture`, `WakeDetector` and `TemplateWakeDetector`
classes using javac from JDK 17 or newer.
Run it with template-WAV directory, corpus directory and detector threshold.
Capture its TSV output and use `scripts/evaluate_voice_replay.py` to produce
source-separated evaluation. The replay tests actual PCM capture ordering with
connection delays of zero, one, three and ten seconds, detecting dropped or
duplicated samples. It also reports streaming detector activation positions.
This host JVM test does not simulate Android service restrictions or the S22
microphone hardware. Those still need emulator and real-device trials.

Wake quality must be assessed separately from transcription and transport:
held-out one-take positives; confusable speech without a wake phrase; several
hours of background speech/music; phone locked and unlocked; calls/Bluetooth;
airplane mode and reconnect; eight-hour matched battery trials. Keep failed
clips and trace timestamps to diagnose each failure rather than raising
sensitivity blindly. A manual Talk button remains available during evaluation.

For a stronger learned detector, [openWakeWord's training guide](https://github.com/dscripka/openWakeWord#training-new-models)
recommends thousands of generated positive examples and substantial negative
data. The small personal corpus is useful for calibration and regression; it
cannot establish a production-quality wake model or an hours-long false-wake rate.
Porcupine's custom Android model remains another candidate when its model,
AccessKey and applicable license are provisioned. No candidate is accepted merely
because its SDK compiles.

An alternative that does not require training a phrase-specific classifier is
[Sherpa's open-vocabulary keyword spotter](https://k2-fsa.github.io/sherpa/onnx/kws/index.html).
It uses a small pretrained streaming recognizer constrained to chosen keywords.
`scripts/evaluate_sherpa_wake.py` streams the same private WAV fixtures in 20 ms
frames through its Python runtime, recording trigger positions, per-source misses,
false activations and exact model hashes. Its keyword boost and probability
threshold must be evaluated together; raising sensitivity may create false wakes.
Testing the official English model on the real recordings is required before
choosing it for the Android build. No account or custom training is required.

Small personal calibration counts do not establish an hours-long false-activation
rate; keep the wake option explicitly experimental until acceptance passes.
Keep actual speaker-specific reports and model hashes in private state, and test
new recordings before making stronger accuracy claims. Specify the exact keyword
boost and probability threshold in the keyword asset so Android uses the same
settings as the replay.
