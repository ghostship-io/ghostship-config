# Podman 5.8.8 - security fix for CVE-2026-94603 / GHSA-2cvf-wqm6-wr9g.
#
# Upstream advisory:
# https://github.com/podman-container-tools/podman/security/advisories/GHSA-2cvf-wqm6-wr9g
#
# "podman run" treated any image carrying the
# io.podman.annotations.checkpoint.runtime.name annotation as a checkpoint and
# silently restored it, discarding the sandbox the caller asked for (for
# example --cap-drop=ALL) and using the capability set stored in the image
# instead. The upstream fix removes that behaviour and rejects checkpoint
# images on "podman run" outright; "podman container restore" stays available.
# Rootless containers are not affected because they do not support
# checkpoint/restore.
#
# The pinned nixpkgs still carries Podman 5.8.6 on its 5.8 line, so the 5.8
# branch is pinned here instead of bumping nixpkgs. Podman 5.8.8 is the
# upstream fix release for exactly that line and also carries the 5.8.7
# fixes that follow 5.8.4 (the threshold for GHSA-4hq8-gpf5-8p68).
{
  pkgs,
  prev,
}:
let
  version = "5.8.8";

  src = pkgs.fetchFromGitHub {
    owner = "podman-container-tools";
    repo = "podman";
    tag = "v${version}";
    # Verified against the fetched tree.
    hash = "sha256-fl2/HyUh2EBbSw6O50H04Bltu2ZNF1Fay9XNNzKVpSE=";
  };

  # The pinned nixpkgs expression builds Podman from the release tarball with
  # vendorHash = null: the tarball ships its own vendor/ tree, so the module
  # set is unchanged and only the source and the version move. The helper
  # binary wrapper, the AppArmor, seccomp and SELinux inputs, the
  # extraPackages and extraRuntimes overrides used by the NixOS podman module
  # and the systemd unit files are all inherited unchanged.
  # Podman 6.1.3 carries the same fix (and 6.0.0 the GHSA-4hq8 fix). Once the
  # nixpkgs input ships such a release, use it instead of the 5.8 pin; the
  # 5.8.8 tree no longer builds against the 6.x expression's patches.
  upstreamFixed = prev.lib.versionAtLeast prev.podman.version "6.1.3";

  package =
    if upstreamFixed then
      prev.podman.overrideAttrs (old: {
        patches = (old.patches or [ ]) ++ [ ../podman-network/clamp-cursor.patch ];
      })
    else
      prev.podman.overrideAttrs (old: {
        inherit version src;
        patches = (old.patches or [ ]) ++ [ ../podman-network/clamp-cursor.patch ];
      });
in
{
  inherit upstreamFixed package;
  inherit (package) version src;
}
