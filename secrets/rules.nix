let
  recipients = import ./recipients.nix;
  catalog = import ./catalog.nix { inherit recipients; };
  toRagenixPath =
    relativeFile:
    let
      prefix = "secrets/";
      prefixLength = builtins.stringLength prefix;
    in
    if builtins.substring 0 prefixLength relativeFile == prefix then
      builtins.substring prefixLength ((builtins.stringLength relativeFile) - prefixLength) relativeFile
    else
      throw "Expected secrets-relative file path, got ${relativeFile}";
in
builtins.listToAttrs (
  map
    (name: {
      name = toRagenixPath catalog.units.${name}.relativeFile;
      value.publicKeys = catalog.units.${name}.recipients;
    })
    (builtins.attrNames catalog.units)
)
