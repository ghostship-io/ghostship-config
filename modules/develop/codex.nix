{ config, ... }:

{
  home.file.".codex/AGENTS.md" = {
    source = ../../home/config/AGENTS.md;
    force = true;
  };
}
