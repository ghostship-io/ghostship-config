{ lib, ... }:

{
  options.ghostship.agentHost = {
    enable = lib.mkEnableOption "Ghostship agent host platform";

    uid = lib.mkOption {
      type = lib.types.int;
      default = 3000;
      description = "Default UID for agent execution";
    };

    gid = lib.mkOption {
      type = lib.types.int;
      default = 3000;
      description = "Default GID for agent execution";
    };

    workspacePath = lib.mkOption {
      type = lib.types.str;
      default = "/srv/ghostship/workspace";
      description = "Host path mounted as /workspace inside the agent runtime";
    };

    sharedPath = lib.mkOption {
      type = lib.types.str;
      default = "/mnt/share";
      description = "Host shared path for media and bulk storage";
    };

    readOnlyShare = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Whether to mount /mnt/share as read-only inside agent containers by default";
    };
  };

  options.ghostship.agentProjects = lib.mkOption {
    type = lib.types.attrsOf (
      lib.types.submodule {
        options = {
          name = lib.mkOption {
            type = lib.types.str;
            description = "Project name";
          };
          path = lib.mkOption {
            type = lib.types.str;
            description = "Absolute path to the project inside /workspace";
          };
          autoRegister = lib.mkOption {
            type = lib.types.bool;
            default = true;
            description = "Whether to automatically register the project with active agent control planes";
          };
          defaultBranch = lib.mkOption {
            type = lib.types.str;
            default = "main";
            description = "Default Git branch for this project";
          };
          description = lib.mkOption {
            type = lib.types.str;
            default = "";
            description = "Project purpose and role description";
          };
        };
      }
    );
    default = {
      ghostship-agent = {
        name = "ghostship-agent";
        path = "/workspace/ghostship-agent";
        autoRegister = true;
        defaultBranch = "main";
        description = "Shared provider-neutral Ghostship agent tooling, skills, and operations workspace";
      };
      nixos-config = {
        name = "nixos-config";
        path = "/workspace/nixos-config";
        autoRegister = true;
        defaultBranch = "main";
        description = "Authoritative NixOS system configuration for chill-penguin";
      };
      ghostship-roms = {
        name = "ghostship-roms";
        path = "/workspace/ghostship-roms";
        autoRegister = true;
        defaultBranch = "main";
        description = "ROM management and automation workflows";
      };
      ghostship-newsletter = {
        name = "ghostship-newsletter";
        path = "/workspace/ghostship-newsletter";
        autoRegister = true;
        defaultBranch = "main";
        description = "Ghostship newsletter and publication workspace";
      };
    };
    description = "Declarative registry of Ghostship agent projects";
  };
}
