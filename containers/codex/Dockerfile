FROM docker.io/nixos/nix:latest

ENV NIX_SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt \
    NPM_CONFIG_PREFIX=/usr/local \
    npm_config_prefix=/usr/local \
    PATH=/usr/local/bin:/root/.nix-profile/bin:/nix/var/nix/profiles/default/bin:/run/current-system/sw/bin:/usr/bin:/bin

RUN nix-channel --update \
    && nix-env -iA \
      nixpkgs.bashInteractive \
      nixpkgs.cacert \
      nixpkgs.coreutils \
      nixpkgs.curl \
      nixpkgs.docker \
      nixpkgs.findutils \
      nixpkgs.gnugrep \
      nixpkgs.gnused \
      nixpkgs.gnutar \
      nixpkgs.gzip \
      nixpkgs.nodejs_22 \
      nixpkgs.openssh \
      nixpkgs.procps \
      nixpkgs.ripgrep \
    && mkdir -p /home/codexapp /var/lib/docker /usr/local/bin

COPY codex-entrypoint /usr/local/bin/codex-entrypoint
COPY codex-provider-mux /usr/local/bin/codex-provider-mux
RUN chmod 0755 /usr/local/bin/codex-entrypoint /usr/local/bin/codex-provider-mux

WORKDIR /home/codexapp
EXPOSE 5900

ENTRYPOINT ["/root/.nix-profile/bin/bash", "/usr/local/bin/codex-entrypoint"]
