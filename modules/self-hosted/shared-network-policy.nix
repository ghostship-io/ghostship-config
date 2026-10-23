# Admission reads the native OCI network fields and canonical argv consumed by
# Podman. Refuse split/ambiguous tokens rather than partially emulate pflag.
{
  lib,
  containers,
  name,
  start,
  end,
}:
let
  ipv4 =
    value:
    let
      parts = lib.splitString "." value;
      valid =
        builtins.length parts == 4 && lib.all (part: builtins.match "[0-9]{1,3}" part != null) parts;
      numbers = map lib.toInt parts;
    in
    if !valid || !lib.all (n: n >= 0 && n <= 255) numbers then
      null
    else
      lib.foldl' (total: n: total * 256 + n) 0 numbers;
  lower = ipv4 start;
  upper = ipv4 end;
  valueOf = flag: option: lib.removePrefix "--${flag}=" option;
  flagValues =
    flags: options:
    lib.concatMap (
      option:
      lib.concatMap (flag: lib.optional (lib.hasPrefix "--${flag}=" option) (valueOf flag option)) flags
    ) options;
  network =
    value:
    let
      parts = lib.splitString ":" value;
    in
    {
      name = builtins.head parts;
      options = lib.optionals (builtins.length parts > 1) (
        lib.splitString "," (lib.concatStringsSep ":" (builtins.tail parts))
      );
    };
  parsed =
    container:
    map network (
      (container.networks or [ ]) ++ flagValues [ "network" "net" ] (container.extraOptions or [ ])
    );
  canonical =
    container:
    lib.all (
      option:
      builtins.elem option [
        "--init"
        "--privileged"
        "--read-only"
        "--tty"
        "--interactive"
        "--rm"
      ]
      || builtins.match "--[a-z][a-z0-9-]*=.*" option != null
    ) (container.extraOptions or [ ])
    && lib.all (
      net:
      builtins.match "[a-zA-Z0-9_.-]+" net.name != null
      && (
        if net.name == "container" then
          builtins.length net.options == 1
          && builtins.match "[a-zA-Z0-9_.-]+" (builtins.head net.options) != null
        else if net.name == "ns" then
          builtins.length net.options == 1 && lib.hasPrefix "/" (builtins.head net.options)
        else
          lib.all (option: builtins.match "(ip|ip6|alias|interface_name)=.+" option != null) net.options
      )
    ) (parsed container);
  addresses =
    container:
    let
      networks = parsed container;
      inline = lib.concatMap (
        net:
        lib.concatMap (
          option: lib.optional (lib.hasPrefix "ip=" option) (lib.removePrefix "ip=" option)
        ) net.options
      ) (builtins.filter (net: net.name == name) networks);
    in
    inline
    ++ lib.optionals (lib.any (net: net.name == name) networks) (
      flagValues [ "ip" ] (container.extraOptions or [ ])
    );
  outside =
    address:
    let
      number = ipv4 address;
    in
    number != null && (number < lower || number > upper);
in
[
  {
    assertion = lower != null && upper != null && lower <= upper;
    message = "Shared network allocation bounds must be valid IPv4 addresses.";
  }
  {
    assertion = lib.all canonical (builtins.attrValues containers);
    message = "Shared network admission requires canonical --flag=value argv and unambiguous native networks.";
  }
  {
    assertion = lib.all (container: lib.all outside (addresses container)) (
      builtins.attrValues containers
    );
    message = "Shared network static addresses must be valid IPv4 addresses outside the dynamic allocation range.";
  }
]
