{
  config,
  lib,
  osConfig,
  pkgs,
  ...
}:

let
  worker = osConfig.ghostship.t3Worker;
in
{
  # The develop profile already links the repo-local instructions to the Codex,
  # OpenCode, Gemini, and worker-facing paths. The shared skill catalog is
  # linked by ghostship-agent-sync; this profile owns the remaining provider
  # instruction entrypoints and the worker environment variables.
  home.file = lib.mkIf worker.enable {
    ".agents/AGENTS.md".source = ../config/AGENTS.md;
    ".claude/CLAUDE.md".source = ../config/AGENTS.md;
  };

  home.sessionVariables = lib.mkIf worker.enable {
    T3CODE_HOME = worker.baseDir;
  };

  # `t3 connect` and `t3 serve` need the installed agent CLIs on PATH. The
  # develop role's wrappers expose codex/opencode/claude/cursor/gemini, and
  # ghostship-agent-maintenance installs t3 and grok into the same prefix.
  home.sessionPath = lib.mkIf worker.enable [
    "$HOME/.local/share/ghostship-agent-tools/npm/bin"
    "$HOME/.local/bin"
  ];
}
