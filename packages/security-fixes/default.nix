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
      # Carried over unchanged, the upstream check could only ever fail here:
      # the version it compares against is the one this overlay pins, and the
      # file it reads is the one this overlay cannot touch. A test that is
      # red by construction is not a regression test, it is a permanent
      # failure that every consumer of this package set inherits, so the
      # upstream comparison is replaced by the question that decides whether
      # the difference matters.
      #
      # The fallback paths name the Nix an installer fetches when the store
      # does not hold one. In the pinned nixpkgs input nothing reads that
      # file: the installer takes Nix from config.nix.package, which this
      # overlay does fix. The file is only read by the upstream check and by
      # the nixpkgs upgrade test. The difference between the file and the
      # installed Nix therefore cannot reach a runtime consumer, and that is
      # what this check proves:
      #
      #   * the file names the installed Nix, so there is no difference; or
      #   * the file names another release and nothing in the input's NixOS
      #     modules reads it, so the difference is inert.
      #
      # The check fails when the file names another release and the input
      # reads it, because then the difference would reach an installer that
      # would fetch the release the advisory lists as affected. It does not
      # try to repair the file, which belongs to the input; it reports the
      # state that needs the input to move to a Nix release that carries the
      # fix.
      #
      # The identity of the installed Nix is covered by the upstream
      # "srcVersion" test that this suite carries over: it compares the
      # reported version with the ".version" file of the fetched tree.
      nixFallbackPathsTest =
        prev.runCommand "test-nix-fallback-paths-are-not-consumed"
          {
            paths = lib.concatStringsSep "\n" (
              builtins.attrValues (
                import "${prev.path}/nixos/modules/installer/tools/nix-fallback-paths.nix"
              )
            );
            inherit (nix.package) version;
            # The NixOS module tree of the pinned input. A reader of the
            # fallback paths can only be a module of that tree, and the tree
            # is read from the input, so the check sees the input as it is.
            nixosModules = "${prev.path}/nixos";
          }
          ''
            # NOTE: name may contain cross compilation details between the pname
            #       and version this is permitted thanks to ([^-]*-)*
            if ! grep -vqE 'nix-([^-]*-)*${
              lib.strings.replaceStrings [ "." ] [ "\\." ] nix.version
            }$' <<< "$paths"; then
              echo "every fallback path names the installed Nix (nix-${nix.version})"
            else
              echo "the fallback paths name another release than the installed Nix (nix-${nix.version})"
              echo "The following paths are not up to date:"
              grep -v 'nix-${nix.version}$' <<< "$paths"
              echo
              consumers=$(grep -rl --include='*.nix' 'nix-fallback-paths' "$nixosModules" || true)
              if [ -z "$consumers" ]; then
                echo "Nothing in the pinned nixpkgs input reads the fallback paths."
                echo "The installer takes Nix from config.nix.package, which this overlay"
                echo "fixes, so the difference cannot reach a runtime consumer."
              else
                echo "The pinned nixpkgs input reads the fallback paths:"
                echo "$consumers"
                echo
                echo "The input has to move to a Nix release that carries the fix,"
                echo "because this repository cannot repair a file of the input."
                exit 1
              fi
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
