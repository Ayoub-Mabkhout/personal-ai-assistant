# Optional neural wake runtime

The native companion can use Sherpa ONNX open-vocabulary keyword spotting without
a vendor key. The detector receives the same 16 kHz frames as the rolling capture
buffer. It does not open another microphone or send standby audio to a server.
The model, operating threshold, background battery cost and handset behavior still
need to be evaluated. An APK build does not establish wake reliability.

`SherpaWakeDetector` loads the pinned Kotlin/JNI runtime through reflection so a
plain Java build can still omit it. Models use standardized packaged asset paths
under `voice/sherpa/`. Both the English 2024 BPE and Chinese-English 2025 phoneme
model formats are supported; the keyword file must match the selected model's
tokens. Prefer the actual model and threshold evaluated with independent positive,
negative and noisy samples. Keep a manual Talk option.

Prepare the official model in a protected tool/cache directory outside the public
checkout. Generate the model's tokenized keyword file using Sherpa's documented
`text2token` command or its corresponding tokenizer. Then prepare the runtime:

```powershell
.venv/Scripts/python.exe scripts/fetch_wake_runtime.py --model-dir MODEL_DIRECTORY --keywords TOKENIZED_KEYWORDS_FILE
.venv/Scripts/python.exe scripts/build_android_companion.py --wake-runtime PRIVATE_RUNTIME_JSON
```

The fetcher stores dependencies under `~/.personal-assistant/android-wake/`, outside
OneDrive. It pins Sherpa ONNX 1.13.8's static ONNX Runtime AAR to the official GitHub
release's SHA256 and Kotlin 1.9.25 to its checked SHA256. The library matches the
SDK 35 dex compiler's supported metadata format. It selects quantized
encoder/joiner exports where supplied and a matching chunk8 export when available,
otherwise chunk16. The generated runtime manifest records every jar, native library
and model checksum. The builder verifies them before packaging and rejects unrelated,
traversing or duplicate archive entries. Binaries are never tracked in Git. License
texts are bundled as app assets. The runtime uses one inference thread.

Default preparation packages only `arm64-v8a` for a modern physical handset. For an
x86_64 Android emulator, prepare another runtime with `--abis x86_64` and build a
separate test APK. Its app signing identity can remain the same, but never publish
different APK bytes under an already published version code. Builds include a
16 KiB native-library alignment pass; actual device/native loading must still be
verified. Model and runtime assets contain no service credential.

References: [Sherpa keyword spotting](https://k2-fsa.github.io/sherpa/onnx/kws/index.html),
[official pretrained models](https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html),
[pinned runtime release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v1.13.8),
[Kotlin Android API](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/sherpa-onnx/kotlin-api/KeywordSpotter.kt).

## Optional custom openWakeWord head

`OpenWakeDetector` and `scripts/fetch_openwake_runtime.py` provide an alternative
runtime for a separately evaluated classifier. They do not activate or package a
new classifier automatically. Use independent real recordings and voices excluded
from training to establish whether it improves the current detector. A failed
training acceptance report remains a failed experiment.

The alternative bundles pinned ONNX Runtime Android 1.24.2 with its Java API and
replaces the Sherpa runtime. It uses raw PCM16 converted to float32, 1280 new samples
per block and 480 samples of overlap. The frozen mel model produces 32 bins;
values are transformed by `/10 + 2`. Each block embeds the latest 76 mel frames
into 96 features. The classifier consumes the latest 16 embeddings. Cold startup
initializes mel history to ones and feature history to zeros, and suppresses
predictions for the first 26 blocks (about 2.08 seconds). Activation resets that
history so a previous wake phrase cannot be detected again after a command.

The settings sidecar binds the exact classifier checksum, chosen threshold,
sample rate, hop and patience. Deterministic Python feature fixtures and actual
Android JNI inference should be compared before selecting this alternative.
The optional artifact directory stays outside the checkout, and contains models
and licenses rather than personal voice recordings. The official
[openWakeWord architecture and model licenses](https://github.com/dscripka/openWakeWord/blob/v0.6.0/README.md#model-architecture)
and [ONNX Runtime Java API](https://onnxruntime.ai/docs/get-started/with-java.html)
describe the underlying components.

For numeric port verification, `scripts/export_wake_reference.py` exports private
PCM and per-block Python feature vectors. `scripts/build_android_openwake_tests.py`
builds a separately signed instrumentation APK that runs the actual target APK's
ONNX Java/JNI classes. It checks every mel frame, embedding, classifier history
and probability, the first 26 suppressed startup blocks, and fragmented stream
input. Run only on a disposable emulator; it makes no cloud calls or shopping
changes. A diagnostic classifier can prove feature parity while still failing
wake acceptance. Diagnostic release metadata is marked `diagnostic_only` and is
rejected by the publication hook. Never publish the diagnostic target/test APKs.

An alternative `feature_type: "logmel-cnn"` keeps the latest 196 transformed mel
frames and sends `[1,1,196,32]` directly to the classifier. It loads no embedding
session or embedding asset. The same 1280-sample hop, 480-sample overlap and
26-block startup suppression apply. `WakeDetector.reset()` clears partial audio,
temporal history and the last probability while retaining model sessions/weights.
This supports clean resumption after command capture, speech playback and Live
sessions. An inactive diagnostic raw-mel head passed actual Android JNI parity
for all 80 fixture blocks, including fragmented input and reset/replay. That
numeric result does not approve the failed diagnostic head's wake accuracy.

## Optional Vosk streaming detector

`scripts/fetch_vosk_runtime.py` prepares the official generic English small
model and pinned Vosk Android 0.3.75/JNA 5.18.1. This alternative replaces Sherpa
and ORT runtime assets rather than packaging all engines together. It retains
upstream model README, Vosk COPYING and JNA's embedded license files. The model
is copied once from APK assets into a checksum-bound internal directory; no
personal recordings or downloaded credentials belong in that bundle.

`VoskWakeDetector` uses the frozen contrast grammar documented in
[wake engine experiments](wake-engine-experiments.md). It reads uncommitted
partial text every 320 samples, requires four consecutive matching frames and
stops decoding once the wake is accepted. It never waits for the complete
command's endpoint. Reset replaces only the recognizer, retaining the loaded
model and clearing partial audio/hypotheses so separated phrases cannot combine.
Cold Talk with wake disabled still bypasses all local model loading.

First enabling this model also copies approximately 71 MB of generic assets into
internal app storage and initializes the native recognizer. That preparation
took 4.57 seconds on the test emulator; wait for the listening status before
trying the wake phrase. A physical phone's preparation time and battery use may
differ. The copied model is reused on later starts, and recognizer resets do
not copy assets or reload model weights.

The default fetch creates an inactive diagnostic bundle. Actual JNI replay uses
`scripts/prepare_vosk_jni_fixtures.py` and `scripts/build_android_vosk_tests.py`
with separate private test assets. These tests compare the actual Java/JNA
recognizer's detection and timing to the offline Python policy, continuous
negative speech, fragmented PCM and reset behavior. Diagnostic target/test APKs
remain barred from publication. `--release` prepares an activation-capable
generic runtime only after native results have been assessed; it does not change
the user-facing experimental/off-by-default setting or establish handset battery
life. The recognizer is larger than a compact keyword classifier and a measured
Android runtime must fit the publisher's APK size limit.
