{ config, pkgs, ... }:

let
  agent-zero-secrets = config.ghostship.selfHostedSecrets.projections.agent-zero.path;
  agent-zero-registry-secrets = config.ghostship.selfHostedSecrets.projections."agent-zero-registry".path;
  render-agent-zero-secrets = "${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project agent-zero";
  render-agent-zero-registry-secrets = "${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project agent-zero-registry";
  agent-zero-registry-auth-file = "/run/containers/0/agent-zero-ghcr-auth.json";
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

  systemd.services.podman-agent-zero = {
    environment.REGISTRY_AUTH_FILE = agent-zero-registry-auth-file;
    preStart = ''
      install -d -m0755 -o root -g root \
        /srv/apps/agent-zero \
        /srv/apps/agent-zero/usr \
        /srv/apps/agent-zero/root

      ${render-agent-zero-secrets}
      ${render-agent-zero-registry-secrets}

      for secret_file in \
        "${agent-zero-secrets}" \
        "${agent-zero-registry-secrets}"
      do
        if [ ! -f "$secret_file" ]; then
          echo "Waiting for Agent Zero secret source at $secret_file..."
          for _ in $(seq 1 30); do
            if [ -f "$secret_file" ]; then
              break
            fi
            sleep 1
          done
        fi

        if [ ! -f "$secret_file" ]; then
          echo "Missing Agent Zero secret source at $secret_file" >&2
          exit 1
        fi
      done

      set -a
      . "${agent-zero-registry-secrets}"
      set +a

      if [ -z "''${GITHUB_TOKEN:-}" ]; then
        echo "Missing GITHUB_TOKEN for Agent Zero GHCR pull" >&2
        exit 1
      fi

      install -d -m0700 /run/containers/0
      AUTH="$(${pkgs.coreutils}/bin/printf '%s:%s' "owner" "$GITHUB_TOKEN" | ${pkgs.coreutils}/bin/base64 -w0)"
      cat > "${agent-zero-registry-auth-file}" <<EOF
{"auths":{"ghcr.io":{"auth":"$AUTH"}}}
EOF
      chmod 600 "${agent-zero-registry-auth-file}"
    '';
  };
}
