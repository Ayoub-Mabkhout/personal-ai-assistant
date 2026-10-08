# Wake engine experiments

Use development audio to commit settings before replaying personal recordings.
Previously inspected recordings are regressions; independent-provider generated
speech is a synthetic regression, not fresh human acceptance evidence. No benchmark
script executes assistant intents or makes speech API calls.

`scripts/benchmark_sherpa_candidates.py` commits a bounded grid of English model
precision, keyword boosting score, trigger threshold, trailing blanks and active
paths. It selects from annotated development streams, then evaluates only the
selected policy against the existing regression and continuous negative speech.
Decision latency is the audio time at trigger minus the annotated complete-wake
end, rather than the decoder's token timestamp. A small crop tolerance is explicit.
The script separates ordinary commands, near-confusables and natural speech errors.

Sherpa's parameters have different meanings: score biases keyword paths during
search, threshold controls detection conservatism, trailing blanks defer trigger
finalization, and active paths control the beam. Lowering a threshold does not
guarantee correct recognition of an accent or background noise. See the
[official KWS explanation](https://k2-fsa.github.io/sherpa/onnx/kws/index.html) and
[configuration definitions](https://k2-fsa.github.io/sherpa/onnx/c-api/html/structSherpaOnnxKeywordSpotterConfig.html).

`scripts/train_wake_embedding_temporal.py` is one bounded local alternative to
the flat frozen-feature head. It retains the pretrained openWakeWord frontend,
uses shared time convolutions, dropout and regularization, and includes the
isolated controls from the corrected dataset. Its operating point and checkpoint
are chosen from development streams before replaying commands. The exported
classifier keeps the `[1,16,96]` frontend contract. Failed classifiers remain
diagnostic artifacts; export parity alone is not acceptance.

`scripts/evaluate_embedding_latency.py` measures the frozen temporal classifier's
annotated decision latency and keeps feature state across a continuous natural
negative stream. `scripts/evaluate_external_wake.py` replays another synthetic
provider using a saved policy; it never chooses a new threshold from those clips.

Vosk offers a practical alternative using a pretrained speech recognizer with a
small dynamic grammar. The official
[model list](https://alphacephei.com/vosk/models) identifies
`vosk-model-small-en-us-0.15` as a 40 MB Android/Raspberry Pi model under Apache2.
Use the contrast grammar declared in `scripts/evaluate_vosk_wake.py`, retaining
similar phrases and `[unk]` as competitors. A grammar containing only the desired
phrase can force near-sounding speech into a wake.

The relevant Vosk wake policy reads normal uncommitted partial text, rather than
timestamped partial-word output, and requires adjacent `hey chat` words over four
320-sample input frames (80 ms at16 kHz). Partial hypotheses can retract, so this
stability check is a declared operating policy, not proof of perfect recognition.
`scripts/benchmark_vosk_development.py` evaluates the same annotated development
streams used for Sherpa and a persistent recognizer over untouched continuous
negative speech. It does not reset at source boundaries. A short zero-error
background replay cannot certify an hours-long field false-wake rate.

For Vosk, reproduce policy outcomes using the actual Android JNI version before
changing the phone default. Python and Android library releases may differ.
Retain the loaded model when resetting recognition history at microphone/session
boundaries. Check real handset microphone input, locked-screen startup and
one-take buffering separately from classifier inference and server connection.
Model initialization, wake finalization and network startup are distinct timings.

`scripts/benchmark_vosk_sensitivity.py` tests detector-only bounded PCM gain and
40/80 ms partial-hypothesis stability. Its declared development cases attenuate
positive clips to half, quarter, one tenth and three percent amplitude, and pair
them with commands without the wake and near-confusables. The development policy
is frozen before original recordings are replayed. `--regression-only` can compare
all previously declared profiles while retaining that policy hash; it cannot
change the selection. Continuous speech uses one recognizer per gain, without
resetting at source boundaries.

Uniform attenuation preserves signal-to-noise ratio and does not reproduce a
distant microphone, noise suppression, automatic gain control or an Android
audio source. Gain may change endpoint behavior or quantization at very low
levels, but cannot recover phonemes already removed by microphone processing.
Higher gain can clip normal-volume input. Shorter stability confirms a hypothesis
sooner; it does not increase acoustic sensitivity. Prefer a measured microphone
source fix and actual raw RMS observations over assuming that a gain multiplier
will solve a handset problem. Keep captured and streamed PCM raw when testing
detector-only gain, and validate post-wake speech endpointing independently.

`scripts/benchmark_capture_speech_gate.py` evaluates capture endpointing separately
from wake detection. It reuses frozen activation times, simulates the actual
ambient-floor estimator, seeds 6400 voiced samples after a recognized wake and
checks the 1.2-second silence timeout and 30-second cap. It compares the former
450-RMS/2.8× gate with the quiet 80-RMS/2× gate. Longer synthetic one-take commands
help reveal clipping that short commands with late wake triggers may hide.
Speech-end estimates use the full-amplitude energy envelope, not manual phoneme
annotations; synthetic quiet variants may reuse a normal-volume wake time to
isolate endpointing. Keep these limitations explicit.

Background tests should distinguish noise already learned before capture from
noise that begins abruptly afterward. Freezing an energy-only noise floor during
capture can mistake an unlearned noise step for sustained speech until the cap.
Continuous real read speech may correctly keep a capture open; it is not a silence
test. Do not undo quiet-speech improvements merely to hide a synthetic noise case.
Collect actual microphone input before adding another threshold or stationary-
noise heuristic, and test any new endpoint policy for quiet-word truncation.

The [Voicute repository](https://github.com/voicute/onnx-wakeword) explicitly
describes its public project as inference-only and directs custom training to its
online service. Its published demo/model claims are author-reported synthetic
benchmarks. A small model or public repository does not establish an available
local trainer or permission to reuse source/weights; inspect the exact license
before integration. No vendor account is needed for the Vosk/Sherpa experiments.

[microWakeWord](https://github.com/OHF-Voice/micro-wake-word) provides an Apache2
training framework, streaming feature preprocessing and mixed depthwise
convolutions. Its authors warn that the basic training notebook is only a starting
point and is unlikely to produce a usable model. Adopting that trainer is a new
data/training experiment, not an automatic fix for insufficient real microphone
coverage.
