#!/usr/bin/env bash
# Waydroid TV box installer: modular, idempotent, one command. Run as root on Proxmox VE 9 / Debian 13
# with an AMD or Intel iGPU and an HDMI TV.
#
#   curl -fsSL https://raw.githubusercontent.com/TheK3R1M/waydroid-tv-box/main/install.sh | bash
#   bash install.sh                                              # interactive module menu
#   bash install.sh --modules core,remote,live-tv,voice,keyboard,guard,backup --yes
#   bash install.sh --modules core,remote --dry-run              # print the plan, change nothing
#   bash install.sh --uninstall voice                            # remove one module
#
# Log: /var/log/tvbox-install.log   State: /etc/tvbox/installed   Per-module file lists: /etc/tvbox/manifests/
# Installs no third-party video apps. Piracy and stream-scraper apps are not part of this installer.
set -Eeuo pipefail
shopt -s nullglob

VERSION=0.1.0
REPO_URL=https://github.com/TheK3R1M/waydroid-tv-box
LOG=/var/log/tvbox-install.log
STATE_DIR=/etc/tvbox
STATE=$STATE_DIR/installed
MDIR=$STATE_DIR/manifests
WORK=$(mktemp -d "${TMPDIR:-/tmp}/tvbox.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
trap 'echo "[FAIL] line $LINENO: $BASH_COMMAND (details in $LOG)" >&2' ERR

ALL_MODULES="core remote live-tv voice keyboard guard backup"
DEFAULT_OPT="remote live-tv keyboard guard backup"          # voice is off by default (needs a mic + 500 MB model)
declare -A DESC=(
  [core]="TV stack: Weston kiosk, PipeWire audio, Waydroid Android TV 13. Required."
  [remote]="Phone web remote on port 8090, adb LAN rule for the admin PC, debug page"
  [live-tv]="Live channels in host mpv: Turkish channel list, split screen, yt-dlp"
  [voice]="Offline voice key: whisper.cpp + command parser (needs a mic on the remote)"
  [keyboard]="TV Klavye on-screen Turkish keyboard, built from source, default input method"
  [guard]="LAN isolation for Android (internet stays open) and the tv-guard watchdog"
  [backup]="Nightly Android data backup at 04:40 (rsync)"
)
declare -A NEEDS=([live-tv]="remote" [voice]="remote" [keyboard]="core" [guard]="core" [backup]="core" [remote]="core")

# Kit files per module, relative to files/ (installed to the same path under /). Keep in sync with the kit.
FILES_core="etc/tv/env etc/tv/weston.ini etc/systemd/logind.conf.d/10-tv-no-powerkey.conf
 etc/systemd/system/tv-base.service etc/systemd/system/tv-weston.service etc/systemd/system/tv-pipewire.service
 etc/systemd/system/tv-pipewire-pulse.service etc/systemd/system/tv-wireplumber.service
 etc/systemd/system/tv-android.service etc/systemd/system/tv-android-heal.service etc/systemd/system/tv-android-heal.timer
 etc/systemd/system/waydroid-container.service.d/override.conf etc/systemd/system/waydroid-container.service.d/no-debugfs.conf
 usr/local/bin/setup-binderfs.sh usr/local/bin/waydroid-no-debugfs.sh usr/local/bin/tv-android-heal.sh usr/local/bin/tvshot
 usr/local/bin/tv-weston-watch.sh usr/local/bin/tv-weston-follow.sh etc/systemd/system/tv-weston.service.d/20-follow.conf
 etc/systemd/system/tv-weston-watch.service var/lib/waydroid/waydroid_base.prop"
FILES_wireless="etc/modprobe.d/rtw89-stable.conf etc/systemd/system/wifi-watchdog.service usr/local/bin/wifi-watchdog.sh"
FILES_remote="usr/local/bin/tv-vol-pin.sh etc/systemd/system/tv-vol-pin.service etc/systemd/system/tv-vol-pin.timer etc/systemd/system/tv-android.service.d/vol.conf
 usr/local/bin/tv-remote.py usr/local/share/tv-remote/index.html etc/systemd/system/tv-remote.service
 usr/local/bin/tv-remote-restart-when-idle.sh usr/local/bin/tv-adb-lan.sh etc/systemd/system/tv-android.service.d/adb.conf
 usr/local/bin/tv-intent.py usr/local/bin/tv-fix.sh usr/local/bin/tv-why.py usr/local/bin/tv-blackbox.py
 etc/systemd/system/tv-blackbox.service usr/local/bin/tv-hdmi-stream
 usr/local/bin/tv-epg.py etc/systemd/system/tv-epg.service etc/systemd/system/tv-epg.timer"
FILES_live_tv="usr/local/bin/tv-channels.py usr/local/bin/tv-channels-extra.py
 etc/systemd/system/tv-channels-extra.service etc/systemd/system/tv-channels-extra.timer"
FILES_voice="usr/local/bin/tv-voice.py usr/local/bin/tv-nlu.py usr/local/bin/tv-understand.py
 etc/systemd/system/tv-voice.service etc/systemd/system/tv-whisper.service"
FILES_guard="usr/local/bin/tv-net-isolate.sh usr/local/bin/tv-guard-check.py usr/local/bin/tv-guard-fw.sh
 etc/systemd/system/tv-net-isolate.service etc/systemd/system/tv-net-isolate.timer
 etc/systemd/system/tv-guard.service etc/systemd/system/tv-guard.timer etc/systemd/system/tv-android.service.d/isolate.conf"
FILES_backup="usr/local/bin/tv-backup.sh usr/local/bin/tv-restore.sh etc/systemd/system/tv-backup.service etc/systemd/system/tv-backup.timer"

CORE_PKGS="weston pipewire pipewire-bin pipewire-pulse wireplumber gstreamer1.0-pipewire pulseaudio-utils mpv ffmpeg
 mesa-va-drivers adb socat python3 python3-evdev iptables ifupdown2 dbus-daemon curl ca-certificates git openssl
 rsync"

DRY=0; YES=0; MODULES=""; UNINSTALL=""
declare -A V=()
RESULTS=()
CUR=""

# ---------- output helpers ----------
say()  { printf '%s\n' "$*" | tee -a "$LOG"; }
info() { say "[info] $*"; }
warn() { say "[warn] $*"; }
die()  { say "[FAIL] $*"; exit 1; }
step() { say ""; say "== $* =="; }
run() {  # run a command (logged); in dry-run only print it
  say "+ $*"
  [ "$DRY" = 1 ] && return 0
  "$@" >>"$LOG" 2>&1
}

# ---------- prompts (read from the terminal even under curl | bash) ----------
ask() {  # ask VAR "question" default
  local var=$1 q=$2 def=${3:-} ans=""
  if [ "$YES" = 1 ] || [ ! -r /dev/tty ]; then ans=$def
  else read -r -p "$q [$def]: " ans </dev/tty || ans=$def; fi
  printf -v "$var" '%s' "${ans:-$def}"
}
confirm() {  # confirm "question" y|n  -> 0 = yes
  local d=${2:-n} ans
  if [ "$YES" = 1 ] || [ ! -r /dev/tty ]; then [ "$d" = y ]; return; fi
  read -r -p "$1 [$([ "$d" = y ] && echo Y/n || echo y/N)]: " ans </dev/tty || ans=""
  ans=${ans:-$d}
  [[ $ans =~ ^[Yy] ]]
}
valid_ip() { [[ ${1:-} =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; }

# ---------- source of the kit ----------
locate_source() {
  local here=""
  here=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd) || here=""
  if [ -n "$here" ] && [ -d "$here/files" ] && [ -d "$here/android" ]; then SRC=$here; return; fi
  SRC=/opt/waydroid-tv-box
  if [ ! -d "$SRC/files" ]; then
    [ "$DRY" = 1 ] && { SRC=$here; info "dry run: no kit checkout found"; return; }
    info "no local kit checkout: cloning $REPO_URL to $SRC"
    command -v git >/dev/null || { apt-get update -qq >>"$LOG" 2>&1; apt-get install -y -qq git ca-certificates >>"$LOG" 2>&1; }
    git clone --depth 1 "$REPO_URL" "$SRC" >>"$LOG" 2>&1 || die "cannot download the kit from $REPO_URL (see $LOG)"
  fi
}

kit_check() {  # every file a module needs must exist in the kit before anything changes
  local m rel missing=0 list="$1"
  [ "${V[wireless]:-0}" = 1 ] && list="$list wireless"
  for m in $list; do
    for rel in $(files_of "$m"); do
      [ -f "$SRC/files/$rel" ] || { say "  missing in kit: files/$rel"; missing=1; }
    done
  done
  [ "$missing" = 0 ] || die "the kit is incomplete for the selected modules (see list above)"
}

files_of() {  # files_of <module> -> relative paths (wireless extras are added in deploy_list)
  local v="FILES_${1//-/_}"; echo "${!v:-}" | tr -s ' \n' '\n' | grep -v '^$' || true
}

# ---------- preflight ----------
preflight() {
  step "Preflight"
  [ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || die "run as root (sudo -i)"
  # OS
  if [ -r /etc/os-release ]; then . /etc/os-release; fi
  if [ "${ID:-}" = debian ] && [ "${VERSION_ID:-}" = 13 ]; then info "OS: ${PRETTY_NAME:-debian 13}"
  else warn "tested on Debian 13 / Proxmox VE 9 only (found ${PRETTY_NAME:-unknown})"; confirm "continue anyway?" n || die "stopped by user"; fi
  # CPU. Zen+ (family 23, model 24, e.g. Ryzen Embedded R2314) cannot boot the Android TV 16 image.
  V[cpu]=$(awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo)
  local fam mdl
  fam=$(awk -F': ' '/^cpu family/{print $2; exit}' /proc/cpuinfo)
  mdl=$(awk -F': ' '/^model[[:space:]]*:/{print $2; exit}' /proc/cpuinfo)
  info "CPU: ${V[cpu]} (family $fam, model $mdl)"
  if [ "$fam" = 23 ] && [ "$mdl" = 24 ]; then
    info "Zen+ detected: this installer uses the Android TV 13 image only (ATV 16 does not boot here)"
  else
    warn "Android TV 13 is the only image this kit was tested with; the installer uses it on every CPU"
  fi
  # Display: first connected DRM connector
  local s n found=""
  for s in /sys/class/drm/card[0-9]*-*/status; do
    if [ "$(cat "$s" 2>/dev/null)" = connected ]; then n=$(basename "$(dirname "$s")"); found=$n; break; fi
  done
  if [ -n "$found" ]; then
    V[card]=${found%%-*}; V[card]=${V[card]#card}; V[connector]=${found#card*-}
    V[card]=/dev/dri/card${V[card]}; V[card]=${V[card]#/dev/dri/}
    info "display: connected connector ${V[connector]} on ${V[card]}"
  else
    warn "no connected display found (plug the TV in, or type the connector name)"
    ask V_CONN "HDMI/DP connector name (e.g. DP-3, HDMI-A-1)" "" ; V[connector]=${V_CONN:-DP-3}
    V[card]=card1
  fi
  [ -e /dev/dri/card0 ] || [ -e /dev/dri/card1 ] || die "no DRM device (/dev/dri): this needs a GPU with a display output"
  # RAM and disk
  local ram_gb free_gb
  ram_gb=$(awk '/MemTotal/{printf "%d", $2/1048576}' /proc/meminfo)
  free_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
  info "RAM ${ram_gb} GB, free on / ${free_gb} GB"
  [ "$ram_gb" -ge 8 ] || warn "reference box has 13 GB RAM; below 8 GB the live TV and voice will be unreliable"
  [ "$free_gb" -ge 20 ] || die "need at least 20 GB free on / (Waydroid image + apps); have ${free_gb} GB"
  # Network: uplink, addresses
  local dev gw src
  dev=$(ip -4 route show default | awk '{print $5; exit}')
  gw=$(ip -4 route show default | awk '{print $3; exit}')
  src=$(ip -4 -o addr show dev "$dev" | awk '{print $4; exit}')
  [ -n "$dev" ] && [ -n "$src" ] || die "no default route: connect the host to the LAN first"
  V[uplink_if]=$dev; V[gateway]=$gw; V[host_ip]=${src%/*}
  V[lan_cidr]=$(python3 -c 'import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)' "$src")
  if [ -d "/sys/class/net/$dev/wireless" ] || [ -d "/sys/class/net/$dev/phy80211" ]; then V[wireless]=1; else V[wireless]=0; fi
  info "uplink $dev (wireless=${V[wireless]}), host ${V[host_ip]}, gateway $gw, LAN ${V[lan_cidr]}"
  if command -v curl >/dev/null && ! curl -fsI --max-time 10 https://github.com >/dev/null 2>&1; then
    warn "github.com not reachable: downloads (Waydroid image, yt-dlp, whisper model) will fail"
  fi
}

# ---------- values (asked once, placeholders filled from them) ----------
gather_values() {
  step "Values"
  local v
  ask V_HOST "Host LAN address (the TV box, where phones connect)" "${TV_HOST_IP:-${V[host_ip]}}"; V[host_ip]=$V_HOST
  ask V_GW "Router / gateway address" "${GATEWAY_IP:-${V[gateway]}}"; V[gateway]=$V_GW
  ask V_LAN "LAN subnet (CIDR)" "${LAN_CIDR:-${V[lan_cidr]}}"; V[lan_cidr]=$V_LAN
  ask V_HOSTNAME "Name the remote answers to (no public DNS needed)" "${TV_HOSTNAME:-tvbox.home.arpa}"; V[hostname]=$V_HOSTNAME
  V[android_ip]=${ANDROID_IP:-0.0.0.0}   # read from waydroid after the first boot (core); remote refuses 0.0.0.0
  V[vpn_router]=${VPN_ROUTER_IP:-}
  V[ssid]=${WIFI_SSID:-}; V[pin]=${AIRPLAY_PIN:-}
  V[tv_sink]=""
  if [[ " $MODULES " == *" remote "* ]]; then
    V[admin_ip]=${ADMIN_PC_IP:-}
    while true; do
      ask V_ADMIN "Admin PC LAN address (the only machine allowed to use adb and the HDMI viewer)" "${V[admin_ip]}"
      if valid_ip "$V_ADMIN"; then V[admin_ip]=$V_ADMIN; break; fi
      [ "$YES" = 1 ] && die "ADMIN_PC_IP must be set for the remote module (e.g. ADMIN_PC_IP=192.168.10.9)"
      warn "not an IPv4 address: $V_ADMIN"
    done
  else
    V[admin_ip]=${ADMIN_PC_IP:-}
  fi
  for v in host_ip gateway lan_cidr hostname admin_ip android_ip; do
    case ${V[$v]} in *'|'*|*'&'*|*' '*|*'\'*) die "value for $v contains an illegal character";; esac
  done
  info "host ${V[host_ip]} gateway ${V[gateway]} LAN ${V[lan_cidr]} remote name ${V[hostname]} admin ${V[admin_ip]:-none}"
}

fill() {  # stdin -> stdout with __TOKEN__ placeholders replaced by detected/answered values
  sed -e "s|__TV_HOST_IP__|${V[host_ip]}|g" -e "s|__ADMIN_PC_IP__|${V[admin_ip]:-}|g" \
      -e "s|__LAN_CIDR__|${V[lan_cidr]}|g" -e "s|__GATEWAY_IP__|${V[gateway]}|g" \
      -e "s|__TV_HOSTNAME__|${V[hostname]}|g" -e "s|__ANDROID_IP__|${V[android_ip]}|g" \
      -e "s|__VPN_ROUTER_IP__|${V[vpn_router]:-}|g" -e "s|__WIFI_SSID__|${V[ssid]:-}|g" \
      -e "s|__AIRPLAY_PIN__|${V[pin]:-}|g"
}

deploy() {  # deploy <kit-relative path>: fill, back up a changed file, install to /<path>, record it
  local rel=$1 dst="/$1" src="$SRC/files/$1" mode=0644 tmp
  [[ $rel == usr/local/bin/* ]] && mode=0755
  [ -f "$src" ] || die "kit file missing: files/$rel"
  say "  deploy /$rel"
  [ "$DRY" = 1 ] && return 0
  tmp="$WORK/$(echo "$rel" | tr / _)"
  fill < "$src" > "$tmp"
  case "$rel" in
    etc/tv/weston.ini) sed -i "s|^name=.*|name=${V[connector]}|" "$tmp" ;;
    usr/local/bin/tvshot|usr/local/bin/tv-hdmi-stream) sed -i "s|/dev/dri/card[0-9]*|/dev/dri/${V[card]}|g" "$tmp" ;;
    etc/tv/env) [ -n "${V[tv_sink]:-}" ] && sed -i "s|^TV_SINK=.*|TV_SINK=${V[tv_sink]}|" "$tmp" ;;
  esac
  if grep -qE '__[A-Z][A-Z_]+__' "$tmp"; then
    die "unfilled placeholder in $rel: $(grep -oE '__[A-Z_]+__' "$tmp" | sort -u | tr '\n' ' ')"
  fi
  mkdir -p "$(dirname "$dst")"
  if [ -f "$dst" ] && ! cmp -s "$tmp" "$dst"; then cp -a "$dst" "$dst.tvbox-bak-$(date +%Y%m%d%H%M%S)"; fi
  install -m "$mode" "$tmp" "$dst"
  mkdir -p "$MDIR"; grep -qxF "$dst" "$MDIR/$CUR.list" 2>/dev/null || echo "$dst" >> "$MDIR/$CUR.list"
}

deploy_list() {  # deploy_list <module> ; adds the wireless extras when the uplink is WiFi
  local rel extra=""
  [ "${V[wireless]:-0}" = 1 ] && extra=$(files_of wireless)
  for rel in $(files_of "$1") $extra; do deploy "$rel"; done
}

reload_units() { run systemctl daemon-reload; }

disable_units() {  # for uninstall: stop + disable every unit recorded for this module
  local f
  [ -f "$MDIR/$1.list" ] || return 0
  while read -r f; do
    case "$f" in
      /etc/systemd/system/*.service|/etc/systemd/system/*.timer)
        run systemctl disable --now "$(basename "$f")" || true ;;
    esac
  done < "$MDIR/$1.list"
}

record_state() {
  [ "$DRY" = 1 ] && return 0
  mkdir -p "$STATE_DIR"; touch "$STATE"
  sed -i "/^$1 /d" "$STATE"; echo "$1 $VERSION $(date -Is)" >> "$STATE"
}
is_installed() { grep -q "^$1 " "$STATE" 2>/dev/null; }
need() { is_installed "$1" || [ "$DRY" = 1 ] || die "module $1 is required first (add it to --modules)"; }

# ---------- repository and kernel prerequisites (core) ----------
fix_pve_repos() {
  command -v pveversion >/dev/null 2>&1 || { info "not a Proxmox host: repository fix skipped"; return 0; }
  local node f
  node=$(hostname -s)
  if pvesh get "/nodes/$node/subscription" --output-format json 2>/dev/null | grep -q '"status":"Active"'; then
    info "Proxmox subscription active: enterprise repositories left enabled"
  else
    for f in /etc/apt/sources.list.d/pve-enterprise.sources /etc/apt/sources.list.d/ceph.sources; do
      [ -f "$f" ] || continue
      grep -q '^Enabled: no' "$f" && continue
      say "  disabling $f (no subscription, would fail with 401)"
      [ "$DRY" = 1 ] && continue
      cp -a "$f" "$f.tvbox-bak"; sed -i '1i Enabled: no' "$f"
    done
  fi
  if ! grep -rqs 'pve-no-subscription' /etc/apt/sources.list.d /etc/apt/sources.list 2>/dev/null; then
    say "  adding pve-no-subscription repository"
    [ "$DRY" = 1 ] && return 0
    cat > /etc/apt/sources.list.d/proxmox.sources <<'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
  fi
}

install_waydroid_pkg() {
  if command -v waydroid >/dev/null 2>&1; then info "waydroid already installed"; return 0; fi
  say "  adding the Waydroid apt repository"
  [ "$DRY" = 1 ] && return 0
  curl -fsSL https://repo.waydro.id/waydroid.gpg -o /usr/share/keyrings/waydroid.gpg \
    || die "cannot fetch the Waydroid repository key (check the key URL in the Waydroid docs)"
  echo "deb [signed-by=/usr/share/keyrings/waydroid.gpg] https://repo.waydro.id/ trixie main" > /etc/apt/sources.list.d/waydroid.list
  apt-get update -qq >>"$LOG" 2>&1
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq waydroid >>"$LOG" 2>&1 || die "apt install waydroid failed (see $LOG)"
}

kernel_modules() {
  say "  kernel modules: binder_linux uinput (persisted in /etc/modules-load.d/tvbox.conf)"
  [ "$DRY" = 1 ] && return 0
  printf '%s\n' binder_linux uinput > /etc/modules-load.d/tvbox.conf
  for m in binder_linux uinput; do modprobe "$m" >>"$LOG" 2>&1 || warn "modprobe $m failed (built in, or missing from this kernel)"; done
  [ -e /dev/uinput ] || warn "/dev/uinput missing: the phone mouse will not work"
}

# ---------- module: core ----------
install_core() {
  CUR=core
  step "Module core"
  fix_pve_repos
  run apt-get update -qq
  DEBIAN_FRONTEND=noninteractive run apt-get install -y -qq $CORE_PKGS
  install_waydroid_pkg
  kernel_modules
  mkdir -p /etc/tv/tls /usr/local/share/tv-remote /var/tmp/tv-media /var/tmp/tvdiag /var/log/tv-weston
  touch /var/log/tv-remote.log /var/log/tv-split.log
  deploy_list core
  reload_units
  run systemctl start tv-weston tv-pipewire-pulse tv-wireplumber
  detect_tv_sink
  if [ ! -f /var/lib/waydroid/images/system.img ]; then
    step "Waydroid image (several GB, 10-30 minutes)"
    confirm "Download and initialise the Android TV 13 image now?" y || die "stopped before Waydroid init"
    run waydroid init -f -c https://waydroid-atv.github.io/ota/system -v https://waydroid-atv.github.io/ota/vendor -r lineage -s GAPPS
  else
    info "Waydroid already initialised (images present): keeping it"
  fi
  if [ -f /var/lib/waydroid/lxc/waydroid/config_nodes ]; then
    run sed -i '/sys\/kernel\/debug/d' /var/lib/waydroid/lxc/waydroid/config_nodes
  fi
  run /usr/local/bin/waydroid-no-debugfs.sh
  deploy var/lib/waydroid/waydroid_base.prop
  reload_units
  run systemctl enable --now waydroid-container
  run systemctl enable --now tv-android tv-android-heal.timer tv-weston-watch
  if [ "$DRY" = 0 ]; then
    if wait_boot; then info "Android booted"; else warn "Android did not report boot in 10 min (see journalctl -u tv-android)"; fi
    detect_android_ip
  fi
}

detect_tv_sink() {
  [ "$DRY" = 1 ] && return 0
  local s
  s=$(pactl -s unix:/run/tv/pulse/native list short sinks 2>/dev/null | awk '$2 ~ /hdmi/ {print $2; exit}')
  if [ -n "$s" ]; then
    V[tv_sink]=$s; info "HDMI sink: $s"
    sed -i "s|^TV_SINK=.*|TV_SINK=$s|" /etc/tv/env
    run systemctl restart tv-wireplumber
  else
    warn "no HDMI audio sink found yet: check 'pactl list short sinks' and set TV_SINK in /etc/tv/env"
  fi
}

wait_boot() {
  local i
  for i in $(seq 1 60); do
    [ "$(timeout 15 waydroid shell -- getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] && return 0
    sleep 10
  done
  return 1
}

detect_android_ip() {
  local ip
  ip=$(waydroid status 2>/dev/null | grep -i 'ip address' | awk -F': *' '{print $2}' | tr -d '\r ')
  if valid_ip "$ip" && [ "$ip" != "${V[android_ip]}" ]; then
    info "Android container address is $ip (kit default ${V[android_ip]}): using it"
    V[android_ip]=$ip
  fi
}

# ---------- module: remote ----------
install_remote() {
  CUR=remote
  step "Module remote"
  need core
  if [ "$DRY" = 0 ] && [ "${V[android_ip]}" = 0.0.0.0 ]; then
    die "Android container address unknown: start the session (waydroid session start), then re-run --modules remote"
  fi
  deploy_list remote
  reload_units
  run systemctl enable --now tv-vol-pin.timer; run systemctl enable --now tv-remote
  if [ -f /root/admin-adbkey.pub ]; then authorize_adb_key; else
    info "adb: copy the admin PC's ~/.android/adbkey.pub to /root/admin-adbkey.pub, then re-run with --modules remote"
  fi
  warn "the adb LAN rule and the adb drop-in apply when tv-android restarts (this interrupts a film, so it is not done here)"
  run systemctl daemon-reload
}

authorize_adb_key() {
  local keys=/root/.local/share/waydroid/data/misc/adb/adb_keys
  [ "$DRY" = 1 ] && return 0
  [ -f "$keys" ] || { warn "adb_keys not found yet (start the session once)"; return 0; }
  grep -qxF "$(cat /root/admin-adbkey.pub)" "$keys" 2>/dev/null || cat /root/admin-adbkey.pub >> "$keys"
  timeout 20 waydroid shell -- sh -c 'chown system:shell /data/misc/adb/adb_keys; chmod 640 /data/misc/adb/adb_keys; restorecon /data/misc/adb/adb_keys; stop adbd; start adbd' >>"$LOG" 2>&1 || true
  info "admin PC key authorised (adb may reconnect in a few seconds)"
}

# ---------- module: live-tv ----------
install_live_tv() {
  CUR=live-tv
  step "Module live-tv"
  need core; need remote
  if [ ! -x /usr/local/bin/yt-dlp ]; then
    say "  yt-dlp (standalone build from the GitHub release)"
    run curl -fL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
    run chmod 755 /usr/local/bin/yt-dlp
  fi
  deploy_list live-tv
  reload_units
  run systemctl enable --now tv-channels-extra.timer
  if [ "$DRY" = 0 ] && [ ! -s /etc/tv/turkiye.m3u ]; then
    confirm "Build the channel list now? (probes about 100 streams, takes minutes; do it when nobody is watching)" y \
      && run timeout 1500 /usr/local/bin/tv-channels.py --write || warn "channel list not built; run /usr/local/bin/tv-channels.py --write later"
  fi
}

# ---------- module: voice ----------
install_voice() {
  CUR=voice
  step "Module voice"
  need core; need remote
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq build-essential cmake
  if [ ! -x /opt/tv-voice/whisper.cpp/build/bin/whisper-server ]; then
    run git clone --depth 1 https://github.com/ggml-org/whisper.cpp /opt/tv-voice/whisper.cpp
    run cmake -S /opt/tv-voice/whisper.cpp -B /opt/tv-voice/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release
    run cmake --build /opt/tv-voice/whisper.cpp/build -j2 --config Release --target whisper-server
  fi
  mkdir -p /opt/tv-voice/models
  local model=/opt/tv-voice/models/ggml-small-q5_1.bin
  if [ ! -s "$model" ] || [ "$(stat -c %s "$model" 2>/dev/null || echo 0)" -lt 150000000 ]; then
    run curl -fL https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin -o "$model"
  fi
  deploy_list voice
  reload_units
  run systemctl enable --now tv-whisper tv-voice
}

# ---------- module: keyboard ----------
install_keyboard() {
  CUR=keyboard
  step "Module keyboard"
  need core
  local t missing=""
  for t in javac java aapt2 zipalign apksigner keytool; do command -v "$t" >/dev/null 2>&1 || missing="$missing $t"; done
  if [ -n "$missing" ]; then
    warn "missing build tools:$missing (apt packages: openjdk/zipalign/apksigner/aapt2, names differ per release; see docs/06)"
    [ "$DRY" = 1 ] || die "keyboard needs the Android build tools; install them and re-run (--modules keyboard)"
  fi
  [ -f /opt/tv-voice/android/android.jar ] || { warn "missing /opt/tv-voice/android/android.jar (Android platform jar)"; [ "$DRY" = 1 ] || die "place the Android platform jar there and re-run"; }
  local ks=/root/tv-keys/kanallar.jks
  if [ "$DRY" = 0 ] && [ ! -f "$ks" ]; then
    mkdir -p /root/tv-keys; umask 077
    openssl rand -hex 16 > /root/tv-keys/kanallar.pass
    keytool -genkeypair -keystore "$ks" -storetype PKCS12 -storepass "$(cat /root/tv-keys/kanallar.pass)" \
      -alias tvbox -keyalg RSA -keysize 2048 -validity 10950 -dname "CN=TV Klavye, O=waydroid-tv-box" >>"$LOG" 2>&1
    info "signing key created in /root/tv-keys (keep it; back it up)"
  fi
  if [ "$DRY" = 0 ]; then
    local bdir="$WORK/klavye"; rm -rf "$bdir"; cp -a "$SRC/android/klavye" "$bdir"
    sh "$SRC/android/klavye/build.sh" "$bdir" >>"$LOG" 2>&1 || die "klavye build failed (see $LOG)"
    set -a; . /etc/tv/env; set +a
    timeout 300 waydroid app install "$bdir/klavye.apk" >>"$LOG" 2>&1 || die "waydroid app install failed (is the session running?)"
    echo "org.tvbox.klavye" > "$MDIR/keyboard.pkg"
  else
    say "+ build klavye.apk and waydroid app install"
  fi
  run timeout 30 waydroid shell -- sh -c 'ime enable org.tvbox.klavye/.KlavyeIME; settings put secure default_input_method org.tvbox.klavye/.KlavyeIME'
  info "TV Klavye is the default input method: check it on a text field before the family uses it"
}

# ---------- module: guard ----------
install_guard() {
  CUR=guard
  step "Module guard"
  need core
  mkdir -p /var/lib/tv-guard /var/log
  deploy_list guard
  reload_units
  run /usr/local/bin/tv-net-isolate.sh
  run systemctl enable --now tv-net-isolate.timer tv-guard.timer
  info "tv-guard needs its baseline (/var/lib/tv-guard/baseline.json) once the remote is up; see docs/15"
}

# ---------- module: backup ----------
install_backup() {
  CUR=backup
  step "Module backup"
  need core
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq lxc rsync
  mkdir -p /var/lib/tv-backup
  deploy_list backup
  reload_units
  run systemctl enable --now tv-backup.timer
}

# ---------- verify (one line per check; the module passes when all pass) ----------
check() {
  local label=$1; shift
  if [ "$DRY" = 1 ]; then say "  (dry) $label"; return 0; fi
  if "$@" >/dev/null 2>&1; then say "  PASS $label"; return 0; fi
  say "  FAIL $label"; return 1
}
verify_module() {
  local m=$1 fails=0
  step "Verify $m"
  case "$m" in
    core)
      check "tv-weston active" systemctl is-active --quiet tv-weston || fails=$((fails+1))
      check "tv-wireplumber active" systemctl is-active --quiet tv-wireplumber || fails=$((fails+1))
      check "one weston process" test "$(pgrep -xc weston)" = 1 || fails=$((fails+1))
      check "Android booted" test "$(timeout 15 waydroid shell -- getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 || fails=$((fails+1))
      check "software video decode (media.sf.hwaccel=0)" test "$(timeout 15 waydroid shell -- getprop media.sf.hwaccel 2>/dev/null | tr -d '\r')" = 0 || fails=$((fails+1))
      check "power key ignored (logind)" sh -c 'busctl get-property org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager HandlePowerKey | grep -q ignore' || fails=$((fails+1))
      ;;
    remote)
      check "tv-remote active" systemctl is-active --quiet tv-remote || fails=$((fails+1))
      check "remote answers on :8090" sh -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/)\" = 200 ]" || fails=$((fails+1))
      ;;
    live-tv)
      check "channel list has entries" sh -c 'grep -q EXTINF /etc/tv/turkiye.m3u' || fails=$((fails+1))
      check "channel refresh timer active" systemctl is-active --quiet tv-channels-extra.timer || fails=$((fails+1))
      ;;
    voice)
      check "tv-whisper active" systemctl is-active --quiet tv-whisper || fails=$((fails+1))
      check "tv-voice active" systemctl is-active --quiet tv-voice || fails=$((fails+1))
      ;;
    keyboard)
      check "TV Klavye installed" timeout 30 waydroid shell -- pm path org.tvbox.klavye || fails=$((fails+1))
      ;;
    guard)
      check "isolation timer active" systemctl is-active --quiet tv-net-isolate.timer || fails=$((fails+1))
      check "TV-ISOLATE chain present" sh -c 'iptables -w 5 -S TV-ISOLATE | grep -q RETURN' || fails=$((fails+1))
      check "tv-guard timer active" systemctl is-active --quiet tv-guard.timer || fails=$((fails+1))
      ;;
    backup)
      check "backup timer active" systemctl is-active --quiet tv-backup.timer || fails=$((fails+1))
      ;;
  esac
  if [ "$fails" = 0 ]; then RESULTS+=("$m: PASS"); else RESULTS+=("$m: $fails check(s) FAILED"); fi
}

# ---------- uninstall ----------
uninstall_module() {
  local m=$1
  step "Uninstall $m"
  [ "$m" = core ] && { confirm "Removing core stops the TV box entirely. Continue?" n || die "stopped"; }
  disable_units "$m"
  if [ "$m" = keyboard ] && [ -f "$MDIR/keyboard.pkg" ]; then
    run timeout 60 waydroid app remove "$(cat "$MDIR/keyboard.pkg")" || true
  fi
  if [ -f "$MDIR/$m.list" ]; then
    while read -r f; do
      if [ "$DRY" = 1 ]; then say "  would remove $f"; else rm -f "$f"; say "  removed $f"; fi
    done < "$MDIR/$m.list"
    [ "$DRY" = 1 ] || rm -f "$MDIR/$m.list"
  fi
  reload_units
  [ "$DRY" = 1 ] || sed -i "/^$m /d" "$STATE" 2>/dev/null || true
  say "Module $m removed. Apt packages and the Waydroid image are kept."
}

# ---------- arguments and selection ----------
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --modules) MODULES=${2:-}; shift 2 ;;
      --modules=*) MODULES=${1#*=}; shift ;;
      --yes|-y) YES=1; shift ;;
      --dry-run) DRY=1; shift ;;
      --uninstall) UNINSTALL=${2:-}; shift 2 ;;
      --uninstall=*) UNINSTALL=${1#*=}; shift ;;
      -h|--help) usage ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
  done
  if [ "$MODULES" = all ]; then MODULES=$ALL_MODULES; fi
  if [ -n "$UNINSTALL" ]; then case " $ALL_MODULES " in *" $UNINSTALL "*) ;; *) echo "unknown module $UNINSTALL" >&2; exit 2;; esac; fi
}

choose_modules() {
  if [ -n "$MODULES" ]; then return 0; fi
  if [ "$YES" = 1 ] || [ ! -r /dev/tty ]; then MODULES="core $DEFAULT_OPT"; return 0; fi
  step "Choose modules (core is always installed)"
  local m sel="core"
  for m in remote live-tv voice keyboard guard backup; do
    local d=n; [[ " $DEFAULT_OPT " == *" $m "* ]] && d=y
    say "  $m: ${DESC[$m]}"
    confirm "  install $m?" "$d" && sel="$sel $m"
  done
  MODULES=$sel
}

resolve_modules() {
  local m dep out="core" changed=1
  MODULES=" core $(echo "$MODULES" | tr ',' ' ') "
  while [ "$changed" = 1 ]; do
    changed=0
    for m in $MODULES; do
      dep=${NEEDS[$m]:-}
      if [ -n "$dep" ] && [[ " $MODULES " != *" $dep "* ]]; then MODULES="$MODULES $dep"; say "[info] $m needs $dep: adding it"; changed=1; fi
    done
  done
  for m in $ALL_MODULES; do [[ " $MODULES " == *" $m "* ]] && out="$out $m"; done
  MODULES=$(echo $out | tr -s ' ')
  for m in $MODULES; do case " $ALL_MODULES " in *" $m "*) ;; *) die "unknown module: $m";; esac; done
}

main() {
  parse_args "$@"
  mkdir -p "$(dirname "$LOG")" "$STATE_DIR" "$MDIR"; touch "$LOG"
  say "waydroid-tv-box installer $VERSION  ($(date -Is))$([ "$DRY" = 1 ] && echo '  [DRY RUN]')"
  locate_source
  if [ -n "$UNINSTALL" ]; then
    [ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || die "run as root"
    uninstall_module "$UNINSTALL"; exit 0
  fi
  preflight
  choose_modules
  resolve_modules
  kit_check "$MODULES"
  gather_values
  step "Plan"
  say "  modules: $MODULES   image: Android TV 13 (LineageOS 20 + GApps)   log: $LOG"
  confirm "Proceed?" y || die "stopped by user"
  local m
  for m in core remote live-tv voice keyboard guard backup; do
    [[ " $MODULES " == *" $m "* ]] || continue
    "install_${m//-/_}"
    [ "$DRY" = 1 ] || record_state "$m"
    verify_module "$m"
  done
  step "Summary"
  for m in "${RESULTS[@]}"; do say "  $m"; done
  say "Log: $LOG"
  if [ "$DRY" = 0 ]; then
    say "Next: open http://${V[host_ip]}:8090 on a phone on the LAN. Run 'bash install.sh --uninstall <module>' to remove a module."
  fi
}

main "$@"
