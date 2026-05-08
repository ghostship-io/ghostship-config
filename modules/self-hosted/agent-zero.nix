{ config, ... }:

let
  agent-zero-secrets = config.ghostship.selfHostedSecrets.projections.agent-zero.path;
  render-agent-zero-secrets = "${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project agent-zero";
in
{
  virtualisation.oci-containers.containers."agent-zero" = {
    image = "ghcr.io/ghostship-io/ghostship-agent-zero:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:80/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environmentFiles = [ agent-zero-secrets ];
    volumes = [
      "/srv/apps/agent-zero/usr:/a0/usr:rw"
      "/srv/apps/agent-zero/root:/root:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/agent-zero 0755 root root -"
    "d /srv/apps/agent-zero/usr 0755 root root -"
    "d /srv/apps/agent-zero/root 0755 root root -"
  ];

  systemd.services.podman-agent-zero.preStart = ''
    install -d -m0755 -o root -g root \
      /srv/apps/agent-zero \
      /srv/apps/agent-zero/usr \
      /srv/apps/agent-zero/root

    ${render-agent-zero-secrets}

    if [ ! -f "${agent-zero-secrets}" ]; then
      echo "Waiting for Agent Zero secrets at ${agent-zero-secrets}..."
      for _ in $(seq 1 30); do
        if [ -f "${agent-zero-secrets}" ]; then
          break
        fi
        sleep 1
      done
    fi

    if [ ! -f "${agent-zero-secrets}" ]; then
      echo "Missing Agent Zero secrets file at ${agent-zero-secrets}" >&2
      exit 1
    fi
  '';
}
