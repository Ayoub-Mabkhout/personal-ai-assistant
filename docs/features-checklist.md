# Features checklist

One shared list of the assistant's planned features. Checking an item marks it
implemented and moves it from the open list into **Finished**; unchecking moves it
back. The relay hosts the list in `features.sqlite3` beside its queue database
(`/data` on the server), so the Companion reaches it over mobile data and the
laptop dashboard reaches it through the relay. A new deployment starts empty.

## API

Both mounts share one store and one contract. Responses are `private, no-store`.

| Client | Base path | Authentication |
|---|---|---|
| Companion app | `/groceries/v1/mobile/features` | Paired phone token, `Authorization: Bearer pa_mobile_…` (as other `Cloud.call` routes) |
| Dashboard and scripts | `/v1/features` (through the HTTPS `/relay` path) | Relay submit credential |

- `GET <base>` returns `{"revision": int, "items": [...]}`. Each item has `id`,
  `title` (1–200), `detail` (0–1000), `area` (`companion`, `dashboard` or
  `assistant`), `done`, `done_at` (Unix seconds or null), `created` and `updated`.
  Open items come first in creation order, then finished items, newest first.
  `revision` rises with every effective change.
- `POST <base>` with `{"id"?, "title", "detail"?, "area"?}` creates an item
  (`201`). The ID is optional; a client may generate one (8–64 letters, digits,
  `_` or `-`, so a UUID fits). Repeating a known ID returns the stored item (`200`)
  unchanged, so an offline outbox can replay safely. Edits use PATCH. The default
  area is `assistant`.
- `PATCH <base>/{id}` with any of `done`, `title`, `detail`, `area`. `done: true`
  sets `done_at` once; repeating it keeps the original time. `done: false` clears
  it. An empty change returns the item unchanged.
- `DELETE <base>/{id}` returns `{"deleted": true}`, also for an unknown ID.
  A deleted ID is remembered: creating it again returns `409`, so a late replay
  cannot bring an entry back.
- `POST <base>/{id}` equals PATCH and `POST <base>/{id}/delete` equals DELETE,
  for HTTP stacks without PATCH (Android `HttpURLConnection`).

Invalid bodies, wrong types (`"done": "true"`), unknown fields or a blank title
return `422`. An unknown or malformed ID returns `404`. Missing or wrong
credentials return `401`; the phone token is rejected on `/v1/features` and the
submit credential on the phone mount. A revoked phone loses access immediately.
Fields merge per request, so checking an item on the phone and renaming it on the
dashboard do not overwrite each other.

## Dashboard

The **Features** page lists open items with checkboxes, an add field with an area,
and a collapsible **Finished** section with its count and each finish date.
Checking draws the tick and strike, then moves the row to Finished; unchecking a
finished item moves it back. A failed change is rolled back with a message. A new
entry keeps its ID in the browser until the relay confirms it, so a retry cannot
add it twice. Removing asks for a second press.

## Initial list

There is no seeded content. To import a private starting list, write a JSON list
under ignored `state/`, for example `state/features.json`:

```json
[{"title": "Example feature", "detail": "Optional note", "area": "companion", "done": false}]
```

```powershell
.venv/Scripts/python.exe scripts/import_features.py --file state/features.json
```

The script uses the worker config's `relay_url` and `submit_token_file`. Entries
without an ID get one derived from area and title, so a repeated import adds
nothing twice, never overwrites later edits or checks, and does not revive
deleted entries.
