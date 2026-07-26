FROM node:24-bookworm AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      imagemagick \
      python3 \
      ripgrep \
      unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build/codex-desktop-web
COPY package.json package-lock.json ./
RUN npm ci \
    && node node_modules/electron/install.js \
    && npx electron-rebuild -f -w better-sqlite3 -w node-pty \
    && find node_modules/better-sqlite3 node_modules/node-pty -name '*.node' -print

COPY bridge ./bridge
COPY compatibility ./compatibility
COPY releases ./releases
COPY scripts ./scripts

ARG CODEX_DESKTOP_RELEASE=26.721.41059
RUN --mount=type=cache,target=/build/cache \
    node scripts/prepare-upstream.mjs \
      --release "$CODEX_DESKTOP_RELEASE" \
      --cache /build/cache \
      --output /build/prepared

FROM node:24-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      dbus \
      git \
      libasound2 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libcairo2 \
      libcups2 \
      libdbus-1-3 \
      libdrm2 \
      libgbm1 \
      libglib2.0-0 \
      libgtk-3-0 \
      libnss3 \
      libpango-1.0-0 \
      libx11-6 \
      libxcb1 \
      libxcomposite1 \
      libxdamage1 \
      libxext6 \
      libxfixes3 \
      libxkbcommon0 \
      libxrandr2 \
      openssh-client \
      ripgrep \
      xz-utils \
      xvfb \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 3000 --shell /bin/bash codex \
    && mkdir -p /workspace /opt/codex-desktop /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix \
    && chown -R codex:codex /workspace /opt/codex-desktop

COPY --from=builder --chown=codex:codex /build/prepared /opt/codex-desktop
COPY --chown=codex:codex docker/entrypoint.sh /opt/codex-desktop/entrypoint.sh
RUN chmod 0755 /opt/codex-desktop/entrypoint.sh

USER codex
WORKDIR /workspace
ENV HOME=/home/codex
ENV CODEX_HOME=/home/codex/.codex
ENV CODEX_WEB_PORT=8214
ENV CODEX_WEB_HOST=0.0.0.0
EXPOSE 8214
VOLUME ["/home/codex", "/workspace"]
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=6 \
  CMD node -e "fetch('http://127.0.0.1:8214/health').then(r=>r.json()).then(v=>{if(v.status!=='ok')process.exit(1)}).catch(()=>process.exit(1))"
ENTRYPOINT ["/opt/codex-desktop/entrypoint.sh"]
