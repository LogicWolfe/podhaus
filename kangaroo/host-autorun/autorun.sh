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
# started. This starts it; Docker's restart policies bring the rest up.
#
# Replaces a `@reboot` crontab line that never ran: kangaroo's cron is
# BusyBox crond, which doesn't implement the `@reboot` nickname. Lives on
# the boot DOM, so it survives firmware AND Container Station upgrades.
# Installed by kangaroo/host-autorun/install.sh.
QPKG=/share/CACHEDEV2_DATA/.qpkg/container-station

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
) >> /var/log/komodo-periphery-boot.log 2>&1 &
# <<< podhaus kangaroo autorun <<<
