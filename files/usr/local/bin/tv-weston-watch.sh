#!/bin/sh
# Weston 14 bug: after the TV is switched on (DP-3 hotplug) weston logs
# "computed repaint delay ... is abnormal" and stops scanning out -> black HDMI.
# On that line: wait until nobody watches live TV / used the remote for 60 s, then restart the screen stack.
LOG=/run/tv/weston.log
RL=/var/log/tv-remote.log
while :; do
  [ -f "$LOG" ] || { sleep 5; continue; }
  tail -n0 -F "$LOG" 2>/dev/null | while read -r line; do
    case "$line" in *"repaint delay"*abnormal*) ;; *) continue ;; esac
    sleep 8
    pgrep -x mpv >/dev/null && { logger -t tv-weston-watch "abnormal repaint, mpv running -> skip"; continue; }
    last=$(stat -c %Y "$RL" 2>/dev/null || echo 0)
    [ $(( $(date +%s) - last )) -lt 60 ] && sleep 60
    printf '%s\tHermes\t-\tTV açılınca ekran takıldı -> ekran otomatik yenilendi\n' "$(date '+%F %T')" >> "$RL"
    logger -t tv-weston-watch "abnormal repaint -> restarting tv-weston"
    systemctl restart tv-weston
    exit 0
  done
  sleep 5
done
