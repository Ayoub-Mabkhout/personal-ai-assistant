# Personal assistant

An extensible assistant with its own calendar, headless integrations, execution
history and phone interface. Public reusable code and an ignored private
workspace share this checkout.

The selected phone interface is the native Assistant Companion, backed by an
always-on HTTPS relay and an outbound laptop worker. It provides local wake
capture, offline queues, shopping, task history and same-session follow-ups.
Standalone relay login and native notifications replace the retired Home Assistant stack. Phone access works over the internet; shared LAN discovery is
unnecessary. Host details, provider configuration and credentials stay outside
public source files. A clone does not inherit a deployed owner's connections.

- [Architecture and implementation sequence](docs/architecture.md)
- [Running costs](docs/costs.md)
- [Repository layout and private storage](docs/repository-layout.md)
- [Calendar commands](docs/calendar.md)
- [Connectivity and source integration design](docs/connectivity-and-integrations.md)
- [Server deployment and phone connection](docs/server-deployment.md)
- [Laptop worker and local dashboard](docs/laptop-services.md)
- [Read-only mail and document collection](docs/mail-ingestion.md)
- [Per-task coding environments](docs/coding-workbench.md)
- [Themed personal context](docs/personal-profile.md)
- [Phone shopping and recipes](docs/groceries.md)
- [Shared features checklist (Companion and dashboard)](docs/features-checklist.md)
- [Android and extended voice options](docs/phone-voice.md)
- [Custom wake-word and buffered capture design](docs/custom-phone-voice.md)
- [Receiving-only WhatsApp bridge](docs/whatsapp.md)
- [Agent inbox and persistent Luna dispatcher](docs/task-dispatch.md)
- [Phone task updates and answers](docs/phone-task-status.md)
- [Replying to task notifications](docs/notification-replies.md)
- [Cloud calendar reminders](docs/calendar-reminders.md)
- [Background mail collection and follow-ups](docs/mail-automation.md)
- [Phone widget and alarms](docs/phone-companion.md)
- [Phone scripting through Termux (Claude/Codex/shared CLI)](docs/termux-bridge.md)
- [Companion app and local wake testing](docs/companion-app.md)
- [Native task history, notifications and Firebase setup](docs/native-companion.md)
- [Signed releases and GitHub Actions](docs/releases.md)
- [AnyList recipe migration](docs/anylist-migration.md)

## Feature tracker

Keep this checklist current when a feature ships. Checked means implemented and
validated at the level stated; physical-phone outcomes and provider setup have
separate checks. Unchecked means remaining work. Ideas below are a backlog, not
configured services or a commitment to build everything. Keep personal details
and runtime evidence in the ignored private workspace.

### Working

- [x] Remote HTTPS phone access through the standalone relay.
- [x] Durable cloud queues: programmatic commands and agent prompts stay separate.
- [x] Laptop startup, reconnect, readiness reporting and interrupted-task recovery.
- [x] Persistent Luna dispatcher chooses worker model/effort and reviews results.
- [x] Headless local coding agents with execution logs and per-task environments.
- [x] Programmed commands run directly; unmatched native and legacy voice requests
      enter the Luna queue without a dispatch prefix; dashboard submission also works.
- [x] Legacy phone task-status notifications and signed task answer pages;
      opening a notification without signing in is confirmed on the handset.
- [x] Assistant-owned local calendar: agendas, appointments, edits and audit history.
- [x] Live Gmail search, thread reading and authorized email sending from agents.
- [x] Email skill: context gathering, related threads, writing and document filing.
- [x] Attachment catalogue, duplicate detection and original-file filing workflow;
      at least one original attachment downloaded and verified.
- [x] WhatsApp linked-device connection and received-message archive.
- [x] Cloud shopping list independent of laptop uptime; phone app, recipes and
      offline shopping outbox. Adding an item through phone Assist is confirmed.
- [x] Local dashboard: Today, Documents, Notes and editable visual Profile;
      light and dark themes.
- [x] Themed personal profile, private storage boundaries and reusable skill library.

### Next priorities

- [x] Native voice capture and configured cloud transcription.
- [ ] Test recognition accuracy/latency with the actual phone in public places.
- [ ] File semantic search: text extraction, OCR, exact filters, embeddings,
      source excerpts and incremental indexing.
- [x] Calendar reminder projection and cloud delivery while the laptop sleeps.
- [x] Native reminder snooze control and durable cloud rescheduling.
- [ ] Native reminder delivery/snooze on the handset; reminder dismissal controls.
- [x] Contextual task notification replies: cloud ingress, durable queueing and
      the same Luna session.
- [x] Follow-ups from task details resume the existing worker session directly;
      queued instructions and results stay on the original conversation page.
- [x] Cloud task history with search, pagination and links to resumable task pages.
- [x] Paired native task history/details, cached answers, timestamps and stable-ID
      follow-ups that resume the recorded worker session.
- [x] Native task notification/reply, reminder, alarm and update event journal;
      provider acceptance and phone receipt are separate records.
- [x] Firebase client/server provisioning and real background FCM delivery with
      authenticated receipts and native Details opening verified on an emulator.
- [x] Native Companion notification delivery, FCM error health, owner notification status and a deploy
      preflight; see [native delivery](docs/native-companion.md#native-delivery).
- [ ] Verify native notification display and Reply end to end on the handset.
- [x] Standalone relay authentication and native-only service deployment; see the retirement runbook.
- [ ] Task cancellation/retry and attachment access from phone task history.
- [x] Supervised live-Gmail collection and source-qualified follow-up extraction.
- [ ] Finish attachment backfill and establish complete historical coverage.

### Voice and phone

- [x] Native Voice, Shopping, Activity and Settings pages with light/dark/system
      themes, tonal gradients, subtle motion and preserved drafts during updates.
- [x] Dusk Aurora across native screens, dashboard, groceries and task pages;
      sunrise/sunset uses private runtime settings and follows System when unset.
- [x] Version 0.6 single-command voice: one wake/Talk, one acknowledged readback,
      then wake standby when background listening is enabled.
- [x] Explicit Start conversation control or spoken request; **That was all**
      ends continuing turns and preserves the background wake setting.
- [x] Timestamped native voice chat with distinct requests and acknowledgements;
      linked queued tasks open their native conversation.
- [x] Local wake-test flow with microphone level, partial words and detection
      count; locked screen-off no-command behavior verified on an emulator.
- [x] Explicit background listening, paused-listening resume and microphone
      Quick Settings tile; setup shortcuts keep the usual Home app.
- [x] Native cached recipe ingredient picker with offline additions and selected
      quantities, plus recent command receipts and native full task history.
- [x] Native buffered voice capture and durable command retries; spoken follow-ups
      are enabled through explicit conversation mode.
- [x] Optional GPT-Live speech bridge using existing stores and the Luna queue.
- [x] Alternative Realtime conversational speech, with server speech detection,
      backend action receipts and interruption playback reset.
- [ ] Verify extended conversations, interruptions and task results on the handset.
- [ ] Selectively speak completed task results when useful and permitted, without
      repeating queued acknowledgements or reading every background result aloud.
- [ ] Add a fast path for suitable questions that avoids unnecessary full task dispatch.
- [ ] Evaluate a lightweight local or fast acknowledgement model with truthful
      queue/completion wording and measured latency/cost.
- [x] Lock-screen assistant entry and warm screen-off capture verified on an emulator.
- [ ] Verify locked-phone voice and wake detection on the Galaxy handset.
- [ ] Measure wake-word battery use after latency and locked operation are established.
- [x] Phone-local command capture and durable replay when the cloud is unreachable.
- [ ] Verify offline voice capture/reconnect and exactly one result on the handset.
- [x] Paired companion alarm queue and Clock-intent handoff with delivery status.
- [x] Tag-based signed release automation, durable update events, verified downloads and
      Android installer handoff; diagnostic/private-fixture APKs are rejected.
- [ ] Verify companion update installation and data preservation on the handset.
- [ ] Verify installation/Clock creation on the handset; add timers and alarm management.
- [x] Native shopping widget, quick-add entry, cached list and offline mutation queue.
- [ ] Verify the current native build's pairing, task screens and widget on the handset.
- [x] Shared recipe import, ingredient selection and AnyList migration procedure.
- [ ] Import and verify actual AnyList exports; complete the personal migration.
- [ ] Recipe ingredient scaling, pantry tracking and shopping-list consolidation.
- [ ] Store-specific grocery product matching; availability still needs verification.

### Email, messages and documents

- [ ] Connect the remaining personal/academic Outlook account.
- [ ] Background Gmail/Outlook sync using independently authenticated crawlers.
- [ ] WhatsApp media downloads and voice-note transcription.
- [ ] WhatsApp search and conversation summaries exposed to task workers.
- [ ] Authorized WhatsApp sending with recorded delivery outcomes.
- [x] Email deadline/renewal/awaiting-reply records with exact excerpts and review status.
- [ ] Extract obligations from document contents, including scanned files.
- [ ] Suggest filing categories for new documents; preserve originals and provenance.
- [ ] Unified search across files, email, messages and personal notes.

### Everyday assistant ideas

- [ ] A useful daily brief: agenda, deadlines, waiting replies and outstanding tasks.
- [ ] Personal task list with recurring chores, priorities and reminders.
- [x] Follow-ups dashboard with source links and Done/Dismiss/Reopen controls.
- [ ] Extend follow-up tracking to promises and non-email sources.
- [ ] Appointment preparation: relevant documents, location and questions to ask.
- [ ] Subscription/contract renewal tracking and cancellation reminders.
- [ ] Receipt/invoice organisation and spending summaries.
- [ ] Travel preparation: bookings, tickets, packing list and departure reminders.
- [ ] Application tracking and reusable CV/cover-letter preparation.
- [ ] Study/research workspace: papers, citations, notes and thesis milestones.
- [ ] Profile updates suggested from new information, with sources and corrections.

### Reliability and maintenance

- [ ] Verify real laptop sleep/resume and queued-command recovery end to end.
- [ ] Verify all notification states on the handset, including offline delivery.
- [ ] Backup automation and tested restore for calendar, queues, files and settings.
- [ ] Connection-health alerts for expired authentication or failed services.
- [ ] Per-task runtime/model usage reporting and a hosting-cost overview.

## Development setup

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[server,test]'
.venv/Scripts/python.exe scripts/bootstrap_workspace.py
./scripts/verify.ps1
```

Read the calendar setup before initializing a new store. Bootstrap creates
private folders/templates without overwriting files. The first portable skill
is skills/local-calendar/SKILL.md.

## Private workspace

Keep profile/documents in ignored private/, databases/traces/continuity in
ignored state/, and local configuration in config/local/. When present,
state/CONTEXT.md contains continuity and state/source-conversation.md the transcript.

GitHub is public. Actual credentials belong in a protected external store;
account metadata contains references only. This checkout is under OneDrive:
Git ignore does not prevent OneDrive sync. Do not sync actively written SQLite
stores between machines or place raw credentials here.
