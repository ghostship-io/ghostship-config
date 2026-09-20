{ lib ? null }:

let
  versions = import ./versions.nix;
in
{
  inherit versions;

  providers = {
    codex = {
      name = "codex";
      package = versions.codex.package;
      version = versions.codex.version;
      required = true;
      authType = "native";
      skillDirs = [ ".agents/skills" ];
      description = "OpenAI Codex CLI provider";
      binary = "codex";
    };

    claude = {
      name = "claude";
      package = versions.claude.package;
      version = versions.claude.version;
      required = true;
      authType = "native";
      skillDirs = [ ".claude/skills" ".agents/skills" ];
      description = "Anthropic Claude Code provider";
      binary = "claude";
    };

    opencode = {
      name = "opencode";
      package = versions.opencode.package;
      version = versions.opencode.version;
      required = true;
      authType = "instance-env";
      skillDirs = [ ".agents/skills" ];
      description = "OpenCode AI provider";
      binary = "opencode";
    };

    grok = {
      name = "grok";
      package = versions.grok.package;
      version = versions.grok.version;
      required = false;
      authType = "native";
      skillDirs = [ ".agents/skills" ];
      description = "xAI Grok CLI provider";
      binary = "grok";
    };

    antigravity = {
      name = "antigravity";
      specialPlatformAdapter = true;
      required = false;
      authType = "account-instance";
      skillDirs = [ ".gemini/config/skills" ];
      description = "Antigravity ACP provider";
      binary = "agy_acp_server.par";
    };
  };
}
