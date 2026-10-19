let
  flake = builtins.getFlake (toString ../.);
  base = flake.nixosConfigurations.chill-penguin;
  inherit (base.pkgs) lib;
  failures =
    override:
    map (a: a.message) (
      builtins.filter (a: !a.assertion) (base.extendModules { modules = [ override ]; }).config.assertions
    );
  fails = message: override: builtins.elem message (failures override);
in
assert failures { } == [ ];
assert fails "Every Internet-facing Ghostship service must declare an AppArmor profile." {
  ghostship.apps.plex.apparmorProfile = lib.mkForce null;
};
assert fails "Internet access outside Cloudflare Access requires recorded explicit user approval." {
  ghostship.apps.plex.cloudflareBypassApproval = lib.mkForce null;
};
assert fails "Application AppArmor profiles must exist and be enabled." {
  ghostship.apps.plex.apparmorProfile = lib.mkForce "missing-profile";
};
assert fails "Application AppArmor profiles must exist and be enabled." {
  security.apparmor.policies.ghostship-plex.state = lib.mkForce "disable";
};
assert fails "Profiled public services require AppArmor to be enabled on the host." {
  security.apparmor.enable = lib.mkForce false;
};
assert fails "Containers must use their declared AppArmor profile." {
  virtualisation.oci-containers.containers.plex.extraOptions = [
    "--security-opt=apparmor=unconfined"
  ];
};
assert fails "Cloudflare Access path bypasses require recorded explicit user approval and an AppArmor profile." {
  ghostship.apps.hooks.cloudflareBypassApproval = lib.mkForce null;
};
assert fails "Cloudflare Access path bypasses require recorded explicit user approval and an AppArmor profile." {
  ghostship.apps.hooks.apparmorProfile = lib.mkForce null;
};
true
