#!/usr/bin/env bash
set -euo pipefail
cd ~/openclaw

echo "[post-recreate] waiting for openclaw-gateway to be running..."
for i in $(seq 1 60); do
  if docker compose ps --status running --services 2>/dev/null | grep -qx "openclaw-gateway"; then
    break
  fi
  sleep 2
done

echo "[post-recreate] waiting for gateway exec readiness..."
for i in $(seq 1 60); do
  if docker compose exec -T openclaw-gateway sh -lc 'echo ready' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "[post-recreate] applying apt sudoers rule..."
docker compose exec -T -u root openclaw-gateway sh -lc '
cat >/etc/sudoers.d/node-apt <<EOF
node ALL=(root) NOPASSWD:/usr/bin/apt-get,/usr/bin/apt
EOF
chmod 440 /etc/sudoers.d/node-apt
visudo -cf /etc/sudoers >/dev/null
'

echo "[post-recreate] verifying apt sudo access..."
docker compose exec -T openclaw-gateway sh -lc \
  'sudo -n apt-get -v >/dev/null && echo SUDO_APT_OK || (echo SUDO_APT_FAIL; exit 1)'

echo "[post-recreate] installing clawdhub..."
docker compose exec -T openclaw-gateway sh -lc '
  sudo -n npm install -g npm@11.10.1 && \
  sudo -n npm i -g clawdhub && \
  cd /usr/local/lib/node_modules/clawdhub && \
  sudo -n npm install undici && \
  echo CLAWDHUB_OK || echo CLAWDHUB_FAIL
'

echo "[post-recreate] done."
