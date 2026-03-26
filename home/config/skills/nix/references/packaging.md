# Packaging Patterns

## Generic `stdenv.mkDerivation`
```nix
{ stdenv, fetchFromGitHub, pkgs }:
stdenv.mkDerivation rec {
  pname = "hello";
  version = "1.0";
  src = fetchFromGitHub {
    owner = "example";
    repo = "hello";
    rev = "v${version}";
    sha256 = "0000000000000000000000000000000000000000000000000000";
  };
  nativeBuildInputs = [ pkgs.cmake ];
  buildInputs = [ pkgs.zlib ];
}
```
