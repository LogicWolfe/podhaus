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
# started. This starts it, then reconciles the dockernet bridge and any
# container left off its network — whether `exited` or running-but-
# detached (the reconcile block below).
#
# Replaces a `@reboot` crontab line that never ran: kangaroo's cron is
# BusyBox crond, which doesn't implement the `@reboot` nickname. Lives on
# the boot DOM, so it survives firmware AND Container Station upgrades.
# Installed by kangaroo/host-autorun/install.sh.
QPKG=/share/CACHEDEV2_DATA/.qpkg/container-station
DOCKER="$QPKG/usr/bin/docker"
IP=/usr/bin/ip

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

    # Reconcile the dockernet bridge and the containers that ride it.
    # Two Container-Station-churn failure modes (firmware reboot, engine
    # restart), both seen on kangaroo:
    #
    #  1. dockernet goes "phantom" — the libnetwork record survives, so
    #     `network inspect` passes, but the bridge datapath is gone and
    #     every endpoint attach fails with "network <id> does not exist".
    #     Probe the real bridge interface, not the record; if it's gone,
    #     force-clear endpoints, drop the stale record, recreate it live.
    #  2. a managed container ends up off its network — either `exited`
    #     (restart policy gave up; autoheal only watches *running*) or
    #     *running but detached* (port still open, so the healthcheck is
    #     green and autoheal ignores it — this is exactly how alloy went
    #     stale while looking healthy, 2026-06-18). Reconcile both: a
    #     container's NetworkMode names the network it belongs on.
    #
    # One-shot inits (restart:no) are skipped by the policy filter.
    managed() {
        case "$("$DOCKER" inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$1")" in
            always|unless-stopped) return 0 ;;
            *) return 1 ;;
        esac
    }

    ensure_dockernet() {
        if "$DOCKER" network inspect dockernet >/dev/null 2>&1; then
            netid=$("$DOCKER" network inspect -f '{{.Id}}' dockernet)
            "$IP" link show "br-$(echo "$netid" | cut -c1-12)" >/dev/null 2>&1 && return 0
            echo "reconcile: dockernet phantom (record present, bridge gone) — recreating"
            for c in $("$DOCKER" ps -aq); do
                "$DOCKER" network disconnect -f dockernet "$c" >/dev/null 2>&1 || true
            done
            "$DOCKER" network rm dockernet >/dev/null 2>&1 || true
        fi
        "$DOCKER" network create dockernet >/dev/null 2>&1 \
            && echo "reconcile: created dockernet" \
            || echo "reconcile: FAILED to create dockernet"
    }
    ensure_dockernet

    # Pass 1: start exited-but-should-run containers. A plain `docker
    # start` can fail on a stale endpoint ("network ... does not exist");
    # clear the endpoints first, then retry.
    for c in $("$DOCKER" ps -aq --filter status=exited); do
        managed "$c" || continue
        "$DOCKER" start "$c" >/dev/null 2>&1 && { echo "reconcile: started $c"; continue; }
        for net in $("$DOCKER" inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c"); do
            "$DOCKER" network disconnect -f "$net" "$c" >/dev/null 2>&1 || true
        done
        "$DOCKER" start "$c" >/dev/null 2>&1 \
            && echo "reconcile: started $c (cleared stale endpoint)" \
            || echo "reconcile: FAILED to start $c"
    done

    # Pass 2: reattach running-but-detached containers. NetworkMode names
    # the user network the container belongs on; if it's missing from the
    # live attachment, reconnect. host/none/default/bridge have no user
    # bridge to rejoin, so they're skipped.
    for c in $("$DOCKER" ps -q); do
        managed "$c" || continue
        nm=$("$DOCKER" inspect -f '{{.HostConfig.NetworkMode}}' "$c")
        case "$nm" in host|none|default|bridge|"") continue ;; esac
        "$DOCKER" inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c" \
            | grep -qw "$nm" && continue
        "$DOCKER" network connect "$nm" "$c" >/dev/null 2>&1 \
            && echo "reconcile: reattached $c to $nm" \
            || echo "reconcile: FAILED to reattach $c to $nm"
    done
) >> /var/log/komodo-periphery-boot.log 2>&1 &
# <<< podhaus kangaroo autorun <<<
