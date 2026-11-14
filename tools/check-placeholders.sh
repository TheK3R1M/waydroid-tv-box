#!/usr/bin/env bash
# Fails if any __PLACEHOLDER__ token is still present in config/script files (run after fill-placeholders.sh).
# Skips *.md (documentation mentions tokens on purpose), .git and this tools/ folder.
DIR="${1:?usage: $0 <dir>}"
if grep -rnE '__[A-Z_]+__' "$DIR" --exclude-dir=tools --exclude-dir=.git --exclude='*.md'; then
  echo "UNFILLED placeholders above"; exit 1
fi
echo "OK: no placeholders left in $DIR (config/script files)"
