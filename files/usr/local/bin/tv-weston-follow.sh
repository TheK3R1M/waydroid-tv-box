#!/bin/sh
# ExecStartPost of tv-weston: when weston (re)starts while Android is already running
# (crash / watchdog restart), Android lost its surface -> restart it too. At boot tv-android is not active yet.
set -a; . /etc/tv/env; set +a
for i in $(seq 1 30); do [ -S /run/tv/wayland-tv ] && break; sleep 0.5; done
# keep a copy of each weston log (it is overwritten on every start)
mkdir -p /var/log/tv-weston
if systemctl is-active -q tv-android; then
  logger -t tv-weston-follow "weston restarted under a running Android -> restarting tv-android"
  systemctl --no-block restart tv-android
fi
exit 0
