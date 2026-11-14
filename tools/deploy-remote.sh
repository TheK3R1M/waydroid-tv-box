#!/usr/bin/env bash
# Deploy the web remote (tv-remote.py + index.html + VERSION) from a FILLED copy of this kit to the TV host.
#
#   tools/deploy-remote.sh <filled-copy-dir>          restart now if the TV is idle, else when it becomes idle
#   tools/deploy-remote.sh <filled-copy-dir> --now    restart right away (stops a playing channel!)
#
# Rules this script enforces:
#  - refuses to run on the unfilled kit (check-placeholders.sh must pass on the copy)
#  - the host keeps the previous release in /root/tv-remote-releases/<version>/ (last 10 kept)
#  - python3 -m py_compile on the host before the swap; files are moved into place atomically
#  - restarts tv-remote only if no mpv runs and no remote action in the last 5 min (else it schedules a restart
#    via tv-remote-restart-when-idle.sh), because a restart kills the playing channel
# Host alias: TV_HOST (default pve-tv, see docs/11-pc-viewer.md). Requires key-based ssh (BatchMode).
set -euo pipefail
HOST="${TV_HOST:-pve-tv}"
SRC="${1:?usage: $0 <filled-copy-dir> [--now]}"
NOW=0; [ "${2:-}" = "--now" ] && NOW=1
cd "$SRC"
"$(dirname "$0")/check-placeholders.sh" "$SRC" >/dev/null || { echo "placeholders left: fill the copy first"; exit 2; }
for f in files/usr/local/bin/tv-remote.py files/usr/local/share/tv-remote/index.html files/usr/local/bin/tv-remote-restart-when-idle.sh; do
  [ -f "$f" ] || { echo "missing $f"; exit 2; }
done
VER="$(git rev-parse --short=10 HEAD 2>/dev/null || echo unversioned)-$(date +%F)"
TMP="$(mktemp -d "$PWD/.deploy.XXXXXX")"; trap 'rm -rf "$TMP"' EXIT
cp files/usr/local/bin/tv-remote.py "$TMP/tv-remote.py"
cp files/usr/local/share/tv-remote/index.html "$TMP/index.html"
cp files/usr/local/bin/tv-remote-restart-when-idle.sh "$TMP/restart-when-idle.sh"
echo "$VER" > "$TMP/VERSION"
python -m py_compile "$TMP/tv-remote.py"

echo "Deploying $VER to $HOST ..."
scp -q "$TMP/tv-remote.py" "$HOST:/usr/local/bin/tv-remote.py.new"
scp -q "$TMP/index.html" "$HOST:/usr/local/share/tv-remote/index.html.new"
scp -q "$TMP/VERSION" "$HOST:/usr/local/share/tv-remote/VERSION.new"
scp -q "$TMP/restart-when-idle.sh" "$HOST:/usr/local/bin/tv-remote-restart-when-idle.sh.new"
ssh -o BatchMode=yes "$HOST" NOW="$NOW" VER="'$VER'" 'sh -s' <<'EOF'
set -e
R=/root/tv-remote-releases; mkdir -p $R
old=$(cut -d" " -f1 /usr/local/share/tv-remote/VERSION 2>/dev/null); old=${old:-pre-versioned}
mkdir -p "$R/$old" && cp -a /usr/local/bin/tv-remote.py /usr/local/share/tv-remote/index.html "$R/$old/" 2>/dev/null || true
ls -1dt $R/* | tail -n +11 | xargs -r rm -rf          # keep the last 10 releases
python3 -m py_compile /usr/local/bin/tv-remote.py.new
mv /usr/local/bin/tv-remote.py.new /usr/local/bin/tv-remote.py; chmod 755 /usr/local/bin/tv-remote.py
mv /usr/local/share/tv-remote/index.html.new /usr/local/share/tv-remote/index.html
mv /usr/local/share/tv-remote/VERSION.new /usr/local/share/tv-remote/VERSION
mv /usr/local/bin/tv-remote-restart-when-idle.sh.new /usr/local/bin/tv-remote-restart-when-idle.sh; chmod 755 /usr/local/bin/tv-remote-restart-when-idle.sh
systemctl stop tv-remote-deploy 2>/dev/null || true
last=$(tail -1 /var/log/tv-remote.log | cut -f1); age=$(( $(date +%s) - $(date -d "$last" +%s 2>/dev/null || echo 0) ))
if [ "$NOW" = 1 ] || { ! pgrep -x mpv >/dev/null && [ "$age" -gt 300 ]; }; then
  systemctl restart tv-remote; sleep 3
  printf '%s\tHermes\t-\tkumanda güncellendi (%s)\n' "$(date '+%F %T')" "$VER" >> /var/log/tv-remote.log
  echo "restarted: $(systemctl is-active tv-remote) (previous release: $R/$old)"
else
  systemd-run --unit=tv-remote-deploy --collect /usr/local/bin/tv-remote-restart-when-idle.sh >/dev/null
  echo "TV in use: page is live, server restarts when idle. Previous release: $R/$old"
fi
EOF
