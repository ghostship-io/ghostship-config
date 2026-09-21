{ lib ? null }:

{
  providers = {
    codex = {
      name = "codex";
      package = "@openai/codex";
      autoUpdate = true;
      required = true;
      authType = "native";
      skillDirs = [ ".agents/skills" ];
      description = "OpenAI Codex CLI provider";
      binary = "codex";
    };

    claude = {
      name = "claude";
      package = "@anthropic-ai/claude-code";
      autoUpdate = true;
      required = true;
      authType = "native";
      skillDirs = [ ".claude/skills" ".agents/skills" ];
      description = "Anthropic Claude Code provider";
      binary = "claude";
    };

    cursor = {
      name = "cursor";
      package = "cursor-agent";
      autoUpdate = true;
      required = false;
      authType = "native";
      skillDirs = [ ".agents/skills" ];
      description = "Cursor AI Agent CLI";
      binary = "cursor";
    };

    opencode = {
      name = "opencode";
      package = "opencode-ai";
      autoUpdate = true;
      required = true;
      authType = "instance-env";
      skillDirs = [ ".agents/skills" ];
      description = "OpenCode AI provider";
      binary = "opencode";
    };

    grok = {
      name = "grok";
      package = "@xai-official/grok";
      autoUpdate = true;
      required = false;
      authType = "native";
      skillDirs = [ ".agents/skills" ];
      description = "xAI Grok CLI provider";
      binary = "grok";
    };

    antigravity = {
      name = "antigravity";
      specialPlatformAdapter = true;
      autoUpdate = true;
      required = false;
      authType = "account-instance";
      skillDirs = [ ".gemini/config/skills" ];
      description = "Antigravity ACP provider";
      binary = "agy_acp_server.par";
    };
  };
}
