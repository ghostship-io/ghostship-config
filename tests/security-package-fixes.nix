# Evaluation checks for the pinned security-fixed Nix and Podman.
#
# Run with: nix eval --impure --json --file tests/security-package-fixes.nix
#
# The checks cover the identity of the pinned builds: the deployed packages
# are the upstream fixed releases, their sources are the pinned upstream trees,
# and the Nix aliases that name the 2.34 line resolve to the pinned build.
# The source-level and behavioural regression proofs live in
# packages/security-fixes/proofs.nix and are built through
# system.build.securityPackageFixes.
let
  flake = builtins.getFlake (toString ../.);
  host = flake.nixosConfigurations.chill-penguin;
  config = host.config;
  pkgs = host.pkgs;
  inherit (pkgs) lib;

  # The upstream release that carries the fix for each advisory.
  nixFixedVersion = "2.34.9";
  podmanFixedVersion = "5.8.8";
in
# The Nix the host installs and the nix-daemon runs.
assert config.nix.package.version == nixFixedVersion;
assert config.nix.package.src == pkgs.nix.src;
assert config.nix.package.out == pkgs.nix.out;

# The aliases that name the 2.34 line resolve to the pinned build, so no
# consumer can pick up the affected 2.34.8 release by accident. The other Nix
# lines in the pinned nixpkgs are not repointed by this overlay and stay on
# the releases the input ships.
assert pkgs.nixVersions.stable.version == nixFixedVersion;
assert pkgs.nixVersions.nix_2_34.version == nixFixedVersion;
assert pkgs.nixVersions.nixComponents_2_34.version == nixFixedVersion;
assert pkgs.nixVersions.stable.src == pkgs.nix.src;
assert pkgs.nixVersions.nix_2_34.src == pkgs.nix.src;
assert pkgs.nix.passthru.nix-cli.version == nixFixedVersion;

# The upstream test suite is carried over and bound to the pinned build, and
# the upstream fallback-path coherence check is retained rather than replaced.
assert pkgs.nixVersions.stable.tests ? srcVersion;
assert pkgs.nixVersions.stable.tests ? nixpkgs-lib;
assert pkgs.nixVersions.stable.tests ? nix-fallback-paths;
assert pkgs.nixVersions.nix_2_34.tests ? srcVersion;

# The Podman the container units run, including the helper override that the
# NixOS podman module applies on top of the pinned build.
assert config.virtualisation.podman.package.version == podmanFixedVersion;
assert config.virtualisation.podman.package.src == pkgs.podman.src;
assert pkgs.podman.version == podmanFixedVersion;

# The pinned builds come from the upstream release trees, not from a rebuilt
# tree that only carries the version string.
assert pkgs.nix.src != pkgs.nixVersions.latest.src;
assert pkgs.podman.src != flake.inputs.nixpkgs.legacyPackages.${pkgs.stdenv.hostPlatform.system}.podman.src;

# The Podman helper wrapper and the security inputs survive the version bump.
assert pkgs.podman.passthru.helpersBin != null;
assert pkgs.podman.passthru.binPath != [ ];

# The nix-daemon the host runs is the pinned build, and it is restarted rather
# than stopped when the unit changes.
assert lib.elem config.nix.package.out config.systemd.services.nix-daemon.path;
assert config.systemd.services.nix-daemon.restartIfChanged;
assert !config.systemd.services.nix-daemon.stopIfChanged;

# The container unit that runs the T3 Code image keeps the podman package it
# was built against.
assert lib.elem config.virtualisation.podman.package config.systemd.services.podman-t3code.path;

# Every host in this repository resolves the same pinned releases.
assert builtins.all (
  name:
  let
    candidate = flake.nixosConfigurations.${name};
  in
  candidate.config.nix.package.version == nixFixedVersion
  && candidate.config.virtualisation.podman.package.version == podmanFixedVersion
) (builtins.attrNames flake.nixosConfigurations);

true
