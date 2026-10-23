# Every service capable of propagating a stop to T3 must survive a host switch.
{ services, seeds }:
let
  serviceName = name: builtins.match "(.*)\\.service" name;
  nodes = builtins.genericClosure {
    startSet = map (name: { key = name; }) seeds;
    operator = node:
      let
        unit = services.${node.key} or {};
        dependencies = (unit.requires or []) ++ (unit.bindsTo or []) ++ (unit.partOf or []);
      in map (name: { key = builtins.head (serviceName name); })
        (builtins.filter (name: serviceName name != null) dependencies);
  };
in map (node: node.key) (builtins.filter (node:
  let unit = services.${node.key} or {};
  in (unit.restartIfChanged or true) || (unit.stopIfChanged or true)
) nodes)
