# Agent code and generated tools are published into a private store at runtime.
{ pkgs, name, uid, gid ? uid }:
pkgs.dockerTools.buildLayeredImage {
  inherit name;
  tag = null;
  contents = [ pkgs.bash pkgs.coreutils pkgs.cacert ];
  fakeRootCommands = ''
    mkdir -p ./etc ./tmp ./run ./state ./spool ./nix
    echo 'ghostship:x:${uid}:${gid}:Ghostship:/state:/nonexistent' > ./etc/passwd
    echo 'ghostship:x:${gid}:' > ./etc/group
    chmod 1777 ./tmp
  '';
  config = {
    User = "${uid}:${gid}";
    Entrypoint = [ "/run/ghostship-runtime/current/bin/start" ];
    Env = [ "HOME=/state" ];
  };
}
