# Money

Read-only money auditing for the owner's own bank accounts. The banks are read through a
licensed open-banking provider (Enable Banking, PSD2 account information). Nothing here can
move money.

## Architecture

| Part | Where | What it does |
|---|---|---|
| `banking/enablebanking.py` | laptop | Provider client: RS256 application JWT, `/auth`, `/sessions`, balances, paginated transactions. |
| `banking/ledger.py` | laptop | Private SQLite ledger (`~/.personal-assistant/banking/ledger.sqlite3`). Dedupe by bank reference; reference-less pending rows get a content hash and are marked gone when the bank stops listing them. Additive migration preserves existing decisions. Ordered audit jobs, leases, replies, explicit off-bank adjustments and period arithmetic live here. |
| `banking/agent.py` | laptop | One persistent headless Codex auditor session, resumed for ordered batches of up to 80 jobs. It has no shell tools or workspace. It decides meaning, recurring status, monthly amounts and income coverage. A dated ledger narrative rebuilds context if its session cannot resume. Code computes totals; owner decisions prevail. |
| `banking/service.py` | laptop | Link (consent through the relay), sync (at most 4 unattended fetches a day per account), durable owner answers, local question and explanation requests, publish the summary. |
| `relay/banking.py` | server | Catches the bank redirect for a consent the laptop announced, hands the one-time code to the laptop once. Holds the latest summary for the phone and the owner's answers for the laptop. No provider key on the server. |
| `scripts/banking.py` | laptop | `status`, `link <bank>`, `sync`, `audit`, `run`, `summary`, `allowance`. |

The provider application file and private key live in the protected store outside OneDrive
(`~/.personal-assistant/secrets/banking/`). Owner context for the auditor (which account is used
for what, how income arrives) is the private `banking_notes` value in the worker configuration.

Decisions are the only judgement. Code sums decided rows. The default allowance is monthly
regular income minus recurring costs; `scripts/banking.py allowance AMOUNT` pins a manual
amount. A late payment covering several months has a monthly amount and explicit coverage months.
`net_cents` is period bank cash flow; `payday_aware_net_cents` replaces actual recurring flows
with their monthly amounts and adds confirmed off-bank offsets. No bank row is fabricated for cash
or shared-cost repayments.

## Auditor and integration contract

- New bank rows enqueue `transaction` jobs in the same SQLite transaction as the row. An upgrade
  also queues undecided and legacy AI-decided rows for recurring review. Existing owner decisions
  remain authoritative. Phone answers are committed locally before their relay sequence is acknowledged.
- `audit(ledger, config)` returns `(decided_count, insights)`. A single SQLite lease fences each
  model response. An expired or superseded response cannot write decisions. Jobs and the session ID
  survive process restart. The Codex session is OS-local private state; no live model call is needed
  for `summarise`.
- `service.ask_question(ledger, request_id, text, transaction=None)` and
  `service.explain(ledger, request_id, transaction, text='')` enqueue idempotent requests and
  return a job sequence. After `audit`, read `ledger.audit_output(sequence)`. Stable request IDs
  prevent duplicate jobs.
- `service.record_offset(ledger, id, day, kind, amount_cents, category, linked, reason, source)`
  records a confirmed `cash_offset` or `shared_cost_offset`. It is idempotent by ID and appears
  in `adjustments` and `category_transactions` as an off-bank record. The caller supplies explicit
  provenance; no synthetic bank transaction is inserted.
- Companion's **Confirm** accepts the auditor's answer, and **Correct** opens an
  editable text/dictation clarification. Both enqueue evidence for the same auditor;
  they do not freeze the old category. The auditor decides the resulting category,
  links and recurring fields, with newer owner edits taking precedence. Ambiguous
  answers keep a follow-up question visible.
- **Ask the money specialist** opens one persistent chat with timestamped replies,
  cached history and earlier-message pagination. A failed send retries its saved ID.
  The laptop checks interactive requests every 15 seconds while its service is
  running; unattended bank syncs retain their separate minimum six-hour interval.
  No model is called when the audit queue is empty.
- `summarise` exposes `regular_income_cents`, `recurring_costs_cents`,
  `free_to_spend_cents`, `payday_aware_net_cents`, `category_transactions`,
  `recurring_breakdown`, `fixed_costs`, `fixed_cost_transactions` and `adjustments`
  alongside the existing keys.
  `categories` includes all period spending categories, net of linked reimbursements and explicit
  offsets; `spent_cents` includes only decisions marked `counts` and off-bank offsets.

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
