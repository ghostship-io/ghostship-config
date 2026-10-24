{ config, lib, pkgs, ... }:
let
  runners = [ "ghostship-agent" "ghostship-agent-2" "ghostship-config" "ghostship-3dprinting" ];
  repositoryFor = name: if name == "ghostship-agent-2" then "ghostship-agent" else name;
  runnerNameFor = name: if name == "ghostship-agent-2" then "ghostship-agent-fast-2" else "${name}-fast";
  tokenPath = "/run/ghostship-ci/registration-token";
  projection = config.ghostship.selfHostedSecrets.projections.ghostship-ci-registration;
  registrationCommand = name: op: lib.escapeShellArgs [
    "${pkgs.python3}/bin/python3" "${./github-ci-register.py}" "--op" op
    "--runner" "${config.services.github-runners.${name}.package}/bin/Runner.Listener"
    "--token-file" tokenPath "--repository" "ghostship-io/${repositoryFor name}"
    "--name" (runnerNameFor name) "--label" "ghostship-fast"
    "--state-dir" "/var/lib/github-runner/${name}"
    "--work-dir" "/run/github-runner/${name}"
    "--logs-dir" "/var/log/github-runner/${name}"
  ];
in
{
  # Repository-scoped runners need no organization-admin token. The normal
  # runner module hides the registration PAT from job processes. Each job gets
  # a clean workspace/user while the Nix store and per-repository caches persist.
  ghostship.secretProjections.ghostship-ci-registration = {
    fileName = "ghostship-ci/registration.env";
    owner = "root";
    group = "root";
    mode = "0400";
    fields.GITHUB_TOKEN = { unit = "github-runner-registration"; key = "TOKEN"; };
  };
  system.activationScripts.ghostship-ci-registration = {
    deps = [ "ghostship-secret-projections" ];
    text = ''
      (
        set -eu
        . ${projection.path}
        test -n "$GITHUB_TOKEN"
        umask 077
        ${pkgs.coreutils}/bin/install -d -m0700 /run/ghostship-ci
        printf %s "$GITHUB_TOKEN" > ${tokenPath}.new
        ${pkgs.coreutils}/bin/chmod 0600 ${tokenPath}.new
        ${pkgs.coreutils}/bin/mv ${tokenPath}.new ${tokenPath}
      )
    '';
    supportsDryActivation = false;
  };
  services.github-runners = lib.genAttrs runners (name: let repo = repositoryFor name; in {
    enable = true;
    url = "https://github.com/ghostship-io/${repo}";
    name = runnerNameFor name;
    tokenFile = tokenPath;
    ephemeral = true;
    replace = true;
    extraLabels = [ "ghostship-fast" ];
    extraPackages = with pkgs; [ curl jq openssh python3 unzip xz ];
    extraEnvironment.XDG_CACHE_HOME = "/var/cache/github-ci-${name}";
    # Keep commit history for ledger guards, fetching old file blobs on demand.
    # This also fixes queued workflows whose checkout still requests all history.
    extraEnvironment.GIT_CONFIG_COUNT = "2";
    extraEnvironment.GIT_CONFIG_KEY_0 = "remote.origin.promisor";
    extraEnvironment.GIT_CONFIG_VALUE_0 = "true";
    extraEnvironment.GIT_CONFIG_KEY_1 = "remote.origin.partialclonefilter";
    extraEnvironment.GIT_CONFIG_VALUE_1 = "blob:none";
    # Read by the runner process, outside workflow-controlled environment.
    # The immutable hook runs before checkout and before container setup.
    extraEnvironment.ACTIONS_RUNNER_HOOK_JOB_STARTED = pkgs.writeShellScript "github-ci-source-guard.sh" ''
      exec ${pkgs.python3}/bin/python3 -I -S ${./github-ci-guard.py} "ghostship-io/${repo}"
    '';
    serviceOverrides = {
      # The upstream configure helper puts the PAT in --pat and a temporary
      # user-readable file. Keep B in the root registrar; only its one-use
      # registration token reaches the configure process, through its environment.
      ExecStartPre = lib.mkForce [
        ("+" + registrationCommand name "prepare")
        (registrationCommand name "configure")
      ];
      # The former .current-token copy no longer exists. Hide the root PAT
      # source from configure/run; only the privileged preparation reads it.
      InaccessiblePaths = lib.mkForce [ "-${tokenPath}" ];
      CacheDirectory = "github-ci-${name}";
      CacheDirectoryMode = "0700";
      CPUQuota = if repo == "ghostship-3dprinting" then "400%" else "200%";
      MemoryMax = "8G";
      TasksMax = 1024;
    };
  });
}
