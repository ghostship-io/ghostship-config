{ pkgs, lib, ... }:

let
  agentTooling = import ./agent-tooling.nix { inherit pkgs; };
  libsecretPath = lib.makeLibraryPath [ pkgs.libsecret ];

  base-gemini = pkgs.writeShellScriptBin "gemini-base" ''
    set -euo pipefail

    check_extension() {
      name="$1"
      repo="$2"
      dir="$HOME/.gemini/extensions/$name"
      remote_head="$(${pkgs.git}/bin/git ls-remote "$repo" HEAD | cut -f1)"
      local_head=""

      if [ -d "$dir" ] && [ ! -d "$dir/.git" ]; then
        return 0
      fi

      if [ -z "$remote_head" ]; then
        return 0
      fi

      if [ -d "$dir/.git" ]; then
        local_head="$(${pkgs.git}/bin/git -C "$dir" rev-parse HEAD 2>/dev/null || true)"
      fi

      if [ -z "$local_head" ]; then
        ${pkgs.nodejs}/bin/npx -y @google/gemini-cli extensions install "$repo" --auto-update --consent
      elif [ "$local_head" != "$remote_head" ]; then
        ${pkgs.nodejs}/bin/npx -y @google/gemini-cli extensions update "$name" || true
      fi
    }

    ${lib.concatMapStrings (extension: ''
    check_extension "${extension.name}" "${extension.repo}"
'') agentTooling.geminiExtensions}

    export LD_LIBRARY_PATH="${libsecretPath}${if libsecretPath != "" then ":" else ""}$LD_LIBRARY_PATH"
    ${pkgs.nodejs}/bin/npx -y @google/gemini-cli "$@"
  '';

  base-skills = pkgs.writeShellScriptBin "skills-base" ''
    npx -y skills "$@"
  '';

  gemini-cli = pkgs.symlinkJoin {
    name = "gemini";
    paths = [ base-gemini base-skills ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postBuild = ''
      wrapProgram $out/bin/gemini-base \
        --prefix PATH : ${agentTooling.runtimeBinPath} \
        --prefix LD_LIBRARY_PATH : ${libsecretPath} \
        --set NODE_NO_WARNINGS 1
      mv $out/bin/gemini-base $out/bin/gemini

      # Provide mcp-ssh as a wrapper around npx
      echo "#!${pkgs.bash}/bin/bash" > $out/bin/mcp-ssh
      echo "exec npx -y @aiondadotcom/mcp-ssh \"\$@\"" >> $out/bin/mcp-ssh
      chmod +x $out/bin/mcp-ssh

      wrapProgram $out/bin/skills-base \
        --set NODE_NO_WARNINGS 1
      mv $out/bin/skills-base $out/bin/skills
    '';
  };
in
{
  environment.systemPackages = [
    gemini-cli
  ];
}
