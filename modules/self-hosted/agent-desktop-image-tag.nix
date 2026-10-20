# Content-addressed tag of the agent desktop image, shared by the NixOS
# module and the desktop update service, so the canary-tested candidate is
# exactly the image a switch deploys. Only the build context counts.
{ path }:
"localhost/ghostship-agent-desktop:"
+ builtins.substring 11 12 (
  builtins.path {
    inherit path;
    name = "ghostship-agent-desktop-context";
  }
)
