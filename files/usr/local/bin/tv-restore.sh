#!/bin/sh
# tv-restore.sh — roll Android's user data back to a snapshot made by tv-backup.sh.
#   tv-restore.sh            -> list snapshots (+ apps installed in each)
#   tv-restore.sh <name>     -> stop Android, safety-snapshot the current state, restore <name>, start Android
set -eu
DST=/var/lib/tv-backup
DATA=/root/.local/share/waydroid/data
if [ $# -eq 0 ]; then
  for d in $(find $DST -mindepth 1 -maxdepth 1 -type d -name '20*' ! -name '*.part' | sort); do
    echo "$(basename $d)  ($(wc -l < $d.packages 2>/dev/null || echo ?) apps)"
  done
  exit 0
fi
SNAP=$DST/$1
[ -d "$SNAP" ] || { echo "no snapshot $1"; exit 1; }
tv-backup.sh now >/dev/null            # current state first, so the restore itself can be undone
systemctl stop tv-android
waydroid container stop 2>/dev/null || true
rsync -aHAX --numeric-ids --delete "$SNAP/" "$DATA/"
systemctl start tv-android
printf '%s\tYedek\t-\tAndroid %s yedeğine geri döndürüldü\n' "$(date '+%F %T')" "$1" >> /var/log/tv-remote.log
echo "restored $1 (Android restarting, ~1 min)"
