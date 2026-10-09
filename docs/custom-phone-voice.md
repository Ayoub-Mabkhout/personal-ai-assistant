# Custom phone voice design

Status: native capture, local wake interface, durable command outbox and explicit
conversational speech implemented. Reliability targets below remain targets.
The companion is the selected phone interface and connects directly to the relay. Native notifications require
Firebase client/server configuration and device registration, then handset
verification. Select the custom app as **Digital assistant**
when testing it. Keep Samsung One UI Home as the **Home app**.

## Wake detection and capture

The prepared wake runtime uses Vosk's streaming English recognizer with **Hey Chat**
and a fixed contrast grammar, which gives similar phrases their own competing
recognition paths. Stable partial text triggers capture before the rest of the
command finishes. It remains experimental and off by default: recorded replay is
stronger than the previous Sherpa runtime, while wider confusable speech still
causes errors. Generic model assets contain no personal recordings. The optional
Sherpa adapter remains available for separately built comparisons.
Personal DTW templates were evaluated and rejected as a default detector; they
are not included in the publicly downloadable APK.

Porcupine's native Android SDK is a possible comparison, with a custom **Hey Chat** model.
It supports custom keyword models and caller-supplied audio frames. This is a
candidate to measure. Its AccessKey,
model generation and acceptable current licensing must be established before
shipping this integration. Its current [pricing FAQ](https://picovoice.ai/docs/faq/general/)
offers an enterprise trial and says there is no dedicated personal-use plan;
do not assume free ongoing use or make it a dependency without suitable pricing.
No paid plan is selected. Keep the detector replaceable;
openWakeWord with a custom TFLite model is the open-source alternative.

One phone microphone recorder feeds both the detector and a two-second rolling
audio buffer. On detection, capture continues immediately while the network
connection starts in parallel. Send buffered audio first, then new frames, with
no gap or duplication. The user can say the wake phrase and command in one take.
Connection latency may delay the answer but must not lose the first command words.
Audio is not continuously streamed to the cloud while waiting for the wake phrase.

Use VoiceInteractionService and a session service for the default-assistant role,
plus the supported microphone lifecycle. Do not assume privileged low-power DSP
access. Display accurate off/listening/capturing/connecting/unavailable states.
Handle calls, microphone permissions, Bluetooth changes and process interruption.
Keep one recorder owner; the UI and network consume its frame queue.

One wake or **Talk** normally captures one command. The backend returns one
authoritative acknowledgement, the phone speaks it once, then returns to local
wake monitoring. Ordinary speech after that response is not another command.
Shopping and other programmed actions run directly in the cloud. Unmatched
requests enter the laptop queue; the acknowledgement reads back the request,
for example, “Queued command to the laptop: find my latest invoice.”

Say **“start conversation mode”** or **“let's talk”**, or use the conversation
button, to enable continuing turns. **“That was all”**, **“that's all”**, and
**“end conversation”** return to local wake monitoring. A phrase must be the
whole request to act as a control; “email Sam that was all I needed” remains a
normal request. Stopping a conversation does not disable background wake.

During explicit conversation, retain the connection and microphone for follow-ups. Tune
silence detection to tolerate pauses, prevent self-triggering from spoken replies,
and support interruption. Stop after an explicit end or idle timeout. Return to
local wake monitoring. Sensitivity and available noise/echo processing need actual
phone measurements rather than assumptions.

## Server and commands

The authenticated `/groceries/v1/mobile/voice` endpoint accepts bounded mono
16 kHz PCM16 WAV captures with stable IDs, creation time and timezone. It uses
OpenAI mini transcription, with existing cloud Whisper as a free fallback.
The optional `/groceries/v1/mobile/voice/live` WebSocket accepts continuous PCM16
with paired-device authentication and a server-owned API key. The server can
select Realtime conversational speech or GPT-Live using `conversation_provider`.
Realtime preserves resampling phase between packets, runs server speech detection,
returns backend action receipts and resets phone playback when the user interrupts.
The phone continues capturing while either provider connects.
Reuse the same shopping store,
calendar and task queues. Programmed behavior runs directly; everything unmatched
defaults to Luna without a dispatch prefix.

Give each captured command an ID before upload. Offline capture persists locally
and replays the same envelope on reconnect, preserving time/timezone and expiry.
Distinguish phone-only storage from cloud acknowledgement and task completion.
The general voice outbox is implemented separately from shopping changes. A
capture persists before upload, and a lost HTTP acknowledgement retries the same
ID. Live connection failure after session startup is uncertain and must not
automatically replay the conversation's actions.

OpenAI conversational speech uses those same cloud tools. Keep
wake detection independent of the speech provider. Model access, credentials,
billing and the current transport contract need verification before changing models.
Factual questions
and actions default to the persistent Luna queue; native shopping and connection
queries run directly. Voice receipts and bounded conversation history live in the
private relay ledger, and selected history reaches workers without replacing the
exact latest request.

The server's configured budget reserves conservative transcription cost for each
attempt and maximum conversational-session cost before opening a connection.
Defaults are $8 per UTC month, ten minutes per GPT-Live connection and five minutes
per Realtime connection. Realtime reserves $0.30 per minute conservatively, then
reconciles returned token usage and a separate transcription allowance. The ledger is an application
estimate, not an authoritative provider invoice; other API clients use a separate
budget. Local transcription remains available if this budget is reached.
API keys stay outside OneDrive locally and in restricted server runtime files;
`config/local/voice.env` contains a local file reference. APKs contain no provider key.

## Installation and verification

Install the current APK, pair it from the shopping page, allow microphone access,
and use **Talk** first. Enable **Transcription preview** for no-action checks.
Start local wake listening while the app is visible; its ongoing notification
shows microphone state and provides Stop. Android permissions, foreground-service
rules and Samsung battery settings can affect locked-screen operation. Select the
app as Digital assistant if desired, never as the Home app. Only one wake listener
should own the microphone during comparisons.

Command mode uses Android TTS for its single receipt and never starts follow-up
capture. Explicit conversational mode uses
the selected speech provider, continuous microphone streaming and device echo cancellation
when available. A saved legacy `voice_live` switch no longer changes command mode.
Transcription preview forces the non-live path and performs no actions. The live
session has a duration cap and explicit end; an idle chained conversation closes
after 30 seconds. Neither live provider polls queued tasks to speak their later
completion. Selective spoken completion, a fast path for suitable questions and
a lightweight local or fast acknowledgement model are backlog items; no model
or new runtime is configured for them. Network
failure, queue acceptance and task completion are distinct states.

User recordings and generated/augmented evaluation fixtures remain under ignored
`state/voice/`. Preserve source-family splits: augmentations of training templates
are not independent held-out evidence. JVM replay verifies actual ring/capture
ordering under delayed connection; physical microphone, lock-screen behaviour
and overnight false activation/battery require handset trials.

[OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text),
[GPT-Live WebSockets](https://developers.openai.com/api/docs/guides/voice-websockets),
and [client delegation](https://developers.openai.com/api/docs/guides/live-delegation).

## Prototype and evaluation

Build wake detection and buffered capture before the full conversational interface.
Test locked-screen operation and one-take commands with a deliberately delayed
server. Compare builds using the same phrases and locations, with
only one wake listener enabled at a time.

Measure missed wakes, false activations, first-word loss, recognition errors,
response delay and battery separately. Include quiet rooms, streets, shops,
public transport, airplane mode, calls, battery saver and overnight idle.

Initial acceptance targets, not promises:

- At least 95% wake detection in quiet and 90% in representative street/shop trials.
- Fewer than one false activation per eight hours.
- No first-word loss in 30 one-take command trials.
- Local acknowledgement within 200 ms after a detector trigger.
- No more than three additional battery percentage points in an eight-hour
  matched screen-off trial.

If software monitoring misses the battery target, investigate supported hardware
detection and retain a button/gesture fallback. Alexa-like reliability is not
established until these handset measurements pass.

## Primary references

- [Porcupine Android SDK](https://github.com/Picovoice/porcupine/tree/master/binding/android)
- [Custom wake-word quickstart](https://picovoice.ai/quick-start/wake-word-android/)
- [openWakeWord](https://github.com/dscripka/openWakeWord)
- [Sherpa open-vocabulary keyword spotting](https://k2-fsa.github.io/sherpa/onnx/kws/index.html)
- [Android voice-interaction service](https://developer.android.com/reference/android/service/voice/VoiceInteractionService)
- [Microphone service restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)
- [Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations)

## Buffered connection startup

The socket batches microphone samples into 100 ms packets and bounds its backlog
to 60 seconds. A slow connection must not discard the first words or overflow a
queue sized in tiny 20 ms packets. The `start` event reports the actual
`buffered_audio_seconds` (bounded to 0–60); the server accounts for those earlier
samples alongside elapsed connection time. Existing clients default to two seconds
of pre-roll. Partial packets flush before a graceful stop. Exact byte-order tests
cover delayed readers and the explicit overflow boundary; capture fallback retains
audio when a connection fails before acknowledgement. An acknowledged conversation
remains uncertain on disconnection and is not automatically replayed.
