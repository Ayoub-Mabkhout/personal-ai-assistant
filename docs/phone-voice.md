# Phone voice

Native Companion owns Talk, the local Hey Chat detector and rolling capture
buffer. One wake captures one request, acknowledges acceptance once through
Android TTS and returns to standby when background listening is enabled.
Conversation mode starts explicitly; end-conversation phrases leave the background
wake setting intact. Unmatched requests enter the existing Luna agent queue.

Configured cloud STT uses the protected voice provider/key/model and budget.
The retired Wyoming Whisper/Piper and Home Assistant pipelines are unavailable.
Missing STT configuration fails clearly instead of sending audio elsewhere.
See [custom voice](custom-phone-voice.md), [native delivery](native-companion.md)
and [architecture](architecture.md). Physical microphone, locked-service lifetime
and battery tests remain separate from emulator and replay validation.
