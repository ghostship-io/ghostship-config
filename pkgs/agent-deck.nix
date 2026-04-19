{ lib, buildGoModule, fetchFromGitHub }:

buildGoModule rec {
  pname = "agent-deck";
  version = "1.7.21";

  src = fetchFromGitHub {
    owner = "asheshgoplani";
    repo = "agent-deck";
    tag = "v${version}";
    hash = "sha256-V2TAhHzCwtClmbgb/w/0YL638QZDh9xXz8tmvm2btw0=";
  };

  vendorHash = "sha256-1aCd3tT5Oh+K7kLils2r3kX4YMkDCL3Eqoj5XJ9R8m0=";

  subPackages = [ "cmd/agent-deck" ];

  doCheck = false;

  ldflags = [
    "-s"
    "-w"
    "-X main.Version=${version}"
  ];

  meta = {
    description = "Terminal session manager for AI coding agents";
    homepage = "https://github.com/asheshgoplani/agent-deck";
    license = lib.licenses.mit;
    mainProgram = "agent-deck";
    platforms = lib.platforms.linux ++ lib.platforms.darwin;
    maintainers = [ ];
  };
}
