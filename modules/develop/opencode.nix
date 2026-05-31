{ ... }:

let
  opencode-config = builtins.toJSON {
    "$schema" = "https://opencode.ai/config.json";
    permission = "allow";
  };
in
{
  home.file.".config/opencode/opencode.json" = {
    text = opencode-config;
    force = true;
  };
}
