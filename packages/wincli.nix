{
  buildDotnetModule,
  dotnet-sdk_10,
  fetchFromGitHub,
}:

buildDotnetModule {
  pname = "wincli";
  version = "1.3.24-unstable-2026-09-13";

  src = fetchFromGitHub {
    owner = "sbroenne";
    repo = "mcp-windows";
    rev = "67ba78d6b3a99bdabee27898dab64b38aafb55ed";
    hash = "sha256-kjMBUx8MYJ/iOFSSBRJNnCeed1bYwUBHzKXJZ5/Q27Q=";
  };

  projectFile = "src/Sbroenne.WindowsMcp.Cli/Sbroenne.WindowsMcp.Cli.csproj";
  nugetDeps = ./wincli-deps.json;
  dotnet-sdk = dotnet-sdk_10;
  runtimeId = "win-x64";
  selfContainedBuild = true;
  dotnetFlags = [
    "-p:EnableWindowsTargeting=true"
    "-p:EnforceCodeStyleInBuild=false"
  ];

  postPatch = ''
    rm global.json
  '';

  doCheck = false;
  dontStrip = true;

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/bin"
    dotnet publish src/Sbroenne.WindowsMcp.Cli/Sbroenne.WindowsMcp.Cli.csproj \
      --configuration Release \
      --runtime win-x64 \
      --self-contained \
      --no-restore \
      --no-build \
      -p:EnableWindowsTargeting=true \
      -p:EnforceCodeStyleInBuild=false \
      --output "$out/bin"
    rm -f "$out/bin/"*.xml "$out/bin/"*.pdb
    runHook postInstall
  '';
}
