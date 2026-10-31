# Shared active workspace for Wisp and the orchestrator (Basic Memory).
#
# Dark by default. Enabling this module is the owner's security decision: it
# creates a dedicated internal Podman network with only `t3code` and
# `agent-memory`, adds the private data volume, and registers the notes tools
# on the connector. Nothing is attached until the reviewed configuration
# enables it.
#
# The image is built on the host (never pulled at runtime) from the pinned
# upstream release plus a pre-baked embedding model, so the service has no
# egress and no model download at cold start:
#
#   podman build -f modules/self-hosted/agent-memory.Containerfile \
#     -t localhost/agent-memory:1.0.0 modules/self-hosted
#
# The container is unauthenticated by upstream design. Its only protection is
# the dedicated network and the authenticated connector boundary; never publish
# a port, route or hostname for it.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.ghostship.agentMemory;
  network = "agent_memory_net";
  subnet = "10.89.23.0/24";
  gateway = "10.89.23.1";
  endpoint = "http://agent-memory:8000/mcp";
in
{
  options.ghostship.agentMemory = {
    enable = lib.mkEnableOption "the shared Basic Memory workspace and its connector tools";
    image = lib.mkOption {
      type = lib.types.str;
      default = "localhost/agent-memory:1.0.0";
      description = "Local image built from agent-memory.Containerfile; never pulled.";
    };
    dataDir = lib.mkOption {
      type = lib.types.str;
      default = "/srv/apps/agent-memory";
      description = "Private data volume for config, SQLite and Markdown notes.";
    };
    project = lib.mkOption {
      type = lib.types.str;
      default = "agent-memory";
      description = "Production project name; the only project the connector defaults to.";
    };
    testProject = lib.mkOption {
      type = lib.types.str;
      default = "agent-memory-test";
      description = "Separate project for disposable test fixtures.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.tmpfiles.rules = [
      "d ${cfg.dataDir} 0700 3000 3000 -"
      "d ${cfg.dataDir}/config 0700 3000 3000 -"
      "d ${cfg.dataDir}/projects 0700 3000 3000 -"
    ];

    systemd.services.init-agent-memory-net = {
      description = "Create the private agent memory Podman network";
      after = [ "network.target" ];
      before = [
        "podman-agent-memory.service"
        "podman-t3code.service"
      ];
      wantedBy = [ "multi-user.target" ];
      restartIfChanged = false;
      stopIfChanged = false;
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        ${pkgs.podman}/bin/podman network inspect ${network} >/dev/null 2>&1 || \
        ${pkgs.podman}/bin/podman network create --internal --subnet ${subnet} \
          --gateway ${gateway} ${network}
      '';
    };

    # Create both projects before the server starts. `project add` is
    # idempotent (a repeat reindexes and exits 0). --network=none proves the
    # pre-baked model cache is sufficient: the bootstrap cannot download one.
    systemd.services.agent-memory-projects = {
      description = "Create the shared Basic Memory projects";
      before = [ "podman-agent-memory.service" ];
      requiredBy = [ "podman-agent-memory.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        UMask = "0077";
      };
      script = ''
        ${pkgs.podman}/bin/podman run --rm --pull=never --network=none \
          --user 3000:3000 \
          --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
          -e HOME=/tmp \
          -e BASIC_MEMORY_CONFIG_DIR=/data/config \
          -e BASIC_MEMORY_HOME=/data/projects/.main \
          -e BASIC_MEMORY_PROJECT_ROOT=/data/projects \
          -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache \
          -v ${cfg.dataDir}:/data:rw \
          ${cfg.image} \
          basic-memory project add ${cfg.project} /data/projects/${cfg.project}
        ${pkgs.podman}/bin/podman run --rm --pull=never --network=none \
          --user 3000:3000 \
          --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
          -e HOME=/tmp \
          -e BASIC_MEMORY_CONFIG_DIR=/data/config \
          -e BASIC_MEMORY_HOME=/data/projects/.main \
          -e BASIC_MEMORY_PROJECT_ROOT=/data/projects \
          -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache \
          -v ${cfg.dataDir}:/data:rw \
          ${cfg.image} \
          basic-memory project add ${cfg.testProject} /data/projects/${cfg.testProject}
      '';
    };

    # Netavark adds no DNS input rule for an internal network. Without this,
    # t3code cannot resolve `agent-memory` through aardvark-dns; the network
    # still has no external route. Same rule as the github internal network.
    networking.firewall.extraCommands = lib.concatMapStrings (proto: ''
      iptables -w -A nixos-fw -s ${subnet} -d ${gateway} -p ${proto} --dport 53 -j nixos-fw-accept
    '') [ "udp" "tcp" ];

    virtualisation.oci-containers.containers."agent-memory" = {
      image = cfg.image;
      pull = "never";
      user = "3000:3000";
      cmd = [
        "basic-memory"
        "mcp"
        "--transport"
        "streamable-http"
        "--host"
        "0.0.0.0"
        "--port"
        "8000"
        "--path"
        "/mcp"
      ];
      environment = {
        HOME = "/tmp";
        BASIC_MEMORY_CONFIG_DIR = "/data/config";
        # Basic Memory seeds a `main` project when none exists. Keep it in an
        # empty sibling so it never indexes the image or a named project; the
        # connector allow-list refuses it and every caller names a real project.
        BASIC_MEMORY_HOME = "/data/projects/.main";
        BASIC_MEMORY_PROJECT_ROOT = "/data/projects";
        FASTEMBED_CACHE_PATH = "/opt/agent-memory/fastembed_cache";
        # Accepted DB transactions survive an OS or power failure. The
        # Markdown materialization is atomic but not fsynced, so the backup is
        # the recovery for the last bytes; see docs/agent-operations.md.
        BASIC_MEMORY_SQLITE_SYNCHRONOUS = "FULL";
        # Metadata and text reads are the contract; hybrid search is not.
        BASIC_MEMORY_DEFAULT_SEARCH_TYPE = "text";
        BASIC_MEMORY_LOG_LEVEL = "INFO";
      };
      volumes = [
        "${cfg.dataDir}:/data:rw,noexec,nosuid,nodev"
      ];
      extraOptions = [
        "--network=${network}"
        "--hostname=agent-memory"
        "--cap-drop=ALL"
        "--security-opt=no-new-privileges"
        "--pids-limit=256"
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m"
        "--health-cmd=basic-memory --version"
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=30s"
        "--health-on-failure=kill"
      ];
    };

    systemd.services.podman-agent-memory = {
      after = [
        "init-agent-memory-net.service"
        "agent-memory-projects.service"
      ];
      requires = [ "agent-memory-projects.service" ];
    };

    # The connector reaches the private MCP endpoint on the dedicated network.
    # No host port, Cloudflare route or muximux entry exists.
    virtualisation.oci-containers.containers."t3code" = {
      extraOptions = lib.mkAfter [ "--network=${network}" ];
      environment = {
        GHOSTSHIP_NOTES_ENDPOINT = endpoint;
        GHOSTSHIP_NOTES_ALLOW_PRIVATE_HTTP = "1";
        GHOSTSHIP_NOTES_PROJECT = cfg.project;
        GHOSTSHIP_NOTES_TEST_PROJECT = cfg.testProject;
      };
    };

    systemd.services.podman-t3code = {
      after = lib.mkAfter [ "init-agent-memory-net.service" ];
      requires = lib.mkAfter [ "init-agent-memory-net.service" ];
    };
  };
}
