package netavark

import (
    "net"
    "path/filepath"
    "testing"

    "go.etcd.io/bbolt"
    "go.podman.io/common/libnetwork/types"
)

func TestLeaseRangeClampsSavedCursor(t *testing.T) {
    cidr, err := types.ParseCIDR("192.0.2.0/24")
    if err != nil { t.Fatal(err) }
    subnet := &types.Subnet{
        Subnet: cidr,
        Gateway: net.ParseIP("192.0.2.1"),
        LeaseRange: &types.LeaseRange{StartIP: net.ParseIP("192.0.2.32"), EndIP: net.ParseIP("192.0.2.34")},
    }
    for _, saved := range []string{"", "192.0.2.14", "192.0.2.15", "192.0.2.30", "192.0.2.34", "192.0.2.99"} {
        t.Run(saved, func(t *testing.T) {
            db, err := bbolt.Open(filepath.Join(t.TempDir(), "fixture.db"), 0600, nil)
            if err != nil { t.Fatal(err) }
            defer db.Close()
            err = db.Update(func(tx *bbolt.Tx) error {
                bucket, err := tx.CreateBucket([]byte("fixture"))
                if err != nil { return err }
                if saved != "" {
                    if err := bucket.Put(lastIPKey, net.ParseIP(saved)); err != nil { return err }
                }
                got, err := getFreeIPFromBucket(bucket, subnet)
                if err != nil { return err }
                if !got.Equal(net.ParseIP("192.0.2.32")) { t.Fatalf("cursor %q escaped lease range: %s", saved, got) }
                // Full ranges must terminate, including a cursor above the range.
                for _, address := range []string{"192.0.2.32", "192.0.2.33", "192.0.2.34"} {
                    if err := bucket.Put(net.ParseIP(address).To4(), []byte("occupied")); err != nil { return err }
                    if err := bucket.Put(net.ParseIP(address).To16(), []byte("occupied")); err != nil { return err }
                }
                if _, err := getFreeIPFromBucket(bucket, subnet); err == nil { t.Fatal("full lease range allocated an address") }
                return nil
            })
            if err != nil { t.Fatal(err) }
        })
    }
}
