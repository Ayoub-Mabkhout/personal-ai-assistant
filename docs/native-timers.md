# Native voice timers

In command mode, say “Hey Chat, set a timer for five minutes” or “set a timer for
one hour and thirty minutes”. Minutes, hours and seconds, singular/plural,
decimal quantities, common English number words and mixed units are parsed by
the Android app. “Half an hour” and “one and a half hours” work. The duration
must be a whole number of seconds between one second and 24 hours; invalid
timer requests ask for a duration and never enter the laptop agent queue.

Wake detection and buffering are unchanged. **Speech transcription still needs
internet and the configured cloud OpenAI speech provider.** This is not offline
speech recognition. There is no Whisper/Home Assistant fallback. Once recognized,
the timer runs entirely on the phone: no Luna, laptop wake, server deadline or
internet is needed for its countdown or completion alert. Current Realtime and
legacy Live conversation modes wait for the phone's actual timer receipt before
the speech provider gives the acknowledgement. A missing receipt reports
uncertainty and never claims the timer started.

The native notification shows a countdown and Cancel. Tapping it opens the timer
details and cancellation control. Completion posts an alarm-sound notification
through Android's Voice timers channel; the user's channel, sound and Do Not
Disturb settings still apply. This is a notification alert, not a continuously
ringing full-screen Clock alarm. Timers do not start when Companion notifications
or that channel are blocked.

For precise sleep/lock-screen delivery, tap a timer notification and choose
**Allow precise timers**, then grant Android's Alarms and reminders access. With
access, the app uses `setExactAndAllowWhileIdle`; without it, it uses
`setAndAllowWhileIdle` and explicitly says the alert may be delayed during sleep.
Android can batch non-exact alarms substantially, and throttles idle alarms even
with exact access. Do not treat the inexact fallback as a precise kitchen timer.
Force-stopping Companion, revoking alarm/notification access, and phone shutdown
can prevent alerts. Opening voice or a timer screen repairs saved active timers.

A durable phone ledger stores the stable voice command ID, original duration,
elapsed-time deadline and reboot fallback deadline before scheduling. Retries
and reconnects reschedule that same alarm without restarting the duration.
Reboot/app update and exact-access grant rebuild active alarms; overdue timers
post their completion alert. Commands recognized more than two minutes after
capture are rejected rather than unexpectedly starting after an outage.
Cancellation is durable and a late alarm cannot revive a cancelled timer.

**Use Clock instead** is an optional explicit foreground action in timer details.
It sends Android `ACTION_SET_TIMER` with the remaining whole seconds, a duration
label and `EXTRA_SKIP_UI=false`. The native countdown stops after the intent is
delegated. Check Clock to confirm registration: Android exposes no result proving
Clock accepted or started the timer. The app saves a handoff claim before launch
and never automatically repeats an uncertain handoff. A locked/background phone
never triggers a blind Clock activity launch; unlock before choosing this action.

The [Android Clock contract](https://developer.android.com/reference/android/provider/AlarmClock)
defines seconds/label and 1–86400 second bounds. Android documents
[exact alarm access and idle delivery](https://developer.android.com/develop/background-work/services/alarms/schedule).

Validation uses `tests/test_android_timer.py`, mocked voice routing/Live contracts
and `TimerInstrumentation` on an unpaired disposable emulator. Build its app with
`scripts/build_android_companion.py --workspace state/timer-build --signing
state/timer-signing --output state/exports/timer-qa.apk`, then build the test APK
with `scripts/build_android_timer_tests.py`. Test APKs and signing files stay in
ignored state and must never be published. Emulator scheduling and synthetic
recognized text do not establish real Samsung speech, battery, long-idle alarm,
reboot or handset delivery quality; check those on the handset separately.

Wake capture keeps short commands through a pause after Hey Chat: the wake prefix
does not count as new command speech, a short wake command retains a five second
window and no new speech times out after eight seconds. Recognized wake-only
receipts allow the next command for thirty seconds after the listening reply.
A bounded screen wake cue follows capture start, keeps the keyguard locked and
never launches a background Activity. If Android refuses display wake, the
haptic cue remains.
