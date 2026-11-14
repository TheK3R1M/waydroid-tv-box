#!/usr/bin/env bash
# Privacy gate for the kit. Fails (exit 1) if the repo contains anything that identifies the owner, the home
# network, a device, a secret, or a piracy app. Run before every commit and before publishing.
#   Usage: tools/privacy-scan.sh [dir]        (default: the kit root = parent of this tools/ folder)
# Allowed on purpose: the box name "Spike", __PLACEHOLDER__ tokens, <angle-bracket> examples, RFC 5737 /
# documentation ranges such as 10.0.0.x and 192.168.10.x that are not on the owner's network.
set -uo pipefail
ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
fail=0

# name|extended-regex|case (i = ignore case)
RULES=(
  "home LAN address|192\.168\.1\.[0-9]+|"
  "Waydroid container address (the default gateway 192.168.240.1 is allowed)|192\.168\.240\.(1[0-9]+|[02-9][0-9]*)|"
  "CGNAT / VPN address|100\.92\.[0-9]+|"
  "MAC address|([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}|"
  "WiFi SSID literal|SSID[[:space:]]*[=:][[:space:]]*[\"']?[A-Za-z0-9]|i"
  "WiFi name tr-*|(^|[^A-Za-z])tr-[0-9A-Za-z]{3,}|"
  "UUID (app/session token)|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|i"
  "secret / token / PIN value|(token|secret|passwd|password|psk|api[_-]?key|pin)[[:space:]]*[=:][[:space:]]*[\"']?[A-Za-z0-9_/+-]{3,}|i"
  "private key / certificate material|BEGIN [A-Z ]*PRIVATE KEY|"
  "Windows home path|C:[/\\]Users[/\\]|i"
  "piracy / stream-scraper app|stremio|i"
  "piracy / stream-scraper app|cloudstream|i"
)
# Owner-specific words (names, domains, device names, local app ids) live in an UNTRACKED file next to this
# script so the public repo never contains them: tools/privacy-patterns.local, same "label|regex|flags" format.
LOCAL="$(dirname "$0")/privacy-patterns.local"
if [ -f "$LOCAL" ]; then
  while IFS= read -r l; do [ -n "$l" ] && [ "${l#\#}" = "$l" ] && RULES+=("$l"); done < "$LOCAL"
else
  echo "note: $LOCAL missing - only generic rules run (create it with your own names/domains/devices)"
fi

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
for rule in "${RULES[@]}"; do
  IFS='|' read -r label re flags <<<"$rule"
  # re may itself contain '|' (alternation): rebuild it from the fields after the label
  re="${rule#*|}"; re="${re%|*}"; flags="${rule##*|}"
  opts=(-rIn -E --exclude-dir=.git --exclude=privacy-scan.sh --exclude=privacy-patterns.local --exclude=sanitize-map.local)
  [ "$flags" = i ] && opts+=(-i)
  grep "${opts[@]}" -e "$re" "$ROOT" 2>/dev/null \
    | grep -v -- "$SELF" \
    | grep -v -E '__[A-Z][A-Z_]*__|<[A-Za-z_ ]+>' > "$tmp" || true
  if [ -s "$tmp" ]; then
    fail=1
    echo "FAIL [$label]"
    sed 's/^/    /' "$tmp" | cut -c1-220 | head -20
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "PRIVACY SCAN FAILED: remove or placeholder the items above (see docs/13-agent-rules.md rule 10)."
  exit 1
fi
echo "OK: privacy scan clean in $ROOT ($(find "$ROOT" -path "$ROOT/.git" -prune -o -type f -print | wc -l) files, $(echo ${#RULES[@]}) rules)"
