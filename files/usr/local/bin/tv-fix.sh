#!/bin/sh
# "TV'yi düzelt" (from the phone remote). Stage 1: restart the Android session. Stage 2, only if Android did not
# come back (container not RUNNING or boot not completed in 90 s, or Weston dead): restart the Waydroid container
# and Weston too. Runs detached (systemd-run) so the remote's HTTP request never waits on it. Logged for the family.
LOG=/var/log/tv-remote.log
say() { printf '%s\tTV\t-\t%s\n' "$(date '+%F %T')" "$1" >> $LOG; logger -t tv-fix "$1"; }

android_ok() {
  waydroid status 2>/dev/null | grep -q '^Container:.*RUNNING' || return 1
  [ "$(timeout 8 waydroid shell -- getprop sys.boot_completed 2>/dev/null)" = "1" ] || return 1
  pgrep -x weston >/dev/null || return 1
  return 0
}

wait_ok() {
  i=0
  while [ $i -lt 90 ]; do
    android_ok && return 0
    sleep 1; i=$((i + 1))
  done
  return 1
}

say "TV'yi düzelt: Android yeniden başlatılıyor"
systemctl restart tv-android
if wait_ok; then
  say "TV'yi düzelt: Android geri geldi"
  exit 0
fi

say "TV'yi düzelt: Android gelmedi, Waydroid konteyneri ve Weston yeniden başlatılıyor"
systemctl stop tv-android
timeout 60 waydroid container restart >/dev/null 2>&1
systemctl restart tv-weston
sleep 5
systemctl start tv-android
if wait_ok; then
  say "TV'yi düzelt: ikinci denemede Android geri geldi"
else
  say "TV'yi düzelt: Android hâlâ açılmadı (kayıt: journalctl -u tv-android)"
fi
