{ config, lib, pkgs, ... }:

let
  recipients = import ../../secrets/recipients.nix;
  catalog = import ../../secrets/catalog.nix { inherit recipients; };
  unitCatalog = catalog.units;
  projectionCatalog = catalog.projections;
  projectionDir = "/run/ghostship-secrets";

  mkAgeSecret = meta:
    {
      file = meta.path;
    }
    // lib.optionalAttrs (meta ? owner) { owner = meta.owner; }
    // lib.optionalAttrs (meta ? group) { group = meta.group; }
    // lib.optionalAttrs (meta ? mode) { mode = meta.mode; };

  projectionRenderer = pkgs.writeTextFile {
    name = "ghostship-secret-project";
    destination = "/bin/ghostship-secret-project";
    executable = true;
    text = ''
      #!${pkgs.python3}/bin/python3
      import grp
      import json
      import os
      import pwd
      import shlex
      import sys
      import tempfile
      from pathlib import Path

      SPEC = json.loads(${builtins.toJSON (builtins.toJSON {
        units = lib.mapAttrs (name: _: { path = (builtins.getAttr name config.age.secrets).path; }) unitCatalog;
        projections = lib.mapAttrs (name: meta: meta // { path = "${projectionDir}/" + meta.fileName; }) projectionCatalog;
      })})

      def parse_env_file(path_str):
          path = Path(path_str)
          values = {}
          if not path.is_file():
              return values
          for raw_line in path.read_text().splitlines():
              line = raw_line.strip()
              if not line or line.startswith('#'):
                  continue
              if line.startswith('export '):
                  line = line[7:].lstrip()
              if '=' not in line:
                  continue
              key, value = line.split('=', 1)
              key = key.strip()
              value = value.strip()
              if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                  value = value[1:-1]
              values[key] = value
          return values

      def write_projection(name):
          projection = SPEC['projections'][name]
          rendered = {}
          cache = {}
          for target_key, source in projection['fields'].items():
              unit_name = source['unit']
              source_key = source['key']
              if unit_name not in cache:
                  cache[unit_name] = parse_env_file(SPEC['units'][unit_name]['path'])
              value = cache[unit_name].get(source_key)
              if value is not None and value != "":
                  rendered[target_key] = value

          output_path = Path(projection['path'])
          output_path.parent.mkdir(parents=True, exist_ok=True)
          fd, tmp_name = tempfile.mkstemp(dir=str(output_path.parent), prefix=f"{name}.")
          tmp_path = Path(tmp_name)
          with os.fdopen(fd, 'w') as handle:
              for key, value in rendered.items():
                  handle.write(f"{key}={shlex.quote(value)}\n")
          os.chmod(tmp_path, int(projection['mode'], 8))
          os.chown(tmp_path, pwd.getpwnam(projection['owner']).pw_uid, grp.getgrnam(projection['group']).gr_gid)
          tmp_path.replace(output_path)

      def main():
          if len(sys.argv) != 2:
              print('Usage: ghostship-secret-project <projection-name>', file=sys.stderr)
              return 1
          name = sys.argv[1]
          if name not in SPEC['projections']:
              print(f'Unknown projection: {name}', file=sys.stderr)
              return 1
          write_projection(name)
          return 0

      raise SystemExit(main())
    '';
  };
in
{
  options.ghostship.selfHostedSecrets = lib.mkOption {
    type = lib.types.attrs;
    default = { };
    description = "Read-only self-hosted secret unit and projection metadata.";
  };

  config = {
    age.identityPaths = [ "/etc/ssh/ssh_host_ed25519_key" ];

    age.secrets = lib.mapAttrs (_: meta: mkAgeSecret meta) unitCatalog;

    ghostship.selfHostedSecrets = {
      units = lib.mapAttrs (name: meta: meta // { path = (builtins.getAttr name config.age.secrets).path; }) unitCatalog;
      projections = lib.mapAttrs (name: meta: meta // { path = "${projectionDir}/" + meta.fileName; }) projectionCatalog;
      render = projectionRenderer;
    };

    systemd.tmpfiles.rules = [
      "d ${projectionDir} 0755 root root -"
    ];
  };
}
