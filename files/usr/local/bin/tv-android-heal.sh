#!/bin/sh
# Waydroid bug: after ~1h Android stops attaching new app processes ("failed to attach"/"start timeout") -> black/frozen apps.
# Every minute: if new such errors appeared since last check -> restart Android session (~45 s).
ST=/run/tv-heal.count
[ "$(waydroid shell -- getprop sys.boot_completed 2>/dev/null)" = "1" ] || exit 0
N=$(waydroid shell -- logcat -d -b main,system 2>/dev/null | grep -c "failed to attach")
O=$(cat $ST 2>/dev/null || echo 0)
echo $N > $ST
if [ "$N" -gt "$O" ]; then
  logger -t tv-heal "Android process attach failures ($O -> $N), restarting tv-android"
  echo 0 > $ST
  systemctl restart tv-android
fi

# Ensure SW video decode (VA-API copy path on Raven2 = ~6-16 fps, stalls)
[ "$(waydroid shell -- getprop media.sf.hwaccel 2>/dev/null)" = "0" ] || waydroid shell -- setprop media.sf.hwaccel 0
