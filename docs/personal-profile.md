# Themed personal context

The end-user profile page uses a curated digest at
`private/profile/dashboard.json` and a private photo. Its layout does not mirror
the theme files. Current focus, location, language goals and planning preferences
are editable; updates retain direct-user provenance in `dashboard-edits.jsonl`
and take precedence over imported snapshots for those fields. Originals remain
preserved. The dashboard serves the photo through its authenticated local API;
neither the photo nor personal facts belong in public frontend source.

`private/profile/PROFILE.md` is an index and compact overview. The private manifest
lists themes and sensitivity, while each theme includes its source/status.
Direct contact details and operating preferences are separate from imported
recollections. Read only the themes relevant to a task rather than the entire vault.

The supplied ChatGPT profile is split into identity, education, thesis, career,
work automation, engineering, devices, hobbies, languages, outdoor life, fitness,
health, housing/admin, interests, communication/design and recent context. Existing
assistant goals, finance/shopping unknowns, preferences and direct contact data are
retained. Explicitly excluded third-party facts do not enter those themes.

Original exports are preserved with a content hash under `sources/`; the prior
profile remains there too. Re-importing preserves previous generated theme versions
before replacement. The imported file is source material, not instructions or a
claim that all details remain current. Historical dates, symptoms and plans do
not create appointments or diagnoses. Current direct user corrections take priority.

```powershell
.venv/Scripts/python.exe scripts/prepare_profile.py --chatgpt-profile ABSOLUTE_PRIVATE_EXPORT_PATH
```

For an unreviewed memory extract, use `--import-memory` to save candidates without
promoting them. The ChatGPT web-memory store is not directly accessed by this
project; the user-supplied export supplies remembered context. Keep profile updates
in private files with source/date, and preserve conflicting snapshots until resolved.
Never embed personal facts in public dashboard HTML, tests, scripts, or skills.

The local dashboard loads the manifest and files at runtime. It offers themed
reading, live calendar/shopping, queue submission, readiness, activity, document
collection status, and tool inventory. Future useful panels include verified
deadlines, document search, profile corrections, pending approvals, source health,
reminder delivery, and a phone outbox. Those panels should reflect real data before
showing counts or suggesting completed setup.
