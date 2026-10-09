# Phone companion, shopping widget and alarms

Assistant Companion is the selected native Android interface for voice, shopping,
task history, same-session follow-ups, notifications and phone actions. It shares
the cloud shopping list, keeps a local cache and saved changes, and provides a
home-screen widget. The server, list and recipes remain available while the laptop
sleeps. Home Assistant supports legacy voice/browser access and migration delivery.

Source and build tooling are implemented. Native Firebase project configuration,
phone registration and real notification delivery require deployment acceptance.
Installing, pairing, native task screens, widget rendering and Clock handoff on
the actual handset still require verification. An APK build or server request is
not a handset test.

## Build and install

Use JDK 17 or newer and the official Android SDK with `platforms;android-35` and
`build-tools;35.0.0`. The builder invokes the pinned Gradle/AGP project; Android
Studio is optional. See [Android build setup](../apps/android/README.md) and
[signed release automation](releases.md):

```powershell
.venv/Scripts/python.exe scripts/build_android_companion.py --sdk PRIVATE_ANDROID_SDK_DIRECTORY
```

The default APK is under ignored `state/exports/assistant-companion.apk`. Signing
material stays in `%LOCALAPPDATA%/PersonalAssistant/secrets/android-signing`,
outside OneDrive. Keep the same key for app updates; replacing it requires
uninstalling and risks losing the phone's saved changes. The generic APK contains
no account token or personal server address. Version 0.6 retains the Voice,
Shopping, Activity and Settings pages, themes, microphone meter and local wake
test, and adds one-command readback, explicit conversation, timestamped chat and
native task history/details/continuations. Native push requires external Firebase
Android client configuration at build time and protected server configuration.
See [the app guide](companion-app.md) for everyday flows. The physical-handset
build includes ARM64 native libraries and generic wake-model assets, rather than
personal voice recordings.

Once the APK is deployed, open the cloud `/groceries/` page, sign in with the
existing Home Assistant account, and choose **Phone widget & alarms**. Download
the APK and install **Assistant Companion**. Android may ask to allow installation
from that browser. Open the installed app and enter the HTTPS server origin and
the one-use pairing code shown on the groceries page. Pairing expires after ten
minutes; request a new code if necessary. The resulting device credential permits
shopping changes, voice commands, the owner's protected native task history and
continuations, and fetching that phone's actions. It cannot administer Home
Assistant, access another phone's alarm queue or use the raw agent administration
endpoints. Do not share codes.

Long-press the Android home screen, choose **Widgets**, then **Assistant
Companion**. Its shopping widget shows up to six unchecked items, the cached sync
time and saved-change status. Tap an item to mark it bought, **Refresh** to request
sync, or the title/add control to open the app. Opening/refreshing syncs promptly;
periodic background sync uses Android JobScheduler and is subject to battery and
network scheduling. It is not continuous polling or an immediate push-updated
widget. Offline changes remain saved until the connection returns. Review
conflicting changes in the app rather than overwriting newer cloud versions.

The native recipe picker uses cached recipes and queues selected ingredients
through the same offline shopping outbox. The cloud **Recipes and import** page
remains available for editing and imports. Shared text can also open the native
app's parsed recipe preview before saving. See the recipe/AnyList migration
documentation for the preview-and-import workflow; existing AnyList data is not
automatically deleted.

## App updates

With Firebase configured and the phone registered, releases arrive through the
native durable event journal and a content-free FCM hint. The app schedules a
network job to fetch and verify the release from its paired server. An older
installation can receive a migration hint through official Home Assistant
Companion's existing `command_broadcast_intent` receiver. Opening the app also
checks for a missed event, with a five-minute
foreground throttle; **Check for updates** remains available. Scheduled shopping
sync retries a pending update download but does not check for new releases.

Install the release with this receiver manually once; version 0.2.0 has the older
daily updater and version 0.1.0 has no updater. Future releases appear under **App updates**.
Enable update notifications if desired, then tap **Install update** when ready.
Android may ask to allow installations from Assistant Companion and still requires
the normal installation confirmation. Background checks depend on Android job
scheduling and network availability; push acceptance is not proof of handset
delivery. The Home Assistant phone app is needed for the legacy migration bridge;
configured native FCM delivery works independently. Android can delay delivery or
prevent a force-stopped app from running.

Downloads are checked against the published checksum, package, version and the
installed app's signing certificate before installation. Updates retain the same
app identity and signing key so pairing and local data can be preserved. The
release feed and previous APK were deployed and verified; push-triggered native
installation on a handset remains to be tested. Voice development is documented
separately in `docs/custom-phone-voice.md`.

The [tag-based release workflow](releases.md) publishes the exact signed APK and
its `.release.json` sidecar through a narrow authenticated HTTPS endpoint, then
records an update event. Diagnostic and private-fixture APKs cannot be published.

For a legacy manually staged release, the existing authenticated hook remains:

```powershell
.venv/Scripts/python.exe scripts/notify_companion_release.py state/exports/assistant-companion.release.json
```

The hook checks the downloadable artifact against the exact version and checksum,
rejects changed bytes under an already published version, and saves a durable
push request. Retries of the hook do not produce another accepted push. Failed
provider calls retry with backoff and survive server restarts; phone notifications/downloads
also deduplicate by version. A crash after the provider accepts a push can cause a
duplicate hint, which safely fetches the same verified release. Status is available
to the owner at `GET /groceries/v1/mobile/release/status`. Never publish a new APK
under the same version code. The APK and metadata remain public generic artifacts.

The bridge follows the official [HA broadcast notification command](https://companion.home-assistant.io/docs/notifications/notification-commands/#broadcast-intent).

## Alarms through the assistant

`scripts/phone_actions.py` uses the existing worker Home Assistant refresh-login
file referenced by protected `~/.personal-assistant/worker/config.json`. It does
not read the owner password or require passing a token in the command line.

```powershell
.venv/Scripts/python.exe scripts/phone_actions.py phones
.venv/Scripts/python.exe scripts/phone_actions.py alarm --id UNIQUE_STABLE_REQUEST_ID --time 07:30 --label "Morning"
.venv/Scripts/python.exe scripts/phone_actions.py status UNIQUE_STABLE_REQUEST_ID
```

The alarm command is an actual write; examples should only be executed for an
alarm the user requested. Preserve its ID on retries. If exactly one active phone
is paired it is selected; otherwise ask which phone and add `--phone PHONE_ID`.
Time is a 24-hour HH:MM in the phone Clock's local timezone. This initial interface
supports a single alarm time and label, not arbitrary dates or recurrence.

The configured native provider delivers a phone-scoped alarm event and a
notification that opens Assistant Companion to fetch the queued request. The
legacy Home Assistant provider offers its existing **Set alarm** button. Both
paths hand it to the installed Clock app through `ACTION_SET_ALARM`, with hour, minute,
label and `EXTRA_SKIP_UI`. The phone keeps an action-ID journal to avoid blindly
launching an acknowledged alarm twice. If it crashes during a handoff whose
outcome is uncertain, inspect Clock before submitting another request.

The legacy `--launch` option requests an immediate app launch using HA Companion's
`command_activity`. Enable it only after the user grants **Display over other
apps** to the official HA Companion in Android settings. Android lock-screen,
background-activity and manufacturer restrictions can still affect launching.
The button path does not require granting that background-launch permission.
The native Companion cannot be launched this way: with native delivery `--launch`
still produces the tap-to-set-alarm card.

An alarm request remains valid for ten minutes. If the phone is offline longer,
it expires rather than unexpectedly setting the next day's alarm. A cloud
`queued` receipt means the request is saved; `push_api_accepted` means the selected
provider accepted the wake-up notification. `delegated` means the app handed the
intent to Clock. **None proves Clock registered the alarm.** The response explicitly retains
`clock_registration_verified: false`; inspect the actual Clock alarm on the first
handset test. `failed` and `expired` require a corrected/new request. No live test
alarm is inserted automatically.

[Android AlarmClock intent contract](https://developer.android.com/reference/android/provider/AlarmClock).
[HA Companion activity launch and Android permission](https://companion.home-assistant.io/docs/notifications/notification-commands/#activity).
