# Security-fixed package pins for the October 2026 upstream advisories.
#
# This module installs a narrow nixpkgs overlay that replaces exactly two
# packages with their upstream fixed releases:
#
#   Nix 2.34.8 -> 2.34.9    CVE-2026-110449, CVE-2026-110450,
#                            CVE-2026-110451, CVE-2026-110452,
#                            CVE-2026-110453
#   Podman 5.8.6 -> 5.8.8   CVE-2026-94603 (GHSA-2cvf-wqm6-wr9g)
#
# The overlay repoints the Nix aliases that name the 2.34 line (pkgs.nix,
# pkgs.nixVersions.stable, pkgs.nixVersions.nix_2_34 and
# pkgs.nixVersions.nixComponents_2_34) and pkgs.podman. The other Nix lines
# that the pinned nixpkgs carries are not repointed and stay on the releases
# the input ships; the same advisory lists those releases as affected and no
# host configuration here references them.
#
# The pins are applied through nixpkgs.overlays, so the installed packages
# resolve to the fixed builds: the NixOS nix module (nix.package), the
# nix-daemon unit this repository writes into the T3 Code container image, the
# NixOS podman module (virtualisation.podman.package) and every direct
# pkgs.podman use.
#
# See docs/security-package-fixes.md for the source identity, the upstream
# patch references, the regression proofs and the activation impact.
{
  config,
  pkgs,
  ...
}:
let
  overlay = (import ../../packages/security-fixes).overlay;

  # Regression proofs for the pinned releases: they read the pinned sources
  # and the built artefacts, and one of them exercises the fixed Podman
  # behaviour against a throwaway image in a throwaway storage root.
  proofs = import ../../packages/security-fixes/proofs.nix {
    inherit (pkgs) runCommand python3;
    nix = pkgs.nix;
    podman = pkgs.podman;
  };
in
{
  nixpkgs.overlays = [ overlay ];

  system.build.securityPackageFixes = proofs;

  assertions = [
    {
      assertion = config.nix.package.version == "2.34.9";
      message = ''
        nix.package must resolve to the security-fixed Nix 2.34.9
        (CVE-2026-110449, CVE-2026-110450, CVE-2026-110451, CVE-2026-110452,
        CVE-2026-110453) but resolves to ${config.nix.package.version}.
      '';
    }
    {
      # The daemon unit runs the pinned Nix: the module puts the package on
      # the unit path, so the daemon that answers on the socket is the fixed
      # build and not the release the nixpkgs input ships.
      assertion = builtins.elem config.nix.package.out config.systemd.services.nix-daemon.path;
      message = ''
        nix-daemon.service does not run the pinned Nix 2.34.9
        (${config.nix.package.out}).
      '';
    }
    {
      assertion = config.virtualisation.podman.package.version == "5.8.8";
      message = ''
        virtualisation.podman.package must resolve to the security-fixed
        Podman 5.8.8 (CVE-2026-94603) but resolves to
        ${config.virtualisation.podman.package.version}.
      '';
    }
    {
      # The podman package the NixOS module hands to the systemd units is
      # produced by an extra override on top of the pinned build. It must
      # still be the pinned source, not a rebuild of the vulnerable release.
      assertion = config.virtualisation.podman.package.src == pkgs.podman.src;
      message = ''
        virtualisation.podman.package lost the pinned Podman 5.8.8 source
        when the NixOS podman module applied its helper overrides.
      '';
    }
  ];
}
