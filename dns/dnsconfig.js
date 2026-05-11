// DNSControl is retained for UniFi split-horizon DNS only.
//
// The Cloudflare side of every zone is managed by Terraform now (see
// `cloudflare/`). The UniFi controller doesn't have a Terraform provider
// worth the maintenance burden for these two A records, so this file
// stays as the source of truth for the LAN-side overrides that resolve
// `unifi.pod.haus` and `bilby.pod.haus` to internal IPs when on the
// home network.

var REG_NONE = NewRegistrar("none");
var DSP_UNI  = NewDnsProvider("unifi");

// --- UniFi local DNS — split-horizon for LAN access ---
D("pod.haus!unifi", REG_NONE, DnsProvider(DSP_UNI),
    A("unifi", "10.0.0.1"),
    A("bilby", "10.0.0.119")
);
