# Android companion

A native personal assistant app provides one-command voice capture, explicit
conversation mode, timestamped chat, task history and follow-ups, native push
notifications, shopping and recipes, an offline-first features checklist, a shopping widget, and requested alarm
handoff to the installed Clock application. Task details use the phone's paired
session and open inside the app.

Build with `scripts/build_android_companion.py`, the pinned Gradle wrapper and official Android SDK tools.
Build outputs live under ignored `state/`; the persistent signing key lives in
the protected OS-local secret directory outside the checkout. Gradle merges Firebase Messaging SDK resources, manifest
providers and consumer shrink rules; Analytics is not included. The wake
build adds a pinned Vosk Android runtime and generic model
assets; see [wake runtime setup](../../docs/android-wake-runtime.md). The signed APK is served from private cloud runtime
at `/groceries/v1/mobile/companion.apk`.

Release artifacts and metadata live outside tracked files. A compiled APK does
not establish handset behavior; emulator evidence and phone checks are recorded
separately. Personal recordings and experimental classifiers are excluded from
public builds.

Install and pair through the shopping web app's **Phone widget & alarms** button.
Add **Assistant Companion → Shopping list** from Android's widget picker.
See [phone setup and limits](../../docs/phone-companion.md). Compiled and signed
does not mean handset verified. Low-power scheduled refresh is approximate;
Refresh and foreground sync are available. Voice microphone use is opt-in and
visible through an ongoing notification. Wake listening is experimental and off
by default. Talk, transcription preview, durable offline capture and optional
live speech are available after pairing and microphone permission. A wake or Talk
handles one command and returns to standby. Say **Start conversation mode**, or
use the native button, to keep talking; say **That was all** to end it. The local
wake test never submits commands or starts a cloud conversation.

**Activity → All task history** searches saved requests and answers. Open a task
to see the original request and every follow-up in order. **Continue this task**
saves an instruction durably on the phone before sending it to the same laptop
session. Offline retries retain the same identifier, and typing survives task
updates. Its microphone button dictates into the draft without sending, and
**Talk about this task** sends each spoken turn as a follow-up of that task and
reads the answer aloud. No browser sign-in is required. Voice chat uses private, bounded local
storage; streaming revisions update an existing message with its first timestamp.

App releases use an authenticated publication hook to schedule a verified
download. Opening the app recovers missed events and prompts once for each new
downloaded version; **Later** leaves the install action in Settings. Android
requires user confirmation to install. If Android asks to allow installs from
this app, installation opens automatically when that permission is granted.
The build emits a release
metadata sidecar; publish it alongside the APK and run
`scripts/notify_companion_release.py`. Keep the signing key persistent so updates
preserve app identity and pairing. Native background push requires Firebase app
metadata in build configuration and server-side push credentials in a protected
store. The app displays registration state rather than assuming delivery. See
the phone setup guide for permission and deployment requirements.


## Build on another computer

Install Python 3.10+, JDK 17+ and Android SDK `platforms;android-35` and
`build-tools;35.0.0`. The official Gradle 8.11.1 wrapper verifies the distribution
checksum; Android Gradle Plugin 8.9.2 and Firebase Messaging 25.0.1 are pinned.
The Python CLI selects the host's SDK executables, stages generated inputs and
keeps Gradle caches/build output out of tracked files.

```powershell
python scripts/fetch_vosk_runtime.py --cache $env:TEMP/assistant-vosk --abis arm64-v8a --release
python scripts/build_android_companion.py --sdk $env:ANDROID_HOME --wake-runtime $env:TEMP/assistant-vosk/runtime.json --firebase-config EXTERNAL_GOOGLE_SERVICES_JSON --signing PROTECTED_SIGNING_DIRECTORY
```

The Firebase configuration file is optional for local development. It contains
public Android app identifiers and a public Firebase API key; generate its
resources from an external file rather than hard-coding account information.
Native background push needs this metadata plus the independently protected
server credentials. The APK never includes a service-account private key,
paired-phone bearer, or relay/worker credentials.

The local builder can create a first signing identity under the protected
signing directory. Preserve it for future updates. CI refuses to create a new
identity and requires existing `companion.p12` and `password.txt` files, alias
`companion`. `--require-existing-signing` applies the same check locally.

Release R8 rules preserve app/native wake reflection while shrinking SDK code
and resources. The selected runtime's ABIs constrain JNI packaging. Ordinary
ZIP entries use level-9 compression; native libraries and `resources.arsc`
stay uncompressed, then 16 KiB zip alignment and signing run. Every extracted
model file retains its declared SHA-256. The v6 bootstrap must remain below
50 MiB so the older updater can fetch it; future updater/feed limits are 64 MiB.
Diagnostic `--assets` builds are automatically marked non-publishable.
