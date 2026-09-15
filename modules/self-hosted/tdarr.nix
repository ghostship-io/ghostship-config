{
  config,
  lib,
  pkgs,
  ...
}:
let
  ffmpeg = lib.getExe pkgs.ffmpeg-headless;
  podman = lib.getExe config.virtualisation.podman.package;
  flow = builtins.fromJSON (builtins.readFile ./tdarr-flow.json);
  hours = lib.range 0 23;
  days = [
    "Sun"
    "Mon"
    "Tue"
    "Wed"
    "Thur"
    "Fri"
    "Sat"
  ];
  hourString = hour: if hour < 10 then "0${toString hour}" else toString hour;
  pilotLibrary = {
    _id = "plex-hevc-pilot";
    name = "Plex HEVC Pilot";
    priority = 0;
    folder = "/media";
    foldersToIgnore = "";
    foldersToIgnoreCaseInsensitive = false;
    folderWatchScanInterval = 300;
    scannerThreadCount = 1;
    cache = "/temp/pilot";
    output = "";
    folderToFolderConversion = false;
    folderToFolderConversionDeleteSource = false;
    folderToFolderRecordHistory = true;
    copyIfConditionsMet = false;
    container = ".mkv";
    containerFilter = "mkv,mp4,mov,m4v,mpg,mpeg,avi,webm,wmv,m2ts,ts";
    createdAt = 1789430400000;
    folderWatching = false;
    useFsEvents = false;
    scheduledScanFindNew = false;
    processLibrary = true;
    processTranscodes = true;
    processHealthChecks = false;
    scanOnStart = false;
    exifToolScan = true;
    mediaInfoScan = true;
    ffprobeShowData = false;
    isDirectoryLibrary = false;
    closedCaptionScan = false;
    scanButtons = true;
    scanFound = "";
    navItemSelected = "navSourceFolder";
    pluginIDs = [ ];
    pluginCommunity = true;
    handbrake = false;
    ffmpeg = true;
    handbrakescan = false;
    ffmpegscan = true;
    preset = "";
    decisionMaker = {
      settingsPlugin = false;
      settingsFlows = true;
      settingsVideo = false;
      settingsAudio = false;
      videoExcludeSwitch = false;
      video_codec_names_exclude = [ ];
      video_size_range_include = {
        min = 0;
        max = 100000;
      };
      video_height_range_include = {
        min = 0;
        max = 1080;
      };
      video_width_range_include = {
        min = 0;
        max = 1920;
      };
      audioExcludeSwitch = false;
      audio_codec_names_exclude = [ ];
      audio_size_range_include = {
        min = 0;
        max = 100000;
      };
    };
    flowId = flow._id;
    schedule = lib.concatMap (
      day:
      map (hour: {
        _id = "${day}:${hourString hour}-${hourString (lib.mod (hour + 1) 24)}";
        # Node pause is the processing gate. An all-false library schedule
        # keeps queued files out of the transcode table.
        checked = true;
      }) hours
    ) days;
    totalHealthCheckCount = 0;
    totalTranscodeCount = 0;
    sizeDiff = 0;
    holdNewFiles = false;
    holdFor = 3600;
    holdForDisplayUnit = "hours";
    pluginStackOverview = false;
    filterResolutionsSkip = "";
    filterCodecsSkip = "";
    filterContainersSkip = "";
    filterHardlinked = false;
    processPluginsSequentially = true;
  };
  request =
    collection: mode: docID: obj:
    pkgs.writeText "tdarr-${docID}-${mode}.json" (
      builtins.toJSON {
        data = {
          inherit
            collection
            mode
            docID
            obj
            ;
        };
      }
    );
  getRequest =
    collection: docID:
    pkgs.writeText "tdarr-${docID}-get.json" (
      builtins.toJSON {
        data = {
          inherit collection docID;
          mode = "getById";
        };
      }
    );
  flowGet = getRequest "FlowsJSONDB" flow._id;
  flowInsert = request "FlowsJSONDB" "insert" flow._id flow;
  flowUpdate = request "FlowsJSONDB" "update" flow._id flow;
  libraryGet = getRequest "LibrarySettingsJSONDB" pilotLibrary._id;
  libraryInsert = request "LibrarySettingsJSONDB" "insert" pilotLibrary._id pilotLibrary;
  libraryUpdate = request "LibrarySettingsJSONDB" "update" pilotLibrary._id pilotLibrary;
  bootstrap = pkgs.writeShellApplication {
    name = "tdarr-bootstrap";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      upsert() {
        get_request="$1"
        insert_request="$2"
        update_request="$3"
        existing="$(${podman} exec tdarr curl -fsS -H 'Content-Type: application/json' \
          --data-binary "@$get_request" http://127.0.0.1:8265/api/v2/cruddb)"
        if test -n "$existing"; then
          request_file="$update_request"
        else
          request_file="$insert_request"
        fi
        ${podman} exec tdarr curl -fsS -H 'Content-Type: application/json' \
          --data-binary "@$request_file" http://127.0.0.1:8265/api/v2/cruddb >/dev/null
      }

      upsert /bootstrap/flow-get.json /bootstrap/flow-insert.json /bootstrap/flow-update.json
      upsert /bootstrap/library-get.json /bootstrap/library-insert.json /bootstrap/library-update.json
    '';
  };
in
{
  # Pilot: only staged copies are writable. Production is mounted read-only.
  # Root startup is required by the upstream image's ownership initialization;
  # Tdarr runs with the standard apps PUID/PGID afterward.
  virtualisation.oci-containers.containers.tdarr = {
    image = "ghcr.io/haveagitgat/tdarr@sha256:a7cf8ad422a5a640588f496150f42e5def8060041bb02f348d319062161f5b2c";
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
      ffmpegPath = ffmpeg;
      openBrowser = "false";
      cronPluginUpdate = "";
    };
    volumes = [
      "/srv/apps/tdarr/server:/app/server"
      "/srv/apps/tdarr/configs:/app/configs"
      "/srv/apps/tdarr/logs:/app/logs"
      "/srv/apps/tdarr/cache:/temp"
      "/srv/apps/tdarr/pilot:/media"
      "/srv/apps/tdarr/policy:/policy:ro"
      "/nix/store:/nix/store:ro"
      "/mnt/share/Library/Movies:/source/Movies:ro"
      "/mnt/share/Library/TV:/source/TV:ro"
      "${./tdarr-plugins}:/app/server/Tdarr/Plugins/FlowPlugins/LocalFlowPlugins:ro"
      "${flowGet}:/bootstrap/flow-get.json:ro"
      "${flowInsert}:/bootstrap/flow-insert.json:ro"
      "${flowUpdate}:/bootstrap/flow-update.json:ro"
      "${libraryGet}:/bootstrap/library-get.json:ro"
      "${libraryInsert}:/bootstrap/library-insert.json:ro"
      "${libraryUpdate}:/bootstrap/library-update.json:ro"
    ];
    extraOptions = [
      "--network=ghostship_net"
      "--cpus=8"
      "--memory=12g"
      "--health-cmd=curl -fsS --max-time 5 http://127.0.0.1:8265/ >/dev/null || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=3m"
      "--health-on-failure=kill"
    ];
  };
  systemd.tmpfiles.rules = map (dir: "d /srv/apps/tdarr${dir} 0750 apps apps -") [
    ""
    "/server"
    "/configs"
    "/logs"
    "/cache"
    "/cache/pilot"
    "/pilot"
    "/policy"
  ];
  systemd.services.tdarr-language-policy = {
    description = "Generate original-language policy for Tdarr";
    before = [ "podman-tdarr.service" ];
    serviceConfig = {
      Type = "oneshot";
      User = "apps";
      Group = "apps";
      UMask = "0077";
      ExecStart = "${pkgs.python3}/bin/python3 ${./tdarr-language-policy.py}";
    };
  };
  systemd.timers.tdarr-language-policy = {
    description = "Refresh Tdarr original-language policy";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "10m";
      OnUnitActiveSec = "1h";
      RandomizedDelaySec = "5m";
      Persistent = true;
    };
  };
  systemd.services.podman-tdarr = {
    after = [
      "init-ghostship-net.service"
      "tdarr-language-policy.service"
    ];
    requires = [
      "init-ghostship-net.service"
      "tdarr-language-policy.service"
    ];
    postStart = "${lib.getExe bootstrap}";
    unitConfig.RequiresMountsFor = [ "/mnt/share/Library" ];
    serviceConfig = {
      Nice = 15;
      IOWeight = 10;
    };
  };
}
