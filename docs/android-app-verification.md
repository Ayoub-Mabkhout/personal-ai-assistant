# Android companion verification

The app's UI and source can be checked without paid speech APIs or a physical
phone. Use a disposable, unpaired API35 emulator and the existing protected
signing key. Test APKs and synthetic runtime records belong under ignored
`state/` or the external workbench; never publish replay/test APKs.

`scripts/build_android_ui_tests.py` builds real Activity instrumentation. It
checks pairing drafts/focus/selection through asynchronous updates, invalid
address validation, optimistic shopping/cache rendering and durable offline
adds, selected native recipe ingredients, separate transcript/reply panes,
microphone level binding, sensitivity selection, update-ready visibility and
background/local-test controls. It also covers the recipe sheet's Back
navigation and refusals, the timed Undo for ticked shopping rows (nothing is
queued inside the window; Undo, ticking another row and leaving the screen),
the shopping widget layouts in day and night mode and its Add shortcut landing
on the focused add field, and every Appearance choice. Its `theme` argument is
`light`, `dark` or `sun`; `sun` leaves the preference unset to exercise the
default. Its `screens_only` option captures views using explicit synthetic UI
data. `reduced_motion=true` additionally
requires the emulator animator scale to be zero and checks that page/meter
updates settle without a running animation. Restore the previous system scale
after the test. A visual-only run is not a functional-suite pass.

`VoskGainInstrumentation` runs a small actual Java/JNA/native control set. It
verifies balanced input is unchanged, Sensitive applies exactly 2x saturating
gain only to detector input, original/captured PCM is byte-exact, model weights
survive sensitivity changes and known positive/no-wake controls remain correct.
This is not a new full-corpus calibration or a battery benchmark.

The separately staged replay target runs the actual production recorder loop
against paced private PCM. `ReplayInstrumentation` with `local_test=true`
requires a secure, locked, screen-off emulator. It turns the Live preference ON
while local testing is active and asserts an actual wake count, no capture,
no saved envelope and no live-session attempt. Its source/sink overrides remain
only in the diagnostic APK. The normal app always reads its real microphone.

`UpgradeInstrumentation` is framework-only so it can seed a signed version4
install, then verify that a version5 install preserves synthetic pairing,
cached shopping data, a stable pending mutation ID and appearance preferences.
With `theme=unset` in both steps it leaves the preference unset and checks that
the upgraded app follows sunrise and sunset, the default since the Dusk Aurora
release; with no private coordinates cached that means the phone's System theme.
The fixture uses an empty server origin and cleans itself afterward. Do not
run it against a real paired phone.

`scripts/evaluate_android_storage.py` compiles the actual queue classes against
minimal JVM shims and a controlled transport. It reproduces blocked network
requests without opening a connection, checks that local shopping/voice saves
and pending counts remain responsive, protects concurrent queued additions,
verifies detached optimistic views and completion rebasing, and checks stable
Live acknowledgement history merging.

`TaskUiInstrumentation` also drives the history paging merge (Load more, refresh,
new search) and the Today and Yesterday separators across daylight saving
changes. `SolarUiInstrumentation` proves the appearance lifecycle on an unpaired
emulator with neutral drafts: a palette change waits for active voice capture,
an open dialog and installer handoffs, then recreates the screen with the
shopping or pairing draft, caret, focus, tab and scroll intact; an unset
Sunrise & sunset follows System without a timer; locked voice entry recreation
starts no recording. The sunrise and sunset maths (synthetic coordinates), the
solar boundary harness `tests/jvm/DaylightThemeHarness.java`, quick-add
splitting and voice status wording are plain Java and run in
`tests/test_android_jvm.py` wherever a JDK is installed.

Not covered by the emulator suites, so check by hand in light, dark and sun
themes after changing them: the assistant gesture overlay (it needs the
assistant role), the Quick Settings microphone tile and its subtitle, the
locked voice entry over the keyguard, and the notification small icon and
accent colour. Record the outcomes with the handset notes below.

Local instrumentation does not establish physical Samsung microphone quality,
overnight battery use, real account exchange or push delivery. Record actual
handset outcomes separately. Keep historical failed harness/AVD attempts distinct
from final passing evidence; emulator recovery is not an app behavior result.
