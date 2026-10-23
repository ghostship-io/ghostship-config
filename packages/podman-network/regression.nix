{ pkgs }:
pkgs.runCommand "podman-lease-range-regression"
  {
    nativeBuildInputs = [
      pkgs.go
      pkgs.patch
    ];
  }
  ''
    cp -r ${pkgs.podman.src} source
    chmod -R u+w source
    cd source
    patch -p1 < ${./clamp-cursor.patch}
    cp ${./ipam_range_test.go} vendor/go.podman.io/common/libnetwork/netavark/ipam_range_test.go
    export HOME=$TMPDIR GOCACHE=$TMPDIR/go-cache CGO_ENABLED=0 GOPROXY=off GOMAXPROCS=2
    go test -p 2 -mod=vendor ./vendor/go.podman.io/common/libnetwork/netavark \
      -run TestLeaseRangeClampsSavedCursor -count=1 -timeout=20s
    touch $out
  ''
