let
  operatorEditKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIN+8CwidWx8nvTrjzJnvcS0Y5xcAu/fpQnwh6YcShlg/ nixos@launch-octopus";
  chillPenguinHostKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIM/T11y26OiGS9bWD3QaBY3Cfgt+KM/V5351E6saTOUG root@chill-penguin";
  armoredArmadilloEditKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPCsSQVs2eDV+wkfkARTRUoPz7og9Zcfo8oKj4u6oBvv nixos@armored-armadillo-ragenix";
in
rec {
  keys = {
    operators = {
      ragenix = operatorEditKey;
      armored-armadillo = armoredArmadilloEditKey;
    };

    hosts = {
      chill-penguin = chillPenguinHostKey;
    };
  };

  groups = {
    editors = [ keys.operators.ragenix keys.operators.armored-armadillo ];
    self-hosted-runtime = groups.editors ++ [ keys.hosts.chill-penguin ];
  };
}
