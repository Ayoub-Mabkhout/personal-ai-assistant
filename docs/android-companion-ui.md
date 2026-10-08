# Phone companion

The native app opens on Voice. Its bottom tabs are Voice, Shopping, Activity and
Settings. Theme follows the phone by default; Light and Dark can be selected
under Appearance. Light uses warm ivory and slate with plum/periwinkle accents; Dark uses ink
and plum with muted lavender. A layered circular Talk control anchors Voice,
Shopping uses an inline quick-add and compact rows, Activity uses a dated
timeline, and Settings groups compact icon actions. Tonal backgrounds and
short status/page transitions stay understated. Animation respects Android
animation disable; microphone interpolation uses actual input levels and does
not animate a synthetic listening pulse.

## Voice and locked operation

Talk starts one request or interrupts spoken playback. One acknowledgement is
spoken before returning to wake standby when background listening is enabled.
Start conversation explicitly to allow continuing turns; That was all or the
End conversation control finishes them without changing the wake setting.
Timestamped chat shows user requests and responses, with native task links for
queued work.

Background listening is a
separate desired setting for Hey Chat while the app is closed or the phone is
locked. If desired listening is on but microphone metrics are stale/off, the
app shows Listening paused and offers Resume listening. It does not infer
microphone activity from a persisted enabled flag alone.

Test wake runs the detector locally, displays the actual microphone level,
decoded words and wake count, and sends no commands or API requests. Test
temporarily keeps the listener running; Finish test restores the desired
background setting. Settings provides microphone, Digital assistant and app
battery shortcuts. Choose Unrestricted in the phone's app battery settings.
The app never selects a Home launcher or dismisses keyguard.

The locked voice entry uses the same theme, timestamped chat and
microphone meter. Android microphone permission must already be granted.
The Quick Settings microphone tile offers another explicit stop/resume entry.

## Shopping, recipes and history

Shopping projects pending local changes over the cached cloud list. Text entry
and focus survive asynchronous sync, voice updates and app update checks;
background callbacks update existing views rather than rebuilding forms.

The native recipe library reads cached recipes and pending recipe saves.
Choose a recipe, uncheck ingredients already available, and add the selection
through the same stable offline outbox. Recipe import previews existing shared
text through the server; it needs a connection. The web library remains an
optional route.

Activity lists recent durable voice receipts and opens native searchable task
history/details for reading answers or continuing the recorded worker session.
Settings retains pairing, notifications,
APK updates and widget setup. Pairing uses a separate connection thread so an
update download or shopping sync cannot delay its exchange. A failed/revoked
connection preserves cached lists and pending commands for reconnection.

## Verification

Native UI automation uses stable view tags, including `nav_voice`,
`background_listening`, `test_wake`, `resume_listening`, `server_address`,
`pairing_code`, `pair`, `shopping_item` and `recipe_add_selected`. UI tests run
on an isolated emulator with generic data and do not call paid voice APIs.
Light/dark screenshots, narrow screens and larger fonts are separate visual
checks. Physical Samsung microphone, locked service lifetime and battery
behavior still require handset observation.
