{
  lib,
  rustPlatform,
  fetchFromGitHub,
  installShellFiles,
  git,
}:

rustPlatform.buildRustPackage rec {
  pname = "workmux";
  version = "0.1.178";

  src = fetchFromGitHub {
    owner = "raine";
    repo = "workmux";
    tag = "v${version}";
    hash = "sha256-hhHWjcYkqHM5IdYYzSnqCCpbWM3j9igh1xLoDuCCgjI=";
  };

  cargoLock = {
    lockFile = "${src}/Cargo.lock";
    outputHashes = {
      "crossterm-0.29.0" = "sha256-rfAaqGylDaxx3bjmofifnzSh7Hmh21BzHp5fS/w2Z6I=";
    };
  };

  cargoDepsName = "${pname}-${version}";

  nativeBuildInputs = [
    git
    installShellFiles
  ];

  postInstall = ''
    export HOME=$TMPDIR
    installShellCompletion --cmd workmux \
      --bash <($out/bin/workmux completions bash) \
      --fish <($out/bin/workmux completions fish) \
      --zsh <($out/bin/workmux completions zsh)
  '';

  meta = {
    description = "Parallel development in tmux with git worktrees";
    homepage = "https://github.com/raine/workmux";
    license = lib.licenses.mit;
    mainProgram = "workmux";
    platforms = lib.platforms.linux ++ lib.platforms.darwin;
    maintainers = [ ];
  };
}
