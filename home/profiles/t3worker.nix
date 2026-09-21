{
  config,
  lib,
  osConfig,
  ...
}:

let
  worker = osConfig.ghostship.t3Worker;

  # WSL2 workers are standalone Windows development boxes, not Ghostship
  # runtime hosts. They receive only the skills and instructions that live in
  # this repository; the ghostship-agent catalog is intentionally not installed
  # or cloned on them.
  repoSKills = [
    "ghostship-audit-worktree"
    "ghostship-merge-worktree"
    "ghostship-pull-worktree"
    "grill-me"
  ];

  skillLink = name: {
    ".claude/skills/${name}".source = ../config/skills/${name};
    ".gemini/config/skills/${name}".source = ../config/skills/${name};
  };
in
{
  # The develop profile already links the repo-local skills under
  # ~/.agents/skills and the shared instructions to the Codex, OpenCode, and
  # Gemini entrypoints. This profile adds the remaining provider instruction
  # path and mirrors the skills to Claude Code and Antigravity ACP.
  home.file = lib.mkIf worker.enable (
    lib.mkMerge [
      {
        ".agents/AGENTS.md".source = ../config/AGENTS.md;
        ".claude/CLAUDE.md".source = ../config/AGENTS.md;
      }
      (lib.mkMerge (map skillLink repoSKills))
    ]
  );

  home.sessionVariables = lib.mkIf worker.enable {
    T3CODE_HOME = worker.baseDir;
  };

  # `t3 connect` and `t3 serve` need the installed agent CLIs on PATH. The
  # develop role's wrappers expose codex/opencode/claude/cursor/gemini, and the
  # maintenance service installs t3 and grok into the same prefix.
  home.sessionPath = lib.mkIf worker.enable [
    "$HOME/.local/share/ghostship-agent-tools/npm/bin"
    "$HOME/.local/bin"
  ];
}
