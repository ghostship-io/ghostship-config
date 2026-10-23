# This builds only the staged engine artifacts, never the production T3 image.
let
  flake = builtins.getFlake (toString ../.);
  candidate = flake.nixosConfigurations.chill-penguin.extendModules {
    modules = [ { ghostship.t3codePodman.candidate = true; } ];
  };
in
candidate.config.system.build.t3codePodmanCandidate
