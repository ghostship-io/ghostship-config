{ pkgs }:
(pkgs.buildGoModule.override { go = pkgs.go_1_26; }) {
  pname = "ghostship-mcp-rollout";
  version = "1";
  src = ./.;
  vendorHash = null;
  subPackages = [ "." ];
  meta.mainProgram = "mcp-rollout";
}
