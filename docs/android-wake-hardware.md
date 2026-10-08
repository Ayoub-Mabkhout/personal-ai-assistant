# Android wake hardware access

The current companion uses a foreground microphone and a CPU wake detector.
Selecting it as Digital assistant enables system assistant entry points and
service lifecycle support; it does not establish access to Samsung's low-power
hotword DSP. The official
[VoiceInteractionService reference](https://developer.android.com/reference/android/service/voice/VoiceInteractionService)
describes the system-managed service lifecycle.

Android's `CAPTURE_AUDIO_HOTWORD` and `MANAGE_SOUND_TRIGGER` permissions include
the `role` protection flag as well as signature/privileged protection. They
should not be described as signature-only. `MANAGE_HOTWORD_DETECTION` is
internal/preinstalled, while enrollment management requires privileged
`MANAGE_VOICE_KEYPHRASES`. These declarations are visible in the
[AOSP framework manifest](https://android.googlesource.com/platform/frameworks/base/+/master/core/res/AndroidManifest.xml).

The ordinary assistant role's declared permission list does not include the
hotword capture and sound-trigger permissions. A separate system-only ambient
audio intelligence role includes them. The assistant is also marked
`requestable=false`, so the companion opens Default Apps settings for selection.
See the [AOSP role definitions](https://android.googlesource.com/platform/packages/modules/Permission/+/refs/heads/main/PermissionController/res/xml/roles.xml).

The legacy AlwaysOnHotwordDetector factory and newer trusted detector factories
are System API/hidden interfaces in current framework source. The trusted
service path requires `MANAGE_HOTWORD_DETECTION`. Their presence in a framework
does not make every factory usable through the ordinary public SDK. See
[VoiceInteractionService source](https://android.googlesource.com/platform/frameworks/base/+/master/core/java/android/service/voice/VoiceInteractionService.java).

## Actual API 35 capability check

A separate read-only probe app declared the relevant permissions, was assigned
the assistant role, and became the active VoiceInteractionService on the
official Google APIs x86_64 emulator. Normal role assignment granted none of
the four declared permissions:

| Permission | Runtime protection value | Granted after assistant selection |
| --- | --- | --- |
| CAPTURE_AUDIO_HOTWORD | 0x4000012 | No |
| MANAGE_SOUND_TRIGGER | 0x4000012 | No |
| MANAGE_HOTWORD_DETECTION | 0x404 | No |
| MANAGE_VOICE_KEYPHRASES | 0x12 | No |

The legacy factory methods were visible through ordinary reflection, but
`listModuleProperties` was unavailable to this SDK app. This is a query-access
result, not proof that a physical phone lacks DSP hardware. A read-only
`isKeyphraseAndLocaleSupportedForHotword` query returned false for Hey Chat and
Hey Google in en-US; no visible enrollment provider was found. The emulator
is not evidence of Samsung's enrollment or DSP capabilities.

The probe started no recorder, detector recognition, network connection or
enrollment. It changed no protected permission or hidden-API policy. The
companion role was restored after the isolated test. Runtime proof is retained
under ignored `state/voice/`.

## Optional Samsung check

`scripts/build_android_wake_probe.py` builds the small standalone debug APK from
`tests/android/wakeprobe/` into ignored `state/android-wake-probe/`. It has no
internet or recording permission, and the companion release does not include
it. If a phone hardware check is wanted, install it separately, select
**Assistant hardware probe** as Digital assistant, return to its page, and then
restore the previous Digital assistant. Only the user-driven default-app
selection is needed. Do not grant privileged permissions manually or change
hidden-API enforcement to manufacture a positive result.

A phone result may reveal OEM differences. Even an available module and an
enrollment provider would not make a generic ONNX keyword classifier a vendor
DSP sound model. Hardware offload requires supported enrollment and vendor
model integration. The
[AOSP voice interaction guide](https://source.android.com/docs/automotive/voice/voice_interaction_guide/app_development)
describes those dependencies for system-integrated automotive assistants; it
does not authorize them for an ordinary Samsung app.

Until a supported phone path is demonstrated, use the CPU detector and measure
screen-off battery drain against a matched baseline. Button Talk with wake
disabled skips model initialization and needs no continuous wake listener.

Current standby holds a partial wake lock for the listening service and reads
the microphone continuously at 16 kHz. The recorder blocks on 20 ms reads;
there is no standby network-polling loop, and detector weights stay loaded
across stream resets. Continuous audio, effects and CPU inference still consume
power and the wake lock prevents application-processor deep sleep. Emulator
latency and numeric parity cannot establish a Samsung overnight battery budget.
Measure actual screen-off drain before changing wake-lock behavior or claiming
low-power reliability.
