#!/bin/sh
# One volume for the whole TV: Android's own STREAM_MUSIC stays at its maximum (25 steps); the host PipeWire sink
# (0-150 %, boost > 100) does all level control, from the phone page and the physical remote alike.
# Runs every minute (tv-vol-pin.timer) and after each Android start (tv-android drop-in). It only calls --set when the
# value differs, so Android's volume panel never pops up on the TV.
[ "$(waydroid shell -- getprop sys.boot_completed 2>/dev/null)" = "1" ] || exit 0
OUT=$(waydroid shell -- cmd media_session volume --stream 3 --get 2>/dev/null)
CUR=$(echo "$OUT" | sed -n 's/.*volume is \([0-9]*\).*/\1/p')
MAX=$(echo "$OUT" | sed -n 's/.*range \[0\.\.\([0-9]*\)\].*/\1/p')
[ -n "$MAX" ] && [ -n "$CUR" ] || exit 0
[ "$CUR" = "$MAX" ] && exit 0
waydroid shell -- cmd media_session volume --stream 3 --set "$MAX" >/dev/null 2>&1
logger -t tv-vol "Android STREAM_MUSIC $CUR -> $MAX (host sink does the volume)"
