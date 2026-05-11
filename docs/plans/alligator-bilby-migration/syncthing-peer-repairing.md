# Syncthing peer re-pairing

After Phase 16's relocation of Syncthing from bilby (host process) to
kangaroo (Komodo-managed stack), the device came up with a **fresh
identity**. Every peer device that used to sync with bilby's old
Syncthing still has the old device ID configured — those connections
are dead and need to be re-introduced to the new kangaroo-side
device ID.

## Kangaroo's new device ID

```
J7Z7LNA-U65UY7V-C7BTJXK-XBOON5E-5UAZBXM-KOXNWRP-DBOIFEL-DCXTEQD
```

## Per-peer steps

About 2 minutes per peer in the Syncthing UI. Do each one of these:

1. Open the Syncthing UI on the peer (phone, laptop, etc.).
2. Remove the old `bilby` device.
3. Add a new device with the ID above. The peer doesn't need to be on
   the same LAN — Syncthing global discovery + relay will find it.
4. From kangaroo's Syncthing UI (sync.pod.haus), accept the new peer
   when its pairing request shows up.
5. On the peer, accept each folder share kangaroo offers.

After pairing, the existing `.stignore` patterns at the root of each
shared folder are picked up automatically.

## Expected first-sync behaviour

The Pouch share is ~30 TB. A peer that previously held a copy will
mostly use the local hash database and finish quickly. A peer setting
up fresh will do a full sync — that's bandwidth-bound, not Syncthing-
bound, and obviously takes a while.

Kangaroo-side hashing performance was measured at ~42 MB/s on the
GX-420MC at startup, so the *initial folder scan* on first peer-pairing
is the slow part for kangaroo. After that, steady-state delta-sync is
fast.

## Verification

`https://sync.pod.haus` shows the connected peers and per-folder sync
state. Each folder should reach "Up to Date" after the initial sync.
