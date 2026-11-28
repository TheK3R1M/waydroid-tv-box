#!/bin/sh
# After the TV is switched on (DP-3 hotplug) the screen can stay black.
# Since 2026-11-25 kiosk-shell is patched to re-home windows on hotplug, so this is only a safety net:
# it no longer restarts blindly on weston's "repaint delay ... abnormal" warning (that warning shows up
# after EVERY TV power-on and is harmless). It grabs the real HDMI frame (tvshot) 3 times over ~10 s and
# restarts the screen stack only if all three are black.
LOG=/run/tv/weston.log
RL=/var/log/tv-remote.log
yavg() { tvshot /tmp/tv-watch.jpg >/dev/null 2>&1 || { echo 999; return; }
  ffmpeg -hide_banner -i /tmp/tv-watch.jpg -vf signalstats,metadata=print -f null - 2>&1 \
    | sed -n 's/.*YAVG=\([0-9]*\).*/\1/p' | head -1; }
is_black() { v=$(yavg); [ -n "$v" ] && [ "$v" -lt 20 ]; }
while :; do
  [ -f "$LOG" ] || { sleep 5; continue; }
  hp=0
  tail -n0 -F "$LOG" 2>/dev/null | while read -r line; do
    # only a real unplug->replug (TV off/on); weston's own startup also prints "enabled"
    case "$line" in *"Output 'DP-3' no heads left"*) hp=1; continue ;; esac
    case "$line" in *"Output 'DP-3' enabled"*) [ $hp = 1 ] || continue ;; *) continue ;; esac
    hp=0
    sleep 15
    if is_black && sleep 4 && is_black && sleep 4 && is_black; then
      printf '%s\tHermes\t-\tTV açılınca ekran siyah kaldı -> ekran otomatik yenilendi\n' "$(date '+%F %T')" >> "$RL"
      logger -t tv-weston-watch "DP-3 re-enabled, HDMI frame black 3x -> restarting tv-weston"
      systemctl restart tv-weston
      exit 0
    fi
    logger -t tv-weston-watch "DP-3 re-enabled, picture OK -> nothing to do"
  done
  sleep 5
done
