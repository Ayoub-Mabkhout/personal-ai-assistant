# Phone voice entry points

Use native **Assistant Companion** as the selected voice interface. Pair the app,
grant microphone permission, and try **Talk** before enabling **Background
listening**. Select it as the phone's Digital assistant for the supported system
entry point, while retaining the usual Home app. Gesture details and locked
microphone behavior need verification on the actual phone.

One Hey Chat wake or Talk captures one command and speaks one accepted readback.
Programmed actions can complete directly; laptop requests are acknowledged as
queued. The app then returns to local wake standby if background listening is
enabled. **Start conversation** or a whole-request **start conversation mode**
enables continuing turns; **That was all** ends them without disabling wake.
Timestamped chat and native task history keep acknowledgements and task completion
separate. See [everyday app controls](companion-app.md) and
[voice implementation and verification](custom-phone-voice.md).

The generic Vosk Hey Chat detector remains experimental and off by default.
Emulator and recorded replay checks do not establish physical microphone quality,
locked service lifetime or battery consumption. A gesture/shortcut remains a
useful fallback. Native Firebase notifications are a separate delivery channel:
they require client/server configuration and device registration, then actual
handset receipt tests.

## Legacy and alternative entry points

Home Assistant Companion remains available for its existing Assist and legacy
notification paths. Its Android setup uses Settings → Companion app → Assist for
Android; the default-assistant choice belongs to whichever interface is being
tested. Its optional wake words and the custom app's Hey Chat detector are
configured separately. [Home Assistant's Android setup](https://www.home-assistant.io/voice_control/android/).

Selecting ChatGPT as Android's default Digital assistant gives it the system
assistant entry point. That selection alone does not configure **Hey Chat**, a
connection to this relay, or our offline command queue. Test button/gesture startup
with a securely locked phone separately from keeping an already-started voice
conversation active. Actual Samsung behavior remains unverified.

A ChatGPT plugin exposing groceries and queued tasks is a possible separate
integration. Custom-tool availability in the installed Android Voice experience
must be verified before choosing it as the command interface. The fetched
[official ChatGPT Voice page](https://learn.chatgpt.com/docs/features/voice)
documents desktop and Codex iOS behavior; it does not establish Android custom
wake words or this integration. Do not infer those capabilities from it.

The native Android client implements explicit conversations, a list widget,
phone-side offline queues and controlled command dispatch. Start
microphone capture through a visible activity or supported assistant/notification
entry point, use a microphone foreground service during the session, and stop it
when the session ends. Do not promise silent background microphone activation.
[Android foreground-service restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start).

The native client uses an authenticated speech bridge with the configured
Realtime or GPT-Live provider, metered API charges and a server-owned credential.
Its speech path connects to the existing stores and Luna queue; see the
[official voice-agent architectures](https://developers.openai.com/api/docs/guides/voice-agents)
and [custom voice implementation](custom-phone-voice.md). Home Assistant retains
its existing Whisper/Piper pipeline. Emulator capture, secure keyguard entry and
native runtime checks passed; actual S22 wake reliability, battery use and long
conversations remain unverified.

## Current Home Assistant recognition

The cloud Wyoming service uses `base-int8`, five decoding beams, two CPU threads,
Silero speech filtering and a short general command-vocabulary prompt. Its default
language is automatic; Home Assistant's existing English pipeline still explicitly
supplies English. Select/configure another pipeline language when needed; automatic
service fallback does not make the English intent sentences multilingual.

On the existing ARM server, four controlled synthetic clean/noisy clips were
transcribed correctly with these final settings in roughly 1.6 seconds per clip.
The tiny baseline made six word edits; the small model matched correctly but took
roughly 4.5–4.8 seconds after warm-up. These are narrow synthetic checks, not a
benchmark of real accents, competing speakers or wind. An actual HA STT-only
pipeline run also returned the expected transcript without executing its intent.
Phone microphone/public-place verification remains necessary.

`ASSISTANT_WHISPER_MODEL` overrides the model in the private server environment;
the default is `base-int8`. Restart only the Whisper service after changing it.
The pinned image and cached models stay in the existing speech volume. No OpenAI
API key or additional billed service is used. `scripts/benchmark_speech.py` runs
inside that speech container; use `--fixtures` to reuse identical audio when
comparing models. It sends no commands to the conversation engine.
