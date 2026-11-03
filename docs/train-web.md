# Train web app

`apps/train-web` is the installable Train client for iPhone and Android browsers. The relay serves it at `/train/` (see
"Standalone Train" in `docs/workout.md`). It has no build step and no runtime dependencies: plain ES modules, the Onest font
and the native glyph set copied from the Android app.

## Structure

- `app.js` boots: `GET me`, the join screen for an invite link, first-run setup when `setup_complete` is false, then the
  dashboard over the member's on-device store.
- `js/store.js` ports the Android `WorkoutStore`: revisioned entities and an ordered outbox with stable mutation IDs in
  IndexedDB, keyed by the member ID. Drafts of the live session and of a past-workout correction live there too.
- `js/live.js` is the live session and historical editor (set types, supersets, swipe to complete or delete, reorder,
  previous sets by kind, per-exercise kg/lb). `js/history.js`, `js/plan.js`, `js/coach.js`, `js/body.js` and
  `js/screen.js` hold the remaining screens; `js/setup.js` is the first-run flow.
- `js/chart.js` and `js/calendar.js` port the native chart (drag, hold to scrub, range chips, dashed gaps) and the history
  calendar (session colours, sprint bands, month bars).

## Rules

- The session is an HttpOnly cookie. Nothing secret goes in `localStorage`; it holds only the member ID and name for an
  offline start, the per-exercise unit swaps and the last known reminder settings.
- `sw.js` caches the static shell only. It never stores anything under `/train/api/`.
- Push subscriptions are created from a tap in Profile. On iPhone this works only from the Home Screen app, and members
  should join in Safari before adding it, so the cookie carries over.

## Local check

`scripts/train_web_fixture.py` serves the app over a throwaway relay seeded with invented athletes, synthetic gradient
photos and a stand-in coach, and prints one-use join links for a seeded member and for a new member:

```
python scripts/train_web_fixture.py --port 8790
```

Open the printed link in a phone-sized browser window. Never point it at real data.
