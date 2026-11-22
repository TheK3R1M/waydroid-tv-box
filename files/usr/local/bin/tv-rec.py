#!/usr/bin/env python3
"""Scheduled recording worker: tv-rec.py <master_url> <out.ts> <seconds>.
Started by a transient systemd unit (systemd-run --on-calendar), so it outlives a tv-remote restart.
Picks the best <=1080p variant, prunes old recordings to the disk cap, then ffmpeg -c copy into <out>.part
and renames to <out> only when complete (the phone list shows .ts files only)."""
import os
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tvsched  # noqa: E402

URL_RE = re.compile(r"^https?://[\w\-.:/?=&%~+@,;]+$")


def main(argv):
    if len(argv) != 4:
        print("usage: tv-rec.py <url> <out.ts> <seconds>", file=sys.stderr)
        return 2
    url, out, secs = argv[1], argv[2], int(argv[3])
    if not URL_RE.match(url) or not out.startswith(tvsched.REC_DIR + os.sep) or not out.endswith(".ts"):
        print("refused: bad url or path", file=sys.stderr)
        return 2
    secs = max(10, min(secs, 4 * 3600))
    src = url
    try:
        txt = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                     timeout=10).read(400000).decode("utf-8", "ignore")
        src = tvsched.best_variant_from_text(txt, url) or url
    except Exception as e:                      # master unreachable: try the URL as given (ffmpeg retries too)
        print("variant lookup failed:", e, file=sys.stderr)
    os.makedirs(tvsched.REC_DIR, exist_ok=True)
    removed = tvsched.prune(tvsched.REC_DIR, tvsched.REC_CAP, reserve=2 * 1024 ** 3)   # ~4 Mb/s x 1 h headroom
    if removed:
        print("pruned:", len(removed), file=sys.stderr)
    part = out + ".part"
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning", "-reconnect", "1",
           "-reconnect_streamed", "1", "-reconnect_delay_max", "5", "-i", src, "-t", str(secs),
           "-map", "0", "-c", "copy", "-f", "mpegts", "-y", part]
    rc = subprocess.run(cmd).returncode
    if os.path.exists(part) and os.path.getsize(part) > 0:
        os.replace(part, out)
    elif os.path.exists(part):
        os.remove(part)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
