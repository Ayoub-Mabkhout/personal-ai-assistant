# First server deployment

The stack is deployed on Ubuntu 24.04 ARM64 with 2 OCPUs, 4 GB RAM and a 50 GB
boot volume. The public HTTPS address and credentials are recorded only in private
state/protected local storage. The Windows development host needs no Docker Engine.

Verification: all 27 tests passed (calendar, relay/API, owner-setup guards and
privacy-allowlisted bundle); pip dependency checks, Compose config and both
Caddy configurations and HA's runtime configuration checker passed. Public TLS,
authenticated WebSockets, shopping-list actions and offline queue persistence
across relay restart passed. A synthetic STT/intent/TTS round trip passed in
about 2.25 seconds; this does not measure a phone microphone or cellular latency.
An encrypted off-VM snapshot passed decryption, staging extraction and both SQLite
integrity checks. Full replacement-VM restoration and actual phone tests remain
pending. TestClient emits a non-failing upstream httpx deprecation warning.

## What is included

- Home Assistant Container 2026.9.4 with shopping list, mobile-app integration,
  native Assist, custom queue/status sentences and a readiness sensor.
- Caddy automatic public TLS, WebSocket-capable proxy and HTTP-to-HTTPS redirect.
- Persistent SQLite relay with separate submit/worker credentials, original
  request timestamps/timezones, duplicate detection, cancellation, deadline
  expiry, renewable fenced leases, readiness heartbeat expiry, and an event ledger.
- Optional server-local Whisper/Piper containers (voice profile, enabled by the
  deploy routine). Tiny English recognition is a starting point to benchmark;
  language/quality can be changed without altering the queue protocol.
- A first-owner bootstrap gate: public frontend returns 503 until account setup
  is finished privately and the proxy is switched to the normal configuration.

Only ports 80/443 are publicly published. Home Assistant port 8123 and relay
port 8765 are bound to host loopback for administration. Speech ports and
databases stay inside Docker. No privileged container, device mounts, host LAN
discovery or public Windows port is needed for these features. Source credentials
and documents remain on the laptop; the server holds submitted commands/results.

Container images are pinned to registry digests checked on 2026-10-01; see
infra/server/images.lock.json. Python runtime dependencies are pinned in
requirements-server.lock. Upgrade deliberately and verify before publishing.
Ubuntu 24.04 can use `infra/server/cloud-init.yaml` to install Docker/Compose,
enable security updates, configure key-only SSH and add 2 GB of swap. The cloud
provider firewall still needs configuration; cloud-init creates no cloud resources.
The backend subnet is 172.30.0.0/24. Dynamic addresses are restricted to
172.30.0.128/25 so they cannot take the fixed proxy address 172.30.0.2.
If changed for a host-network collision,
change the proxy IP and HA trusted_proxies together.

## Prerequisites

A Linux x86-64 or ARM64 VM with Docker Engine and Compose, Python 3, and a DNS hostname pointing
to its public IP. Use Ubuntu/Debian; start with 2 vCPU and 4 GB, measuring speech
latency/memory before increasing size. Configure the provider firewall to allow
80/443 and SSH from your administrative connection. Do not open 8123/8765 or
speech ports publicly. Do not install a Docker runtime on the personal laptop
just to make this deployment always available.

The pinned images were checked for both `linux/amd64` and `linux/arm64` registry
manifests. This supports Oracle Ampere A1 as well as an x86 VPS. The ARM64 A1
deployment passed speech testing; benchmark actual phone latency before resizing.

## Oracle Free Tier option

The current Always Free A1 allowance is a total of 2 OCPUs and 12 GB memory,
with 200 GB combined boot/block storage. A 2 OCPU / 4 GB Ubuntu instance with
a 50 GB boot disk is a suitable starting allocation for this stack. Stay within
Always Free limits even during the introductory trial; selecting a paid shape
does not make it permanently free. Home-region capacity is not guaranteed.

Oracle may reclaim an Always Free instance when CPU, network and (for A1)
memory usage all meet its idle criteria over seven days. This is a material
availability limit for a personal assistant. Keep recoverable backups outside
the VM, and test restoration before relying on the service. Do not generate
artificial load to avoid reclamation.

Create the account at [Oracle signup](https://signup.cloud.oracle.com/). Signup
needs email verification, a password, billing contact information, and usually
a verification card. The provider has no documented CLI account-signup workflow.
Choose the home region carefully; it cannot be changed later. Keep passwords,
card details, API signing keys and session tokens out of the repository and chat.
After signup, use the official OCI CLI with a short browser login session or an
API public key registered in the Console. Register only the public key; the
private signing key belongs in protected local storage outside synced folders.

References: [current free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm),
[signup requirements](https://docs.oracle.com/en-us/iaas/Content/GSG/Tasks/signingup_topic-Sign_Up_for_Free_Oracle_Cloud_Promotion.htm),
[CLI authentication](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/clitoken.htm).

Configure a public subnet, internet gateway and route, then allow public TCP
80/443 and TCP 22 only from the administrator's public IP. Check both OCI network
rules and the Ubuntu image's host firewall. Docker ports remain as configured in
Compose. Do not open Home Assistant, relay or speech ports to the internet.

For initial HTTPS without purchasing a domain, [sslip.io](https://sslip.io/)
provides DNS names containing the server's public IP. Use a unique prefix and
let Caddy obtain a certificate for that hostname. Verify DNS, certificate issuance
and mobile access before giving the address to the user. If the IP changes, that
hostname must change too; an owned domain can be added later.

## Paid fallback

OVHcloud's German public catalog checked on 2026-10-01 lists VPS-1 2027
(2 vCPU, 4 GB RAM, 40 GB NVMe) at EUR 4.49 excluding VAT on its monthly,
zero-commitment pricing mode: EUR 5.34 including 19% VAT. The installation
phase is zero. The product includes a dedicated IPv4 address and a daily
backup with one-day retention. Run Home Assistant and the relay on the same
VM; neither needs a separate subscription. Confirm the actual order total,
region availability and renewal terms before purchasing. Do not select annual
upfront billing merely to get the lower advertised monthly equivalent.

References: [VPS specifications](https://www.ovhcloud.com/de/vps/),
[German public pricing catalog](https://eu.api.ovh.com/1.0/order/catalog/public/vps?ovhSubsidiary=DE).
The included VM backup does not replace a tested application-level backup and
restore process. No paid fallback server or OVHcloud account has been created.

References: [Home Assistant Container](https://www.home-assistant.io/installation/linux/),
[Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/),
[remote HTTPS access](https://www.home-assistant.io/docs/configuration/remote/).
Do not blindly load local-device/hardware discovery instructions into this VM.

## Package and upload

The GitHub repository currently has unpushed local work. A fresh clone does not
contain this implementation yet. Build the bundle from this checkout instead:

```powershell
.venv/Scripts/python.exe scripts/build_deployment_bundle.py
scp state/exports/server-deployment.tar.gz SERVER_USER@SERVER_IP:~/
```

SERVER_USER/SERVER_IP are placeholders; no server identity has been selected.
The source allowlist excludes .env files, credentials, profiles, documents,
databases, traces, virtual environments and tooling. It includes only public
deployment templates, code and this guide. Extract on the host into a source
directory, for example ~/personal-assistant-source:

```sh
mkdir -p ~/personal-assistant-source
tar -xzf ~/server-deployment.tar.gz -C ~/personal-assistant-source
cd ~/personal-assistant-source
sudo python3 scripts/prepare_server.py init \
  --domain YOUR_HOSTNAME --email YOUR_CERTIFICATE_CONTACT_EMAIL
sudo sh scripts/deploy_server.sh /opt/personal-assistant/.env
```

These are assistant/operator routines; we can run them when a host is selected.
Initial preparation must run with sudo on Linux to set the relay UID/GID 10001
directory and secret-file permissions. Generated data/secrets live in
/opt/personal-assistant, outside the source tree. Tokens are not printed.
Repeated preparation preserves existing credentials/configuration; it does not
silently merge template changes into an existing Home Assistant installation.
Running Docker may require sudo or an authorized Docker group. The deploy script
never installs packages, edits firewalls, purchases hosting or changes DNS.

First start can take minutes, especially voice model downloads. Proxy startup
waits for Home Assistant and relay health. Inspect with:

```sh
cd ~/personal-assistant-source/infra/server
sudo docker compose --env-file /opt/personal-assistant/.env --profile voice ps
sudo docker compose --env-file /opt/personal-assistant/.env logs --tail=80
```

Do not paste verbose private logs or secrets into public issues. Compose config
--quiet is safe for structural validation; avoid printing resolved credentials.

## Create the owner privately, then enable public access

For an explicitly authorized headless setup, create the owner through the
server's loopback onboarding API:

```sh
sudo python3 scripts/onboard_homeassistant.py --name 'YOUR_DISPLAY_NAME'
sudo python3 scripts/configure_homeassistant_http.py
sudo python3 scripts/configure_homeassistant_voice.py
```

This generates a password and stores it, along with the setup refresh token,
in `/opt/personal-assistant/secrets/homeassistant-owner.json` (root-only mode
0600). It does not print credentials or open public access. Transfer credentials
only into a protected local store outside synced folders. Verify authenticated
access on the running server before publishing. If an owner already exists
without saved setup credentials, the routine refuses to replace that owner.
The onboarding API is based on the pinned
[Home Assistant source](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/components/onboarding/views.py)
and [authentication API](https://developers.home-assistant.io/docs/auth_api/).

Alternatively, create the owner interactively through an SSH tunnel:

On the personal laptop, open an SSH tunnel:

```powershell
ssh -N -L 18123:127.0.0.1:8123 SERVER_USER@SERVER_IP
```

In a local browser visit http://127.0.0.1:18123 and complete Home Assistant's
onboarding. Choose the owner username/password yourself; it is separate from
the laptop account and relay service tokens. Finish onboarding and enable MFA
in the Home Assistant profile. Public access is still gated at this stage.

On the server, switch the proxy after the owner exists:

```sh
cd ~/personal-assistant-source
sudo python3 scripts/prepare_server.py publish
cd infra/server
sudo docker compose --env-file /opt/personal-assistant/.env up -d --force-recreate proxy
python3 ../../scripts/smoke_server.py https://YOUR_HOSTNAME
sudo python3 ../../scripts/confirm_homeassistant_https.py
```

Publish checks Home Assistant's persisted active-owner flags and refuses before
an owner exists. It edits only the private proxy selection; recreation applies
it. It does not itself confirm successful login, MFA or voice. Initial public
HTTPS requires working DNS, inbound 80/443 and successful certificate issuance.

For HA 2026.9.4, YAML HTTP settings migrate to a pending configuration that rolls
back after five minutes without confirmation. The HTTPS confirmation script
authenticates through the actual public WebSocket before promoting these settings.
Run it promptly after configuration/restart; repeat the HTTP setup and confirmation
if migration already rolled back. The HTTP helper also completes the Shopping
List integration's pending import flow; a YAML declaration alone is insufficient.
Helpers use the default private directory and Compose container name above.

## Connect the Android app

Your screenshots show the correct flow:

1. Tap Enter address manually.
2. Replace the homeassistant.local placeholder with https://YOUR_HOSTNAME.
3. Tap Connect and sign in with the Home Assistant account created above.
4. Name the phone, permit microphone and notifications as needed. Location
   access is optional for this assistant's initial shopping/voice use.
5. Turn Wi-Fi off and test the same connection over mobile data.

[Official Companion setup](https://companion.home-assistant.io/docs/getting_started/)
explicitly supports manual server entry when connecting remotely. Enter the
Home Assistant root URL, not /relay, the VM's Docker IP, or port 8123. Use
the public address generated by the completed hosting deployment.

## Enable voice

In Home Assistant: Settings > Devices & services > Add integration > Wyoming
Protocol. Add whisper at host whisper, port 10300, then piper at host piper,
port 10200. These names resolve inside the Docker network; never use the public
hostname for them. Model downloads must finish before the services respond.
In Settings > Voice assistants, create/select an English assistant using the
Home Assistant conversation agent, Whisper speech-to-text and Piper text-to-speech.
Choose it in Companion. Ensure Shopping List is exposed to Assist if required.

Test with 'add milk to my shopping list'. Native shopping commands need no laptop
or LLM. 'Is my laptop connected?' queries the relay freshly. 'Ask my assistant
to check my calendar' saves a command and reports laptop availability. The
laptop calendar worker now executes this read-only query when ready. When paused,
asleep or unavailable, requests remain queued. General AI task dispatch is not enabled.

References: [local voice setup](https://www.home-assistant.io/voice_control/voice_remote_local_assistant/),
[Shopping List](https://www.home-assistant.io/integrations/shopping_list/),
[intent action responses](https://www.home-assistant.io/integrations/intent_script/).
Recognition latency/accuracy, custom sentences and actual phone actions require
the end-to-end host/device check; local config validation alone does not prove them.

## Next stages and operating limits

The per-user laptop service consumes calendar queries and records outcomes before
relay acknowledgement. Mail collectors and a separate explicitly invoked coding
runner are prepared, but no inbox is authenticated and no general AI dispatcher,
phone result push or calendar reminder projection is active. Phone-local offline capture/queueing and alarms are still to
build; server-side queuing works only after the phone reaches Home Assistant.

The first version uses two revocable static service credentials for one trusted
HA submitter and one laptop worker. It is not multi-user/device pairing. Keep
tokens private; worker token only goes to the laptop through protected storage.
Readiness expires after 60 seconds. Queries distinguish reachable-but-unavailable
from a failed relay request (unknown); no continuous phone socket is needed.

Lease fencing protects queue acknowledgements, not arbitrary external effects.
Workers must reconcile local action records before repeating an action,
resolve relative dates from original request time, and honor cancellation/stale
deadlines. Cancelling a running command cannot undo an effect already performed.
No automatic message sending or purchasing is enabled.

Server restart persistence, voice processing, shopping-list actions and rejected
anonymous API access have passed. Still test mobile-data login, phone microphone,
shopping while laptop asleep, and restoration onto a replacement VM.
Back up HA config, queue and credentials securely; use SQLite backup API or stop
the relay during capture, rather than copying a live SQLite/WAL pair casually.
Backup restore and log/data retention must be configured with the actual host.
