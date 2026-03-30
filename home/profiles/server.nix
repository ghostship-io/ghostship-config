{ lib, ... }:

{
  programs.bash = {
    enable = true;
    enableCompletion = true;
    shellAliases = {
      gs = "git status";
      reload = "exec bash";
    };
  };
}
