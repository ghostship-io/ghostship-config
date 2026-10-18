# Container policy, inspected on chill-penguin (aarch64), 2026-10-18:
# LinuxServer Plex 1.43.4.10903; s6-overlay 3.2.1.0; uid/gid 3000.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# A policy change restarts that observation window; elapsed time alone is not proof.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions: their implicit permissions would obscure this allowlist.

@{ghostship_plex_pms} = /usr/lib/plexmediaserver
@{ghostship_plex_state} = "/config/Library/Application Support/Plex Media Server"
@{ghostship_plex_s6} = /package/admin/s6-overlay-3.2.1.0

profile ghostship-plex flags=(complain,attach_disconnected,mediate_deleted) {
  # Startup, server and interpreter stay in complain mode while collecting
  # missing accesses. Omitted permissions are NOT enforced in this mode.
  #include <plex-apparmor-startup.inc>
  "@{ghostship_plex_pms}/Plex Media Server" cx -> server,
  "@{ghostship_plex_pms}/Plex Script Host" px -> ghostship-plex//python,

  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    # The server and its helpers get no shell, downloader, or startup-tool execs.
    "@{ghostship_plex_pms}/Plex Media Server" rix,
    #include <plex-apparmor-runtime.inc>
  }

  profile python flags=(complain,attach_disconnected,mediate_deleted) {
    #include <plex-apparmor-python.inc>
  }
}
