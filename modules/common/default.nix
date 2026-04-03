{ pkgs, ... }:

{
  imports = [
    ./host-roles.nix
    ./automation.nix
    ./user-nixos.nix
    ./users.nix
    ./secrets.nix
  ];

  nixpkgs.overlays = [
    (import ./ghostship-pkg.nix)
  ];

  # Core Nix Settings
  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    auto-optimise-store = true;
    warn-dirty = false;
    # Optimize for large downloads
    download-buffer-size = 134217728; # 128MB
    max-jobs = "auto";
  };

  nix.gc = {
    automatic = true;
    dates = "daily";
    options = "--delete-older-than 7d";
  };

  nixpkgs.config.allowAliases = false;

  environment.variables = {
    NIXPKGS_ALLOW_ALIASES = "0";
  };

  systemd.tmpfiles.rules = [
    "L+ /usr/bin/bwrap - - - - ${pkgs.bubblewrap}/bin/bwrap"
  ];

  # Common System Packages
  environment.systemPackages = with pkgs; [
    # Tech Stack Tools
    ghostship-config
    nh          # Nix Helper
    nvd         # Nix Visual Diff
    comma       # Run any binary from nixpkgs
    libnotify   # Desktop notifications

    # Essential CLI tools
    coreutils
    git
    neovim
    curl
    wget
    ripgrep
    jq
    yq-go
    htop
    lsof        # List open files
    strace      # System call tracer
    psmisc      # killall, fuser, pstree
    file        # File type detection
    tree        # Directory tree viewer
    bubblewrap
    binutils    # Provides strings
    python3
    uv
    tmux
    zip
    unzip
    nodejs

    # System Administration
    iotop       # Disk I/O monitor
    sysstat     # iostat, mpstat, pidstat, sar
    usbutils    # lsusb
    pciutils    # lspci
    pv          # Pipe viewer / progress

    # Network Tools
    socat       # Multipurpose relay
    nmap        # Provides ncat
    traceroute  # Network path tracer

    # Standard Utilities
    _7zz
    ncdu        # Disk usage analyzer
    ldns        # Provides drill
    xdotool

    # Provide dig as a wrapper around drill system-wide
    (pkgs.writeShellScriptBin "dig" ''exec ${pkgs.ldns}/bin/drill "$@"'')

    # Provide vi and vim as wrappers around neovim system-wide
    (pkgs.writeShellScriptBin "vi" ''exec ${pkgs.neovim}/bin/nvim "$@"'')
    (pkgs.writeShellScriptBin "vim" ''exec ${pkgs.neovim}/bin/nvim "$@"'')
  ];

  # Enable nix-ld for dynamically linked binaries (e.g., VS Code Server)
  programs.nix-ld.enable = true;
  programs.nix-ld.libraries = with pkgs; [
    stdenv.cc.cc
    zlib
    fuse3
    icu
    libsecret
    nss
    openssl
    curl
    expat
  ];

  # Fast, persistent development environment loading
  programs.direnv = {
    enable = true;
    nix-direnv.enable = true;
    settings.global.warn_timeout = "30s";
  };

  programs.bash = {
    completion.enable = true;
    interactiveShellInit = ''
      bind 'set show-all-if-ambiguous on'
      bind 'set completion-ignore-case on'

      HISTCONTROL=ignoredups:erasedups
      HISTSIZE=10000
      HISTFILESIZE=10000

      shopt -s histappend
      shopt -s checkwinsize

      case ";$PROMPT_COMMAND;" in
        *";history -a;"*) ;;
        "") PROMPT_COMMAND='history -a' ;;
        *) PROMPT_COMMAND="history -a; $PROMPT_COMMAND" ;;
      esac
    '';
  };

  # Set your time zone.
  time.timeZone = "UTC"; # User should override this in host config if needed

  # Select internationalisation properties.
  i18n.defaultLocale = "en_US.UTF-8";
}
