# Security monitoring (SIEM) for chill-penguin: docs/siem.md.
{
  imports = [
    ./storage.nix
    ./collection.nix
    ./autonomous-work.nix
    ./falco.nix
    ./alerting.nix
    ./ui.nix
  ];
}
