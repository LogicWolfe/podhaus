# Lending quokka to Sky, and bringing it back

## Goal

Quokka works as Sky's everyday laptop while her Framework is being recovered,
and every change that makes that possible can be undone, so quokka can return
to the fleet as the same headless development host it was before.

Moving Sky back onto her Framework is a separate plan,
[Sky's return to the Framework](sky-framework-return.md). Quokka's return
waits for that plan's last step, a verified Framework backup.

## Status

The loan is in place as of 2026-10-29: quokka is parked, every change in the
two tables below is applied, and every check in
[Verification of the loan](#verification-of-the-loan) passed, including a
reboot straight to the login screen. Two items are open. Bitwarden on quokka is
not yet signed in, because it needs the new-device code emailed to Sky; her
next `chezmoi-apply` asks for it. Lid-close suspend was not watched directly:
quokka went silent as soon as lid handling came back with its lid closed.
[Returning quokka to the fleet](#returning-quokka-to-the-fleet) is still to do.

## Why lend quokka instead of reinstalling it

Quokka already runs Fedora 44 on x86-64, the same as the Framework, so Sky's
chezmoi source (`git.pod.haus/sky/chezmoi`) applies to it unchanged, including
the x86-64-only Signal Flatpak. Adding her as a second user on the existing
install avoids an interactive Fedora install and keeps Nathan's account, the
TPM machine key and the Pomerium SSH trust in place, which are what make both
the setup and the return remote and reversible.

Rejected: a clean reinstall as Sky's machine. Her provisioning docs assume
one, but it needs someone at the keyboard, destroys quokka's fleet identity,
and makes the return a full reprovision instead of a revert.

Her provisioning docs expect `sky` to be UID 1000. Nathan holds that UID on
quokka, so `sky` gets the next free one. Nothing in her chezmoi source or her
backup reads the number: the restore runs as `sky`, so restic writes every file
as her, and her units are per-user systemd units.

## Data Sky starts from

| Source | Covers | State on 2026-10-29 |
|---|---|---|
| Restic repository `s3:https://pouch.pod.haus/sky-backups/personal-laptop` | Her whole home folder | Newest snapshot `e236b98b`, 2026-10-22 16:06 Perth, host `framework-2f2dafc2`; 238.9 GiB, 204,831 files. `restic check` reported no errors |
| Syncthing on Kangaroo | `~/Work` (folder `ujcpv-tvfvs`) and `~/Documents/Publii/sites/leftover-words` | Shared with the Framework (device ending `D4JJBAZ`), last seen 2026-10-23 08:14 Perth |

Anything she changed outside those two folders after 2026-10-22 16:06 is lost
unless the Framework's SSD turns out to be readable. Nathan accepted that.

## Parking quokka in podhaus

A podhaus commit and a docs-server commit park quokka, and reverting them
unparks it. They follow the offline-host pattern in the
[Pinelake runbook](../runbooks/pinelake.md), going one step further so no
fleet deploy can fail while quokka is away.
Terraform is untouched: DNS, the Pomerium SSH and docs routes, the Numbat
tunnel restriction, the LAN address and the DHCP reservation all stay as they
are, so neither direction needs a `terraform apply`.

| File | Change while lent | Why |
|---|---|---|
| `komodo/sync/servers.toml` | `enabled = false` on the quokka server, with the comment `quokka is lent to Sky` | Core stops polling it and closes the unreachable alert; its stacks report `unknown`, which the `Komodo stacks` check ignores |
| `gatus/conf/config.yaml` | `enabled: false  # quokka is lent to Sky` on `Quokka Periphery (via Komodo)` and `Docs (quokka, via Komodo)` | Both would be red for the whole loan |
| `komodo/sync/procedures.toml` | Drop `quokka-docs` from the docs push-deploy pattern | Every docs-server change deploys that pattern by exact name and would fail on a disabled server |
| `logging/quokka/`, `lumen/quokka/` and `autoheal/quokka/` `stack.toml` | Renamed to `stack.toml.lent`, so the podhaus sync no longer reads them; `tools/lint-stack-content-hash.py` skips the now-orphaned Autoheal overlay | See below |
| `stack.toml` in the docs-server repo | The `quokka-docs` `[[stack]]` block commented out with the same marker | See below |
| `ansible/inventory/hosts.yml` | Comment quokka out of `provisioned`; it stays in its role groups | A fleet run of `site.yml` would otherwise reapply the headless policy below over Sky's desktop. Not the `excluded` group: its group vars set `ansible_connection: local`, which would make a later `playbooks/quokka.yml` run configure the control node instead |
| `docs/hosts.html` | One sentence: quokka is lent to Sky; this plan is the way back | Docs state what is true |

`grep -rn 'quokka is lent to Sky'` finds every line to revert, and
`find . -name stack.toml.lent` every held-out stack.

**Why the stacks leave Komodo.** The podhaus push deploy ends with
`BatchDeployStackIfChanged` over every stack (`*`; Komodo patterns cannot
exclude). It deploys a stack whose compose text changed, and a quokka stack
includes shared files edited for the whole fleet (`lumen/compose.shared.yaml`,
the logging overlay's shared compose). Deploying to a disabled server fails the
procedure. The content-hash stage before it is safe: a hash change alone
never deploys, and the stage skips any stack whose containers it cannot
inspect. So the four quokka stacks built from shared compose files
(`quokka-autoheal`, `quokka-logging`, `quokka-lumen` and `quokka-docs`) leave
the syncs, which never delete, and are then deleted from Komodo through its
API once the server is disabled, so the deletion cannot reach quokka's
containers. Shared files can then change freely while quokka is away.
`quokka-caddy`, `quokka-ofelia` and `quokka-tunnel` stay: their compose files
are quokka's own, so only an edit to quokka's own stack files could deploy
them. Don't make one while quokka is parked. The `podhaus-quokka` and `docs-server-quokka` repo
resources stay; nothing pulls them while their server is disabled.

## Changes on quokka itself

Each change is reversed by the matching row of
[Returning quokka to the fleet](#returning-quokka-to-the-fleet). Nothing is
deleted: Docker images and volumes, Nathan's home and the repositories stay on
disk.

| Fleet behaviour now | Change while lent | Undone by |
|---|---|---|
| Docker runs Periphery, docs, Lumen, Alloy, Ofelia, Autoheal, Caddy and the tunnel | Every container stopped with `docker stop` (live restore keeps containers running when only the daemon stops), then `docker.service`, `docker.socket` and `containerd.service` disabled and stopped | Ansible `docker` role, then Komodo redeploys |
| Boots to `multi-user.target`; GNOME starts only with a display attached and stops an hour after the lid closes (`gnome_on_demand` role) | Disable and stop the lid watcher, the desktop policy service and the stop timer; rename the DRM rule to `70-podhaus-desktop-policy.rules.lent`; `set-default graphical.target`; enable `gdm` | Rename the rule back, then the Ansible `gnome_on_demand` role |
| All sleep targets masked; lid and idle ignored (`base` role, `podhaus_is_laptop`) | Unmask the five sleep targets; rename `/etc/systemd/logind.conf.d/10-podhaus-laptop.conf` to `10-podhaus-laptop.conf.lent` | Rename it back, then the Ansible `base` role |
| Docs-source reconcile timer and boot unit (`docs_sources` role) | Disable them | Ansible `docs_sources` role |
| Nathan's user manager lingers | `loginctl disable-linger nathan` | `loginctl enable-linger nathan` |
| Nathan on the login screen | `SystemAccount=true` in `/var/lib/AccountsService/users/nathan` | Delete that line |
| GDM logs Nathan in automatically (`AutomaticLoginEnable=True` in `/etc/gdm/custom.conf`, set by hand, not by Ansible) | `AutomaticLoginEnable=False`; the `AutomaticLogin=nathan` line stays | Set it back to `True` |
| The saved `PodHaus` Wi-Fi connection does not autoconnect | `connection.autoconnect yes` | `nmcli connection modify PodHaus connection.autoconnect no` |

Left as is: the TPM-bound disk unlock (no passphrase at boot), the memory
pressure guard, `/tmp` placement, the timezone, the development packages, SSH
with its Pomerium CA trust and liveness settings, and the restart-on-failure
drop-in for user managers.

Sky's chezmoi source makes three system-level changes of its own when it
applies: it installs her packages and Flatpaks system-wide, writes
`/etc/ssh/sshd_config.d/00-sky-access.conf` (password and key login on,
keyboard-interactive and root login off), and enables `sshd.service`, which
was disabled on quokka before. `firewalld` was already enabled with SSH allowed,
so her setup changed nothing there. The return removes the drop-in and disables
`sshd.service` again.

## Sky's account

1. Create `sky` (UID 1001) in `wheel`, with her Framework login password from
   the 1Password item `Sky Laptop` (vault Dev), so the GNOME login keyring
   restored from the backup unlocks at her first login. Add a temporary
   passwordless sudoers drop-in so her chezmoi scripts, which call `sudo`, can
   run unattended, and enable linger during setup so her user units can be
   started remotely.
2. Restore `e236b98b` as `sky` into `~/Restore`, running as a transient
   systemd unit so an SSH drop does not stop it, with two exclusions:
   `~/.local/state/syncthing` (the Framework's device identity, which must
   never run on a second machine) and `~/.config/chezmoi/chezmoistate.boltdb`
   (it records her `run_onchange` scripts as already run, which would skip the
   SSH, desktop and backup-timer setup on quokka).
3. Move the restored tree into `/home/sky`, then run `PRAGMA integrity_check`
   on her Firefox, Zotero, Calibre and Publii databases.
4. Apply her chezmoi source in its non-secret mode
   (`--override-data '{"sshAccessKeyItemUUID":"","resticS3CredentialItemUUID":""}'`)
   to install her software and converge everything but the two Bitwarden
   items, then the full `chezmoi-apply`, unlocking her Bitwarden with the
   master password in the `bitwarden` field of `Sky Laptop`. Bitwarden asks for
   new-device verification on quokka, a code emailed to her login address, so
   the full apply waits for that code. The restore runs before either, reading the Terraform-owned
   1Password item `Sky Backups` (vault Homelab), which holds the same
   credential as her Bitwarden item; the full apply then rewrites
   `~/.config/restic/sky-backups.env` from Bitwarden.
5. Syncthing: start it once to create quokka's own identity. Define
   `leftover-words` and `ujcpv-tvfvs` at their usual paths as **Receive Only**,
   peered only with Kangaroo, never `default`. On Kangaroo, through its LAN
   REST interface, add the new device and share those two folders. Leave the
   Framework's entry on Kangaroo in place, because it comes back. Once both
   folders are Up to Date, review any receive-only local changes one by one
   (files in the backup that Kangaroo no longer has), never with Revert or
   Override. Then switch both folders to send-and-receive and enable the
   service.
6. Remove the sudoers drop-in and Sky's linger, and update her
   `docs/current-status.md` to say quokka is her laptop for now. Without
   linger her user manager runs only while she is logged in, as on the
   Framework. Her backup service takes a sleep inhibitor, which the system
   grants only to an active desktop session, so a timer run with no one logged
   in would fail.

Sky does three things herself: changes the password, joins Wi-Fi, and links
Signal again (its private state is never restored, so desktop history does not
carry over).

## Verification of the loan

| Property | Check |
|---|---|
| Restore is complete | Restic exits 0; restored file count and size match the snapshot (204,831 files, 238.9 GiB) |
| Application data is intact | `PRAGMA integrity_check` returns `ok` for each database |
| Her setup converged | Her `validate-system` passes |
| Backups work from quokka | A manual `restic-sky-backups.service` run succeeds, a snapshot with host `quokka-<machine-id>` appears when listed from `sky-backups-maintenance` on bilby, and the hourly `sky-backups-monitor` reports it as fresh |
| Syncthing has its own identity | Quokka's device ID differs from every ID on Kangaroo; both folders reach Up to Date |
| Quokka is a laptop again | `systemctl get-default` is `graphical.target`; `gdm` is active; `systemctl is-enabled suspend.target` is not `masked`; the logind override is gone. Lid-close suspend is confirmed by closing the lid |
| The fleet is quiet | After the parking push, Komodo shows quokka `Disabled`, and the `Komodo stacks` and `Komodo procedures` checks stay green |

## Returning quokka to the fleet

Start only after [Sky's return to the Framework](sky-framework-return.md) has
a verified Framework backup.

1. **Remove Sky's account.** Disable her backup timers and Syncthing, then
   `userdel -r sky`. On Kangaroo, remove quokka's Syncthing device. Remove
   `/etc/ssh/sshd_config.d/00-sky-access.conf` (`sshd -t`, reload) and
   `systemctl disable sshd.service`. Her system-wide packages and Flatpaks
   may stay; they do not affect the fleet roles.
2. **Undo the host changes.** Rename the two `.lent` files back, remove
   `SystemAccount=true` for Nathan, set `AutomaticLoginEnable=True` in
   `/etc/gdm/custom.conf`, turn `PodHaus` autoconnect off again, and
   `loginctl enable-linger nathan`.
3. **Reapply Ansible first.** `ansible-playbook playbooks/quokka.yml --check
   --diff`, read every delta, then run it for real. It masks the sleep
   targets, restores the lid policy and GNOME on demand, and re-enables Docker,
   Periphery and the docs-source units. If the `docker` role does not start the
   daemon on its own, start `docker.service` by hand. Periphery must answer
   before the next step, because that step deploys to it.
4. **Unpark.** Revert the podhaus parking commit (`68a419c`) and push, then
   revert the docs-server commit (`2c19e1e`) and push. The syncs recreate the four held-out stacks; as
   stacks new to Komodo, the next podhaus push deploy and the docs push deploy
   fully deploy them.
5. **Start the stacks that stayed in Komodo.** The containers were stopped by
   hand, so Docker does not restart them, and an unchanged stack is never
   redeployed. Run `BatchDeployStack` with pattern `quokka-*` from Komodo,
   which also covers anything step 4 missed. If Periphery itself is not
   running after the Ansible run, `docker start komodo-periphery` first.

Verify:

- Komodo shows quokka `Ok`
- `Quokka Periphery (via Komodo)` and `Docs (quokka, via Komodo)` are green
- `quokka.docs.pod.haus` serves
- `systemctl get-default` is `multi-user.target`
- `getent passwd sky` is empty
- Kangaroo lists no quokka device
