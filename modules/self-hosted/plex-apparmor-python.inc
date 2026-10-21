# Interpreter domain only: Framework v2 running System.bundle and the shipped
# metadata agents. Enforced: omitted permissions are denied.
# AppArmor cannot filter argv, -c, stdin code, imports or pickle opcodes. This
# constrains effects; it does not establish that only trusted Python runs.
# The only exec is ctypes' `ldconfig -p` probe, into its own read-only domain:
# no shell, generic Python, Plex helper, codec executable or unconfined fallback.
  "@{ghostship_plex_pms}/Plex Script Host" mr,

  # Exact mapped native files from the live System.bundle process on 2026-10-18.
  # No recursive native-library glob and no mutable-codec mappings.
  @{ghostship_plex_pms}/lib/ld-musl-aarch64.so.1 mr,
  @{ghostship_plex_pms}/lib/lib{c++.so.2,crypto.so.3,gcompat.so.0,python27.so,sqlite3.so,ssl.so.3} mr,
  @{ghostship_plex_pms}/lib/libicu{data,i18n,io,uc}plex.so.69 mr,
  @{ghostship_plex_pms}/Resources/Python/lib/python2.7/site-packages/lxml/{etree,objectify}.so mr,
  @{ghostship_plex_pms}/Resources/Python/lib/python2.7/site-packages/simplejson/_speedups.so mr,

  # PYTHONHOME, zip stdlib, bundled site-packages and the framework. The
  # Plug-ins-<build> directory changes with every Plex image, so the build hash
  # is a glob; these image resources are read-only. No custom plugin/scanner code.
  @{ghostship_plex_pms}/Resources/Python/ r,
  @{ghostship_plex_pms}/Resources/Python/python27.zip r,
  @{ghostship_plex_pms}/Resources/Python/lib/python2.7/site-packages/ r,
  @{ghostship_plex_pms}/Resources/Python/lib/python2.7/site-packages/** r,
  @{ghostship_plex_plugins}/ r,
  @{ghostship_plex_plugins}/Framework.bundle/Contents/Resources/Versions/2/ r,
  @{ghostship_plex_plugins}/Framework.bundle/Contents/Resources/Versions/2/** r,
  @{ghostship_plex_plugins}/Framework.bundle/Contents/Resources/Platforms/Shared/Libraries/ r,
  @{ghostship_plex_plugins}/Framework.bundle/Contents/Resources/Platforms/Shared/Libraries/** r,
  # System.bundle and the shipped agents each run in a Script Host (imdb is
  # PlexMovie, none is PersonalMedia). Scanners and WebClient code stay excluded.
  @{ghostship_plex_plugins}/{Fanart-TV,HTbackdrops,LastFM,LocalMedia,LyricFind,MoviePosterDB,Musicbrainz,PersonalMedia,PlexMovie,PlexThemeMusic,System,TheMovieDB,TheTVDB,TheTVDBv4}.bundle/Contents/** r,

  # Bundle discovery reads only the enumerated shipped metadata, not their code.
  @{ghostship_plex_plugins}/{Fanart-TV,Framework,HTbackdrops,LastFM,LocalMedia,LyricFind,Media-Flags,MoviePosterDB,Musicbrainz,PersonalMedia,PlexMovie,PlexThemeMusic,Scanners,System,TheMovieDB,TheTVDB,TheTVDBv4,WebClient}.bundle/ r,
  @{ghostship_plex_plugins}/{Fanart-TV,Framework,HTbackdrops,LastFM,LocalMedia,LyricFind,Media-Flags,MoviePosterDB,Musicbrainz,PersonalMedia,PlexMovie,PlexThemeMusic,Scanners,System,TheMovieDB,TheTVDB,TheTVDBv4,WebClient}.bundle/Contents/ r,
  @{ghostship_plex_plugins}/{Fanart-TV,Framework,HTbackdrops,LastFM,LocalMedia,LyricFind,Media-Flags,MoviePosterDB,Musicbrainz,PersonalMedia,PlexMovie,PlexThemeMusic,Scanners,System,TheMovieDB,TheTVDB,TheTVDBv4,WebClient}.bundle/Contents/{Info.plist,VERSION} r,

  # Per-plugin state for the identifiers present on 2026-10-21, with
  # Storage.save's sibling ._<basename> rename. Dict is a pickle: modifying it can
  # execute Python on the next load. These permissions do not authenticate its
  # contents, including server-written state.
  "@{ghostship_plex_state}/Plug-in Support/Data/@{ghostship_plex_agents}/" rw,
  "@{ghostship_plex_state}/Plug-in Support/Data/@{ghostship_plex_agents}/{,._}{StoredValues,Dict,HTTPCookies}" rwk,
  "@{ghostship_plex_state}/Plug-in Support/Data/@{ghostship_plex_agents}/DataItems/" rw,
  # HTTP cache bodies are data files: write and read, never map or execute.
  "@{ghostship_plex_state}/Plug-in Support/Caches/@{ghostship_plex_agents}/" rw,
  "@{ghostship_plex_state}/Plug-in Support/Caches/@{ghostship_plex_agents}/HTTP.system/" rw,
  "@{ghostship_plex_state}/Plug-in Support/Caches/@{ghostship_plex_agents}/HTTP.system/{,._}CacheInfo" rwk,
  "@{ghostship_plex_state}/Plug-in Support/Caches/@{ghostship_plex_agents}/HTTP.system/[0-9a-f][0-9a-f]/" rw,
  "@{ghostship_plex_state}/Plug-in Support/Caches/@{ghostship_plex_agents}/HTTP.system/[0-9a-f][0-9a-f]/*" rwk,
  "@{ghostship_plex_state}/Plug-in Support/Preferences/" r,
  "@{ghostship_plex_state}/Plug-in Support/Preferences/{,._}@{ghostship_plex_agents}.xml" rwk,
  "@{ghostship_plex_state}/Logs/PMS Plugin Logs/" r,
  "@{ghostship_plex_state}/Logs/PMS Plugin Logs/@{ghostship_plex_agents}.log" rw,
  "@{ghostship_plex_state}/Logs/PMS Plugin Logs/@{ghostship_plex_agents}.log.[1-5]" rw,

  # Directory enumeration only for the currently empty custom-plugin directory.
  "@{ghostship_plex_state}/Plug-ins/" r,
  / r,
  /{etc,dev,proc}/ r,
  /etc/{hosts,resolv.conf,nsswitch.conf,host.conf,gai.conf,localtime,timezone} r,
  /etc/ssl/certs/ r,
  /etc/ssl/certs/** r,
  /usr/share/zoneinfo/** r,
  /dev/null rw,
  /dev/{random,urandom} r,
  /dev/{stdin,stdout,stderr} rw,
  /proc/{self,thread-self}/{stat,status,maps} r,
  /proc/{self,thread-self,[0-9]*}/mounts r,
  # ctypes.util.find_library runs `ldconfig -p`.
  /usr/sbin/ldconfig px -> ghostship-plex//ldconfig,
  # System.bundle HTTP requests to PMS/remote services and DNS resolution.
  # AppArmor socket families/types cannot restrict destinations or ports.
  network inet stream,
  network inet dgram,
  signal (receive) peer=ghostship-plex,
  signal (send, receive) peer=ghostship-plex//server,
  signal (send, receive) peer=ghostship-plex//python,
  signal (receive) peer=unconfined,
