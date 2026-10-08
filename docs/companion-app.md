# Companion app

The native companion groups everyday use into four pages: **Voice**, **Shopping**,
**Activity** and **Settings**. Appearance follows the phone by default, with manual
light and dark choices. Light mode uses tonal ivory and slate; dark mode uses
ink and plum. Periwinkle actions, muted blue setup icons and copper timeline
details give color a clear role. Soft gradients add depth to the circular voice
control. Brief press feedback, status/page fades and microphone-level smoothing
respect disabled system animations; there is no continuous idle animation. Live
updates change existing controls instead of replacing the screen, so typing and
scrolling survive synchronization and voice events.

Version 0.6 adds single-command acknowledgements, explicit conversation mode,
timestamped voice chat and native task history/continuations. These paths are
implemented and covered by isolated server/native tests; Firebase project setup,
registered-device delivery and physical-phone behavior need separate verification.

## Voice

**Talk** or one Hey Chat wake starts one request. The accepted request receives
one spoken acknowledgement; queued laptop work is read back as queued rather than
completed. After that reply, the phone returns to local wake standby when
background listening is on. Ordinary speech after the reply is not another
command.

Use **Start conversation** or say **start conversation mode** to enable continuing
turns. **That was all**, **that's all**, **end conversation**, or **End conversation**
in the app finishes the session without disabling the background wake setting.
Control phrases act only when they are the whole request. Later completion of a
queued task is available in its native task conversation; automatic spoken
completion is a separate backlog item.

**Background listening** keeps the local
Hey Chat detector running after leaving the app or locking the phone. Turn it on
while the app is visible and wait until the preparation indicator clears. The
microphone level shows input strength; it does not measure recognition confidence.
The voice page shows a timestamped chat with distinct request and response turns.
Queued-task links open the native task detail and continuation screen.

**Test wake** starts a local diagnostic session. Say Hey Chat at a normal volume,
then leave the app and repeat while the phone is locked. Detected wakes produce a
short vibration and increment the counter. This mode does not turn detections
into commands, open a speech-model session or save an upload. Finish the test to
restore the previous background-listening choice. Stop microphone exits both
conversation and test mode.

Balanced sensitivity retains the tested recognizer policy. Sensitive amplifies
only the detector input by two; it does not alter captured or uploaded audio.
It may help some quiet phrases, but it cannot recover speech already removed by
the microphone or guarantee recognition at a distance. Recognition input and
disabled standby noise suppression avoid applying call-oriented processing to
the wake stream. Command endpointing also accepts quieter speech than before.

Settings provides microphone permission, Digital assistant selection, notification
and battery shortcuts. Keep the phone's usual Home app. The microphone Quick
Settings tile gives a direct stop control; when Android cannot start the microphone
in the background, its start action opens the Voice page instead.

## Shopping and activity

Shopping uses the same cloud list as the widget and voice actions. New items and
completions appear locally while their stable mutation IDs wait for synchronization.
Slow network requests cannot hold the local queue lock and block a new edit.
Conflicting completions require review instead of silently changing a newer
cloud version. Cached recipes can add selected ingredients through the same queue.

Activity shows recent acknowledged voice requests and the number saved on the
phone awaiting upload. **Task history** opens native searchable history and task
details, including timestamps, answers and same-session follow-ups. Pairing
authorizes the owner's task history through the protected mobile API. Cached
details and unsent follow-up drafts survive a connection loss; stable follow-up
IDs prevent retries from creating a second turn. Phone-only storage, cloud
acknowledgement and task completion remain distinct statuses. Legacy browser
history remains available with its existing Home Assistant sign-in.

## Connection and updates

Internet availability describes the phone's network, not laptop readiness.
Pairing has immediate progress, retry feedback and an expired-code explanation.
Reconnection preserves cached data and pending changes. Install signed releases
over the existing app to retain its pairing, recipes and saved commands.

With Firebase configured and the phone registered, native event hints announce
task changes, reminders and releases. The paired app fetches the durable event
journal; push hints contain no task text. Tapping task Details opens the native
conversation, and Reply uses its existing continuation path. Home Assistant
supports the legacy channel and an older installation's migration hint.

The companion verifies an update's package, version, checksum and installed
signing identity before offering installation. Android still presents its
installation confirmation. See [native delivery setup](native-companion.md) and
[signed releases](releases.md).

Native emulator tests cover input preservation, local queues, navigation and
locked local diagnostics. Native Firebase registration, real notification
receipt/reply and update installation still need handset acceptance. Physical
microphone behavior, long locked sessions and battery consumption also require
handset measurements. The app does
not route confidential company work; that needs the separately approved work path.
