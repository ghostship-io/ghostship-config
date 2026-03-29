{ pkgs, ... }:

{
  virtualisation.oci-containers.containers."muximux" = {
    image = "linuxserver/muximux:latest";
    user = "0:3000";
    extraOptions = [
      "--network=ghostship_net"
    ];
    environment = {
      PUID = "3000";
      PGID = "3000";
      TZ = "UTC";
    };
    volumes = [
      "/srv/apps/muximux:/config:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/muximux 0755 apps apps -"
    "d /srv/apps/muximux/www/muximux 0755 apps apps -"
  ];

  system.activationScripts.muximux-config = {
    text = ''
      CONFIG_FILE="/srv/apps/muximux/www/muximux/settings.ini.php"

      if [ -f "$CONFIG_FILE" ]; then
        echo "Surgically updating Muximux settings..."
        
        mux_args=(
          general.title=literal:"ghostship.io"
          general.userNameInput=literal:"admin"
          Homepage.name=literal:""
          Homepage.url=literal:"https://homepage.ghostship.io"
          Homepage.scale=literal:1
          Homepage.icon=literal:"muximux-home2"
          Homepage.color=literal:"#109f61"
          Homepage.enabled=literal:"true"
          Homepage.default=literal:"true"
          Plex.name=literal:"Plex"
          Plex.url=literal:"https://plex.ghostship.io"
          Plex.scale=literal:1
          Plex.icon=literal:"muximux-plex"
          Plex.color=literal:"#ebaf00"
          Plex.enabled=literal:"true"
          NZBGet.name=literal:"NZBGet"
          NZBGet.url=literal:"https://nzbget.ghostship.io"
          NZBGet.scale=literal:1
          NZBGet.icon=literal:"fa-download"
          NZBGet.color=literal:"#4ad946"
          NZBGet.enabled=literal:"true"
          VueTorrent.name=literal:"VueTorrent"
          VueTorrent.url=literal:"https://vuetorrent.ghostship.io"
          VueTorrent.scale=literal:1
          VueTorrent.icon=literal:"muximux-qwiklabs"
          VueTorrent.color=literal:"#63cda9"
          VueTorrent.enabled=literal:"true"
          Sonarr.name=literal:"Sonarr"
          Sonarr.url=literal:"https://sonarr.ghostship.io"
          Sonarr.scale=literal:1
          Sonarr.icon=literal:"muximux-sonarr"
          Sonarr.color=literal:"#35c5f4"
          Sonarr.enabled=literal:"true"
          Radarr.name=literal:"Radarr"
          Radarr.url=literal:"https://radarr.ghostship.io"
          Radarr.scale=literal:1
          Radarr.icon=literal:"muximux-radarr"
          Radarr.color=literal:"#ffc230"
          Radarr.enabled=literal:"true"
          Prowlarr.name=literal:"Prowlarr"
          Prowlarr.url=literal:"https://prowlarr.ghostship.io"
          Prowlarr.scale=literal:1
          Prowlarr.icon=literal:"muximux-paw"
          Prowlarr.color=literal:"#e45124"
          Prowlarr.enabled=literal:"true"
          Grimmory.name=literal:"Grimmory"
          Grimmory.url=literal:"https://grimmory.ghostship.io"
          Grimmory.scale=literal:1
          Grimmory.icon=literal:"muximux-book2"
          Grimmory.color=literal:"#49da7e"
          Grimmory.enabled=literal:"true"
          Grimmory.dd=literal:"false"
          RomM.name=literal:"RomM"
          RomM.url=literal:"https://romm.ghostship.io"
          RomM.scale=literal:1
          RomM.icon=literal:"muximux-gamepad"
          RomM.color=literal:"#553f99"
          RomM.enabled=literal:"true"
          RomM.dd=literal:"false"
          Synology.name=literal:"Synology"
          Synology.url=literal:"https://synology.ghostship.io"
          Synology.scale=literal:1
          Synology.icon=literal:"muximux-database"
          Synology.color=literal:"#3799ef"
          Synology.enabled=literal:"true"
          Synology.dd=literal:"true"
          Tautulli.name=literal:"Tautulli"
          Tautulli.url=literal:"https://tautulli.ghostship.io"
          Tautulli.scale=literal:1
          Tautulli.icon=literal:"muximux-plexivity"
          Tautulli.color=literal:"#e5a00d"
          Tautulli.enabled=literal:"true"
          Tautulli.dd=literal:"true"
          Bazarr.name=literal:"Bazarr"
          Bazarr.url=literal:"https://bazarr.ghostship.io/"
          Bazarr.scale=literal:1
          Bazarr.icon=literal:"muximux-bazarr"
          Bazarr.color=literal:"#9c36b5"
          Bazarr.enabled=literal:"true"
          Bazarr.dd=literal:"true"
          CloakBrowser.name=literal:"CloakBrowser"
          CloakBrowser.url=literal:"https://cloakbrowser.ghostship.io"
          CloakBrowser.scale=literal:1
          CloakBrowser.icon=literal:"muximux-chrome"
          CloakBrowser.color=literal:"#000000"
          CloakBrowser.enabled=literal:"true"
          CloakBrowser.dd=literal:"true"
          Hermes.name=literal:"Hermes"
          Hermes.url=literal:"https://hermes.ghostship.io"
          Hermes.scale=literal:1
          Hermes.icon=literal:"fa-terminal"
          Hermes.color=literal:"#06b6d4"
          Hermes.enabled=literal:"true"
          Hermes.dd=literal:"true"
          pyLoad.name=literal:"pyLoad"
          pyLoad.url=literal:"https://pyload.ghostship.io"
          pyLoad.scale=literal:1
          pyLoad.icon=literal:"fa-download"
          pyLoad.color=literal:"#ffcc00"
          pyLoad.enabled=literal:"true"
          pyLoad.dd=literal:"true"
          SearXNG.name=literal:"SearXNG"
          SearXNG.url=literal:"https://searxng.ghostship.io"
          SearXNG.scale=literal:1
          SearXNG.icon=literal:"muximux-search"
          SearXNG.color=literal:"#ffffff"
          SearXNG.enabled=literal:"true"
          SearXNG.dd=literal:"true"
          OmniTools.name=literal:"OmniTools"
          OmniTools.url=literal:"https://omnitools.ghostship.io"
          OmniTools.scale=literal:1
          OmniTools.icon=literal:"fa-wrench"
          OmniTools.color=literal:"#ff9800"
          OmniTools.enabled=literal:"true"
          OmniTools.dd=literal:"true"
          MeTube.name=literal:"MeTube"
          MeTube.url=literal:"https://metube.ghostship.io"
          MeTube.scale=literal:1
          MeTube.icon=literal:"muximux-cloud-download2"
          MeTube.color=literal:"#ff4c41"
          MeTube.enabled=literal:"true"
          MeTube.dd=literal:"true"
          ConvertX.name=literal:"ConvertX"
          ConvertX.url=literal:"https://convertx.ghostship.io"
          ConvertX.scale=literal:1
          ConvertX.icon=literal:"muximux-expertsexchange"
          ConvertX.color=literal:"#557f14"
          ConvertX.enabled=literal:"true"
          ConvertX.dd=literal:"true"
          BentoPDF.name=literal:"BentoPDF"
          BentoPDF.url=literal:"https://bentopdf.ghostship.io"
          BentoPDF.scale=literal:1
          BentoPDF.icon=literal:"muximux-file-pdf"
          BentoPDF.color=literal:"#7c86ff"
          BentoPDF.enabled=literal:"true"
          BentoPDF.dd=literal:"true"
          "IT Tools.name"=literal:"IT Tools"
          "IT Tools.url"=literal:"https://it-tools.ghostship.io"
          "IT Tools.scale"=literal:1
          "IT Tools.icon"=literal:"muximux-info2"
          "IT Tools.color"=literal:"#2c9a66"
          "IT Tools.enabled"=literal:"true"
          "IT Tools.dd"=literal:"true"
          SSH.name=literal:"SSH"
          SSH.url=literal:"https://ssh.ghostship.io"
          SSH.scale=literal:1
          SSH.icon=literal:"muximux-terminal3"
          SSH.color=literal:"#0045a6"
          SSH.enabled=literal:"true"
          SSH.dd=literal:"true"
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${mux_args[@]}"
        
        chown apps:apps "$CONFIG_FILE"
      fi
    '';
  };
}
