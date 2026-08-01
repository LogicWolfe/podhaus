# Kangaroo Pouch recovery follow-ups

The June 2026 Pouch recovery is operationally complete. The array was rebuilt
as a healthy four-disk RAID5, container state moved to CACHEDEV2, the 10 GbE
path became active at `10.0.0.25`, and all managed services returned healthy.

This page carries only the remaining validation and cleanup work. The last
recorded host-side verification was 2026-06-13, so re-check live state before
acting on any item below.

## Syncthing recovery mode

Kangaroo was rebuilt with a fresh Syncthing identity and the Pouch folder in
Receive Only mode. Pinelake held the protected subset in Send Only mode. This
prevented an empty rebuilt Pouch from propagating deletions outward.

Before switching Kangaroo back to Send & Receive:

1. Confirm Pinelake and Kangaroo are paired and fully connected.
2. Regenerate Pouch's `.stignore` from the Pinelake-held subset.
3. Confirm the expected files are present on Pouch and Syncthing reports no
   remaining pull errors.
4. Take a fresh backup or snapshot of the recovered configuration.
5. Change the folder mode and watch both sides for unexpected deletions.

Do not restore Kangaroo's old Syncthing identity or folder database against a
partial Pouch. That reintroduces the deletion-cascade risk.

## Reboot validation

The QNAP boot DOM now runs `kangaroo/host-autorun/autorun.sh`. It starts
Container Station's user Docker engine and reconciles exited or detached
containers after boot. The installer and a boot-like minimal environment were
tested, but the recorded recovery never performed a real QNAP reboot because
that would interrupt Pouch and Jump for bilby.

Schedule a controlled reboot, confirm both NFS automounts recover, then verify
Periphery, Syncthing, Backrest, Alloy, and Autoheal return without manual work.

## Disk capacity and replacement

Pouch currently uses four old disks in RAID5 with roughly 21.8 TB usable. Bay
1 is empty after the failed disk was removed.

- Add a fifth disk when capacity requires it.
- Plan rotation of the surviving drives. At the last audit they had roughly
  37,000 to 61,000 power-on hours.
- Keep the monthly scrub on the first Sunday with Service First priority.

## UPS tuning

The APC UPS is armed through NUT and `upsmon`. Review the minutes-based shutdown
thresholds during the controlled reboot window and confirm the host shuts down
with enough battery margin for the array to stop cleanly.

## Plex cleanup

Plex trash still contains media lost with the old Pouch array. Emptying it is
safe for online-agent libraries because watch state is keyed by account and
GUID outside the deleted media rows. Sports and Kids Video use local-hash GUIDs,
so their watch state won't reconnect if the files are later re-added.

This is user-driven and has no urgency. Take a current Plex database backup
before emptying trash.

## Recovery staging

`/share/CACHEDEV2_DATA/recovered/` contains Gmail exports and duplicate photo
and Sky recovery copies. Choose the final home for anything still unique, then
remove duplicate staging data.

The old USB rescue drive had unreadable sectors and should be retired once its
contents are confirmed non-unique.

## Completion

After these items are resolved, record any lasting operating rules in Storage,
Backup and recovery, Syncthing, or Hosts. Then delete this plan.
