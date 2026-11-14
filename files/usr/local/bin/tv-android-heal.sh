#!/bin/sh
# Waydroid bug: after ~1h Android stops attaching new app processes ("failed to attach"/"start timeout") -> black/frozen apps.
# Every minute: if new such errors appeared since last check -> restart Android session (~45 s).
ST=/run/tv-heal.count

# Android "Restart" from the TV's own menu: Android's /init exits, the LXC container stops, but the Waydroid
# session (tv-android) keeps running with nothing on screen. tv-android being up >90 s with the container
# STOPPED never happens in normal use (a normal restart brings the container back within seconds), so the
# proven-safe full restart is used. Logged in the remote log so the family sees why the TV came back.
if systemctl is-active -q tv-android && waydroid status 2>/dev/null | grep -q "^Container:.*STOPPED"; then
  T0=$(date -d "$(systemctl show -p ActiveEnterTimestamp --value tv-android)" +%s 2>/dev/null || echo 0)
  if [ $(( $(date +%s) - T0 )) -gt 90 ]; then
    logger -t tv-heal "Android container stopped by itself (restart from the TV menu?), restarting tv-android"
    printf '%s\tTV\t-\tAndroid kendini kapatmıştı (menüden yeniden başlat) → otomatik yeniden açıldı\n' "$(date '+%F %T')" >> /var/log/tv-remote.log
    systemctl restart tv-android
    exit 0
  fi
fi
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
