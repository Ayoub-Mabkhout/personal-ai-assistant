#!/bin/sh
# Run on the Linux server after Docker Engine/Compose and private config exist.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_path=${1:-/opt/personal-assistant/.env}
cd "$repo_root/infra/server"
docker compose --env-file "$env_path" --profile voice config --quiet
docker compose --env-file "$env_path" --profile voice build relay
docker compose --env-file "$env_path" --profile voice up -d
docker compose --env-file "$env_path" --profile voice ps
