# SIEM storage: VictoriaLogs (events) and VictoriaMetrics (numbers), each in
# Podman on its own network. Host collectors (Vector) write to them through
# ports published on 127.0.0.1 only. The network blocks every connection a
# SIEM container opens, except DNS to its resolver, so a compromised store
# cannot reach the Internet, the LAN, other containers or host services.
# Images are pinned by digest: monitoring must not change under us overnight.
{ lib, pkgs, ... }:
let
  network = "ghostship_siem_net";
  bridge = "ghostsiem0";
  subnet = "10.89.21.0/24";
  gateway = "10.89.21.1";
  root = "/var/lib/ghostship-siem";
  # Owns the stores; no host account or app container uses this uid.
  uid = "3100";
  egressRules = pkgs.writeText "siem-egress.nft" ''
    destroy table inet ghostship_siem
    table inet ghostship_siem {
      chain forward {
        type filter hook forward priority -10; policy accept;
        iifname "${bridge}" ct state established,related accept
        iifname "${bridge}" drop
      }
      chain input {
        type filter hook input priority -10; policy accept;
        iifname "${bridge}" ct state established,related accept
        # Podman's DNS resolver is the sole permitted new host connection.
        iifname "${bridge}" ip daddr ${gateway} meta l4proto { udp, tcp } th dport 53 accept
        iifname "${bridge}" drop
      }
    }
  '';
  store = name: {
    user = "${uid}:${uid}";
    extraOptions = [ "--network=${network}" ];
    volumes = [ "${root}/${name}:/data:rw,noexec,nosuid,nodev" ];
  };
in
{
  ghostship.apps.victorialogs = {
    name = "VictoriaLogs";
    group = "Infrastructure";
    description = "SIEM log store";
    icon = "sh-victoriametrics";
    order = 260;
  };
  ghostship.apps.victoriametrics = {
    name = "VictoriaMetrics";
    group = "Infrastructure";
    description = "SIEM metrics store";
    icon = "sh-victoriametrics";
    order = 261;
  };

  virtualisation.oci-containers.containers.victorialogs = store "logs" // {
    # v1.53.0: v1.52.0 (nixpkgs) can panic or drop logs with duplicate stream fields.
    image = "docker.io/victoriametrics/victoria-logs@sha256:251121fa882af99b95ba0c230a4a2f412ea602d2698c64a96c58dc9842bb755d";
    ports = [ "127.0.0.1:9428:9428" ];
    cmd = [
      "-storageDataPath=/data"
      "-retentionPeriod=180d"
      # Drop the oldest days first rather than fill the shared disk.
      "-retention.maxDiskSpaceUsageBytes=300GiB"
      "-httpListenAddr=:9428"
    ];
  };
  virtualisation.oci-containers.containers.victoriametrics = store "metrics" // {
    image = "docker.io/victoriametrics/victoria-metrics@sha256:c7884f32920dd45a9d86542a717227e63af03e060e53bbf8031e6e6fd0e1e05d";
    ports = [ "127.0.0.1:8428:8428" ];
    cmd = [
      "-storageDataPath=/data"
      "-retentionPeriod=400d"
      "-httpListenAddr=:8428"
      # Its own health in the same store, for collector-silence alerts.
      "-selfScrapeInterval=30s"
    ];
  };

  systemd.tmpfiles.rules = [
    "d ${root} 0750 root root -"
    "d ${root}/logs 0700 ${uid} ${uid} -"
    "d ${root}/metrics 0700 ${uid} ${uid} -"
  ];

  systemd.services = {
    init-ghostship-siem-net = {
      description = "Create the ${network} podman network";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        ${pkgs.podman}/bin/podman network inspect ${network} >/dev/null 2>&1 || \
        ${pkgs.podman}/bin/podman network create --interface-name ${bridge} \
          --subnet ${subnet} --gateway ${gateway} ${network}
      '';
    };
    siem-egress = {
      description = "Block connections opened by SIEM containers";
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${pkgs.nftables}/bin/nft -f ${egressRules}";
        ExecStop = "${pkgs.nftables}/bin/nft destroy table inet ghostship_siem";
      };
    };
  }
  // lib.genAttrs [ "podman-victorialogs" "podman-victoriametrics" ] (_: {
    requires = [ "init-ghostship-siem-net.service" "siem-egress.service" ];
    after = [ "init-ghostship-siem-net.service" "siem-egress.service" ];
    bindsTo = [ "siem-egress.service" ];
  });
}
