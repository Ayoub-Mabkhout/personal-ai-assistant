# Design system: Dusk Aurora

One visual language for the Android companion, the groceries PWA, the task pages
and the laptop dashboard. Light is warm ivory; dark is ink and plum. A single
aurora gradient is the signature and is spent sparingly: the voice orb, the
selected navigation pill and primary actions. Everything else is calm surfaces,
clear type and colour that means state.

## Colour tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `background` | `#FAF5EC` | `#130E1C` | Window and page |
| `surface` | `#FFFEFB` | `#1D1729` | Cards, sheets, nav |
| `surface-alt` | `#F3ECE4` | `#281F38` | Inset areas, pressed rows, fields |
| `text` | `#231A2E` | `#F5F0FB` | Primary text |
| `muted` | `#675C73` | `#ADA3BF` | Secondary text, inactive icons |
| `accent` | `#5B35D5` | `#B39CFF` | Links, selected state, focus |
| `on-accent` | `#FFFFFF` | `#1B1230` | Text on accent or gradient fills |
| `accent-soft` | `#ECE5FF` | `#2E2357` | Selected rows, chips, user bubbles |
| `stroke` | `#E7DDD3` | `#322849` | Hairlines and card edges (decorative) |
| `stroke-strong` | `#8E829E` | `#8479A3` | Field, checkbox and outlined-chip boundaries (3:1) |
| `success` / soft | `#17784A` / `#E0F2E7` | `#74DFA5` / `#173A2A` | Completed, saved to cloud, allowed |
| `warning` / soft | `#965800` / `#FFEFCF` | `#FFC766` / `#3E2D10` | Needs input, saved on phone, offline |
| `danger` / soft | `#B3263E` / `#FCE3E7` | `#FF8FA0` / `#44192A` | Failed, disconnect, permission denied |
| `info` / soft | `#3D52CC` / `#E3E8FF` | `#A4B5FF` / `#232B5C` | In progress, queued |

Aurora gradient stops: light `#5B35D5 → #A23BC6 → #CC3F78`, dark
`#8E6BFF → #C46CF0 → #F08FC4`, with a periwinkle glow `#8EA2FF` (light) and
`#8FA8FF` (dark). Buttons and the nav pill use only the first two stops
(violet to orchid). The rose stop appears only inside the voice orb, so dark
mode stays calm at night.

Every text pair meets WCAG AA (4.5:1 body, 3:1 large text and UI boundaries).
Status is never colour alone: chips pair colour with an icon and a word.

## Type

System sans (Roboto on Android, `system-ui` on the web). Weights 400, 500, 700.

| Role | Size / line | Weight | Tracking |
|---|---|---|---|
| Display (page title) | 32 / 38 | 700 | −0.6 px |
| Title (dialog, hero status) | 24 / 30 | 700 | −0.3 px |
| Heading (card title) | 17 / 24 | 700 | −0.1 px |
| Body | 15 / 22 | 400–500 | 0 |
| Small (meta, chips) | 13 / 18 | 500 | 0 |
| Label (section caps) | 12 / 16 | 700 | +0.9 px, uppercase |

Text sizes use `sp` on Android so they follow the user's font scale.

## Space, shape, elevation

- Spacing scale 4, 8, 12, 16, 20, 24, 32. Page gutter 20; card padding 16–20.
- Radii: icon tile 12, field 16, bubble 20, card 24, hero, nav and sheet 28,
  chips and pills fully rounded.
- Tap targets are at least 48 dp/px, including chips and inline actions.
- Light elevation: cards have a hairline `stroke` plus a soft plum shadow
  (Android: low elevation with an accent-tinted spot shadow on API 28+);
  floating nav and composer use a stronger shadow. Dark elevation: hairline
  plus a faint lavender top highlight; shadows are black and subtle.
- No blur is required anywhere; glass is a 1 dp top highlight on a gradient.

## Components

- **Voice orb.** Layered radial gradients (periwinkle glow, violet, orchid,
  rose) around a gradient core with a soft top-left sheen and a 1.5 dp inner
  light ring. Idle is static. While the microphone is live, the halo alpha
  (≈0.28 + 0.25 × level) and the layer scales (1 + {0.76, 0.5, 0.25} × level)
  follow the real input level. Working states show a determinate or
  state-bound indicator only while that work is actually happening.
- **Navigation.** Floating pill bar on `surface` with an aurora-gradient pill
  behind the selected item, which slides between tabs. Selected icon and label
  use `on-accent`; others use `muted`.
- **Buttons.** Primary: aurora fill, `on-accent` text. Tonal: `accent-soft`
  fill, `accent` text. Ghost: text only, still 48 dp tall. Destructive actions
  use `danger`. The Stop microphone action is always a strong, filled control.
- **Chips.** Status chips: soft semantic fill, semantic text and leading icon.
  Action chips: outlined with `stroke-strong`, 48 dp touch area.
- **Fields.** `surface` fill, 1.5 dp `stroke-strong` boundary, accent boundary
  when focused, radius 16.
- **Lists.** Checked shopping rows tint to `accent-soft`, draw the tick and
  strike, and offer Undo for 4 s before the change is committed.
- **Chat.** User bubbles right-aligned on `accent-soft`; assistant bubbles on
  `surface` with a hairline. Timestamps and state chips sit under the bubble.
- **Empty states.** Small vector illustration, a heading, one line of guidance
  and the next useful action.

## Motion

Motion responds to real events and the real microphone level only. There is
no synthetic listening pulse and no endless idle animation.

| Event | Motion |
|---|---|
| Press | Scale 0.97, 90 ms in, 160 ms out |
| Tab change | Pill slides 260 ms, ease (0.2, 0, 0, 1); page fades in while moving 20 dp from the direction of travel |
| Page or sheet enter | 300 ms, ease (0.05, 0.7, 0.1, 1) |
| Check item | Ring 140 ms, tick 180 ms, strike 220 ms, Undo hold 4 s, collapse 240 ms |
| New chat bubble | Rise 12 dp with fade, 220 ms, new entries only |
| Status text change | Crossfade 150 ms |
| Orb level | Attack 60 ms, release 220 ms, from measured input level |

With Android's animator scale at 0 or `prefers-reduced-motion: reduce`, travel
and scale are removed: state changes apply immediately or crossfade in under
100 ms, and the orb steps between level bands without morphing.

## Theme modes

Every surface offers **Sunrise & sunset** (the default), **System**, **Light**
and **Dark**. Sunrise & sunset uses a deployment's privately configured coarse
coordinates, fetched through an authenticated preferences API and cached for
offline use. A clone without these settings follows the device's System theme.
No location permission, GPS or external geolocation service is involved. The
solar calculation uses the sun's upper limb at −0.833°; open screens switch at
the next transition and recheck when they return to the foreground. Android and
web surfaces use the same runtime location, never a place baked into source.

## Platform notes

- Android draws everything with framework Views, `GradientDrawable`, and
  Canvas shaders. No extra libraries, fonts or bitmaps, because the release APK
  must stay below the 50 MiB bootstrap limit.
- Web pages carry the same tokens as CSS custom properties, resolve their theme
  from the stored mode before first paint (Sunrise & sunset by default;
  System follows `prefers-color-scheme`), and stay self-contained under each
  page's CSP (no external fonts or scripts).
