#!/usr/bin/env python3
"""tv-why HH:MM [YYYY-MM-DD]  -  everything about the TV around one moment (±3 min).

Prints, in time order per source: blackbox lines (state, SNAP, CRASH, MARK), the remote's action log,
the journal of tv-android / tv-weston / tv-remote / tv-blackbox / tv-heal.
"""
import datetime
import re
import subprocess
import sys

BLACKBOX = "/var/log/tv-blackbox.log"
REMOTE = "/var/log/tv-remote.log"
WINDOW = datetime.timedelta(minutes=3)


def main():
    if len(sys.argv) < 2 or not re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", sys.argv[1]):
        print("usage: tv-why HH:MM [YYYY-MM-DD]")
        sys.exit(2)
    hms = sys.argv[1] if sys.argv[1].count(":") == 2 else sys.argv[1] + ":00"
    day = sys.argv[2] if len(sys.argv) > 2 else datetime.date.today().isoformat()
    center = datetime.datetime.strptime(f"{day} {hms}", "%Y-%m-%d %H:%M:%S")
    lo, hi = center - WINDOW, center + WINDOW
    lo_s, hi_s = lo.strftime("%Y-%m-%d %H:%M:%S"), hi.strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== window {lo_s} .. {hi_s} ===")

    def inwin(line):
        return lo_s <= line[:19] <= hi_s and re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", line)

    print("\n--- blackbox (state / SNAP / CRASH / MARK) ---")
    try:
        for line in open(BLACKBOX, encoding="utf-8", errors="replace"):
            if inwin(line):
                print(line.rstrip())
    except FileNotFoundError:
        print("(no blackbox log)")

    print("\n--- remote action log ---")
    try:
        for line in open(REMOTE, encoding="utf-8", errors="replace"):
            if inwin(line):
                print(line.rstrip().replace("\t", " | "))
    except FileNotFoundError:
        print("(no remote log)")

    print("\n--- journal ---")
    units = ["-u", "tv-android", "-u", "tv-weston", "-u", "tv-remote", "-u", "tv-blackbox"]
    for extra in ([], ["-t", "tv-heal"]):
        cmd = ["journalctl", "--no-pager", "-o", "short-iso", "--since", lo_s, "--until", hi_s] + (extra or units)
        out = subprocess.run(cmd, capture_output=True, text=True).stdout.rstrip()
        print(out if out else "(nothing)")


if __name__ == "__main__":
    main()
