let
  operatorEditKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIN+8CwidWx8nvTrjzJnvcS0Y5xcAu/fpQnwh6YcShlg/ nixos@launch-octopus";
  chillPenguinHostKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIM/T11y26OiGS9bWD3QaBY3Cfgt+KM/V5351E6saTOUG root@chill-penguin";
  boomerKuwangerHostKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILT2HGF6WHU2N5BdeVcxmTAu98b8Rpc9ddOx3FXaB179 root@boomer-kuwanger";
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
      boomer-kuwanger = boomerKuwangerHostKey;
    };
  };

  groups = {
    editors = [
      keys.operators.ragenix
      keys.operators.armored-armadillo
    ];
    self-hosted-runtime = groups.editors ++ [ keys.hosts.chill-penguin ];
    emulation-runtime = groups.editors ++ [ keys.hosts.boomer-kuwanger ];
    shared-runtime = groups.editors ++ [
      keys.hosts.chill-penguin
      keys.hosts.boomer-kuwanger
    ];
  };
}
