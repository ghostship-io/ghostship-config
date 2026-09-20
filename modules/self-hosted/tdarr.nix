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
  mkLibrary =
    {
      id,
      name,
      folder,
      cache,
    }:
    {
      _id = id;
      inherit name folder cache;
      priority = 0;
      foldersToIgnore = "";
      foldersToIgnoreCaseInsensitive = false;
      folderWatchScanInterval = 3600;
      scannerThreadCount = 2;
      output = "";
      folderToFolderConversion = false;
      folderToFolderConversionDeleteSource = false;
      folderToFolderRecordHistory = true;
      copyIfConditionsMet = false;
      container = ".mkv";
      containerFilter = "mkv,mp4,mov,m4v,mpg,mpeg,avi,webm,wmv,m2ts,ts";
      createdAt = 1789430400000;
      folderWatching = true;
      useFsEvents = false;
      scheduledScanFindNew = true;
      processLibrary = true;
      processTranscodes = true;
      processHealthChecks = false;
      scanOnStart = true;
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
  libraries = [
    (mkLibrary {
      id = "plex-hevc-pilot";
      name = "Plex HEVC Pilot";
      folder = "/media";
      cache = "/temp/pilot";
    })
    (mkLibrary {
      id = "plex-hevc-movies";
      name = "Plex HEVC Movies";
      folder = "/source/Movies";
      cache = "/temp/movies";
    })
    (mkLibrary {
      id = "plex-hevc-tv";
      name = "Plex HEVC TV";
      folder = "/source/TV";
      cache = "/temp/tv";
    })
  ];
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
  libraryFiles = lib.concatMap (library: [
    {
      name = "${library._id}-get.json";
      path = getRequest "LibrarySettingsJSONDB" library._id;
    }
    {
      name = "${library._id}-insert.json";
      path = request "LibrarySettingsJSONDB" "insert" library._id library;
    }
    {
      name = "${library._id}-update.json";
      path = request "LibrarySettingsJSONDB" "update" library._id library;
    }
  ]) libraries;
  bootstrap = pkgs.writeShellApplication {
    name = "tdarr-bootstrap";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.jq
      pkgs.python3
    ];
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
      ${lib.concatMapStrings (library: ''
        upsert /bootstrap/${library._id}-get.json /bootstrap/${library._id}-insert.json /bootstrap/${library._id}-update.json
      '') libraries}

      node_config=/srv/apps/tdarr/configs/Tdarr_Node_Config.json
      if test -f "$node_config"; then
        python3 -c '
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text())
data["startPaused"] = False
path.write_text(json.dumps(data, indent=2) + "\n")
' "$node_config"
      fi

      node_id="$(${podman} exec tdarr curl -fsS http://127.0.0.1:8265/api/v2/get-nodes | jq -r "keys[0] // empty")"
      if test -n "$node_id"; then
        ${podman} exec tdarr curl -fsS -H "Content-Type: application/json" \
          --data "{\"data\":{\"nodeID\":\"$node_id\",\"nodeUpdates\":{\"nodePaused\":false,\"workerLimits\":{\"healthcheckcpu\":0,\"healthcheckgpu\":0,\"transcodecpu\":1,\"transcodegpu\":0}}}}" \
          http://127.0.0.1:8265/api/v2/update-node >/dev/null
      fi
    '';
  };
in
{
  ghostship.apps.tdarr = {
    healthPath = "/";
    name = "Tdarr";
    group = "Media";
    description = "HEVC encoder";
    icon = "sh-tdarr";
    order = 35;
    hostname = "tdarr.ghostship.io";
    origin = "http://tdarr:8265";
    widget = {
      type = "tdarr";
    };
    muximux = {
      icon = "muximux-video_library";
      color = "#6efefc";
      dropdown = true;
    };
  };

  # Movies and TV are writable so a validated encode can atomically replace
  # the original. Root startup is required by the upstream image's ownership
  # initialization; Tdarr runs with the standard apps PUID/PGID afterward.
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
      startPaused = "false";
      transcodecpuWorkers = "1";
      transcodegpuWorkers = "0";
      healthcheckcpuWorkers = "0";
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
      "/mnt/share/Library/Movies:/source/Movies"
      "/mnt/share/Library/TV:/source/TV"
      "${./tdarr-plugins}:/app/server/Tdarr/Plugins/FlowPlugins/LocalFlowPlugins:ro"
      "${flowGet}:/bootstrap/flow-get.json:ro"
      "${flowInsert}:/bootstrap/flow-insert.json:ro"
      "${flowUpdate}:/bootstrap/flow-update.json:ro"
    ]
    ++ map (file: "${file.path}:/bootstrap/${file.name}:ro") libraryFiles;
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
    "/cache/movies"
    "/cache/tv"
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
