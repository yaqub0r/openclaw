#!/usr/bin/env bash
set -euo pipefail

# Force the script to read an existing .env file safely.
if [ -f ".env" ]; then
  echo "==> Loading existing configuration from .env"
  set -a
  source .env
  set +a
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$ROOT_DIR/scripts/docker/setup.sh"

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "Docker setup script not found at $SCRIPT_PATH" >&2
  exit 1
fi

exec "$SCRIPT_PATH" "$@"
