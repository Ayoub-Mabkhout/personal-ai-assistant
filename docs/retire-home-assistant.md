# Retire the former Home Assistant stack

Perform this migration on the existing host and preserve its public address.
Do not initialize a new relay store or rotate submit/worker/pairing credentials.
The current cloud grocery SQLite store is authoritative. Owner login, phone
commands, release publication, task browsing and notifications use the relay.

## Recovery checkpoint

Before replacement, create a consistent protected off-host backup of the entire
application data/secrets/.env and deployed source. Include the old Home Assistant
`.storage` authentication, database and shopping files as well as every relay
SQLite database, WAL/SHM, paired phones, Firebase, signing and voice key/config.
Quiesce writers or use SQLite online backup; copying a live database alone is not
a consistent snapshot. Record hashes and verify decryption/extraction and SQLite
integrity in private continuity. Never publish this backup or paths identifying
the actual host. Inspect any old shopping list and migrate remaining entries
with stable IDs before deleting its files; preserve recipes/history unchanged.

## Replacement and acceptance

1. Build/upload the new allowlisted source. Keep the old deployment/source/env
   in the verified recovery backup.
2. Run `sudo python3 scripts/configure_owner.py --credentials-file
   /opt/personal-assistant/secrets/homeassistant-owner.json --output
   /opt/personal-assistant/data/relay/owner-login.json` on one shell command line.
   Existing username/password become a salted scrypt hash; refresh tokens are
   discarded. The routine refuses to overwrite an existing owner record.
3. Remove `ha_url`, `auth_file`, `mobile_service` and `provider` from the private
   relay `notifications.json`, retain `enabled`, `public_url`, `companion_push`,
   visibility and `delivery_mode=native`. Preserve Firebase project/key paths.
   Retain configured voice provider, API key path, model and budget; remove only
   obsolete `whisper_host` if present.
4. Run `scripts/deploy_server.sh /opt/personal-assistant/.env`. It builds and runs
   preflight, then recreates relay/proxy as needed. It deliberately does not use
   `--remove-orphans`; old containers remain available for recovery at this stage.
5. Validate unauthenticated grocery/task APIs reject access; owner cookie and
   submit bearer work; worker token fails owner access; logout revokes the copied
   cookie; signed task links still scope reads/follow-ups to the original task.
   Verify existing shopping/recipes, task history, phone IDs and queue state.
6. Use existing protected worker config (`relay_url`, `submit_token_file`) for
   `scripts/phone_actions.py phones`, native release publication and dashboard
   shopping. Remove `homeassistant_url`, `homeassistant_auth_file`,
   `mobile_notify_service` and `notifications_enabled` from the private worker
   config, then restart laptop dashboard/worker. Do not rotate other credentials.
7. Verify native task Details/Reply, notification receipt, reminder projection
   and physical reminder/Snooze delivery separately. Verify phone voice capture,
   wake/buffering, configured transcription and local Android speech playback.
   Record evidence before removing old services.

## Final obsolete service removal

Only after acceptance, stop and remove the three specifically inspected old
containers: Home Assistant, Wyoming Whisper and Wyoming Piper. Use the actual
container IDs from `docker ps -a`; never match all containers by a broad wildcard.
Do not run `compose down -v`, prune volumes, or delete the application data root.
Remove only the obsolete whisper_data/piper_data volumes once no container uses
them and their recovery contents are backed up. Preserve caddy_data/caddy_config
and the relay bind-mounted directory.

After migrating any old shopping rows and confirming the recoverable backup,
remove `data/homeassistant`, `secrets/homeassistant-owner.json` and the exact
legacy relay auth file formerly named by notifications.auth_file (commonly
`data/relay/ha-notifications-auth.json`). Remove the laptop's exact old
homeassistant-auth and owner-login JSON copies from protected storage only once
the standalone owner hash and backup are verified. Inspect resolved absolute
paths before each removal; restrict targets to these obsolete files/directories.
Remove obsolete HA/speech environment keys, retaining domain, ACME contact,
relay directories, service tokens, signing and Firebase configuration.

The old Home Assistant phone app can be uninstalled through Android package
management after verifying Companion is the selected Digital assistant and its
native permissions work. Android may require the handset's OS confirmation for
uninstall; this is separate from server cleanup. Preserve Assistant Companion,
its app data, Termux and the wake service.

Recovery: stop replacement writers, restore verified old source/config/data to
its original location, and start the previous Compose stack. Keep the current
relay data separately before restore so post-cutover actions can be reconciled.
Never restore an old queue snapshot over newer actions without reconciling them.
Changing native mode back to a legacy value is unsupported by the new image;
rollback uses the old image/source and backed-up old configuration.
