# Sky's return to the Framework

## Goal

Sky works on her repaired Framework with everything she created on quokka,
quokka holds nothing of hers that exists nowhere else, and her backups and
Syncthing run from the Framework again under its original identity.

This plan begins once the Framework boots again. It ends with a verified
Framework backup, which is the starting condition for quokka's own return in
[Lending quokka to Sky, and bringing it back](quokka-loan.md).

## Data the move carries

While Sky works on quokka, her home folder there is the authoritative copy.
It started as the Framework's backup from 2026-10-22 and has grown since. Two
mechanisms carry it back:

| Data | Carried by | Notes |
|---|---|---|
| `~/Work` (folder `ujcpv-tvfvs`) and `~/Documents/Publii/sites/leftover-words` | Syncthing through Kangaroo | The Framework keeps its own device identity (ending `D4JJBAZ`), which stays configured on Kangaroo for the whole loan |
| Everything else in her home folder | A direct copy from quokka over the LAN, with a fresh restic snapshot of quokka as the safety net | Firefox, Zotero, Calibre, Publii's app data, Documents, Pictures, Downloads and the rest |

## How the Framework comes back

The first decision depends on what survived. Whoever repairs the Framework
reports which of these it is.

| Framework state | Starting point |
|---|---|
| Original SSD readable, Fedora boots | Her old home folder as of 2026-10-23, with her original Syncthing identity and chezmoi state. Go straight to the one-writer switch |
| New or wiped SSD | Install Fedora Workstation with disk encryption, create `sky`, and follow the two-stage bootstrap in her chezmoi README. That needs her at the keyboard for the install and for Bitwarden. Syncthing then gets a new identity, onboarded receive-only through Kangaroo as her `docs/syncthing-onboarding.md` describes |

## The one-writer switch

Only one of her machines may be a send-capable Syncthing peer and an active
backup source at a time. This sequence moves that role from quokka to the
Framework.

1. **Freeze quokka.** Sky closes her applications on quokka. Run one last
   `restic-sky-backups.service` on quokka and confirm its snapshot (host
   `quokka-<machine-id>`) appears in the repository. Wait for both Syncthing
   folders to be Up to Date with Kangaroo, then disable quokka's Syncthing and
   her backup timers there.
2. **Bring the Framework's Syncthing up behind Kangaroo.** Keep the Framework
   off the network, or keep its Syncthing service stopped, until step 1 is
   done. Then start it with both folders set to Receive Only, let them reach
   Up to Date, review any receive-only local changes one by one, and only then
   switch them back to send-and-receive. This picks up everything quokka
   synced through Kangaroo.
3. **Copy the rest of her home folder from quokka.** With applications closed
   on both machines, copy `/home/sky/` from quokka to the Framework with
   `rsync -aHAX` and no `--delete`. Exclude:
   - `.local/state/syncthing` and the two Syncthing folders, which step 2
     already carried
   - `.config/chezmoi/chezmoistate.boltdb`
   - `.config/restic/sky-backups.env`
   - `.local/state/restic-sky-backups`

   Because the copy has no `--delete`, files Sky deleted on quokka come back on
   the Framework. That is acceptable; the alternative risks removing Framework
   files from the 22 to 23 October window that quokka never had.
4. **Check application data.** Run `PRAGMA integrity_check` on Firefox, Zotero,
   Calibre and Publii databases on the Framework, and open each application
   once.
5. **Re-enable her setup on the Framework.** Run `chezmoi-apply` (Sky
   authenticates Bitwarden), then `validate-system`. Her backup timers come
   back on through chezmoi.
6. **Take a Framework backup.** Run `restic-sky-backups.service` and confirm a
   new snapshot from host `framework-2f2dafc2` (or the new host name after a
   reinstall) in the repository.
7. **Update her chezmoi status page.** `docs/current-status.md` says the
   Framework is authoritative again and quokka is retired from her setup.

Quokka's snapshots stay in the repository under their own host name. Her
backup script passes `--host` to `restic forget`, so the Framework's retention
runs never remove them. Run `restic forget --host quokka-<machine-id> --prune` from
`sky-backups-maintenance` on bilby only once she is satisfied nothing is
missing.

## Verification

| Property | Check |
|---|---|
| Nothing from the loan is lost | Every top-level directory in quokka's last snapshot exists on the Framework; `rsync -aHAXnci` from quokka to the Framework, with the same exclusions, lists only files changed on the Framework since |
| Only one writer | Quokka's Syncthing and backup timers are disabled before the Framework's folders become send-and-receive |
| Syncthing is clean | Both folders Up to Date on the Framework and Kangaroo, with no receive-only changes left unreviewed |
| Backups run from the Framework | A new Framework snapshot is in the repository and `sky-backups-monitor` reports it fresh |
| Applications work | Integrity checks return `ok`; Sky confirms Firefox, Zotero, Calibre and Publii open with her latest work |

When this passes, quokka's return in
[Lending quokka to Sky, and bringing it back](quokka-loan.md#returning-quokka-to-the-fleet)
can start.
