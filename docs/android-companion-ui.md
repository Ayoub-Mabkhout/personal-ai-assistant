# Phone companion

The native app opens on Voice. Its bottom tabs are Voice, Shopping, Activity and
Settings. The Dusk Aurora design system in `design-system.md` defines tokens,
type, glyphs and motion. Appearance offers Sunrise & sunset (default), System,
Light and Dark. Sunrise & sunset uses explicitly configured private coordinates
and follows System when none are configured; see
[private daylight preferences](mobile-preferences.md). Only the foreground
screen watches for the next transition, and it recreates itself for a new
palette once pairing, sync and update work, installer handoffs, an active voice
session and dialogs are idle; drafts, selection, tab and scroll position
survive. A layered circular Talk orb anchors
Voice, Shopping uses an inline quick-add and compact rows, Activity uses a dated
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

Chat uses the shared Dusk Aurora bubble faces, with a timestamp below each
message and a semantic state chip for queued and status entries. Task actions
keep a 48 dp touch target; a streaming revision updates its bubble in place,
keeps its original timestamp and does not replay entry motion. Task history and
continuations are full-screen sheets. Native task notifications and the
microphone tile use the monochrome vector assets.

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

The locked voice entry uses the same theme, orb, status wording, timestamped
chat and microphone meter as the Voice tab. Android microphone permission must
already be granted. The assistant overlay shows the same state on a themed card.
The Quick Settings microphone tile offers another explicit stop/resume entry.

## Shopping, recipes and history

Shopping projects pending local changes over the cached cloud list. Text entry
and focus survive asynchronous sync, voice updates and app update checks;
background callbacks update existing views rather than rebuilding forms.

The Shopping widget's Add button opens Companion on the Shopping tab with the
add field focused and the keyboard up; the title opens the default tab.

The native recipe library is one full-screen sheet with list, recipe and import
pages; the system Back key goes up one level. It reads cached recipes and pending
recipe saves. Choose a recipe, uncheck ingredients already available, and add the
selection through the same stable offline outbox. Recipe import previews existing
shared text through the server; it needs a connection. The web library remains an
optional route.

Activity lists recent durable voice receipts and opens native searchable task
history and a task conversation, as full-screen sheets, for reading answers or
continuing the recorded worker session. Task bubbles match the Voice chat.
Settings retains pairing, notifications,
APK updates and widget setup. Pairing uses a separate connection thread so an
update download or shopping sync cannot delay its exchange. A failed/revoked
connection preserves cached lists and pending commands for reconnection.

## Verification

Native UI automation uses stable view tags, including `nav_voice`,
`background_listening`, `test_wake`, `resume_listening`, `server_address`,
`pairing_code`, `pair`, `shopping_item`, `recipe_add_selected`,
`task_followup_input`, `task_voice_dictate` and `task_voice_talk`. UI tests run
on an isolated emulator with generic data and do not call paid voice APIs.
Light/dark screenshots, narrow screens and larger fonts are separate visual
checks. Physical Samsung microphone, locked service lifetime and battery
behavior still require handset observation.
