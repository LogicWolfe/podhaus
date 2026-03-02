var REG_NONE = NewRegistrar("none");
var DSP_CF   = NewDnsProvider("cloudflare");
var DSP_UNI  = NewDnsProvider("unifi");

var TUNNEL = "cc68c7c9-1dad-42aa-af04-46119d3e515f.cfargotunnel.com.";

// --- Cloudflare public DNS for pod.haus ---
D("pod.haus!cloudflare", REG_NONE, DnsProvider(DSP_CF),

    // Tunnel-routed services (proxied)
    CNAME("home",     TUNNEL, CF_PROXY_ON),
    CNAME("kangaroo", TUNNEL, CF_PROXY_ON),
    CNAME("komodo",   TUNNEL, CF_PROXY_ON),
    CNAME("sync",     TUNNEL, CF_PROXY_ON),
    CNAME("torrent",  TUNNEL, CF_PROXY_ON),
    CNAME("unifi",    TUNNEL, CF_PROXY_ON),

    // Railway apps
    CNAME("doggos.indigo", "x0y6bs3z.up.railway.app.", CF_PROXY_OFF),
    CNAME("uptime",        "j2pkgn87.up.railway.app.", CF_PROXY_OFF),
    CNAME("yiayia",        "06r38qgz.up.railway.app.", CF_PROXY_OFF),

    // Email — Fastmail
    MX("@", 10, "in1-smtp.messagingengine.com."),
    MX("@", 20, "in2-smtp.messagingengine.com."),
    CNAME("fm1._domainkey", "fm1.pod.haus.dkim.fmhosted.com."),
    CNAME("fm2._domainkey", "fm2.pod.haus.dkim.fmhosted.com."),
    CNAME("fm3._domainkey", "fm3.pod.haus.dkim.fmhosted.com."),
    TXT("@", "v=spf1 include:spf.messagingengine.com ?all"),

    // Email — Postmark
    CNAME("pm-bounces", "pm.mtasv.net."),
    TXT("20260118155237pm._domainkey", "k=rsa;p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCIH3KJg5M/6mLqrDZYGuTlo/giMs3jPAOQTDo0P98+Nn4/9+bJci69Gn+i+TUgJDtzftYVi+532+di1NQn2uaZiaw2IjSk1/kanoiexsSrge0oVXCGgAuMXkrWdHk5OO2S90dpmDho+enbWbuxdrOob7BfyZIkSmz6m9s37lW2fQIDAQAB"),

    // Empty DKIM key (Fastmail rotation)
    TXT("@", "k=rsa;p=")
);

// --- UniFi local DNS — split-horizon for LAN access ---
D("pod.haus!unifi", REG_NONE, DnsProvider(DSP_UNI),
    A("unifi",     "10.0.0.1"),
    A("alligator", "10.0.0.83"),
    A("bilby",     "10.0.0.119")
);
