#!/usr/bin/env bash
set -euo pipefail

# Post-recreate fixups for OpenClaw Docker deployment
# Applies apt sudoers rule for node user inside the gateway container.

cd ~/openclaw

echo "[post-recreate] applying node apt sudoers rule..."
docker compose exec -T -u root openclaw-gateway sh -lc '
cat >/etc/sudoers.d/node-apt <<EOF
node ALL=(root) NOPASSWD:/usr/bin/apt-get,/usr/bin/apt
EOF
chmod 440 /etc/sudoers.d/node-apt
visudo -cf /etc/sudoers >/dev/null
'

echo "[post-recreate] verifying sudo apt access as node..."
docker compose exec -T openclaw-gateway sh -lc 'sudo -n apt-get -v >/dev/null && echo OK || (echo FAIL; exit 1)'

echo "[post-recreate] done."
