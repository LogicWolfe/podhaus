# Host recovery access

Status: planned. Voltaire's Pomerium SSH origin is live. Kangaroo and the
Tailscale recovery plane remain to be implemented.

## Goal

Pomerium remains the normal SSH path to Numbat, Bilby, Voltaire, and Kangaroo.
Host-native Tailscale on the homelab hosts provides an independent recovery
path for SSH only. Voltaire stays out of the tailnet.

## Pomerium origins

`pomerium-ssh-origin-bootstrap` is the common target-side procedure. The
operator supplies the initial SSH transport, route name, Numbat address, CA,
Noise key, and per-route token. The script installs the current rathole release,
CA trust, root-only config, and a hardened service. No initial host address or
bootstrap transport is built into it.

Add Kangaroo by extending the same procedure with a QTS service adapter, backed
by Kangaroo's existing persistent autorun mechanism. Terraform adds a
`kangaroo_ssh` token, Numbat loopback listener, and Pomerium route. Nathan's
Pocket ID identity may request Kangaroo's real local SSH account, currently
`admin`. Verify `ssh admin@kangaroo@ssh.pod.haus`, a second idempotent bootstrap,
and recovery after a QTS reboot.

## Tailscale recovery plane

Use a separate `tag:recovery` identity and auth key. Import the existing
tailnet policy into `tailscale_acl` before editing it because that Terraform
resource owns the whole policy file. Preserve `tag:podnet` until Kookaburra's
rollback path is retired. Add policy tests proving:

- member devices can reach `tag:recovery` on TCP 22;
- other ports on recovery nodes are denied;
- recovery nodes cannot initiate connections to member devices, other recovery
  nodes, or `tag:podnet`.

Run Tailscale directly on Bilby, Numbat, and Kangaroo. Linux uses the current
stable package from Tailscale's repository. Kangaroo uses the current stable
QNAP or static package from Tailscale's package server. Every bootstrap checks
for and installs an available upgrade. Nodes accept no routes, advertise no
routes, provide no exit node, and leave Tailscale SSH disabled so OpenSSH keeps
authentication authority.

Run `tailscaled` in userspace networking mode and publish only a Tailscale Serve
TCP 22 forward to `127.0.0.1:22`. This keeps the tailnet out of the host routing
table, including host-network containers. No container receives a Tailscale
socket, state directory, proxy, `/dev/net/tun`, `NET_ADMIN`, or Tailscale-driven
host networking. A successful container escape is already a host compromise;
this design avoids giving containers an additional escape or tailnet primitive.

Keep Kookaburra's existing containerised `tag:podnet` node unchanged until the
old edge is approved for retirement. Replace Bilby's current Tailscale container
only after the host-native recovery node and SSH forward pass independently.

## Verification

For each recovery host, verify ordinary SSH through its MagicDNS name, policy
denial on another port, current stable client version, and recovery after a
reboot. From a bridge and a host-network container, verify that tailnet names
and addresses are unreachable and that no Tailscale control or state path is
present. Stop the primary rathole client during one controlled test and confirm
the Tailscale SSH path still works, then restore and recheck Pomerium.
