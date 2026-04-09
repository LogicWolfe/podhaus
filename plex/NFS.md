# NFS Mount Configuration

NFS mounts for the Mac mini (bilby) connecting to Kangaroo NAS (10.0.0.25) over 10GbE.

## Mounts

| Mount | NAS Export | Purpose | Backing Storage |
|---|---|---|---|
| `/Users/Shared/Jump` | `Kangaroo:/Jump` | Container state (config, databases) | SATA SSD pair, 382GB |
| `/Users/Shared/Pouch` | `Kangaroo:/Pouch` | Media (movies, TV, etc.) | HDD array, 29TB |

## macOS Configuration

Both mounts use autofs via `/etc/auto_nfs`, referenced from `/etc/auto_master`:

```
# /etc/auto_master (add this line if not present)
/-	auto_nfs	-nobrowse
```

```
# /etc/auto_nfs
/System/Volumes/Data/Users/Shared/Jump	-fstype=nfs,vers=4,nosuid,bg,resvport,soft,wsize=1048576,rsize=1048576	Kangaroo:/Jump
/System/Volumes/Data/Users/Shared/Pouch	-fstype=nfs,vers=4,nosuid,bg,resvport,soft,wsize=1048576,rsize=1048576	Kangaroo:/Pouch
```

After editing, reload the automounter:

```
sudo automount -vc
```

Access the mount point (e.g. `ls /Users/Shared/Jump/`) to trigger the automount. If a stale mount persists, force unmount first:

```
sudo umount -f /Users/Shared/Jump
```

### Mount option rationale

| Option | Why |
|---|---|
| `vers=4` | NFS v4.0 — compound operations, built-in locking (good for SQLite), single port. macOS doesn't support v4.1. |
| `nosuid` | Security — don't honour setuid bits from NAS |
| `bg` | Background retry — if NAS is unreachable at boot, retry in background instead of blocking |
| `resvport` | Use privileged source port — required by most NAS NFS exports |
| `soft` | Soft mount — return errors on timeout instead of hanging forever. Appropriate for non-critical data; avoids frozen Finder. |
| `rsize=1048576,wsize=1048576` | 1MB read/write blocks. Default is 32KB. Reduces per-operation overhead for large transfers. No measurable improvement on this QNAP but no downside either. |

## QNAP NAS Configuration (Kangaroo)

### NFS Service

Control Panel > Network & File Services > NFS Service:
- NFS v4 enabled
- Maximum NFS version: 4.x

### Shared Folder NFS Host Access

For each shared folder (Jump, Pouch), configure NFS host access:

Control Panel > Shared Folders > [folder] > Edit Shared Folder Permissions > NFS host access

| Setting | Value | Notes |
|---|---|---|
| Host/IP | `10.0.0.119` | Mac mini's IP. Restrict to this host only. |
| Access | Read/Write | |
| Squash | Map to NAS user uid 1000 | Files created over NFS will be owned by this uid. Must match `PLEX_UID` in container compose files. |
| Sync | Unchecked (async) | Server acks writes before flushing to disk. Safe with UPS. |
| Secure | Unchecked | Don't require privileged source port on server side (resvport on client is sufficient). |

Ensure both Jump and Pouch have identical NFS host access rules.

### Jumbo Frames

The full path (Mac NIC, switch, QNAP NIC) must support MTU 9000:

- **Mac**: System Settings > Network > Ethernet > Hardware > MTU: 9000
- **QNAP**: Control Panel > Network > Ethernet > MTU: 9000
- **Switch**: Must support jumbo frames on the relevant ports

Verify: `ifconfig en0 | grep mtu` should show `mtu 9000`.

## macOS File Descriptor Limit

Containers accessing NFS mounts through OrbStack's VirtioFS can exhaust the default macOS file descriptor soft limit (256). Media-scanning services like Plex easily hit 8000+ open fds during library scans.

A LaunchDaemon at `/Library/LaunchDaemons/limit.maxfiles.plist` raises the limit to 524288 at boot:

```
sudo launchctl limit maxfiles 524288 524288
```

To verify: `launchctl limit maxfiles`

## Performance Benchmarks (April 2026)

Tested with fio on the Mac mini (M1) over 10GbE with jumbo frames (MTU 9000).

| Test | Jump (SSD) | Pouch (HDD) |
|---|---|---|
| Sequential write (1M) | 116 MB/s | 114 MB/s |
| Sequential read (1M) | 332 MB/s | 371 MB/s |
| Rand 4K write + fsync | 1,068 IOPS | 424 IOPS |
| Rand 4K read | 17,100 IOPS / 0.06ms | 17,600 IOPS / 0.05ms |

Key findings:
- Sequential write tops out at ~130 MB/s regardless of client tuning — QNAP NFS server is the bottleneck, not the drives or network
- Jump SSDs show 2.5x better fsync IOPS than Pouch HDDs — confirms SSD volume for database-heavy workloads
- Random reads are excellent on both mounts (NFS client cache)
- 10GbE link is confirmed working (reads exceed 1Gbps)
- 1MB rsize/wsize showed no improvement over 32KB defaults on this QNAP, but no downside either
