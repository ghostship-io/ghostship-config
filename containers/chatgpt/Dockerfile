FROM ghcr.io/linuxserver/baseimage-selkies@sha256:7bdf3c1cc57e80b1c4e192d64a20534e2fec6a3aa8527d2afe18aa3d0fb942b9

ARG CHATGPT_VERSION=26.901.51231
ARG CHATGPT_SHA256=02a2f5c6cb69509c62abcbdd13c76b139cdb2ca9edde7537239ddde024077ea0
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      bubblewrap chromium dbus-x11 git gh gnome-keyring libsecret-1-0 \
      python3-venv build-essential scrot wmctrl xdotool xterm supervisor \
    && curl -fL --retry 3 -o /tmp/chatgpt.deb \
      "https://persistent.oaistatic.com/codex-app-prod/linux/deb/pool/main/c/chatgpt/chatgpt_${CHATGPT_VERSION}_arm64.deb" \
    && echo "${CHATGPT_SHA256}  /tmp/chatgpt.deb" | sha256sum -c - \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/chatgpt.deb \
    && apt-get update \
    && install -d /opt/ghostship-chatgpt/packages \
    && mv /tmp/chatgpt.deb /opt/ghostship-chatgpt/packages/chatgpt.deb \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/ghostship-chatgpt/source
RUN cd /opt/ghostship-chatgpt/source \
    && install -m0755 launch-chatgpt start-session update-chatgpt /usr/local/bin/ \
    && ln -s launch-chatgpt /usr/local/bin/chatgpt \
    && install -m0755 autostart /defaults/autostart \
    && cp -a web /opt/ghostship-chatgpt/web \
    && install -Dm0755 init-workstation /custom-cont-init.d/10-workstation \
    && install -Dm0755 nix-daemon-run /etc/s6-overlay/s6-rc.d/svc-nix/run \
    && install -Dm0755 user-services-run /etc/s6-overlay/s6-rc.d/svc-user-services/run \
    && install -Dm0755 update-run /etc/s6-overlay/s6-rc.d/svc-chatgpt-update/run \
    && install -m0644 supervisor.conf /etc/chatgpt-supervisor.conf \
    && for service in svc-nix svc-user-services svc-chatgpt-update; do \
      echo longrun > /etc/s6-overlay/s6-rc.d/$service/type; \
      mkdir -p /etc/s6-overlay/s6-rc.d/$service/dependencies.d; \
      touch /etc/s6-overlay/s6-rc.d/$service/dependencies.d/init-services; \
      touch /etc/s6-overlay/s6-rc.d/user/contents.d/$service; \
    done
ENV PATH="/opt/ghostship-tools/bin:/config/.local/bin:/lsiopy/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    NIX_REMOTE=daemon NIX_SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV TITLE="ChatGPT" PUID=3000 PGID=3000 TZ=Pacific/Honolulu \
    START_DOCKER=true PIXELFLUX_WAYLAND=false NO_GAMEPAD=true \
    SELKIES_MANUAL_WIDTH=1280 SELKIES_MANUAL_HEIGHT=900 \
    SELKIES_USE_CPU=true SELKIES_FRAMERATE=30 \
    FILE_MANAGER_PATH=/config/Transfers
