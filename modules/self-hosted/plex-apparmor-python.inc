# Interpreter domain only: the observed Framework v2 / System.bundle workload.
# AppArmor cannot filter argv, -c, stdin code, imports or pickle opcodes. Even in
# enforce mode this would constrain effects, not establish trusted Python code.
# In complain mode omitted permissions still only produce observations.
# No x permissions at all: no self-exec, shell, generic Python, Plex helper,
# codec executable, fallback to unconfined, or transition back to startup/server.
  "@{ghostship_plex_pms}/Plex Script Host" mr,

  # Exact mapped native files from the live System.bundle process on 2026-10-18.
  # No recursive native-library glob and no mutable-codec mappings.
  @{ghostship_plex_pms}/lib/ld-musl-aarch64.so.1 mr,
  @{ghostship_plex_pms}/lib/lib{c++.so.2,crypto.so.3,gcompat.so.0,python27.so,sqlite3.so,ssl.so.3} mr,
  @{ghostship_plex_pms}/lib/libicu{data,i18n,io,uc}plex.so.69 mr,
  @{ghostship_plex_pms}/Resources/Python/lib/python2.7/site-packages/lxml/{etree,objectify}.so mr,
  @{ghostship_plex_pms}/Resources/Python/lib/python2.7/site-packages/simplejson/_speedups.so mr,

  # PYTHONHOME, zip stdlib, bundled site-packages, and version-pinned framework.
  # These image resources are read-only here; no custom plugin/scanner code.
  @{ghostship_plex_pms}/Resources/Python/ r,
  @{ghostship_plex_pms}/Resources/Python/python27.zip r,
  @{ghostship_plex_pms}/Resources/Python/lib/python2.7/site-packages/ r,
  @{ghostship_plex_pms}/Resources/Python/lib/python2.7/site-packages/** r,
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/ r,
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/Framework.bundle/Contents/Resources/Versions/2/ r,
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/Framework.bundle/Contents/Resources/Versions/2/** r,
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/Framework.bundle/Contents/Resources/Platforms/Shared/Libraries/ r,
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/Framework.bundle/Contents/Resources/Platforms/Shared/Libraries/** r,
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/System.bundle/Contents/ r,
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/System.bundle/Contents/{DefaultPrefs.json,Info.plist,VERSION} r,
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/System.bundle/Contents/{Code,Resources,Strings}/ r,
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/System.bundle/Contents/{Code,Resources,Strings}/** r,

  # Bundle discovery reads only the enumerated shipped metadata, not their code.
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/{Fanart-TV,Framework,HTbackdrops,LastFM,LocalMedia,LyricFind,Media-Flags,MoviePosterDB,Musicbrainz,PersonalMedia,PlexMovie,PlexThemeMusic,Scanners,System,TheMovieDB,TheTVDB,TheTVDBv4,WebClient}.bundle/ r,
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/{Fanart-TV,Framework,HTbackdrops,LastFM,LocalMedia,LyricFind,Media-Flags,MoviePosterDB,Musicbrainz,PersonalMedia,PlexMovie,PlexThemeMusic,Scanners,System,TheMovieDB,TheTVDB,TheTVDBv4,WebClient}.bundle/Contents/ r,
  @{ghostship_plex_pms}/Resources/Plug-ins-e5521bd8c/{Fanart-TV,Framework,HTbackdrops,LastFM,LocalMedia,LyricFind,Media-Flags,MoviePosterDB,Musicbrainz,PersonalMedia,PlexMovie,PlexThemeMusic,Scanners,System,TheMovieDB,TheTVDB,TheTVDBv4,WebClient}.bundle/Contents/{Info.plist,VERSION} r,

  # Exact system-plugin state, with Storage.save's sibling ._<basename> rename.
  # Dict is a pickle: modifying it can execute Python on the next load. These
  # permissions do not authenticate its contents, including server-written state.
  "@{ghostship_plex_state}/Plug-in Support/Data/com.plexapp.system/" rw,
  "@{ghostship_plex_state}/Plug-in Support/Data/com.plexapp.system/{,._}{StoredValues,Dict,HTTPCookies}" rwk,
  "@{ghostship_plex_state}/Plug-in Support/Data/com.plexapp.system/DataItems/" rw,
  # DataItems and the two-hex-digit HTTP cache directories were empty. Do not
  # preauthorize arbitrary payload filenames or descendants; learn actual needs.
  "@{ghostship_plex_state}/Plug-in Support/Caches/com.plexapp.system/" rw,
  "@{ghostship_plex_state}/Plug-in Support/Caches/com.plexapp.system/HTTP.system/" rw,
  "@{ghostship_plex_state}/Plug-in Support/Caches/com.plexapp.system/HTTP.system/{,._}CacheInfo" rwk,
  "@{ghostship_plex_state}/Plug-in Support/Caches/com.plexapp.system/HTTP.system/[0-9a-f][0-9a-f]/" rw,
  # System preference storage is absent today; the framework's exact destination.
  "@{ghostship_plex_state}/Plug-in Support/Preferences/" r,
  "@{ghostship_plex_state}/Plug-in Support/Preferences/{,._}com.plexapp.system.xml" rwk,
  "@{ghostship_plex_state}/Logs/PMS Plugin Logs/" r,
  "@{ghostship_plex_state}/Logs/PMS Plugin Logs/com.plexapp.system.log" rw,
  "@{ghostship_plex_state}/Logs/PMS Plugin Logs/com.plexapp.system.log.[1-5]" rw,

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
  # System.bundle HTTP requests to PMS/remote services and DNS resolution.
  # AppArmor socket families/types cannot restrict destinations or ports.
  network inet stream,
  network inet dgram,
  signal (receive) peer=ghostship-plex,
  signal (send, receive) peer=ghostship-plex//server,
  signal (send, receive) peer=ghostship-plex//python,
  signal (receive) peer=unconfined,
