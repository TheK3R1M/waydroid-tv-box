#!/usr/bin/env python3
"""Refresh the sanitized copies in files/ and android/ from a live tv-remote source tree.
Usage: tools/sync-remote.py <tv-remote repo dir>
Owner-specific strings -> placeholders come from the UNTRACKED file tools/sanitize-map.local
(one rule per line: <exact text><TAB><replacement>; '#' lines are comments). Longest rules run first.
Copies: server/tv-remote.py, ui/index.html, host/*.service|*.timer -> files/etc/systemd/system/,
host/* (other) -> files/usr/local/bin/, android/{asistan,kanallar,klavye} -> android/ (text + assets).
Box-only files (SKIP) are never copied. Run tools/privacy-scan.sh afterwards; it must print OK."""
import os, sys, shutil

src = sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__)
here = os.path.dirname(os.path.abspath(__file__))
kit = os.path.dirname(here)
rules = []
mp = os.path.join(here, "sanitize-map.local")
if not os.path.exists(mp):
    sys.exit("missing tools/sanitize-map.local (owner strings -> placeholders); refusing to copy unsanitized files")
for line in open(mp, encoding="utf-8"):
    line = line.rstrip("\n")
    if line and not line.startswith("#") and "\t" in line:
        a, b = line.split("\t", 1)
        rules.append((a, b))
rules.sort(key=lambda r: -len(r[0]))

# Box-only: contains app names that must not be published (kit privacy scan rejects them).
SKIP = {"voice-apps.json", "__pycache__"}
NEVER_EXT = {".apk", ".jks", ".pass", ".keystore", ".class", ".dex", ".pyc", ".o"}
NEVER_NAMES = {"klavye.apk", "kanallar.apk", "asistan.apk"}


def sanitize(text):
    for a, b in rules:
        text = text.replace(a, b)
    return text


def write_file(s_path, d_path):
    os.makedirs(os.path.dirname(d_path), exist_ok=True)
    raw = open(s_path, "rb").read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        shutil.copyfile(s_path, d_path)  # binary (png etc.) copied as-is
        return
    open(d_path, "w", encoding="utf-8", newline="\n").write(sanitize(text))


n = 0
# 1) server + UI
PAIRS = {"server/tv-remote.py": "files/usr/local/bin/tv-remote.py",
         "server/tvsched.py": "files/usr/local/bin/tvsched.py",
         "server/tv-rec.py": "files/usr/local/bin/tv-rec.py",
         "ui/index.html": "files/usr/local/share/tv-remote/index.html"}
for s, d in PAIRS.items():
    write_file(os.path.join(src, s), os.path.join(kit, d)); n += 1
    print("synced", d)

# 2) host scripts and units
hdir = os.path.join(src, "host")
for f in sorted(os.listdir(hdir)):
    p = os.path.join(hdir, f)
    if f in SKIP or os.path.isdir(p) or os.path.splitext(f)[1] in NEVER_EXT:
        continue
    if f.endswith((".service", ".timer")):
        d = os.path.join(kit, "files/etc/systemd/system", f)
    else:
        d = os.path.join(kit, "files/usr/local/bin", f)
    write_file(p, d); n += 1
    print("synced", os.path.relpath(d, kit))

# 3) Android APK sources (no build outputs, no keys)
adir = os.path.join(src, "android")
for app in sorted(os.listdir(adir)):
    base = os.path.join(adir, app)
    if not os.path.isdir(base):
        continue
    for root, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if x not in {"build", "out", "bin", "obj", "__pycache__"}]
        for f in files:
            if os.path.splitext(f)[1] in NEVER_EXT or f in NEVER_NAMES:
                continue
            s_path = os.path.join(root, f)
            rel = os.path.relpath(s_path, adir)
            write_file(s_path, os.path.join(kit, "android", rel)); n += 1
    print("synced android/" + app)

print(f"done: {n} files")
