# MacBook setup

How Nathan's personal laptop is set up from a fresh macOS install. Paths
below write its hostname as `<laptop>`, today `nb-macbook-pro`. Chezmoi owns the machine whole; Ansible never runs on it (see
[Host provisioning](host-provisioning.md)). Chezmoi cannot do every step:
some need a person at the keyboard, an account outside the machine, or root.
This page lists all of them, so the laptop's real dependencies are written
down even though no script performs them in this order.

The dotfiles repository's README explains what each chezmoi piece does; this
page says what has to be true around it.

## Before the first apply

The first `chezmoi apply` needs these in place.

| Requirement | Why | How |
|---|---|---|
| FileVault on | The machine key and the 1Password service-account tokens are plain files in the home directory; FileVault is what protects them at rest | System Settings → Privacy & Security → FileVault; `fdesetup status` reports `FileVault is On.` |
| Xcode Command Line Tools | `git` and `curl` for the first clone | `xcode-select --install` |
| 1Password app and CLI, signed in, SSH agent enabled | The first clone authenticates with the personal key in 1Password; it stays the identity for interactive SSH on the Mac | Install both, sign in, enable Settings → Developer → SSH agent |
| Temporary `~/.ssh/config` | Points ssh at 1Password's agent for the first clone; chezmoi replaces it | `Host *` with `IdentityAgent "~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"` |
| Ghostty | The terminal chezmoi configures and Claude Code notifies through; chezmoi does not install it | `brew install --cask ghostty`, after the first apply has installed Homebrew, or the download from ghostty.org before it |
| Full Disk Access for the terminal an agent will run in (Ghostty, or Herdr when the agent runs in a Herdr space), and Local Network for Herdr | macOS keeps `~/Library/Mail`, `Messages`, `Safari`, `Application Support/Firefox` and `Mobile Documents` unreadable to a shell without it, and blocks every LAN connection from an app without Local Network; an unattended agent cannot answer either prompt | System Settings → Privacy & Security → Full Disk Access and Local Network, before the agent starts |
| cc-clip | Chezmoi asks `cc-clip version` while rendering the script that sets up each dev box's clipboard tunnel, so an apply without it fails | `curl -fsSL https://raw.githubusercontent.com/ShunmeiCho/cc-clip/main/scripts/install.sh \| sh` |

Then bootstrap chezmoi with the command in the dotfiles README, checking
Forgejo's host-key fingerprint it gives. The first apply installs Homebrew, the
command-line toolchain, OrbStack, Adrafinil, the 1Password CLI and Codex.

## Identities

### Machine key

The laptop has no TPM or security key chezmoi can use, so its machine key is a
passphrase-less ed25519 file inside FileVault, minted by hand as the dotfiles
README's "Minting a soft key" describes. Registering it is configuration in
this repository:

- `forgejo/keys/nathan/<laptop>-machine.pub`: Terraform adds it to the
  Pocket ID `ssh_keys` claim, which Forgejo syncs, and registers it with GitHub
  for authentication (`terraform/github.tf`).
- GitHub commit signing: added by hand at github.com/settings/keys, the one
  registration Terraform cannot own.
- `podhaus_machine_key` in `ansible/inventory/host_vars/<laptop>.yml`,
  with the laptop in the `remote_dev_machines` group: the `authorized_keys`
  role grants the key on the Linux development hosts, and
  `tools/render-pomerium-keys.py` registers it with Pomerium's SSH routes.
  Apply with `--tags ssh` on each Linux host and redeploy Pomerium.

Rotating the key repeats all three.

### 1Password service accounts

The laptop reads secrets through `op-vault`, never personal 1Password. Create
its two service accounts with the grants listed in the dotfiles README
(Development identities), then enrol each one-time token on the laptop:

```sh
op-vault mint dev
op-vault mint switch
chezmoi apply
```

## Home network

The laptop's wifi MAC holds a UniFi reservation, and the split-horizon record
`<laptop>.pod.haus` points at it, so the development hosts can SSH to the
laptop on the home LAN. The address lives in `config/lan-addresses.json`; the
reservation and record are in `terraform/unifi.tf` and
`terraform/dns_unifi_split_horizon.tf`. A new laptop means a new MAC in
`unifi.tf` and a Terraform apply. Every other client reaches the laptop through
Pomerium's `ssh://<laptop>` route at `ssh.pod.haus`, which the docs tunnel
carries to its sshd while the laptop is awake and online.

## Second laptop during a migration

A replacement laptop runs alongside the old one until it is proven, and
Podhaus carries both:

- They share one machine key. The key moves to the new laptop rather than
  being minted, so it stays registered once, under the old laptop's file in
  `forgejo/keys/nathan/` and the old laptop's GitHub key: GitHub refuses the
  same key twice, and a second file would repeat it in the Pocket ID claim.
  Both laptops' host_vars declare a byte-identical `podhaus_machine_key`, so
  the `authorized_keys` role and `tools/render-pomerium-keys.py` each keep one
  copy. Renaming the file, its comment and the GitHub key waits for the old
  laptop's retirement.
- Both are in `remote_dev_machines`, and each has its own address in
  `config/lan-addresses.json`, UniFi reservation and `.pod.haus` record.
  Reserve the MAC that `ifconfig en0` reports while the laptop is on the home
  network, since macOS 27 may present a locally administered address
  regardless of the Private Wi-Fi Address toggle.
- The docs tunnel runs on one laptop at a time. Terraform issues both a client
  certificate (`terraform/tunnel.tf`), but `tunnel/numbat/restrictions.yaml`
  gives each listener exactly one rule, so `mac.docs.pod.haus` and the SSH
  listener belong to the laptop that rule names. Cutover stops the tunnel on
  the old laptop, moves the rule to the new laptop's name, renames the
  `ssh://<laptop>` route in `pomerium/config.yaml`, and makes the new laptop
  a Podhaus operator in the dotfiles. Push the rule change on its own:
  Numbat's Periphery reaches
  Core through Pomerium, so a push that also redeploys Pomerium loses the
  tunnel server's deploy to a timeout and the rule change does not land until
  the next push. The new laptop's client is refused with HTTP 400 until the
  tunnel server restarts; Numbat's `tunnel-server` log in HyperDX shows
  "Tunnel accepted due to matched restriction: <laptop>" once it has.
- Retirement removes the old laptop's fleet entry, address, reservation,
  record and tunnel client, renames the key file, renames its GitHub resource
  in place (`moved` block) along with its title, which makes Terraform
  recreate the GitHub key, and leaves one Komodo variable (`LAN_<OLD>_IPV4`)
  to delete by hand, because the sync is additive.

## After the first apply

- Run the commands the apply prints to make fish the login shell, then reopen
  the terminal.
- The first plain `ssh` (and git's first contact, which consults the
  1Password agent before falling back to the machine key) raises 1Password's
  key-use prompt; approve it with "always allow" or every connection waits
  on the dialog.
- iCloud Drive → Desktop & Documents Folders **before** copying anything into
  `~/Desktop` or `~/Documents`: a second Mac that turns the sync on with files
  already there does not merge them, it files them under `Desktop - <laptop>`
  and `Documents - <laptop>` in iCloud as duplicates.
- Spotlight search results are `EnabledPreferenceRules` in
  `com.apple.Spotlight`: an array of the categories turned **off**, as
  `System.<category>` ids. The headless equivalent of leaving only
  Applications, Folders and System Settings on is
  `defaults write com.apple.Spotlight EnabledPreferenceRules -array System.iphoneApps System.documents System.images System.movies System.music System.presentations System.spreadsheets System.developer System.calculator System.contacts System.dictionary System.safari System.tips System.pdf`;
  the ids for Mail and Messages, Events, Fonts, Bookmarks, Siri Suggestions,
  Websites and Conversion are unconfirmed and only appear after a toggle in
  the GUI (`defaults read com.apple.Spotlight EnabledPreferenceRules`).
- Login items (Stay, Lunar, Adrafinil, Magnet) are added in System Settings;
  registering them through System Events raises an Automation prompt.
- A podhaus clone needs `pipenv install` (README) and
  `ln -sf ../../tools/pre-commit .git/hooks/pre-commit` before its first
  commit, and Terraform needs `terraform init` once.
- `gh auth login` and `codex login`, both interactive.
- Open OrbStack once to finish its first-run setup.
- Open Adrafinil once and approve its privileged helper, then start `codex`
  and choose "Trust all and continue" so Codex runs Adrafinil's hooks.

### SSH into the laptop

Chezmoi writes `~/.ssh/authorized_keys`: the personal key and each development
host's machine key. sshd's own settings are root-owned, so they are set once by
hand, after the first apply, whose `docs-tunnel-update` places Pomerium's SSH
user CA public key at `~/.config/docs-tunnel/pomerium-user-ca.pub`. These are
the only root steps the laptop takes:

```sh
sudo systemsetup -setremotelogin on
sudo tee /etc/ssh/sshd_config.d/000-key-only.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers nathan
EOF
sudo cp ~/.config/docs-tunnel/pomerium-user-ca.pub /etc/ssh/pomerium-user-ca.pub
sudo tee /etc/ssh/sshd_config.d/001-pomerium-ca.conf >/dev/null <<'EOF'
TrustedUserCAKeys /etc/ssh/pomerium-user-ca.pub
EOF
sudo sshd -t
```

Both files sort before Apple's `100-macos.conf`, and sshd takes the first
value it reads for each setting. Without the first, macOS accepts the account
password over SSH. The second admits the short-lived certificate Pomerium
presents on its `ssh://<laptop>` route; a replaced Pomerium CA means repeating
the copy. sshd starts per connection on macOS, so nothing needs reloading.

## Checking the result

- `chezmoi status` lists nothing except the scripts that run on every apply.
- `ssh-machine -T git@git.pod.haus` authenticates as LogicWolfe with the
  machine key alone.
- `op-vault dev -- op vault list` lists `Dev`.
- `sudo sshd -T | grep -iE '^(authorizedkeysfile|passwordauthentication|allowusers|trustedusercakeys) '`
  shows `.ssh/authorized_keys`, `no`, `nathan` and `/etc/ssh/pomerium-user-ca.pub`.
- `ssh nathan@<laptop>@ssh.pod.haus true` from another machine succeeds
  through Pomerium.
- `docs-url ~/repos/podhaus/docs/macbook-setup.md` prints a localhost link that
  opens this page, and `https://mac.docs.pod.haus/podhaus/macbook-setup.md`
  opens it through Pomerium. The second needs the laptop to be a Podhaus
  operator (its `dev` service account reads Homelab), since the tunnel's
  certificates come from there; chezmoi sets up the rest.
