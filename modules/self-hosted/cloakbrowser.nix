{ ... }:

{
  virtualisation.oci-containers.containers."cloakbrowser-vpn" = {
    image = "cloakhq/cloakbrowser:latest";
    ports = [ "9222:9222" ];
    # Run in CDP server mode with all available cloaking features enabled.
    # --fingerprint: Use a deterministic seed for persistent identity.
    # --geoip=True: Automatically set timezone and locale based on proxy IP.
    # --humanize=True: Enable human-like mouse, keyboard, and scroll patterns.
    # --proxy-server=http://gluetun:8888: Route traffic through Gluetun proxy.
    cmd = [ 
      "cloakserve", 
      "--fingerprint=vpn-profile",
      "--geoip=True",
      "--humanize=True",
      "--proxy-server=http://gluetun:8888"
    ];
    extraOptions = [
      "--network=ghostship_net"
    ];
    volumes = [
      "/srv/apps/cloakbrowser-vpn:/home/cloak/.config/cloakbrowser"
    ];
  };

  virtualisation.oci-containers.containers."cloakbrowser-direct" = {
    image = "cloakhq/cloakbrowser:latest";
    ports = [ "9223:9222" ]; # Map host 9223 to container 9222
    # Profile with direct connection (no proxy).
    cmd = [ 
      "cloakserve", 
      "--fingerprint=direct-profile",
      "--humanize=True"
    ];
    extraOptions = [
      "--network=ghostship_net"
    ];
    volumes = [
      "/srv/apps/cloakbrowser-direct:/home/cloak/.config/cloakbrowser"
    ];
  };

  # Open ports for agent-browser to connect
  networking.firewall.allowedTCPPorts = [ 9222 9223 ];

  systemd.tmpfiles.rules = [
    "d /srv/apps/cloakbrowser-vpn 0755 apps apps -"
    "d /srv/apps/cloakbrowser-direct 0755 apps apps -"
  ];
}
