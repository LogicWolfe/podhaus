# PodHaus Docker Containers

## Flood

**Web interface: 42000**

### Notes

Uses a named volume for configuration and a bind for networking.

It sometimes stalls at startup. Waiting up to about 5 minutes seems to resolve the issue.
It also seems to be possible to kickstart it by running `ls /data`.

## UniFi

**Web interface: 8443**

### Notes

This uses host networking, which is only available in Linux. Actual ports in use are:

* 8080/tcp - Device command/control
* 8443/tcp - Web interface + API
* 8843/tcp - HTTPS portal
* 8880/tcp - HTTP portal
* 3478/udp - STUN service
* 6789/tcp - Speed Test (unifi5 only)
* 10001/udp - UBNT Discovery