{ lib, buildGoModule, fetchFromGitHub }:

buildGoModule rec {
  pname = "agent-deck";
  version = "1.3.4";

  src = fetchFromGitHub {
    owner = "asheshgoplani";
    repo = "agent-deck";
    tag = "v${version}";
    hash = "sha256-x4PRqFZJ102+QQzOlIxZbQo/fATK12/Et27A1WflkZs=";
  };

  vendorHash = "sha256-qKK9Wu5+0bi+x6/OwRueIvPi6f4hFUqG+RkhWnLOr5Q=";

  subPackages = [ "cmd/agent-deck" ];

  doCheck = false;

  ldflags = [
    "-s"
    "-w"
    "-X main.Version=v${version}"
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
