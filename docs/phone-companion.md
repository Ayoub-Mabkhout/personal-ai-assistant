# Phone companion, shopping widget and alarms

Assistant Companion is the selected native Android interface for voice, shopping,
task history, same-session follow-ups, notifications and phone actions. It shares
the cloud shopping list, keeps a local cache and saved changes, and provides a
home-screen widget. The server, list and recipes remain available while the laptop
sleeps. The relay provides standalone browser login and native notifications.

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
standalone Assistant owner account, and choose **Phone widget & alarms**. Download
the APK and install **Assistant Companion**. Android may ask to allow installation
from that browser. Open the installed app and enter the HTTPS server origin and
the one-use pairing code shown on the groceries page. Pairing expires after ten
minutes; request a new code if necessary. The resulting device credential permits
shopping changes, voice commands, the owner's protected native task history and
continuations, and fetching that phone's actions. It cannot access another phone's alarm queue or use the raw agent administration
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
network job to fetch and verify the release from its paired server. Opening the
app checks missed events with a five-minute foreground throttle; Check for updates
remains available. Android requires ordinary installation confirmation and may ask
to allow installation from Companion. Background scheduling and force-stop state
can delay delivery; provider acceptance does not prove handset receipt.

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

## Alarms through the assistant

`scripts/phone_actions.py` uses `relay_url` and `submit_token_file` from the
protected worker config. No password/token is passed on the command line.

```powershell
.venv/Scripts/python.exe scripts/phone_actions.py phones
.venv/Scripts/python.exe scripts/phone_actions.py alarm --id UNIQUE_STABLE_REQUEST_ID --time 07:30 --label "Morning"
.venv/Scripts/python.exe scripts/phone_actions.py status UNIQUE_STABLE_REQUEST_ID
```

Only create an alarm explicitly requested by the user. Retain its ID on retries.
One active phone can be selected automatically; multiple phones require --phone.
Native events open the existing Clock-intent handoff. API acceptance, phone receipt,
intent delegation and verified Clock registration are distinct states. Android
permissions and lock-screen behavior require actual handset verification.
