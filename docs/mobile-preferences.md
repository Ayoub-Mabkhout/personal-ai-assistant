# Private daylight preferences

Companion's Sunrise & sunset appearance calculates the sun's position locally
from an explicitly configured latitude and longitude. It requests no location
permission and performs no location lookup or tracking. A new deployment has no
coordinates: Sunrise & sunset follows the phone's System theme until configured.
Light, Dark and System choices remain available. While no coordinates are
configured, the Appearance dialog labels the choice "Sunrise & sunset · System
until configured" and the Settings row reads "Sun · System".

The paired, read-only `GET /groceries/v1/mobile/preferences` endpoint uses the
existing phone bearer credential and returns only:

```json
{"daylight": null}
```

or a `daylight` object with finite `latitude` and `longitude` numbers. The response
is private and not cacheable by intermediaries. Revocation disables access.
Missing, malformed, oversized or incomplete configuration returns `null`.

The relay reads `companion-preferences.json` beside `phones.sqlite3` by default.
`ASSISTANT_MOBILE_SETTINGS_CONFIG` can select another protected external file.
Keep this file outside source control and synced document folders, with restricted
access for the relay service account. Configure the actual owner's chosen place
privately; do not copy it into app source, public docs or APK build configuration.
This neutral example is only a file-shape illustration:

```json
{"daylight": {"latitude": 0.0, "longitude": 0.0}}
```

Phones fetch these optional preferences through task recovery, at most hourly.
An unavailable or older server leaves the last valid cache in place; a successful
`null` response clears it. Re-pairing or disconnecting clears the prior cache.
Settings fetch failures do not fail task delivery or erase drafts.

The groceries web view receives the same whitelisted settings with its
authenticated list snapshot; task pages use owner-authenticated
`GET /tasks/v1/preferences`. A task's view or follow-up capability does not grant
access to those preferences. Web views cache only the coordinate pair for offline
appearance and use the shared solar controller.

The local dashboard's token-protected `GET /api/preferences` is a separate reader
with its own file, on the laptop rather than the relay host. It reads the optional
`mobile_settings_file` runtime input; `~` is expanded, a relative value is resolved
against the dashboard process's working directory (the repository checkout under the
supervisor, so an absolute path is safest), and an absent, null or empty value
selects `companion-preferences.json` in `runtime_dir`. Configuring the relay file
or `ASSISTANT_MOBILE_SETTINGS_CONFIG` does not configure the dashboard. A missing
file is the unconfigured state and answers `null`. A file that exists but cannot be
read right now (locked, access denied, not a file) answers `503` instead, so the
open page keeps its last cached place rather than clearing it; the next page load
retries. The page does not poll.

Whenever a preferences file is unreadable, oversized, not valid JSON, or holds
missing or out-of-range coordinates, a one-line warning naming only the reason is
written to the service log (the dashboard's `dashboard-service.log` in its runtime
directory when run by the supervisor). It never contains the path or any file
content. A syntactically valid file with no `daylight` entry is simply unconfigured.

The foreground activity evaluates its appearance on resume, clock/date/timezone
changes, configuration changes and private preference updates. A timer targets
the next sunrise or sunset; polar conditions receive an hourly reevaluation.
Automatic palette recreation waits until pairing/sync/update work, active voice
capture, dialogs and installer handoffs are idle. Shopping and pairing drafts,
selection, tab and scroll position survive the refresh. Voice entry recreation
does not request a new recording. Background activities run no theme timer.

The calculation uses the apparent sunrise threshold of 90.833 degrees of zenith
and checks neighboring solar cycles around UTC date boundaries. These are
approximate visual theme transitions, not precision astronomical events. See
[NOAA's equations](https://gml.noaa.gov/grad/solcalc/solareqns.PDF) and
[USNO rise/set definitions](https://aa.usno.navy.mil/faq/RST_defs).
