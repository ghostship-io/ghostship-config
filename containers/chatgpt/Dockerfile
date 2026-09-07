FROM ghcr.io/linuxserver/baseimage-selkies@sha256:7bdf3c1cc57e80b1c4e192d64a20534e2fec6a3aa8527d2afe18aa3d0fb942b9

ARG CHATGPT_VERSION=26.901.51231
ARG CHATGPT_SHA256=02a2f5c6cb69509c62abcbdd13c76b139cdb2ca9edde7537239ddde024077ea0
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      bubblewrap chromium dbus-x11 git gh gnome-keyring libsecret-1-0 nodejs npm \
      python3-venv build-essential scrot wmctrl xdotool xterm \
    && curl -fL --retry 3 -o /tmp/chatgpt.deb \
      "https://persistent.oaistatic.com/codex-app-prod/linux/deb/pool/main/c/chatgpt/chatgpt_${CHATGPT_VERSION}_arm64.deb" \
    && echo "${CHATGPT_SHA256}  /tmp/chatgpt.deb" | sha256sum -c - \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/chatgpt.deb \
    && apt-get update \
    && install -d /opt/ghostship-chatgpt/packages \
    && mv /tmp/chatgpt.deb /opt/ghostship-chatgpt/packages/chatgpt.deb \
    && rm -rf /var/lib/apt/lists/*

COPY launch-chatgpt /usr/local/bin/launch-chatgpt
COPY autostart /defaults/autostart
ENV TITLE="ChatGPT" PUID=3000 PGID=3000 TZ=Pacific/Honolulu \
    START_DOCKER=false PIXELFLUX_WAYLAND=false NO_GAMEPAD=true \
    SELKIES_MANUAL_WIDTH=1280 SELKIES_MANUAL_HEIGHT=900 \
    SELKIES_USE_CPU=true SELKIES_FRAMERATE=30 \
    FILE_MANAGER_PATH=/config/Transfers
