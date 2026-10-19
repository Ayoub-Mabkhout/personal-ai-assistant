# Feature roadmap

This is the detailed implementation checklist, moved from the project README.
The runtime **Features** page is a separate editable cloud checklist shared by
the Companion and dashboard; see [its contract](features-checklist.md).

## Latest additions

- [x] Read-only bank imports, a durable financial auditor, owner corrections and a spending narrative.
- [x] Native Money overview, category history, income tracking and a 2×2 widget.
- [x] Dashboard Money questions, recorded review answers and allowance settings.
- [x] Bundled Onest typography and native New task / Last task shortcuts.
- [ ] Consent-renewal reminders for connected banks.

## Implementation checklist


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
- [x] Programmed commands run directly; unmatched native voice requests
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
      offline shopping outbox. Adding an item through phone voice is confirmed.
- [x] Local dashboard: Today, Documents, Notes and editable visual Profile;
      light and dark themes.
- [x] Themed personal profile, private storage boundaries and reusable skill library.

### Next priorities

- [x] Native voice capture and configured cloud transcription.
- [x] Handset voice recognition and latency field checks.
- [ ] File semantic search: text extraction, OCR, exact filters, embeddings,
      source excerpts and incremental indexing.
- [x] Calendar reminder projection and cloud delivery while the laptop sleeps.
- [x] Native reminder snooze control and durable cloud rescheduling.
- [x] Native reminder delivery/snooze on the handset.
- [ ] Additional reminder dismissal controls.
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
      preflight; see [native delivery](native-companion.md#native-delivery).
- [x] Native notification display and Reply end to end on the handset.
- [x] Standalone relay authentication and native-only service deployment; see the retirement runbook.
- [x] Pictures/files on new tasks and same-session follow-ups, durable phone uploads,
      worker originals and cached attachment access from native task history.
- [ ] Task cancellation/retry controls from phone task history.
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
- [ ] Verify conversation entry **Hey Chat, let's talk** and exit **That was all** on the handset.
- [ ] Selectively speak completed task results when useful and permitted, without
      repeating queued acknowledgements or reading every background result aloud.
- [ ] Add a fast path for suitable questions that avoids unnecessary full task dispatch.
- [ ] Evaluate a lightweight local or fast acknowledgement model with truthful
      queue/completion wording and measured latency/cost.
- [x] Lock-screen assistant entry and warm screen-off capture verified on an emulator.
- [x] Locked-phone voice and wake detection field checks.
- [ ] Measure wake-word battery use on the phone with Settings > Hey Chat battery ([how](listener-battery.md)).
- [x] Phone-local command capture and durable replay when the cloud is unreachable.
- [x] Offline voice capture/reconnect and exactly one result on the handset.
- [x] Paired companion alarm queue and Clock-intent handoff with delivery status.
- [x] Tag-based signed release automation, durable update events, verified downloads and
      Android installer handoff; diagnostic/private-fixture APKs are rejected.
- [x] Companion update installation and data preservation on the handset.
- [x] Clock alarm handoff verified on the handset.
- [x] Native countdown timers, cancellation/recovery and Live/Realtime receipts.
- [ ] Verify the new timer build and immediate locked-screen wake cue on the handset.
- [ ] Additional alarm management.
- [x] Native shopping widget, quick-add entry, cached list and offline mutation queue.
- [x] Native pairing, task screens and widget handset checks.
- [x] Shared recipe import, ingredient selection and AnyList migration procedure.
- [ ] Import and verify actual AnyList exports; complete the personal migration.
- [ ] Recipe ingredient scaling, pantry tracking and shopping-list consolidation.
- [x] Persistent 12-hour retailer check, conservative synonyms and expiring source-backed grocery tags.
- [ ] Obtain supported REWE catalogue access; public headless requests currently return HTTP 403.
- [x] Intelligent cloud grocery edits: multi-item additions, removals, corrections and atomic retries.

### Email, messages and documents

- [x] Connect the academic Outlook inbox through live authenticated IMAP.
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
- [x] Notification state field checks, including offline delivery.
- [ ] Backup automation and tested restore for calendar, queues, files and settings.
- [ ] Connection-health alerts for expired authentication or failed services.
- [ ] Per-task runtime/model usage reporting and a hosting-cost overview.
