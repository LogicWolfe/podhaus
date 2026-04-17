var REG_NONE = NewRegistrar("none");
var DSP_CF   = NewDnsProvider("cloudflare");
var DSP_UNI  = NewDnsProvider("unifi");

var TUNNEL    = "cc68c7c9-1dad-42aa-af04-46119d3e515f.cfargotunnel.com.";
var PL_TUNNEL = "fec5ca76-b634-4185-bdb2-f85c38b1b570.cfargotunnel.com.";

// --- Cloudflare public DNS for pod.haus ---
D("pod.haus!cloudflare", REG_NONE, DnsProvider(DSP_CF),

    // Tunnel-routed services (proxied)
    CNAME("gatus",     TUNNEL, CF_PROXY_ON),  // gatus config-as-code monitoring
    CNAME("grafana",   TUNNEL, CF_PROXY_ON),  // grafana (kept for future dashboards)
    CNAME("home",      TUNNEL, CF_PROXY_ON),
    CNAME("kangaroo",  TUNNEL, CF_PROXY_ON),
    CNAME("komodo",    TUNNEL, CF_PROXY_ON),
    CNAME("logs",      TUNNEL, CF_PROXY_ON),  // victoria-logs vmui (primary log UI)
    CNAME("paperless", TUNNEL, CF_PROXY_ON),
    CNAME("sync",      TUNNEL, CF_PROXY_ON),
    CNAME("torrent",   TUNNEL, CF_PROXY_ON),
    CNAME("unifi",     TUNNEL, CF_PROXY_ON),

    CNAME("uptime",    TUNNEL, CF_PROXY_ON),

    // Railway apps
    CNAME("doggos.indigo", "x0y6bs3z.up.railway.app.", CF_PROXY_OFF),
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
    A("unifi", "10.0.0.1"),
    A("bilby", "10.0.0.119")
);

// --- elusive.email (Fastmail) ---
D("elusive.email", REG_NONE, DnsProvider(DSP_CF),
    MX("@", 10, "in1-smtp.messagingengine.com."),
    MX("@", 20, "in2-smtp.messagingengine.com."),
    CNAME("fm1._domainkey", "fm1.elusive.email.dkim.fmhosted.com."),
    CNAME("fm2._domainkey", "fm2.elusive.email.dkim.fmhosted.com."),
    CNAME("fm3._domainkey", "fm3.elusive.email.dkim.fmhosted.com."),
    TXT("@", "v=spf1 include:spf.messagingengine.com ?all")
);

// --- fractalseed.com (Fastmail) ---
D("fractalseed.com", REG_NONE, DnsProvider(DSP_CF),
    MX("@", 10, "in1-smtp.messagingengine.com."),
    MX("@", 20, "in2-smtp.messagingengine.com."),
    CNAME("fm1._domainkey", "fm1.fractalseed.com.dkim.fmhosted.com."),
    CNAME("fm2._domainkey", "fm2.fractalseed.com.dkim.fmhosted.com."),
    CNAME("fm3._domainkey", "fm3.fractalseed.com.dkim.fmhosted.com."),
    TXT("@", "v=spf1 include:spf.messagingengine.com ?all")
);

// --- logicaldecay.com (Google Workspace email only, XMPP SRV removed) ---
D("logicaldecay.com", REG_NONE, DnsProvider(DSP_CF),
    MX("@",  1, "aspmx.l.google.com."),
    MX("@",  5, "alt1.aspmx.l.google.com."),
    MX("@",  5, "alt2.aspmx.l.google.com."),
    MX("@", 10, "aspmx2.googlemail.com."),
    MX("@", 10, "aspmx3.googlemail.com."),
    TXT("@", "v=spf1 a include:_spf.google.com ~all")
);

// --- logicaldecay.net (Google Workspace email only, XMPP SRV removed) ---
D("logicaldecay.net", REG_NONE, DnsProvider(DSP_CF),
    MX("@", 10, "aspmx.l.google.com."),
    MX("@", 20, "alt1.aspmx.l.google.com."),
    MX("@", 20, "alt2.aspmx.l.google.com."),
    MX("@", 30, "aspmx2.googlemail.com."),
    MX("@", 30, "aspmx3.googlemail.com."),
    MX("@", 30, "aspmx4.googlemail.com."),
    MX("@", 30, "aspmx5.googlemail.com."),
    TXT("@", "v=spf1 a include:_spf.google.com ~all")
);

// --- logicwolfe.com (redirect to nathanbaxter.com) ---
D("logicwolfe.com", REG_NONE, DnsProvider(DSP_CF),
    ALIAS("@", "nathanbaxter.com.", CF_PROXY_ON)
);

// --- nathanbaxter.com (Fastmail email + services) ---
D("nathanbaxter.com", REG_NONE, DnsProvider(DSP_CF),
    // Email — Fastmail
    MX("@",   10, "in1-smtp.messagingengine.com."),
    MX("@",   20, "in2-smtp.messagingengine.com."),
    MX("www", 10, "in1-smtp.messagingengine.com."),
    MX("www", 20, "in2-smtp.messagingengine.com."),
    MX("*",   10, "in1-smtp.messagingengine.com."),
    MX("*",   20, "in2-smtp.messagingengine.com."),
    CNAME("fm1._domainkey", "fm1.nathanbaxter.com.dkim.fmhosted.com."),
    CNAME("fm2._domainkey", "fm2.nathanbaxter.com.dkim.fmhosted.com."),
    CNAME("fm3._domainkey", "fm3.nathanbaxter.com.dkim.fmhosted.com."),
    TXT("@", "v=spf1 include:spf.messagingengine.com ~all"),

    // Fastmail web/caldav/carddav
    CNAME("mail", "app.fastmail.com.", CF_PROXY_ON),
    SRV("_caldavs._tcp",    0, 1, 443, "caldav.fastmail.com."),
    SRV("_carddavs._tcp",   0, 1, 443, "carddav.fastmail.com."),
    SRV("_imaps._tcp",      0, 1, 993, "imap.fastmail.com."),
    SRV("_pop3s._tcp",     10, 1, 995, "pop.fastmail.com."),
    SRV("_submission._tcp",  0, 1, 587, "smtp.fastmail.com."),

    // Email — Postmark
    CNAME("pm-bounces", "pm.mtasv.net."),
    TXT("20251019030332pm._domainkey", "k=rsa;p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDYtsXWV3F5hNjZtbIHesrQ40jJ9fYiX/te3iiDt+6+dGHwjroZQDwGRg9hcEjRX/Ev1UTecR32/14Ie7zoD35OwiZ8c0/V5ojaB2CHtaWVHkzwINwKTCCcOOBbezHFsUvk7JPE7Il5U0weRbcLEcYOxyM1oEXxTrA+wlKS13JkaQIDAQAB"),

    // Keybase verification
    TXT("@", "keybase-site-verification=PYg39KGImTNyG3xYnl4VUNhzg51qNFmDhZyBDwLKO0A")
);

// --- nathanbaxter.net (empty — URI record not supported by DNSControl) ---
D("nathanbaxter.net", REG_NONE, DnsProvider(DSP_CF));

// --- nathanbaxter.org (empty — URI record not supported by DNSControl) ---
D("nathanbaxter.org", REG_NONE, DnsProvider(DSP_CF));

// --- pinelake.haus (tunnel CNAMEs only, stale A records removed) ---
D("pinelake.haus", REG_NONE, DnsProvider(DSP_CF),
    CNAME("home",    PL_TUNNEL, CF_PROXY_ON),
    CNAME("sync",    PL_TUNNEL, CF_PROXY_ON),
    CNAME("torrent", PL_TUNNEL, CF_PROXY_ON)
);

// --- podfoundation.org.au (Cloudflare email routing) ---
D("podfoundation.org.au", REG_NONE, DnsProvider(DSP_CF),
    MX("@", 39, "amir.mx.cloudflare.net."),
    MX("@", 63, "linda.mx.cloudflare.net."),
    MX("@", 76, "isaac.mx.cloudflare.net."),
    TXT("@", "v=spf1 include:_spf.mx.cloudflare.net ~all"),
    TXT("_dmarc", "v=DMARC1; p=none; rua=mailto:nathan@podfoundation.org.au")
);
