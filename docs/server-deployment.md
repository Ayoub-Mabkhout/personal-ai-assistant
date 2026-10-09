# Standalone server deployment

The cloud stack contains Caddy and the persistent relay. Native Companion owns
phone capture, wake buffering, shopping, task conversations and notifications.
Only HTTPS ports 80/443 are public; relay port 8765 binds to loopback. No Home
Assistant, Wyoming Whisper or Piper container is required.

Build the public allowlisted bundle with `scripts/build_deployment_bundle.py`.
Keep runtime data and protected credentials outside the checkout. On a Linux host:

```sh
sudo python3 scripts/prepare_server.py init --domain YOUR_HOSTNAME --email owner@example.com
sudo python3 scripts/configure_owner.py --output /opt/personal-assistant/data/relay/owner-login.json
sudo sh scripts/deploy_server.sh /opt/personal-assistant/.env
sudo python3 scripts/prepare_server.py publish
sudo sh scripts/deploy_server.sh /opt/personal-assistant/.env
```

Owner setup prompts privately for username/password and stores a salted scrypt
hash. Existing deployments can import a protected JSON containing `username` and
`password` with `--credentials-file`. The output is never overwritten and contains
no refresh token. The owner file belongs to relay UID 10001, mode 0600. The public
bootstrap proxy remains closed until a valid owner record is present.

Caddy forwards `/auth/`, `/groceries/`, `/tasks/`, `/companion/` and the root to the
relay; `/relay/` strips its prefix. Owner web login uses a revocable 24-hour Secure,
HttpOnly, SameSite=Strict cookie. Passwords and session tokens are never returned
to JavaScript or stored in browser localStorage. Cookie-authenticated writes
require a matching HTTPS Origin. Service calls use the existing protected submit
token; worker credentials cannot authorize owner grocery/task access.

Native notification configuration is documented in [native delivery](native-companion.md).
Deploy runs Firebase preflight before replacing the running relay. Pairing,
Firebase/signing credentials, queue/history databases and mobile preferences live
under the existing data paths and survive replacement. Config-only changes need
an explicit relay restart. Deployment does not remove orphan containers or data.

Verify `scripts/smoke_server.py https://YOUR_HOSTNAME`, owner login/logout, signed
task views, grocery read/edit, CLI phone status, native receipt, task Reply and real
reminder/Snooze on the paired handset. Provider acceptance and handset display
remain separate checks. Source API credentials stay protected on the laptop.
For removal of an older stack, follow [retirement](retire-home-assistant.md).
