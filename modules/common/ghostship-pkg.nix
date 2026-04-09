self: super: {
  agent-deck = super.callPackage ../../pkgs/agent-deck.nix { };

  ghostship-config = super.writers.writePython3Bin "ghostship-config" {
    libraries = with super.python3Packages; [
      lxml
      ruamel-yaml
    ];
  } (builtins.readFile ./scripts/ghostship-config.py);
}
