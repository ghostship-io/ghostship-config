# Narrow nixpkgs overlay for the two packages covered by the October 2026
# upstream security advisories.
#
# Nothing else in the pinned nixpkgs is touched. The overlay replaces Nix on
# the 2.34 maintenance line and Podman on the 5.8 line, and repoints the
# aliases that name that Nix line at the pinned build:
#
#   pkgs.nix
#   pkgs.nixVersions.stable
#   pkgs.nixVersions.nix_2_34
#   pkgs.nixVersions.nixComponents_2_34
#
# The other Nix lines that the pinned nixpkgs carries (2.31, 2.35 and the git
# snapshot) are not repointed. They stay on the releases the nixpkgs input
# ships, and the same advisory lists those releases as affected. This overlay
# deliberately does not widen to them; see docs/security-package-fixes.md.
#
# Everything here is derived from "prev" (the package set as it stands before
# this overlay). Reading "final" would make the overlay depend on its own
# result, because the result publishes the pinned nixVersions scope.
{
  overlay =
    final: prev:
    let
      inherit (prev) lib;

      nix = import ./nix-2.34.9.nix {
        pkgs = prev;
        prev = prev;
      };

      podman = import ./podman-5.8.8.nix {
        pkgs = prev;
        prev = prev;
      };

      # The upstream Nix test suite, imported from the pinned nixpkgs and bound
      # to the pinned build. The suite is upstream's own file; only the package
      # it is bound to changes. It carries the packaging regression that
      # matters here, "srcVersion", which compares the reported version with
      # the ".version" file of the fetched tree, and the nixpkgs library suite
      # that runs against the pinned Nix.
      nixTests =
        import ("${prev.path}/pkgs/tools/package-management/nix/tests.nix") {
          inherit (prev) runCommand stdenv pkgs pkgsi686Linux pkgsStatic nixosTests;
          inherit lib;
          inherit (nix.package) version src;
          nix = nix.package;
          self_attribute_name = "nix_2_34";
        };

      # Upstream nixpkgs checks that the fallback paths in
      # nixos/modules/installer/tools/nix-fallback-paths.nix name the same Nix
      # version as nixVersions.stable. That file belongs to the nixpkgs input
      # and still names 2.34.8, and this overlay cannot repair a file inside
      # the input it does not own.
      #
      # The check is carried over unchanged and bound to the pinned build, so
      # that the drift stays visible instead of being hidden: it fails until
      # the nixpkgs input moves to a release that carries the fix. It is
      # deliberately not replaced with a check against a file this repository
      # owns, because such a check would only prove that the file matches
      # itself.
      #
      # In the pinned nixpkgs the fallback paths file has no runtime consumer:
      # the installer takes Nix from config.nix.package, which this overlay
      # does fix. The file is only read by this check and by the nixpkgs
      # upgrade test.
      nixFallbackPathsTest =
        prev.runCommand "test-nix-fallback-paths-version-equals-nix-stable"
          {
            inherit lib;
            paths = lib.concatStringsSep "\n" (
              builtins.attrValues (
                import "${prev.path}/nixos/modules/installer/tools/nix-fallback-paths.nix"
              )
            );
            inherit (nix.package) version;
          }
          ''
            # NOTE: name may contain cross compilation details between the pname
            #       and version this is permitted thanks to ([^-]*-)*
            if [[ "" != $(grep -vE 'nix-([^-]*-)*${
              lib.strings.replaceStrings [ "." ] [ "\\." ] nix.version
            }$' <<< "$paths") ]]; then
              echo "nix-fallback-paths not up to date with nixVersions.stable (nix-${nix.version})"
              echo "The following paths are not up to date:"
              grep -v 'nix-${nix.version}$' <<< "$paths"
              echo
              echo "The pinned nixpkgs input still names an older Nix release in"
              echo "nixos/modules/installer/tools/nix-fallback-paths.nix. That file is"
              echo "part of the nixpkgs input, so this repository cannot repair it;"
              echo "the input has to move to a Nix release that carries the fix."
              exit 1
            fi
            touch $out
          '';

      # Mirror the shape upstream nixpkgs gives nix_2_34 and stable: the
      # package carries its test suite at the top level and under passthru.
      nix_2_34 =
        nix.package
        // {
          tests = nix.package.tests or { } // nixTests;
          passthru =
            nix.package.passthru or { }
            // {
              tests = nix.package.passthru.tests or { } // nixTests;
            };
        };

      stable =
        nix_2_34
        // {
          tests = nix_2_34.tests // { nix-fallback-paths = nixFallbackPathsTest; };
          passthru =
            nix_2_34.passthru
            // {
              tests = nix_2_34.passthru.tests // { nix-fallback-paths = nixFallbackPathsTest; };
            };
        };
    in
    {
      nix = stable;
      podman = podman.package;

      # Repoint the aliases that name the 2.34 line at the pinned build.
      nixVersions =
        prev.nixVersions
        // {
          nixComponents_2_34 = nix.scope;
          nix_2_34 = nix_2_34;
          stable = stable;
        };
    };
}
