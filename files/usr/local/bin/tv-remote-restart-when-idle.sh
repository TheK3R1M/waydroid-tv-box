#!/bin/sh
# Restart tv-remote only when nobody is using the TV: no remote action for 20 min and no player (mpv) running,
# or at the latest 05:00. Used after code updates so nobody gets interrupted.
while :; do
  last=$(tail -1 /var/log/tv-remote.log | cut -f1); age=$(( $(date +%s) - $(date -d "$last" +%s 2>/dev/null || echo 0) ))
  if { [ "$age" -gt 1200 ] && ! pgrep -x mpv >/dev/null; } || [ "$(date +%H)" = "05" ]; then
    systemctl restart tv-remote; echo "$(date "+%F %T")	Hermes	-	kumanda güncellendi (boşta yeniden başlatıldı)" >> /var/log/tv-remote.log; exit 0
  fi
  sleep 60
done
