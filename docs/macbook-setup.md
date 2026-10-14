# MacBook setup

How Nathan's personal laptop, `nb-macbook-air`, is set up from a fresh macOS
install. Chezmoi owns the machine whole; Ansible never runs on it (see
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
| cc-clip | Chezmoi asks `cc-clip version` while rendering the script that sets up each dev box's clipboard tunnel, so an apply without it fails | `curl -fsSL https://raw.githubusercontent.com/ShunmeiCho/cc-clip/main/scripts/install.sh \| sh` |

Then bootstrap chezmoi with the command in the dotfiles README, checking
Forgejo's host-key fingerprint it gives. The first apply installs Homebrew, the
command-line toolchain, OrbStack, Zed, Adrafinil, the 1Password CLI and Codex.

## Identities

### Machine key

The laptop has no TPM or security key chezmoi can use, so its machine key is a
passphrase-less ed25519 file inside FileVault, minted by hand as the dotfiles
README's "Minting a soft key" describes. Registering it is configuration in
this repository:

- `forgejo/keys/nathan/nb-macbook-air-machine.pub`: Terraform adds it to the
  Pocket ID `ssh_keys` claim, which Forgejo syncs, and registers it with GitHub
  for authentication (`terraform/github.tf`).
- GitHub commit signing: added by hand at github.com/settings/keys, the one
  registration Terraform cannot own.
- `podhaus_machine_key` in `ansible/inventory/host_vars/nb-macbook-air.yml`,
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
`nb-macbook-air.pod.haus` points at it, so the development hosts can SSH to the
laptop on the home LAN. The address lives in `config/lan-addresses.json`; the
reservation and record are in `terraform/unifi.tf` and
`terraform/dns_unifi_split_horizon.tf`. A new laptop means a new MAC in
`unifi.tf` and a Terraform apply. There is no route to the laptop from outside
the home network.

## After the first apply

- Run the commands the apply prints to make fish the login shell, then reopen
  the terminal.
- `gh auth login` and `codex login`, both interactive.
- Open OrbStack once to finish its first-run setup.
- Open Adrafinil once and approve its privileged helper, then start `codex`
  and choose "Trust all and continue" so Codex runs Adrafinil's hooks.

### SSH into the laptop

Chezmoi writes `~/.ssh/authorized_keys`: the personal key and each development
host's machine key. sshd's own settings are root-owned, so they are set once by
hand. These are the only root steps the laptop takes, and nothing changes them
after:

```sh
sudo systemsetup -setremotelogin on
sudo tee /etc/ssh/sshd_config.d/000-key-only.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers nathan
EOF
sudo sshd -t
```

The file sorts before Apple's `100-macos.conf`, and sshd takes the first value
it reads for each setting. Without it macOS accepts the account password over
SSH. sshd starts per connection on macOS, so nothing needs reloading.

## Checking the result

- `chezmoi status` lists nothing except the scripts that run on every apply.
- `ssh-machine -T git@git.pod.haus` authenticates as LogicWolfe with the
  machine key alone.
- `op-vault dev -- op vault list` lists `Dev`.
- `sudo sshd -T | grep -iE '^(authorizedkeysfile|passwordauthentication|allowusers) '`
  shows `.ssh/authorized_keys`, `no` and `nathan`.
- `docs-url ~/repos/podhaus/docs/macbook-setup.md` prints a localhost link that
  opens this page.
