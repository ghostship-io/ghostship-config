let
  recipients = import ./recipients.nix;
  catalog = import ./catalog.nix { inherit recipients; };
in
builtins.listToAttrs (
  map
    (name: {
      name = catalog.units.${name}.relativeFile;
      value.publicKeys = catalog.units.${name}.recipients;
    })
    (builtins.attrNames catalog.units)
)
