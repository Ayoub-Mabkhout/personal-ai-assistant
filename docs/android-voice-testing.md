# Android voice verification

## Command and conversation policy

Normal wake/Talk uses one buffered capture and one authoritative spoken receipt,
then returns to local wake. Explicit start controls enable continuing conversation;
“That was all” ends it. Local wake test remains action-free in either mode.
`VoiceService.START_CONVERSATION` and `END_CONVERSATION` expose the same controls
to the UI; `voice_conversation_mode` reports the actual transient mode and resets
on service destruction. The old `voice_live` preference does not make ordinary
commands continuous. `VoiceChat` stores private stable-ID role entries and keeps
the first timestamp when a streaming entry is revised.

`tests.test_phone_voice` and `tests.test_voice_context` run isolated ASR/provider
fakes to verify exact start/end controls, unchanged substantive requests, request
readback, direct groceries, durable deduplication, transcript-driven Live end,
and absence of unsolicited completion polling. They make no paid API calls.
The emulator-only replay runner additionally accepts `-e mode_policy true`.
It injects isolated receipts through the real `VoiceService` acknowledgement path,
counts intercepted TTS replies, verifies no default follow-up, explicit conversation
follow-up and end controls, and checks zero live/outbox submission. The normal APK
contains no receipt injection or replay service.

The companion includes one microphone owner, an interchangeable offline wake
detector, a two-second rolling buffer, durable voice commands, chained
transcription/Android TTS and optional live conversational audio. An APK build
and JVM replay do not establish Samsung microphone, locked-screen or battery
reliability.

## Reproducible free checks

`tests/java/VoiceReplay.java --buffer-only` exercises the exact Java classes used
by the APK. Sample order must match byte for byte after transport delays of
0, 1, 3 and 10 seconds. Recorder capture does not wait for network connection.

`scripts/build_android_voice_tests.py --fixtures PRIVATE_DIRECTORY` builds a
separate instrumentation APK with the same protected signing identity as the
companion. The private directory contains `template.pcm`, `positive.pcm` and
`negative.pcm`:
16 kHz mono signed PCM16 little endian, without a WAV header. The tests exercise
the installed APK's buffer, actual native wake adapter when packaged, and
durable WAV envelope. A real positive fixture also runs through the native
detector and command buffer together. The actual Live client queue splits a
two-second pre-roll into ordered 100 ms messages and verifies both the
server's frame limit and byte-for-byte reassembly. Tests do not call OpenAI or
mutate the cloud.

`tests/java/WakeBoundaryReplay.java` exercises the actual `WakeStreamGate` and
template detector. A wake prefix before skipped capture/TTS/transport audio
must not combine with a suffix from a different turn; a contiguous phrase must
still work. The gate resets temporal context exactly once before resumed
monitoring. Models remain loaded, so this does not add model warm-up to Talk.
Android instrumentation additionally splits a real wake clip across that
boundary and compares native resumed decisions with a fresh suffix stream.
The observed suffix produced zero activations, retained the same native model
object and replaced only acoustic/encoder stream state.

On a disposable Android emulator, install the companion and instrumentation
APK with the SDK's `adb`, then run:

```text
adb shell am instrument -w -r com.personalassistant.companion.tests/com.personalassistant.companion.VoiceInstrumentation
```

The output names the wake engine; `template-test-only` verifies the experimental
test fixture and is not a native neural wake result. No personal templates are
included in the public production APK. Provision official SDK system images
outside OneDrive; never change host virtualization or BIOS settings automatically.

Verified on the official API 35 Google APIs x86_64 emulator with WHPX: native
Sherpa wake replay, original no-wake negative, ordered capture, Live queued frame
limits, persistent WAV envelope and foreground microphone readiness. The
Digital assistant role was assigned and bound; the system Assist key launched
the companion voice session. With a test-only PIN and the secure keyguard still
locked, the system Assist key started Talk. A normal assistant-role rebind,
performed outside instrumentation, also started local wake monitoring and its
microphone foreground service while the device remained locked. The test PIN
was cleared and the preferences restored. These checks used no paid API
requests; they do not establish Samsung microphone, power or OEM behavior.

`scripts/build_android_keyguard_tests.py` builds the separate emulator-only
lifecycle test. `KeyguardInstrumentation` refuses physical phones and paired
devices. Its `cold` mode verifies that button voice with wake disabled does not
load a neural runtime: microphone readiness measured 242 ms on the API 35
emulator. Wake mode still provisions the detector, and enabling wake on an
existing button session loads it once idle. The virtual microphone is silent;
recorded fixtures are replayed separately into the actual native detector.

The service tries an optional packaged custom OpenWake model before the Sherpa
adapter; missing assets/runtime fall through to the next adapter. Wake-off Talk
skips both. The lifecycle test's `selection` mode takes `expected_detector` and
checks the actual foreground service's selected adapter on an unpaired,
preview-only emulator. A diagnostic model used for integration checks must not
be mistaken for an approved wake classifier or published in a phone release.
Actual service selection passed for the packaged custom raw-mel CNN adapter
with activation disabled. Wake-off microphone readiness on that same target
measured 247 ms and reported `Wake disabled`; neither model runtime was loaded
by the cold Talk path. This validates integration, not that classifier's wake
accuracy.

For optional hardware capability diagnostics, see
[Android wake hardware access](android-wake-hardware.md). A selected Digital
assistant and a working foreground microphone are separate from access to a
vendor's low-power hotword DSP.

## Locked entry and warm capture

The keyguard callback now starts a lightweight show-when-locked Activity,
following the [official callback contract](https://developer.android.com/reference/android/service/voice/VoiceInteractionService#onLaunchVoiceAssistFromKeyguard()).
It shows voice controls and starts Talk when resumed, without requesting device
unlock. Late assistant-ready signals after shutdown/destruction are ignored.

Secure API 35 screen-off tests directly invoked the actual callback: the
Activity appeared above keyguard and started capture while the device stayed
locked. One cold run measured 444 ms to Activity creation, 1997 ms to microphone
readiness and 2190 ms to first PCM. Specialized SystemUI affordance delivery and
Samsung behavior remain handset checks; generic Assist keys use other paths.

Enabled wake monitoring survived 30 seconds screen-off with the same process.
A deliberate emulator crash recovered to a new process with active monitoring
while screen-off. This does not establish recovery after user force-stop,
reboot before first unlock or Samsung restrictions.

`build_android_replay_target.py` and `build_android_replay_tests.py` create a
separate, publication-blocked diagnostic target and runner. Its test-only
subclass feeds private PCM through the exact production recorder thread,
detector, capture loop and buffer, and intercepts submission without a cloud
call. The public APK contains neither subclass nor fixture. Any compatible
native detector can be exercised by passing its runtime to `--wake-runtime`.

Warm replay stayed screen-off/locked and retained 70,400 samples exactly.
Detection-to-capture improved from 262 ms to 28.4 ms after moving haptic/UI work
off the microphone thread and starting capture first. Endpoint interception was
3.716 seconds after detection, including remaining speech and silence. This
tests the actual loop with injected PCM, not the Samsung microphone or network
latency. Cold Activity startup is separate from continuously listening wake.

The frozen Vosk adapter also passed the same production-loop screen-off replay:
24.8 ms detection-to-capture and 70,720 exact samples, before the following
counter correction. A diagnostic delayed decision after speech ended exposed
an existing bug: buffered speech was ignored by the post-trigger voiced gate,
so capture never submitted. Recognized wake now seeds that minimum voiced
count. The fixed delayed case retained 51,200 exact samples and finalized after
1.2 seconds of PCM silence, with a 31.8 ms capture transition. Manual Talk fed
pure silence still canceled without submission. These checks intercept the
cloud sink; wake-only handling remains the backend's existing `no_command`
path. Very short manual/follow-up words are outside these tests.

## Phone setup and acceptance

Version 0.5 uses recognition input consistently, disables standby noise
suppression, and displays actual microphone level and local recognizer partials.
The local **Test wake** flow counts detections with haptic feedback while
preventing new captures from becoming commands or speech-model sessions.
Previously saved voice uploads defer while this mode is active.

Free host sensitivity checks found no generic quiet-replay improvement from
boosting 1x to 2x: all forty positive cases passed even at 3% amplitude. The
optional 2x profile recovered one original isolated wake at quarter volume;
3x/4x added a confusable trigger without more benefit, so they are excluded.
These are decoder replays, not distance or microphone-processing measurements.

The capture energy gate now uses an 80 RMS minimum and twice the learned noise
floor. Three longer synthetic commands attenuated to 3% retained their endings;
the old 450 RMS gate cut an estimated 1.34-1.90 seconds from their tails.
Speech boundaries were estimated and wake timing reused from normal-volume
replay. Both gates ended learned stationary noise after 1.2 seconds. Abrupt noise
starting after a quiet wake can keep the new gate open to the existing 30-second
cap; actual-phone checks should include this case. Live mode uses the server's
speech detection once connected rather than this local endpoint gate.

Install the signed APK over the old companion without uninstalling. Pair it to
the same server, grant microphone permission and select **Digital assistant**
using the app's button. Keep Samsung One UI Home as the Home app. Allow the
ongoing microphone notification; its Stop control turns listening off.

First enable transcription preview and test Talk without creating shopping
items or dispatching tasks. Then test Hey Chat with the entire command in one
take, both quiet and outside, and compare the displayed transcript. Preview
forces the chained transcription path even if Live mode is selected.

Test wake monitoring with the screen locked, calls, Bluetooth, permission
revocation, process termination and battery saver. A microphone interruption
stops capture and asks the user to reopen the app. Do not claim unattended
process recovery or Alexa-like fidelity until those handset tests pass.

Disconnect the internet during a chained command. The app must say the command
is saved on this phone, preserve its ID and audio through process restart, and
obtain exactly one cloud result when reconnecting. A Live session that reached
the server is not automatically replayed after loss of connection: tools may
already have executed. Existing task notifications remain the result channel.

Finally measure false wakes over several hours, first-word retention in thirty
one-take commands, latency and battery against a matched screen-off baseline.
Synthetic and augmented recordings provide repeatable regression coverage;
they do not replace physical microphone and representative noise recordings.
