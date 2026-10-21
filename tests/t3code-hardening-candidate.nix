# Build with nix build --impure --file tests/t3code-hardening-candidate.nix.
# The ordinary configuration deliberately has no candidate-image attribute:
# this explicit extension prevents testing a legacy rootful Docker image.
let
  flake = builtins.getFlake (toString ../.);
  candidate = flake.nixosConfigurations.chill-penguin.extendModules {
    modules = [{ ghostship.t3code.hardening.enable = true; }];
  };
in
candidate.config.system.build.t3codeCandidateImage
