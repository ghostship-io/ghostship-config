# Runtime permissions for the Plex server domain only.
  "@{ghostship_plex_pms}/Plex Media Scanner" rix,
  "@{ghostship_plex_pms}/Plex Transcoder" rix,
  # Named transition resolves to the sibling interpreter domain, not server//python.
  "@{ghostship_plex_pms}/Plex Script Host" px -> ghostship-plex//python,
  "@{ghostship_plex_pms}/Plex Tuner Service" rix,
  "@{ghostship_plex_pms}/Plex DLNA Server" rix,
  "@{ghostship_plex_pms}/Plex Media Fingerprinter" rix,
  "@{ghostship_plex_pms}/Plex Commercial Skipper" rix,
  "@{ghostship_plex_pms}/Plex Relay" rix,
  @{ghostship_plex_pms}/CrashUploader rix,
  @{ghostship_plex_pms}/Resources/** r,
  # The scanner lists the bundled library directory.
  @{ghostship_plex_pms}/lib/ r,
  @{ghostship_plex_pms}/Resources/Python/lib/python2.7/site-packages/lxml/{etree,objectify}.so mr,
  @{ghostship_plex_pms}/Resources/Python/lib/python2.7/site-packages/simplejson/_speedups.so mr,

  # Bundled libraries: exact basenames/ABIs; no recursive .so wildcard.
  @{ghostship_plex_pms}/lib/ld-musl-aarch64.so.1 mr,
  @{ghostship_plex_pms}/lib/lib{avcodec.so.60,avfilter.so.9,avformat.so.60,avutil.so.58} mr,
  @{ghostship_plex_pms}/lib/libboost_{atomic,chrono,date_time,filesystem,iostreams,json,locale,program_options,random,regex,system,thread,timer}.so mr,
  @{ghostship_plex_pms}/lib/lib{c++.so.2,c.so,charset.so.1,crypto.so.3,curl.so.4,editline.so.1,fmt.so.8,freeimage.so,gcompat.so.0,hdhomerun.so,iconv.so.2} mr,
  @{ghostship_plex_pms}/lib/libicu{data,i18n,io,uc}plex.so.69 mr,
  @{ghostship_plex_pms}/lib/lib{miniupnpc.so.17,nghttp2.so,onnxruntime.so.1.16.3,opencv_core.so.405,opencv_dnn.so.405,opencv_imgcodecs.so.405,opencv_imgproc.so.405,pion.so,python27.so,soci_core.so,soci_sqlite3.so,sqlite3.so,ssl.so.3,swresample.so.4,swscale.so.7,tag.so.1,usb-1.0.so.0} mr,

  # System loader and libraries for shell/startup utilities. Resolved SONAME
  # symlinks need their on-disk filenames too. Version changes require review.
  /{,usr/}lib/aarch64-linux-gnu/ld-linux-aarch64.so.1 mr,
  /{,usr/}lib/aarch64-linux-gnu/lib{c.so.6,dl.so.2,m.so.6,pthread.so.0,rt.so.1,gcc_s.so.1} mr,
  /{,usr/}lib/aarch64-linux-gnu/lib{tinfo.so.6,tinfo.so.6.6,pcre2-8.so.0,pcre2-8.so.0.14.0,z.so.1,z.so.1.3.1,selinux.so.1,acl.so.1,acl.so.1.1.2302,attr.so.1,attr.so.1.1.2502} mr,
  /{,usr/}lib/aarch64-linux-gnu/lib{stdc++.so.6,stdc++.so.6.0.35,jq.so.1,jq.so.1.0.4,onig.so.5,onig.so.5.5.0} mr,

  # Plex downloads codecs into writable state. Executable mappings are allowlisted
  # only for this observed build and these module names. Path allowlisting does NOT
  # validate binary contents: replacing one of these writable files still loads
  # arbitrary code under this profile, as do interpreted Python/plugin files.
  "@{ghostship_plex_state}/Codecs/a336ba9-16a9aaf440ee9a92b75f070b-linux-aarch64/lib{h264,hevc,mpeg4,theora,msmpeg4v3,vc1,mpeg2video,vp9,aac,ac3,dca,mp3,mp2,wmapro}_decoder.so" mr,
  "@{ghostship_plex_state}/Codecs/a336ba9-16a9aaf440ee9a92b75f070b-linux-aarch64/lib{libx264,aac}_encoder.so" mr,
  "@{ghostship_plex_state}/Codecs/EasyAudioEncoder-6a4213e165f8ac3d108a346e-linux-aarch64/EasyAudioEncoder/EasyAudioEncoder" rix,
  # Plex2Shell (CVE-2026-96652/4/5/6) ended by writing a .so into the codec set
  # directory for the transcoder to load. The server may not write or link into
  # the allowlisted sets, so it cannot replace a mapped codec. Plex cannot fetch
  # codecs into them either; a codec change needs a reviewed policy update.
  deny "@{ghostship_plex_state}/Codecs/a336ba9-16a9aaf440ee9a92b75f070b-linux-aarch64/**" wl,
  deny "@{ghostship_plex_state}/Codecs/EasyAudioEncoder-6a4213e165f8ac3d108a346e-linux-aarch64/**" wl,

  # Required mutable mounts; no general execution or executable mmap permission.
  /config/ rw,
  /config/** rwk,
  /library/ rw,
  /library/** rwk,
  /tmp/ rw,
  /tmp/** rwk,
  /run/plex-temp/ rw,
  /run/plex-temp/** rwk,
  /run/lock/ rw,
  /run/lock/** rwk,
  /dev/shm/ rw,
  # PMS hard-links its own shared-memory segments.
  /dev/shm/** rwkl,

  # Configuration reads, DNS/TLS, locale and timezone. Secret content is not
  # embedded here; environment projection is consumed by the existing runtime.
  / r,
  /{etc,usr,usr/lib,usr/share,run,dev,proc,sys}/ r,
  /etc/{passwd,group,nsswitch.conf,hosts,hostname,resolv.conf,host.conf,gai.conf,ld.so.cache,localtime,timezone,machine-id,os-release,lsb-release} r,
  /etc/{ssl/certs,ca-certificates,fonts}/** r,
  /etc/{environment,services,protocols} r,
  /etc/cont-init.d/** r,
  /etc/cont-finish.d/** r,
  /etc/services.d/** r,
  /etc/lsi-release r,
  /usr/lib/{locale,gconv}/** r,
  /usr/share/{zoneinfo,fonts,fontconfig}/** r,
  /var/cache/fontconfig/** r,
  /var/lib/dbus/machine-id r,

  /dev/{null,zero,full,random,urandom,tty} rw,
  /dev/{stdin,stdout,stderr} rw,
  /dev/fd/[0-9]* rw,
  /dev/dri/ r,
  /dev/dri/{card[0-9]*,renderD[0-9]*} rw,
  /proc/{cpuinfo,meminfo,stat,uptime,loadavg,filesystems,version,devices} r,
  /proc/sys/kernel/{hostname,osrelease,ostype,pid_max} r,
  # Harmless daily probe: prove the container-to-journal audit path is alive.
  audit /proc/sys/kernel/random/boot_id r,
  /proc/sys/vm/overcommit_memory r,
  /proc/{self,thread-self,[0-9]*}/{stat,status,statm,maps,smaps,limits,comm,cgroup,mounts,mountinfo,cmdline} r,
  # Network interface and route discovery for LAN/remote-access detection.
  /proc/{self,thread-self,[0-9]*}/net/{if_inet6,route} r,
  /proc/{self,thread-self,[0-9]*}/fd/ r,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  /proc/{self,thread-self,[0-9]*}/task/ r,
  /proc/{self,thread-self,[0-9]*}/task/[0-9]*/{stat,status,comm} r,
  /sys/devices/system/cpu/{online,possible,present} r,
  /sys/devices/system/cpu/cpu[0-9]*/{topology,cpufreq}/** r,
  /sys/devices/system/cpu/cpufreq/policy[0-9]*/cpuinfo_{min,max}_freq r,
  /sys/devices/system/cpu/kernel_max r,
  # Hardware identification in PMS logs and diagnostics; read-only DMI names.
  /sys/devices/virtual/dmi/id/{board_name,board_vendor} r,
  /sys/class/drm/ r,
  /sys/class/drm/** r,

  # AppArmor does not limit IP destinations/ports with these socket rules.
  # TCP serves/relays Plex; UDP covers DNS, discovery and tuner traffic.
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,
  network unix stream,
  network unix dgram,
  signal (receive) peer=ghostship-plex,
  signal (send, receive) peer=ghostship-plex//python,
  signal (send, receive) peer=ghostship-plex//server,
  signal (receive) peer=unconfined,
