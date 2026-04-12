let
  operatorEditKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIN+8CwidWx8nvTrjzJnvcS0Y5xcAu/fpQnwh6YcShlg/ nixos@launch-octopus";
  chillPenguinHostKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIM/T11y26OiGS9bWD3QaBY3Cfgt+KM/V5351E6saTOUG root@chill-penguin";
in
rec {
  keys = {
    operators = {
      ragenix = operatorEditKey;
    };

    hosts = {
      chill-penguin = chillPenguinHostKey;
    };
  };

  groups = {
    editors = [ keys.operators.ragenix ];
    self-hosted-runtime = groups.editors ++ [ keys.hosts.chill-penguin ];
  };
}
