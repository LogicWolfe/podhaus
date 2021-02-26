# PodHaus Docker Containers

## Flood

```
Web interface:  42000
Volumes:        flood-db
Network:        dockernet
Environment:    $MEDIA_DIR
Secrets:        $FLOOD_SECRET
```

### Notes

Uses a named volume for configuration and a bind for networking.

It sometimes stalls at startup. Waiting up to about 5 minutes seems to resolve the issue.
It also seems to be possible to kickstart it by running `ls /data`.

## UniFi

```
Web interface:  8443
Volumes:        unifi
Environment:    $TZ
```
### Notes

This uses host networking, which is only available in Linux. Actual ports in use are:

* 8080/tcp - Device command/control
* 8443/tcp - Web interface + API
* 8843/tcp - HTTPS portal
* 8880/tcp - HTTP portal
* 3478/udp - STUN service
* 6789/tcp - Speed Test (unifi5 only)
* 10001/udp - UBNT Discovery

## Plex

```
Web interface:  32400
Volumes:        plex-config
Environment:    $TZ, $MEDIA_DIR
Secrets:        $PLEX_CLAIM_TOKEN
```

## Certbot

```
Volumes:        letsencrypt
Build Secrets:  $CLOUDFLARE_API_TOKEN
```

## Nginx

```
Volumes:        letsencrypt
Network:        dockernet
```

### Notes

To generate a claim token go to: https://www.plex.tv/claim/

Currently attempting to use macvlan networking to register itself as a new host on the network.
**This isn't working** from my mac, maybe more luck with Linux or switch to host networking. Also,
possible to bridge if necessary with further configuration.

Ports in use are:

* 32400/tcp - Web interface
* 3005/tcp
* 8324/tcp
* 32469/tcp
* 1900/udp
* 32410/udp
* 32414/udp
* 32412/udp
* 32413/udp