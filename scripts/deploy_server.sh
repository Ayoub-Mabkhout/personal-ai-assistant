#!/bin/sh
# Run on the Linux server after Docker Engine/Compose and private config exist.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_path=${1:-/opt/personal-assistant/.env}
cd "$repo_root/infra/server"
docker compose --env-file "$env_path" config --quiet
docker compose --env-file "$env_path" build relay
# A bad notifications file or Firebase credential must stop the deploy here, not crash-loop the running relay.
docker compose --env-file "$env_path" run --rm --no-deps -T relay python -m personal_assistant.relay.preflight
docker compose --env-file "$env_path" up -d --wait relay
# Caddy admin is disabled; recreate to apply the changed bind-mounted routing file.
docker compose --env-file "$env_path" up -d --force-recreate --no-deps proxy
docker compose --env-file "$env_path" ps
