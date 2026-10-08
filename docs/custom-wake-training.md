# Local custom wake training

`scripts/train_personal_wake.py` is a bounded experiment, not an automatic release
pipeline. It uses official openWakeWord frozen speech features and a small NumPy
classifier. Piper generates multiple voices locally. It does not call a paid API,
run assistant commands, or retrain the large pretrained backbone.

Create the task with `scripts/task_environment.py wake-model-training` and read its
`environment.json` and `checks.json`. Install `numpy`, `onnx`, `onnxruntime`,
`openwakeword==0.6.0`, and `piper-tts` into that task's environment. Preserve the
actual `pip freeze` with each run. This avoids changing the assistant's service
dependencies or relying on the legacy full-training TensorFlow stack.

The official Piper LibriTTS-R medium model supports 904 speakers. Its
[model card](https://huggingface.co/rhasspy/piper-voices/raw/main/en/en_US/libritts_r/medium/MODEL_CARD)
identifies the underlying dataset as CC BY 4.0. Keep source attribution, model
hashes, generated sources and seeded transformation metadata with each experiment.
Piper's generated sources are cached, so retries reuse their exact bytes.

Select disjoint training and development speaker IDs. Development scores select
the checkpoint and threshold. Keep real command families, no-wake recordings,
reuploads and all their descendants out of training and threshold selection.
Isolated wake recordings may be used for personalization; report them separately
from held-out commands. Vary speaking speed, amplitude, noise, reverberation and
the spoken words before/after the wake. A classifier that only sees an isolated
wake surrounded by silence may fail during one-take commands.

The script enforces a run deadline for synthesis and training, caches generated
audio and features, verifies exported ONNX probabilities against NumPy, and then
replays the private regression corpus. It reports speaker counts, hashes, threshold,
training history and per-clip activation positions. Failure artifacts should stay
available for diagnosis. An exported file alone is not a successful detector.

The legacy non-streaming experiment selects thresholds from isolated development
windows. Use `--streaming` for the corrected data pipeline in
`scripts/wake_training_data.py`: annotate wake start/end, label only windows that
contain the complete keyword, ignore partial boundary windows, and calibrate on
full utterance maxima. Each positive has the same speaker/command tail without
the wake and with confusable prefixes. Synthetic speakers and licensed natural
speech speakers remain disjoint across training, development and natural test.
Only development streams select checkpoints and thresholds. Real test recordings
must never be used to lower a threshold after a missed wake.

The raw-mel alternative, `scripts/train_wake_cnn.py`, reuses this manifest and
trains a small temporal CNN locally. Install PyTorch in the private task
environment, check actual CUDA availability, and use `--require-cuda` to prevent
an accidental slow CPU training fallback. The script retains per-utterance
feature caches and a selected checkpoint. `--evaluate-only` reuses that checkpoint.
Training and inference disable TF32 for export comparisons. Thresholds are chosen
in finite raw-logit space; an export temperature preserves numerical resolution
without changing class rankings. Temperature and threshold are development-only.

`scripts/prepare_wake_context_correction.py` adds isolated complete keywords,
isolated confusables, personal training fragments and variable silence gaps
before matched command tails. It preserves existing voice partitions and references
immutable baseline caches. This tests whether a model learned the following
command's context instead of the wake phrase. `--temporal-dilations 1,2,4` tests a
shorter ordered convolutional branch while retaining the same exported shape.
Report wake-duration strata: a shorter receptive field must not silently exclude
slow phrases. All transformations and tests remain private; no assistant intent
is executed while preparing or evaluating audio.

Evaluation reports warm continuous microphone state separately from a cold app
start. Cold startup suppresses the first 26 complete 1280-sample blocks; the first
score eligible to trigger is block 27 (zero-based index 26). A command spoken
before microphone startup finishes is not a valid always-listening acceptance
test. `scripts/evaluate_wake_cnn_stream.py` retains feature state across an entire
untouched natural-speech test rather than resetting at every source boundary.
It reports false activations per hour and combined frontend/classifier CPU timing.
Concatenated read speech is not equivalent to a field microphone recording.

`automated_regression_passed` describes the declared automated gate only.
`acceptance_passed` remains false until actual handset, noise and battery checks
pass. Failed experiments are diagnostic artifacts and must not be published as
working wake models.

`scripts/evaluate_wake_operating_point.py` supports one explicitly declared
alternative development policy: choose the highest score threshold reaching a
requested complete-wake recall, freeze it to a policy file, then replay the saved
classifier once on regression recordings. It separates ordinary natural speech
from deliberately similar phrases. It never adjusts the threshold after seeing
personal outcomes. A near-confusable error count cannot be converted to a field
false-wake rate without realistic prevalence and continuous recordings; reject
the candidate if the real no-wake family or its descendants trigger.

The phone feature contract is:

- Mono PCM16 at 16 kHz; convert integers directly to float32 without dividing by
  32768 before the mel model.
- Process 1280 new samples per step, retaining 480 samples of raw overlap.
- Mel model input `input` is `[1, samples]`. Transform output using `value / 10 + 2`.
  Keep the latest 76 frames of 32 mel bins.
- Embedding input `input_1` is `[1, 76, 32, 1]`. Each step produces 96 features;
  keep the latest 16 embedding vectors.
- Classifier input `input` is `[1, 16, 96]`. Output `wake_probability` is `[1, 1]`.
- Initialize mel history with ones and embedding history with zeros. Suppress
  scoring during startup warm-up. Fixture comparison must test cold start,
  streaming overlap and exact normalization, not only isolated inference.

The raw-mel CNN shares PCM, overlap, mel normalization and cold-start behavior,
but keeps 196 mel frames initialized to ones. It omits the embedding model.
Its `input` is `[1, 1, 196, 32]` and `wake_probability` is `[1, 1]`; normalization
and temperature are included in the exported graph. Settings identify
`feature_type: "logmel-cnn"`, `mel_frames: 196`, `hop_samples: 1280`,
`min_embedding_frames: 26`, and the classifier hash. Despite its historical
name, `min_embedding_frames` is the common startup block count in this mode.
`scripts/export_wake_reference.py --feature-type logmel-cnn` produces deterministic
cold-start vectors for actual Android JNI parity, including the complete head
input and score at each step. Passing port parity establishes identical inference,
not detector quality.

The training data is too small to certify a false-wake rate. Use development
confusable speech and separate real background recordings, then an hours-long
natural speech/music/noise test, before claiming dependable wake monitoring.
Independent S22 microphone, locked-screen, calls, Bluetooth and battery tests are
also required. Keep the Talk button available while comparing detectors.

For the next dataset, assign new recordings to training or blind evaluation
before inspecting them. The old personal corpus has been inspected repeatedly;
it remains useful for regressions but cannot serve as fresh blind acceptance.
An initial useful personalization batch is around 20 new positive recordings
across several sessions: isolated wakes, one-take commands with different tails,
fast/slow speech and moderate noise. Pair these with around 20 no-wake and
confusable commands, including the command alone and "Hey", "Chat", "Hey Jack",
"Hey Cat" and "Hey Chad". This is a starting dataset, not a reliability claim.
Include 10–15 minutes of actual microphone background audio. Synthetic read
speech and filtered Gaussian noise do not represent the handset's street input.

Keep another session/location as a fresh blind check, initially about 10 positive
and 10 negative utterances plus a continuous background recording. Select the
checkpoint and operating policy before scoring it; a failed blind check becomes
a diagnostic report, not a reason to lower the same model's threshold. Run longer
continuous speech/music/street negatives and actual phone battery checks before
claiming a dependable false-wake rate. Report fast and slow duration strata
separately and ensure the model covers the longest complete phrase.

Training audio from a phone recorder can be useful, but final validation must use
the companion's actual AudioRecord source, sample rate, foreground service and
locked-screen path. Recorder denoising and gain control may differ. A test-only
capture/replay path should save PCM and detector events without executing shopping,
alarm, email or other intents and without making paid transcription calls. Verify
that this mode exists before using it; it is a testing requirement, not a claim
that the released app already implements diagnostic export.

References: [openWakeWord training](https://github.com/dscripka/openWakeWord#training-new-models),
[frozen feature implementation](https://github.com/dscripka/openWakeWord/blob/main/openwakeword/utils.py),
[LibriSpeech source and license](https://www.openslr.org/12/).
