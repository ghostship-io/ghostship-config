# The kernel module denials, as the host actually hands them to the kernel.
#
# Two kernel modules reach the host through one generated
# `modprobe.d/nixos.conf`: `boot.blacklistedKernelModules` stops the automatic
# hardware probing from loading a module, and the `install` rules in
# `boot.extraModprobeConfig` stop an explicit `modprobe`. Both named modules
# carry a CVE that is in the CISA KEV feed and that the running kernel does
# not fix:
#
#   algif_aead  CVE-2026-31431  the AF_ALG AEAD interface
#   ebt_snat    CVE-2026-53266  the netfilter bridge SNAT target
#
# The rules are containment, not a fix: a privileged direct `insmod` and an
# already loaded module stay outside them, and only a patched kernel removes
# the exposure.
let
  flake = builtins.getFlake (toString ../.);
  base = flake.nixosConfigurations.chill-penguin;
  inherit (base.pkgs) lib;
  config = base.config;
  deniedModules = [
    "algif_aead"
    "ebt_snat"
  ];
  # The generated modprobe configuration, as the host writes it.
  modprobeText = config.environment.etc."modprobe.d/nixos.conf".text;
  installLines = builtins.filter
    (line: lib.hasPrefix "install " line)
    (map lib.trim (lib.splitString "\n" modprobeText));
  # The deny rules the host has to carry: each denied module is handed to a
  # false command instead of being loaded.
  expectedInstallLines = map
    (name: "install ${name} ${base.pkgs.coreutils}/bin/false")
    deniedModules;
  # The install lines the host rendered before this change. Main renders none
  # for this host: no shared module sets `boot.extraModprobeConfig` and the
  # blacklist is empty, so the deny rules are the only additions. The
  # assertion below keeps a later change from dropping one of them.
  mainInstallLines = [ ];
  # The install lines the host renders that no rule accounts for.
  unknownInstallLines = builtins.filter
    (line: !(lib.elem line expectedInstallLines || lib.elem line mainInstallLines))
    installLines;
  # Every denied module must reach a false command, not to a loader.
  denyRules = map
    (name: {
      inherit name;
      prefix = "install ${name} ";
      matches = builtins.filter
        (line: lib.hasPrefix "install ${name} " line)
        installLines;
      # The command the rule hands the module to, empty when no rule exists.
      command =
        let
          matched = builtins.filter
            (line: lib.hasPrefix "install ${name} " line)
            installLines;
        in
        if matched == [ ] then "" else lib.removePrefix "install ${name} " (builtins.head matched);
    })
    deniedModules;
in
assert lib.assertMsg
  (lib.all (name: lib.elem name config.boot.blacklistedKernelModules) deniedModules)
  "boot.blacklistedKernelModules must deny ${lib.concatStringsSep ", " deniedModules}, not ${lib.concatStringsSep ", " config.boot.blacklistedKernelModules}.";
assert lib.assertMsg
  (lib.all (rule: builtins.length rule.matches == 1) denyRules)
  "the generated modprobe configuration must carry exactly one install rule for each denied module, not ${lib.concatStringsSep ", " (map (rule: "${rule.name}: ${toString (builtins.length rule.matches)}") denyRules)}.";
assert lib.assertMsg
  (lib.all (rule: lib.hasSuffix "/bin/false" rule.command) denyRules)
  "every denied module must be installed to a false command, not ${lib.concatStringsSep ", " (map (rule: rule.command) denyRules)}.";
assert lib.assertMsg
  (lib.all (line: lib.elem line installLines) mainInstallLines)
  "the generated modprobe configuration must keep every install line that main rendered, not ${lib.concatStringsSep ", " installLines}.";
assert lib.assertMsg
  (lib.all (line: lib.elem line expectedInstallLines) installLines)
  "the generated modprobe configuration must carry the install rules for ${lib.concatStringsSep ", " deniedModules}, not ${lib.concatStringsSep ", " installLines}.";
assert lib.assertMsg
  (unknownInstallLines == [ ])
  "the generated modprobe configuration must not add an install rule that no rule accounts for, not ${lib.concatStringsSep ", " unknownInstallLines}.";
true
