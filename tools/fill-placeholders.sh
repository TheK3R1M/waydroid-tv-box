#!/usr/bin/env bash
# Fill the __PLACEHOLDER__ tokens in a COPY of the kit (never in the original).
#
# Usage:
#   cp -a <kit> <kit-filled>                       # work on the copy only
#   TV_HOST_IP=... ADMIN_PC_IP=... LAN_CIDR=... GATEWAY_IP=... TV_HOSTNAME=... ANDROID_IP=... \
#   [VPN_ROUTER_IP=...] [WIFI_SSID=...] [AIRPLAY_PIN=...] \
#   tools/fill-placeholders.sh <kit-filled>
#
# Required: TV_HOST_IP ADMIN_PC_IP LAN_CIDR GATEWAY_IP TV_HOSTNAME ANDROID_IP
# Optional: VPN_ROUTER_IP (subnet router for VPN phones; empty = none), WIFI_SSID, AIRPLAY_PIN
# Then it runs check-placeholders.sh, which fails if any __TOKEN__ is still present.
set -euo pipefail
DIR="${1:?usage: $0 <dir>}"
for v in TV_HOST_IP ADMIN_PC_IP LAN_CIDR GATEWAY_IP TV_HOSTNAME ANDROID_IP; do
  [ -n "${!v:-}" ] || { echo "missing env $v"; exit 2; }
done
: "${VPN_ROUTER_IP:=}" "${WIFI_SSID:=__WIFI_SSID__}" "${AIRPLAY_PIN:=__AIRPLAY_PIN__}"

# escape a value for use as a sed replacement with the '|' delimiter
esc() { printf '%s' "$1" | sed -e 's/[&|\]/\&/g'; }

find "$DIR" -type f -not -path '*/.git/*' -print0 | xargs -0 sed -i \
  -e "s|__TV_HOST_IP__|$(esc "$TV_HOST_IP")|g" \
  -e "s|__ADMIN_PC_IP__|$(esc "$ADMIN_PC_IP")|g" \
  -e "s|__LAN_CIDR__|$(esc "$LAN_CIDR")|g" \
  -e "s|__GATEWAY_IP__|$(esc "$GATEWAY_IP")|g" \
  -e "s|__TV_HOSTNAME__|$(esc "$TV_HOSTNAME")|g" \
  -e "s|__ANDROID_IP__|$(esc "$ANDROID_IP")|g" \
  -e "s|__VPN_ROUTER_IP__|$(esc "$VPN_ROUTER_IP")|g" \
  -e "s|__WIFI_SSID__|$(esc "$WIFI_SSID")|g" \
  -e "s|__AIRPLAY_PIN__|$(esc "$AIRPLAY_PIN")|g"

"$(dirname "$0")/check-placeholders.sh" "$DIR"
