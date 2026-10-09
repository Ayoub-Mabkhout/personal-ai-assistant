# Listener battery measurement

Settings > Hey Chat battery shows what background Hey Chat listening costs on
the phone it runs on. It needs no root, computer or extra permission, and its
readings never leave the phone.

## What is recorded

`BatterySampler` appends one reading to a private app file
(`battery-samples.tsv`, at most 2000 rows) with wall and elapsed time, CPU
uptime, the whole-percent level, the charge counter in µAh where Android
reports it, charger, screen state, listener state (off, listening, or other
microphone use such as Talk and conversations) and the wake count.

Readings never wake the phone on their own:

- While `VoiceService` runs it already holds its partial wake lock, so a main
  thread timer adds a reading every 15 minutes, and runtime receivers add one
  at screen on/off and charger connect/disconnect, and at service start and stop.
- With listening off, the existing periodic sync job adds a reading when it runs.

The battery level comes from the sticky `ACTION_BATTERY_CHANGED` broadcast and
`BatteryManager` properties; wake detection, buffering, audio and recognition
are unchanged.

## How the number is computed

`BatteryUsage` (plain Java, tested by `tests/test_android_battery.py`) looks at
each pair of consecutive readings. The interval counts only when both ends are
unplugged, agree on listener and screen state, the clocks agree (no restart or
clock change), the gap is at most 12 hours, the battery did not rise, and no
wake or other microphone use happened in between. A listener-off, screen-off
interval also needs the CPU to have been awake for less than half of it;
otherwise the phone was probably in use between readings.

Counted intervals add up into three states: listening with the screen off,
listening with the screen on, and listener off with the screen off. Each rate is
total drop divided by total time. With a charge counter the rate is in mAh per
hour and converts to percent with a capacity estimated from counter and level
(median); otherwise the whole-percent level is used.

The listener's cost is the screen-off listening rate minus the listener-off
screen-off rate. A state needs two hours of counted time before it shows a
number. The wording follows the weaker side: early estimate under 6 hours,
estimate under 24 hours, steady estimate after that. Until a baseline exists
the sheet shows the total screen-off rate with listening on, which includes
normal standby drain. Differences under 0.05% per hour read as too small to
separate from standby drain.

## Getting a reading

Leave Background listening on for a few hours unplugged with the screen off,
for example overnight. For the baseline, leave it off for a similar unplugged
stretch. Reset measurements starts again, for example after an app or system
update changes the listener.

Limits: readings with listening off depend on when Android runs the sync job,
which needs a network; brief phone use between those readings can still slip
through the awake check and slightly raise the baseline. Samsung's own battery
screen attributes usage differently and is not used here.
