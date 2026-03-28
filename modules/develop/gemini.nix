{ pkgs, lib, ... }:

let
  agentTooling = import ./agent-tooling.nix { inherit pkgs; };
in

{
  environment.etc."gemini-cli/settings.json".text = builtins.toJSON {
    general = {
      sessionRetention = {
        enabled = true;
        maxAge = "30d";
        warningAcknowledged = true;
      };
      defaultApprovalMode = "default";
      enablePromptCompletion = true;
    };
    experimental = {
      modelSteering = true;
      plan = true;
    };
    security = {
      auth = {
        selectedType = "oauth-personal";
      };
      enablePermanentToolApproval = true;
    };
    context = {
      fileFiltering = {
        respectGitIgnore = false;
      };
    };
    skills = {
      enabled = true;
      default = [ ];
    };
    hooksConfig = {
      enabled = true;
    };
    hooks = {
      Notification = [
        {
          matcher = "ToolPermission";
          hooks = [
            {
              name = "user-input-notifier";
              type = "command";
              command = "notify-send \"Gemini\" \"Tool requires approval...\" -u critical";
            }
          ];
        }
      ];
      AfterAgent = [
        {
          matcher = "*";
          hooks = [
            {
              name = "notify-waiting";
              type = "command";
              command = "notify-send \"AGENT\" \"Waiting for input...\" -u critical";
            }
          ];
        }
      ];
    };
  };
}
