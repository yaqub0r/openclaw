#!/usr/bin/env bash
set -euo pipefail

# Container entrypoint for OpenClaw gateway.
# - Starts Debian cron (for security updates / maintenance)
# - Drops privileges to the `node` user to run the gateway process

# Start cron if available (container has no systemd).
if command -v cron >/dev/null 2>&1; then
  # cron daemonizes; ignore failure if already running.
  pgrep -x cron >/dev/null 2>&1 || cron || true
fi

# Execute the requested command as `node` (default). Use safe shell-quoting.
cmd=("$@")
quoted=""
for a in "${cmd[@]}"; do
  printf -v q '%q' "$a"
  quoted+="$q "
done

exec su node -s /bin/bash -c "exec $quoted"
