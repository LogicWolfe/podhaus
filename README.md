# PodHaus Docker Containers

## Flood

**Port: 42000**

### Notes

Uses a named volume for configuration and a bind for networking.

It sometimes stalls at startup. Waiting up to about 5 minutes seems to resolve the issue.
It also seems to be possible to kickstart it by running `ls /data`.

