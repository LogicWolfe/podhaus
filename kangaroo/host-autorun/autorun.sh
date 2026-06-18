#!/bin/sh
# >>> podhaus kangaroo autorun (managed by kangaroo/host-autorun) >>>
# Start Container Station's user Docker engine at boot.
#
# QNAP's /etc/init.d/init_nas.sh runs this file (mounted at
# /tmp/config/autorun.sh off the boot DOM) at startup when
# `getcfg Misc Autorun` is TRUE — after S57init_qpkg has launched
# Container Station. CS leaves its USER-facing Docker engine
# (supervisord `[program:docker]`) at autostart=false, and the qpkg
# boot script starts only system-docker + ctstation. So the kangaroo
# stacks (komodo-periphery, syncthing, backrest, alloy, autoheal) — all
# `restart: unless-stopped` — won't come back until that engine is
# started. This starts it, then reconciles any container the restart
# policy left parked in `exited` (the reconcile loop below).
#
# Replaces a `@reboot` crontab line that never ran: kangaroo's cron is
# BusyBox crond, which doesn't implement the `@reboot` nickname. Lives on
# the boot DOM, so it survives firmware AND Container Station upgrades.
# Installed by kangaroo/host-autorun/install.sh.
QPKG=/share/CACHEDEV2_DATA/.qpkg/container-station
DOCKER="$QPKG/usr/bin/docker"

# Background so init_nas.sh isn't blocked by the wait loop on a cold boot.
(
    i=0
    while [ "$i" -lt 60 ]; do
        [ -S /var/run/container-station/supervisor.sock ] && break
        sleep 5
        i=$((i + 1))
    done
    # Idempotent: starting an already-running program is a no-op. Call
    # supervisord directly (its `ctl` mode) rather than the supervisorctl
    # wrapper, which does a bare-PATH `exec supervisord` — and init_nas.sh
    # runs us with a minimal boot PATH that lacks $QPKG/bin.
    "$QPKG/bin/supervisord" ctl -s unix:///var/run/container-station/supervisor.sock start docker

    # Wait for the engine to accept commands before reconciling.
    i=0
    while [ "$i" -lt 60 ]; do
        "$DOCKER" info >/dev/null 2>&1 && break
        sleep 5
        i=$((i + 1))
    done

    # Reconcile exited-but-should-run containers. A
    # restart:unless-stopped/always container that lost the dockernet-
    # attach race at boot stays `exited`: the daemon's restart policy
    # gives up and autoheal only watches *running* containers, so nothing
    # else brings it back (backrest + alloy hit this after the 2026-06-16
    # firmware-reboot). A plain `docker start` isn't enough either — the
    # stopped container holds a stale network endpoint and start fails
    # with "network ... does not exist" even though dockernet is present;
    # clear the endpoint first, then retry. One-shot inits (restart:no)
    # are skipped by the policy filter.
    "$DOCKER" network inspect dockernet >/dev/null 2>&1 || "$DOCKER" network create dockernet
    for c in $("$DOCKER" ps -aq --filter status=exited); do
        case "$("$DOCKER" inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$c")" in
            always|unless-stopped) ;;
            *) continue ;;
        esac
        "$DOCKER" start "$c" >/dev/null 2>&1 && { echo "reconcile: started $c"; continue; }
        for net in $("$DOCKER" inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c"); do
            "$DOCKER" network disconnect -f "$net" "$c" >/dev/null 2>&1 || true
        done
        "$DOCKER" start "$c" >/dev/null 2>&1 \
            && echo "reconcile: started $c (cleared stale endpoint)" \
            || echo "reconcile: FAILED to start $c"
    done
) >> /var/log/komodo-periphery-boot.log 2>&1 &
# <<< podhaus kangaroo autorun <<<
