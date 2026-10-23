# Regression proofs for the pinned security fixes.
#
# The proofs read the pinned upstream sources and the built artefacts, and one
# of them exercises the fixed Podman behaviour. None of them reproduces an
# exploit, and none of them touches the host: the Podman proof runs against a
# throwaway storage root inside the build sandbox.
{
  runCommand,
  nix,
  podman,
  python3,
}:
let
  # A minimal OCI image layout that carries the annotation the advisory names.
  # Podman must refuse to run it; it must never reach the container runtime.
  checkpointImageBuilder = ''
    import hashlib
    import json
    import os

    annotation = "io.podman.annotations.checkpoint.runtime.name"

    def blob(data):
        return {
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }

    out = "oci-layout"
    blobs = os.path.join(out, "blobs", "sha256")
    os.makedirs(blobs, exist_ok=True)

    layer = b""
    config = json.dumps(
        {
            "architecture": "arm64",
            "os": "linux",
            "config": {"Entrypoint": ["/bin/true"]},
            "rootfs": {"type": "layers", "diff_ids": [blob(layer)["digest"]]},
        },
        sort_keys=True,
    ).encode()
    manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                **blob(config),
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar",
                    **blob(layer),
                }
            ],
            "annotations": {annotation: "crun"},
        },
        sort_keys=True,
    ).encode()

    for data in (config, manifest, layer):
        with open(os.path.join(blobs, blob(data)["digest"].split(":")[1]), "wb") as handle:
            handle.write(data)

    with open(os.path.join(out, "index.json"), "wb") as handle:
        handle.write(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "manifests": [
                        {
                            "mediaType": "application/vnd.oci.image.manifest.v1+json",
                            **blob(manifest),
                            "annotations": {annotation: "crun"},
                        }
                    ],
                },
                sort_keys=True,
            ).encode()
        )
    with open(os.path.join(out, "oci-layout"), "wb") as handle:
        handle.write(json.dumps({"imageLayoutVersion": "1.0.0"}).encode())
  '';
in
{
  # The pinned sources are the upstream fixed releases, not a rebuilt tree
  # that carries the same version string.
  nixSourceVersion =
    runCommand "nix-security-fix-source-version"
      {
        src = nix.src;
        inherit (nix) version;
      }
      ''
        sourceVersion=$(cat "$src/.version")
        if [ "$sourceVersion" != "$version" ]; then
          echo "pinned Nix source is $sourceVersion but the package reports $version"
          exit 1
        fi
        touch $out
      '';

  # CVE-2026-110449: list allocation detects the unsigned size overflow that
  # used to become a heap out-of-bounds write.
  nixAllocationOverflowCheck =
    runCommand "nix-security-fix-allocation-overflow"
      {
        src = nix.src;
      }
      ''
        grep -q '__builtin_mul_overflow' \
          "$src/src/libexpr/include/nix/expr/eval-inline.hh" \
          || {
            echo "the pinned Nix source does not detect the allocation overflow"
            exit 1
          }
        touch $out
      '';

  # CVE-2026-110450: the daemon refuses a repair from an untrusted client on
  # the store-writing paths. The 2.34.8 release only refused a repair on the
  # verify path, so the marker below is the one that the fix introduces.
  nixRepairRestriction =
    runCommand "nix-security-fix-repair-restriction"
      {
        src = nix.src;
      }
      ''
        grep -q 'you are not privileged to repair store paths' "$src/src/libstore/daemon.cc" \
          || {
            echo "the pinned Nix source does not refuse an unprivileged repair on the store paths"
            exit 1
          }
        touch $out
      '';

  # Patch-identity evidence, not executed behaviour: this checks that the
  # built daemon reports 2.34.9 and that the store library it links carries
  # the repair-refusal marker. It does not drive an unprivileged client into
  # AddToStore with repair = true, so it must not be read as a behavioural
  # proof. The daemon and the library come from the component outputs that the
  # aggregate "nix" output links together, so this builds without the
  # aggregate's documentation outputs.
  nixDaemonRepairPatchIdentity =
    runCommand "nix-security-fix-daemon-repair-patch-identity"
      {
        daemon = "${nix.passthru.nix-cli}/bin/nix-daemon";
        store = nix.passthru.libs.nix-store;
      }
      ''
        version=$("$daemon" --version)
        case "$version" in
          *"2.34.9"*) ;;
          *)
            echo "the built nix-daemon reports '$version' instead of 2.34.9"
            exit 1
            ;;
        esac
        if ! grep -rqa 'you are not privileged to repair store paths' "$store/lib"; then
          echo "the built Nix store library does not carry the repair-refusal marker"
          exit 1
        fi
        touch $out
      '';

  # CVE-2026-94603: "podman run" no longer restores a checkpoint image and
  # silently replaces the requested sandbox with the one stored in the image.
  podmanCheckpointRunRemoved =
    runCommand "podman-security-fix-checkpoint-run-removed"
      {
        src = podman.src;
      }
      ''
        if grep -q 'CheckpointAnnotationRuntimeName' \
          "$src/pkg/domain/infra/abi/containers.go"; then
          echo "the pinned Podman source still restores checkpoint images on run"
          exit 1
        fi
        grep -q 'must be started using `podman container restore` instead' \
          "$src/pkg/specgen/generate/container_create.go" \
          || {
            echo "the pinned Podman source does not reject a checkpoint image on run"
            exit 1
          }
        touch $out
      '';

  # The behaviour, not the marker: the built Podman must refuse to run an
  # image that carries the checkpoint annotation, and it must refuse before it
  # creates a container. The image is a throwaway local OCI layout and the
  # storage root lives in the build directory.
  podmanRejectsCheckpointImage =
    runCommand "podman-security-fix-rejects-checkpoint-image"
      {
        nativeBuildInputs = [
          podman
          python3
        ];
      }
      ''
        set -eu

        # The proof must never reach an engine outside this build directory:
        # no remote connection, no inherited containers configuration and no
        # docker endpoint.
        unset CONTAINER_HOST CONTAINER_CONNECTION CONTAINERS_CONF DOCKER_HOST

        export HOME="$PWD/home"
        export XDG_RUNTIME_DIR="$PWD/run"
        export TMPDIR="$PWD/tmp"
        mkdir -p "$HOME/.config/containers" "$XDG_RUNTIME_DIR" "$TMPDIR"
        cat > "$HOME/.config/containers/policy.json" <<'POLICY'
        { "default": [ { "type": "insecureAcceptAnything" } ] }
        POLICY

        python3 - <<'PYTHON'
        ${checkpointImageBuilder}
        PYTHON

        podman_args=(
          --root "$PWD/root"
          --runroot "$PWD/runroot"
          --storage-driver vfs
        )

        image_id=$(podman "''${podman_args[@]}" pull "oci:$PWD/oci-layout" | tail -n 1)

        annotations=$(podman "''${podman_args[@]}" image inspect "$image_id" --format '{{json .Annotations}}')
        case "$annotations" in
          *io.podman.annotations.checkpoint.runtime.name*) ;;
          *)
            echo "the test image does not carry the checkpoint annotation: $annotations"
            exit 1
            ;;
        esac

        set +e
        output=$(podman "''${podman_args[@]}" run --pull=never --network=none "$image_id" /bin/true 2>&1)
        status=$?
        set -e

        echo "$output"
        if [ "$status" -eq 0 ]; then
          echo "podman run accepted a checkpoint image"
          exit 1
        fi
        case "$output" in
          *"is a checkpoint and must be started using"*) ;;
          *)
            echo "podman run did not refuse the checkpoint image"
            exit 1
            ;;
        esac

        containers=$(podman "''${podman_args[@]}" ps -a --format '{{.ID}}')
        if [ -n "$containers" ]; then
          echo "podman created a container for a checkpoint image: $containers"
          exit 1
        fi

        touch $out
      '';
}
