#!/usr/bin/env python3
"""Refresh the sanitized copies in files/ from a live tv-remote source tree.
Usage: tools/sync-remote.py <tv-remote repo dir>
Owner-specific strings -> placeholders come from the UNTRACKED file tools/sanitize-map.local
(one rule per line: <exact text><TAB><replacement>; '#' lines are comments). Longest rules run first.
Run tools/privacy-scan.sh afterwards; it must print OK before you commit."""
import os, sys
src = sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__)
here = os.path.dirname(os.path.abspath(__file__)); kit = os.path.dirname(here)
rules = []
mp = os.path.join(here, "sanitize-map.local")
if not os.path.exists(mp):
    sys.exit("missing tools/sanitize-map.local (owner strings -> placeholders); refusing to copy unsanitized files")
for line in open(mp, encoding="utf-8"):
    line = line.rstrip("\n")
    if line and not line.startswith("#") and "\t" in line:
        a, b = line.split("\t", 1); rules.append((a, b))
rules.sort(key=lambda r: -len(r[0]))
PAIRS = {"server/tv-remote.py": "files/usr/local/bin/tv-remote.py",
         "ui/index.html": "files/usr/local/share/tv-remote/index.html"}
for s, d in PAIRS.items():
    t = open(os.path.join(src, s), encoding="utf-8").read()
    for a, b in rules:
        t = t.replace(a, b)
    open(os.path.join(kit, d), "w", encoding="utf-8", newline="\n").write(t)
    print("synced", d)
