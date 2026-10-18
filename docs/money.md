# Money

Read-only money auditing for the owner's own bank accounts. The banks are read through a
licensed open-banking provider (Enable Banking, PSD2 account information). Nothing here can
move money.

## Architecture

| Part | Where | What it does |
|---|---|---|
| `banking/enablebanking.py` | laptop | Provider client: RS256 application JWT, `/auth`, `/sessions`, balances, paginated transactions. |
| `banking/ledger.py` | laptop | Private SQLite ledger (`~/.personal-assistant/banking/ledger.sqlite3`). Dedupe by bank reference; reference-less pending rows get a content hash and are marked gone when the bank stops listing them. Totals for the period. |
| `banking/agent.py` | laptop | The AI auditor. One headless, tool-less `claude -p --json-schema` call per batch of 80 undecided transactions. It decides kind, category, whether it counts against the allowance, links (transfer legs, payback to dinner, refund to purchase), reasoning, confidence and an optional one-tap question, plus up to five insights. It receives the code's totals and must quote them, never add up itself. It never overrides an owner decision. |
| `banking/service.py` | laptop | Link (consent through the relay), sync (at most 4 unattended fetches a day per account), owner answers, publish the summary. |
| `relay/banking.py` | server | Catches the bank redirect for a consent the laptop announced, hands the one-time code to the laptop once. Holds the latest summary for the phone and the owner's answers for the laptop. No provider key on the server. |
| `scripts/banking.py` | laptop | `status`, `link <bank>`, `sync`, `audit`, `run`, `summary`, `allowance`. |

The provider application file and private key live in the protected store outside OneDrive
(`~/.personal-assistant/secrets/banking/`). Owner context for the auditor (which account is used
for what, how income arrives) is the private `banking_notes` value in the worker configuration.

Decisions are the only judgement. Code only sums decided rows: allowance spent is the sum of rows
with `counts`, net is the sum of all rows except internal transfers and duplicates.

## Design

Style: geometric discipline (4/8/12/16/24/32 spacing, filled shapes instead of cards and rules)
in the assistant's Dusk Aurora palette (`docs/design-system.md`) and system sans. Figures use
tabular numerals. Dark theme first; the light theme maps the same roles.

### Overview screen (Companion and dashboard)

1. **Header.** Small "Money" caption, month name large (26/700, −0.6 tracking), a settings button.
2. **Aurora hero.** A 28px-radius panel with three soft radial aurora fields (`#6A44E6`, `#C2458A`,
   `#3B1E8C`) over `#1A1030`. Left: a ring (r 54, stroke 10) of elective spending, white up to the
   free-to-spend amount and rose `#FF8DB7` beyond it, the elective total in its centre. Right:
   "Free to spend this month", the amount at 30/700, and a chip with the state ("€X left · N days"
   or "€X over · N days left").
3. **Where it went.** A squarified block map of all spending in the period, area proportional to
   euros. Fixed costs (rent, insurance, phone…) form their own region in deep neutral tones with a
   small lock glyph. Elective categories run through the aurora from violet (largest) to rose.
   Blocks: 10px radius, 4px gaps, a faint top inner highlight, name, amount 16/600 and share.
   Small blocks drop the name, then the share. Tapping a block opens its category page.
4. **Fixed vs free.** A 14px stacked bar of a typical month's regular income: each recurring cost
   in its tone, then "Free" in a light lavender gradient. A two-column legend with dot, name and
   amount. The free amount is the default allowance.
5. **Auditor question.** One card at a time: aurora-gradient sparkle tile, the question, the
   evidence in one line, two full-width buttons (primary light, secondary dark), "1 of N".

### Category page

A header panel tinted with the category's two tones, a back pill, the category name, the total at
38/700, "N payments · avg €X" (fixed costs: "fixed, outside your allowance"), and an area chart of
the running total from the first of the period to today (white line, white-to-transparent fill).
Below, every payment grouped by date: a 36px rounded monogram tile (initials; paybacks and refunds
get a green return arrow), merchant, amount (green when money came back). Rows with an auditor
note show "Auditor note"; tapping any row expands the auditor's reasoning.

### Widget (2×2)

Free-to-spend per day, a proportional category strip, and the leading category.

### Allowance

Default: regular monthly income minus recurring costs, both decided by the auditor from history
(irregular top-ups that cover several months are spread over those months), recalculated each
period. The owner can pin a fixed amount instead.
