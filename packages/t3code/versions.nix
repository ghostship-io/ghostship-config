{
  t3 = {
    version = "0.0.40";
    package = "t3";
  };

  codex = {
    version = "0.154.0";
    package = "@openai/codex";
  };

  claude = {
    version = "1.0.0";
    package = "@anthropic-ai/claude-code";
  };

  opencode = {
    version = "1.18.31";
    package = "opencode-ai";
    platformPackageArm64 = "opencode-linux-arm64";
    platformPackageX64 = "opencode-linux-x64";
  };

  grok = {
    version = "1.0.34";
    package = "@xai-official/grok";
  };

  antigravity = {
    version = "1.1.1";
    specialPlatformAdapter = true;
  };
}
