# Nix 2.34.9 - security fix for the October 2026 coordinated disclosure.
#
# Upstream advisory:
# https://discourse.nixos.org/t/security-advisory-for-nix-and-lix-october-2026/80547
#
#   CVE-2026-110449  unsigned integer overflow in list allocation, leading to
#                    a heap out-of-bounds write while evaluating untrusted
#                    expressions (GHSA-25vp-6h23-hj3g)
#   CVE-2026-110450  unprivileged "repair" could destroy and replace a
#                    legitimate store path before its contents were verified,
#                    enabling local privilege escalation
#                    (GHSA-jwvx-xq5j-gc56)
#   CVE-2026-110451  macOS Seatbelt sandbox escape; macOS only and this
#                    deployment is Linux (GHSA-m4vq-qf6v-82pj)
#   CVE-2026-110452  multi-user installer left store contents owned by the
#                    invoking user; installer only, NixOS installs unaffected
#                    (GHSA-hf6w-2rg9-v84g)
#   CVE-2026-110453  nix-daemon did not reject build users on unsandboxed
#                    macOS/FreeBSD configurations (GHSA-92x5-h528-wrmw)
#
# The pinned nixpkgs still carries Nix 2.34.8 on its 2.34 maintenance line, so
# the 2.34 branch is pinned here instead of bumping nixpkgs. Nix 2.34.9 is the
# upstream fix release for exactly that line.
{
  pkgs,
  prev,
}:
let
  version = "2.34.9";

  src = pkgs.fetchFromGitHub {
    owner = "NixOS";
    repo = "nix";
    tag = version;
    # Verified against the fetched tree. Identical to the hash upstream
    # nixpkgs published for the same bump (nixpkgs pull request 573623).
    hash = "sha256-ZJwg/qG4M1Impy774HKMZ3Hsq7vlBJy7sXl1fI9QDXI=";
  };

  # nixpkgs builds Nix from a release source tree that its expression pins per
  # release. overrideSource swaps that tree; overrideAllMesonComponents then
  # re-stamps the version on every component, so the derivation name, the
  # ".version" file written into the build tree and the reported version all
  # agree with the fetched source. Overriding the source alone would leave a
  # 2.34.9 tree labelled 2.34.8.
  scope =
    (
      (prev.nixVersions.nixComponents_2_34.overrideSource src)
        .overrideScope (_finalScope: _prevScope: { inherit version; })
    )
      .overrideAllMesonComponents (_final: _prev: { inherit version; });

  package = scope.nix-everything;
in
{
  inherit version src package scope;
}
