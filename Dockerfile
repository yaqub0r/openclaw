FROM node:22-bookworm

# --- Start Brew Block ---
# 1. Install Brew dependencies as root
USER root
RUN apt-get update && apt-get install -y build-essential procps file git curl sudo cron

# 2. Prep the directories so they are writable by the 'node' user
RUN mkdir -p /home/linuxbrew/.linuxbrew && \
  chown -R node:node /home/linuxbrew/.linuxbrew /home/node

# 3. Perform the actual installation as 'node'
USER node
ENV PATH="/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:${PATH}"
ENV HOMEBREW_PREFIX="/home/linuxbrew/.linuxbrew"

# Non-interactive Brew install
RUN /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 4. Critical for Runtime: Allow 'node' to sudo for Brew if needed
USER root
RUN echo "node ALL=(ALL) NOPASSWD: /usr/bin/apt-get, /usr/bin/apt" >> /etc/sudoers
# --- End Brew Block ---

# Install Bun (required for build scripts)
RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="/root/.bun/bin:${PATH}"

RUN corepack enable

WORKDIR /app

ARG OPENCLAW_DOCKER_APT_PACKAGES=""
RUN if [ -n "$OPENCLAW_DOCKER_APT_PACKAGES" ]; then \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $OPENCLAW_DOCKER_APT_PACKAGES && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*; \
  fi

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY ui/package.json ./ui/package.json
COPY patches ./patches
COPY scripts ./scripts

RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build
# Force pnpm for UI build (Bun may fail on ARM/Synology architectures)
ENV OPENCLAW_PREFER_PNPM=1
RUN pnpm ui:build

ENV NODE_ENV=production

# Allow non-root user to write temp files during runtime/tests.
RUN chown -R node:node /app

# Entrypoint starts cron (as root) and then drops to the 'node' user for the gateway.
# We keep runtime as root only long enough to launch cron.
USER root
ENTRYPOINT ["/app/scripts/gateway-entrypoint.sh"]

# Start gateway server with default config.
# Binds to loopback (127.0.0.1) by default for security.
#
# For container platforms requiring external health checks:
#   1. Set OPENCLAW_GATEWAY_TOKEN or OPENCLAW_GATEWAY_PASSWORD env var
#   2. Override CMD: ["node","openclaw.mjs","gateway","--allow-unconfigured","--bind","lan"]
CMD ["node", "openclaw.mjs", "gateway", "--allow-unconfigured"]
