{ config, lib, pkgs, ... }:
let
  repositories = [ "ghostship-agent" "ghostship-config" "ghostship-3dprinting" ];
  tokenPath = "/run/ghostship-ci/registration-token";
  projection = config.ghostship.selfHostedSecrets.projections.ghostship-ci-registration;
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
  services.github-runners = lib.genAttrs repositories (repo: {
    enable = true;
    url = "https://github.com/ghostship-io/${repo}";
    name = "${repo}-fast";
    tokenFile = tokenPath;
    ephemeral = true;
    replace = true;
    extraLabels = [ "ghostship-fast" ];
    extraPackages = with pkgs; [ curl jq openssh python3 unzip xz ];
    extraEnvironment.XDG_CACHE_HOME = "/var/cache/github-ci-${repo}";
    # Read by the runner process, outside workflow-controlled environment.
    # The immutable hook runs before checkout and before container setup.
    extraEnvironment.ACTIONS_RUNNER_HOOK_JOB_STARTED = pkgs.writeShellScript "github-ci-source-guard.sh" ''
      exec ${pkgs.python3}/bin/python3 -I -S ${./github-ci-guard.py} "ghostship-io/${repo}"
    '';
    serviceOverrides = {
      CacheDirectory = "github-ci-${repo}";
      CacheDirectoryMode = "0700";
      CPUQuota = if repo == "ghostship-3dprinting" then "400%" else "200%";
      MemoryMax = "8G";
      TasksMax = 1024;
    };
  });
}
