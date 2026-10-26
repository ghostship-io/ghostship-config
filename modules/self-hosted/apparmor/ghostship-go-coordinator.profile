# Go coordinator service. Keep this profile in complain mode while the live
# host workload is observed; the allowlist includes only its server, DNS,
# GitHub HTTPS, state, certificates and container heartbeat paths.
profile ghostship-go-coordinator flags=(complain,attach_disconnected,mediate_deleted) {
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-go-coordinator,

  /nix/store/*-ghostship-coordinator-*/bin/ghostship-coordinator rix,
  /opt/ghostship-go-coordinator-heartbeat/read-file rix,
  /nix/store/*-nss-cacert-*/etc/ssl/certs/ca-bundle.crt r,
  /etc/{passwd,group,hosts,resolv.conf,hostname,nsswitch.conf,localtime} r,
  /dev/null rw,
  /dev/urandom r,
  /proc/{self,thread-self}/fd/ r,
  audit /proc/sys/kernel/random/boot_id r,
  /state/ r,
  /state/** rwk,
  /tmp/ r,
  owner /tmp/** rwk,
  /var/tmp/ r,
}
