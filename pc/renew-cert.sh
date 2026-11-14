#!/usr/bin/env bash
# Renew the web-remote certificate (Let's Encrypt, DNS-01 via lego and a zone-scoped DNS token) and push it to the TV host.
# Runs on the ADMIN PC (git-bash). lego renews only when due; tv-remote re-reads the cert file on change (no restart).
# Prints one status line. Silent cron use: pipe to a notifier if you want alerts.
#
# Local config (never in git):
#   TV_CERT_NAME  full name, default __TV_HOSTNAME__
#   TV_CERT_DIR   lego output dir (keep it OUT of the repo), default $HOME/tv-cert
#   TV_CERT_ENV   file with a line  CF_DNS_API_TOKEN=...  (zone-scoped token; keep it OUT of the repo)
#   LEGO_BIN      path to the lego binary
# Owner decision required first: a certificate writes the name into public CT logs (docs/10-security.md §10.7).
set -euo pipefail
NAME="${TV_CERT_NAME:-__TV_HOSTNAME__}"
D="${TV_CERT_DIR:-$HOME/tv-cert}"
ENVF="${TV_CERT_ENV:-$HOME/.config/tv-cert/dns.env}"
LEGO="${LEGO_BIN:-lego}"
HOST="${TV_HOST:-pve-tv}"
CRT="$D/certificates/$NAME.crt"
KEY="$D/certificates/$NAME.key"

[ -f "$ENVF" ] || { echo "no DNS token file at $ENVF"; exit 2; }
before=$(sha1sum "$CRT" 2>/dev/null | cut -c1-12 || echo none)
export CF_DNS_API_TOKEN=$(grep '^CF_DNS_API_TOKEN=' "$ENVF" | cut -d= -f2- | tr -d '\r"')
"$LEGO" run -a -d "$NAME" --dns cloudflare --dns.resolvers 8.8.8.8:53 --path "$D" --no-random-sleep \
  --log.format text --log.level warn 2>&1 | grep -iv token || true
unset CF_DNS_API_TOKEN
after=$(sha1sum "$CRT" | cut -c1-12)
remote=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" 'sha1sum /etc/tv/tls/fullchain.pem | cut -c1-12' 2>/dev/null || echo unreachable)
if [ "$remote" != "$after" ] && [ "$remote" != "unreachable" ]; then
  scp -q "$KEY" "$HOST:/etc/tv/tls/privkey.pem.new"
  scp -q "$CRT" "$HOST:/etc/tv/tls/fullchain.pem.new"
  ssh -o BatchMode=yes "$HOST" 'chmod 600 /etc/tv/tls/privkey.pem.new; mv /etc/tv/tls/privkey.pem.new /etc/tv/tls/privkey.pem; mv /etc/tv/tls/fullchain.pem.new /etc/tv/tls/fullchain.pem'
  remote=$after
fi
exp=$(openssl x509 -enddate -noout -in "$CRT" | cut -d= -f2)
echo "$NAME cert: local=$after (was $before) tv-host=$remote expires=$exp"
