# Remote clipboard rollout: retired

Retired on 2026-11-11. The proposed manual enrolment and shell-startup reminder
have been superseded by the Mac's managed cc-clip deployment script. It sets
up every non-parked devbox when the fleet declaration or cc-clip version
changes, restores the remote user services and removes duplicate SSH blocks.
The old `chezmoi-update` command and `__ccclip_nudge` function are removed.

The current operating contract is in the
[dotfiles remote clipboard instructions](https://git.pod.haus/LogicWolfe/dotfiles/src/branch/main/README.md#remote-clipboard).
Root-owned clipboard permissions remain in Podhaus's `devbox` Ansible role;
user services and SSH configuration belong to chezmoi.

This retirement records the implemented configuration, not a fresh image-paste
test. For functional verification, paste an image into the actual remote
Claude or Codex session; checking a listening port alone is insufficient.
