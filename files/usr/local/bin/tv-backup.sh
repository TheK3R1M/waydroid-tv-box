#!/bin/sh
# tv-backup.sh — snapshot of Android's user data (apps, settings, logins) so a bad APK can be rolled back.
# Daily via tv-backup.timer (04:40, only when the TV is idle) and on demand: `tv-backup.sh now`.
# Rotating hard-link snapshots (rsync --link-dest): unchanged files cost no extra space.
# Keeps 7 daily + 4 weekly (Sunday) snapshots in /var/lib/tv-backup/. Restore: tv-restore.sh <name>.
set -eu
SRC=/root/.local/share/waydroid/data/
DST=/var/lib/tv-backup
LOG=/var/log/tv-remote.log
FORCE=${1:-}
mkdir -p $DST && chmod 700 $DST

idle() {   # no live TV player and no remote use in the last 20 minutes
  pgrep -x mpv >/dev/null && return 1
  last=$(tail -1 $LOG 2>/dev/null | cut -f1)
  [ -z "$last" ] && return 0
  [ $(( $(date +%s) - $(date -d "$last" +%s 2>/dev/null || echo 0) )) -gt 1200 ]
}
if [ "$FORCE" != now ]; then
  for i in $(seq 1 12); do idle && break; sleep 600; done
  idle || { echo "TV busy all night, skipped"; exit 0; }
fi

NAME=$(date +%F_%H%M)
PREV=$(find $DST -mindepth 1 -maxdepth 1 -type d -name '20*' ! -name '*.part' | sort | tail -1)
rm -rf $DST/*.part
# freeze Android while copying so databases are consistent (resume always, even on error)
lxc-freeze -P /var/lib/waydroid/lxc -n waydroid 2>/dev/null && FROZEN=1 || FROZEN=0
trap '[ $FROZEN = 1 ] && lxc-unfreeze -P /var/lib/waydroid/lxc -n waydroid' EXIT
rsync -aHAX --numeric-ids --delete ${PREV:+--link-dest=$PREV} $SRC $DST/$NAME.part/
mv $DST/$NAME.part $DST/$NAME
[ $FROZEN = 1 ] && lxc-unfreeze -P /var/lib/waydroid/lxc -n waydroid; FROZEN=0
# package list next to the data (what was installed at that time)
timeout 20 adb -s __ANDROID_IP__:5555 shell pm list packages -3 2>/dev/null | sort > $DST/$NAME.packages || true

# rotation: newest 7 + Sunday snapshots of the last 4 weeks
snaps() { find $DST -mindepth 1 -maxdepth 1 -type d -name '20*' ! -name '*.part' | sort; }
keep=$( (snaps | tail -7
         for d in $(snaps); do [ "$(date -d "$(basename $d | cut -d_ -f1)" +%u)" = 7 ] && echo $d; done | tail -4) | sort -u)
for d in $(snaps); do
  echo "$keep" | grep -qx "$d" || rm -rf "$d" "$d.packages"
done
SIZE=$(du -sh $DST | cut -f1)
printf '%s\tYedek\t-\tAndroid yedeği alındı: %s (toplam %s)\n' "$(date '+%F %T')" "$NAME" "$SIZE" >> $LOG
echo "backup $NAME ok, total $SIZE"
