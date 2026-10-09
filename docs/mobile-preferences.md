# Private daylight preferences

Companion's Sunrise & sunset appearance calculates the sun's position locally
from an explicitly configured latitude and longitude. It requests no location
permission and performs no location lookup or tracking. A new deployment has no
coordinates: Sunrise & sunset follows the phone's System theme until configured.
Light, Dark and System choices remain available. While no coordinates are
configured, the Appearance dialog labels the choice "Sunrise & sunset · System
until configured" and the Settings row reads "Sunrise & sunset · System".

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
access to those preferences. The local dashboard's token-protected
`GET /api/preferences` reads its `mobile_settings_file` runtime input, defaulting
to `companion-preferences.json` in its runtime directory. Web views cache only the
coordinate pair for offline appearance and use the shared solar controller.

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
