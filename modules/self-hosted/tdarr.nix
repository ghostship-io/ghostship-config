{ ... }:
{
  # Pilot: only staged copies are writable. Production is mounted read-only.
  # Root startup is required by the upstream image's ownership initialization;
  # Tdarr runs with the standard apps PUID/PGID afterward.
  virtualisation.oci-containers.containers.tdarr = {
    image = "ghcr.io/haveagitgat/tdarr:latest";
    pull = "always";
    podman.sdnotify = "healthy";
    environment = {
      TZ = "UTC";
      PUID = "3000";
      PGID = "3000";
      serverIP = "0.0.0.0";
      serverPort = "8266";
      webUIPort = "8265";
      internalNode = "true";
      inContainer = "true";
      nodeName = "chill-penguin-cpu-pilot";
      startPaused = "true";
      transcodecpuWorkers = "1";
      transcodegpuWorkers = "0";
      healthcheckcpuWorkers = "1";
      healthcheckgpuWorkers = "0";
      ffmpegVersion = "7";
      openBrowser = "false";
      cronPluginUpdate = "";
    };
    volumes = [
      "/srv/apps/tdarr/server:/app/server"
      "/srv/apps/tdarr/configs:/app/configs"
      "/srv/apps/tdarr/logs:/app/logs"
      "/srv/apps/tdarr/cache:/temp"
      "/srv/apps/tdarr/pilot:/media"
      "/mnt/share/Library/Movies:/source/Movies:ro"
      "/mnt/share/Library/TV:/source/TV:ro"
    ];
    extraOptions = [
      "--network=ghostship_net"
      "--cpus=2"
      "--memory=6g"
      "--health-cmd=curl -fsS --max-time 5 http://127.0.0.1:8265/ >/dev/null || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=3m"
      "--health-on-failure=kill"
    ];
  };
  systemd.tmpfiles.rules = map
    (dir: "d /srv/apps/tdarr${dir} 0750 apps apps -")
    [ "" "/server" "/configs" "/logs" "/cache" "/pilot" ];
  systemd.services.podman-tdarr = {
    after = [ "init-ghostship-net.service" ];
    requires = [ "init-ghostship-net.service" ];
    unitConfig.RequiresMountsFor = [ "/mnt/share/Library" ];
    serviceConfig = {
      Nice = 15;
      IOWeight = 10;
    };
  };
}
