# Shared active workspace for Wisp and the orchestrator (Basic Memory).
#
# Dark by default. Enabling this module is the owner's security decision: it
# joins the existing `ghostship_net` service network, adds the private data
# volume, and registers the notes tools on the connector. Nothing is attached
# until the reviewed configuration enables it.
#
# The image is built on the host (never pulled at runtime) from the pinned
# upstream release plus a pre-baked embedding model, so cold start needs no
# download:
#
#   podman build -f modules/self-hosted/agent-memory.Containerfile \
#     -t localhost/agent-memory:1.0.0 modules/self-hosted
#
# The container is unauthenticated by upstream design. Its only protection is
# the private service network and the authenticated connector boundary; never
# publish a port, route or hostname for it.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.ghostship.agentMemory;
  # Reuse the existing service network; no per-service network or DNS rule.
  network = "ghostship_net";
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

    # Create both projects before the server starts. `project add` is
    # idempotent (a repeat reindexes and exits 0). --network=none proves the
    # pre-baked model cache is sufficient: the bootstrap cannot download one.
    systemd.services.agent-memory-projects = {
      description = "Create the shared Basic Memory projects";
      before = [ "podman-agent-memory.service" ];
      requiredBy = [ "podman-agent-memory.service" ];
      # The bootstrap writes /data and loads the image's Python; run it under
      # the same enforced profile as the service, after the policy is loaded.
      after = [ "apparmor.service" ];
      requires = [ "apparmor.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        UMask = "0077";
      };
      script = ''
        ${config.virtualisation.podman.package}/bin/podman run --rm --pull=never --network=none \
          --user 3000:3000 \
          --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
          -e HOME=/tmp \
          -e BASIC_MEMORY_CONFIG_DIR=/data/config \
          -e BASIC_MEMORY_HOME=/data/projects/.main \
          -e BASIC_MEMORY_PROJECT_ROOT=/data/projects \
          -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache \
          -v ${cfg.dataDir}:/data:rw \
          --security-opt=apparmor=ghostship-agent-memory \
          ${cfg.image} \
          basic-memory project add ${cfg.project} /data/projects/${cfg.project}
        ${config.virtualisation.podman.package}/bin/podman run --rm --pull=never --network=none \
          --user 3000:3000 \
          --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
          -e HOME=/tmp \
          -e BASIC_MEMORY_CONFIG_DIR=/data/config \
          -e BASIC_MEMORY_HOME=/data/projects/.main \
          -e BASIC_MEMORY_PROJECT_ROOT=/data/projects \
          -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache \
          -v ${cfg.dataDir}:/data:rw \
          --security-opt=apparmor=ghostship-agent-memory \
          ${cfg.image} \
          basic-memory project add ${cfg.testProject} /data/projects/${cfg.testProject}
      '';
    };

    # The dashboard inventory requires every declared container to have an
    # entry; Basic Memory is internal, so it has no hostname, port or route.
    ghostship.apps.agent-memory = {
      container = "agent-memory";
      group = "Agent";
      description = "Basic Memory MCP store shared with the orchestrator";
      apparmorProfile = "ghostship-agent-memory";
    };

    # Strict, enforced profile; the process runs as uid 3000 with no
    # capabilities and the allowlist is derived from the pinned Containerfile.
    security.apparmor.policies.ghostship-agent-memory = {
      state = "enforce";
      profile = builtins.readFile ./apparmor/agent-memory.profile;
    };

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
      after = [ "agent-memory-projects.service" ];
      requires = [ "agent-memory-projects.service" ];
    };

    # The connector reaches the MCP endpoint over the existing service network.
    # t3code is already a member; this adds only the notes environment.
    # No host port, Cloudflare route or muximux entry exists.
    virtualisation.oci-containers.containers."t3code" = {
      environment = {
        GHOSTSHIP_NOTES_ENDPOINT = endpoint;
        GHOSTSHIP_NOTES_ALLOW_PRIVATE_HTTP = "1";
        GHOSTSHIP_NOTES_PROJECT = cfg.project;
        GHOSTSHIP_NOTES_TEST_PROJECT = cfg.testProject;
      };
    };
  };
}
