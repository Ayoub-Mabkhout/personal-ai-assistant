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
- Companion's **Correct** confirms the auditor question, and **Not quite** opens an
  editable text/dictation clarification. Both enqueue evidence for the same auditor;
  they do not freeze the old category. The auditor decides the resulting category,
  links and recurring fields, with newer owner edits taking precedence. Ambiguous
  answers keep a follow-up question visible.
- **Ask the money specialist** opens one persistent chat with timestamped replies,
  cached history and earlier-message pagination. A failed send retries its saved ID.
  The laptop checks interactive requests every 15 seconds while its service is
  running; unattended bank syncs retain their separate minimum six-hour interval.
  No model is called when the audit queue is empty.
- Scheduled summary publication includes up to twelve previous periods within the
  imported history, including empty periods between transactions. The phone's month
  heading opens a picker; past periods show their own total and elective spending,
  without applying the current month's allowance or days remaining.
- `summarise` exposes `regular_income_cents`, `recurring_costs_cents`,
  `free_to_spend_cents`, `payday_aware_net_cents`, `category_transactions`,
  `recurring_breakdown`, `fixed_costs`, `fixed_cost_transactions` and `adjustments`
  alongside the existing keys.
  `categories` includes all period spending categories, net of linked reimbursements and explicit
  offsets; `spent_cents` includes only decisions marked `counts` and off-bank offsets.

## Design

### Transaction display enrichment

Bank fields remain the source of record. Separate `transaction_annotations` rows
hold `display_title`, `merchant_name`, `merchant_brand_id`, `annotation_note`, tags,
confidence, evidence and author. Neither annotations nor logos alter the amount,
date, bank wording or financial classification. Owner annotations take precedence
over later auditor suggestions, independently of owner accounting decisions.

The same persistent auditor can enrich a bounded selection without re-auditing it:

```sh
python scripts/banking.py --config PRIVATE_CONFIG enrich --request-id display-batch-1 --id TRANSACTION_ID --limit 12
```

This only enqueues work. Repeating the request ID reuses the same selected IDs and
jobs. Add `--run` to process one enrichment-only batch of at most twelve rows, with
no bank fetch. Other accounting jobs remain queued. Unknown merchants keep a null
brand ID; logos use only curated catalog keys supported by original bank wording,
with confidence at least 0.85. The auditor never supplies a logo URL. Current and
historical public transaction views include the annotations alongside unchanged
`counterparty` and `description` source fields.

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


## Live specialist tools and merchant logos

The persistent auditor receives a lease-scoped, local stdio MCP server on every
run. `transactions_search` pages/searches all imported months;
`transaction_annotations_write` saves descriptive edits atomically while preserving
owner annotations and bank/accounting facts; `merchant_logo_fetch` downloads and
caches a merchant website icon; `enhancement_status` verifies saved coverage.
A question can use these tools directly, without asking the owner for IDs or
waiting for a separately prepared enrichment list. Tool changes and the final reply
use the same Money conversation. Private CLI traces are retained next to the ledger.

Logo fetches send only a known merchant website domain to Google's favicon endpoint,
not transaction/account data. Unknown domains remain unknown. Valid bounded PNGs
and their domain/evidence/source are stored in the private laptop ledger. Publishing
projects them into immutable SHA-256-addressed cloud assets and replaces inline bytes
with `{cache_id, url}` metadata. Downloads require the normal paired-phone token.
The phone prefetches twelve common merchants, fetches other visible marks on demand,
verifies SHA-256 and bounded dimensions, then reuses its disk cache offline. New logos
and changed logo hashes are data updates; they require no new APK. Existing bundled
marks and monograms remain fallbacks. Cache storage is reclaimable Android cache.
