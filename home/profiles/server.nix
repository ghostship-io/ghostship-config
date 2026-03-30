{ ... }:

{
  programs.bash = {
    enable = true;
    shellAliases = {
      gs = "git status";
      reload = "exec bash";
    };
  };
}
