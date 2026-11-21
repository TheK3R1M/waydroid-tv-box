#!/usr/bin/env python3
"""TV blackbox: one compact state line every 3 s, Android crash lines every 30 s, a full snapshot on every
state change. Lets 'what happened at HH:MM' be answered with tv-why.

  tv-blackbox.py              run as the service (tv-blackbox.service)
  tv-blackbox.py --snap       print a full snapshot line (no write)
  tv-blackbox.py --mark TEXT  append a marker line + full snapshot (used by the remote's 'Sorun bildir')

Log: /var/log/tv-blackbox.log. Kept 7 days and capped at ~50 MB (trimmed in place every 5 min).
"""
import json
import os
import re
import socket
import subprocess
import sys
import time

LOG = "/var/log/tv-blackbox.log"
REMOTE_LOG = "/var/log/tv-remote.log"
ADB = "__ANDROID_IP__:5555"
MPV_SOCK = "/run/tv/mpv-split.sock"
KEEP_SECS = 7 * 86400
MAX_BYTES = 50 * 2**20
TICK = 3
CRASH_EVERY = 30
CRASH_GREP = "FATAL|ANR|has died|Process.*crashed|failed to attach"


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def sh(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception as e:
        return f"ERR:{type(e).__name__}"


def adb(cmd, timeout=5):
    return sh(["adb", "-s", ADB, "shell", cmd], timeout)


def mpv_pid():
    out = sh(["pgrep", "-x", "mpv"]).split()
    return out[0] if out else None


def mpv_get(prop):
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(1)
        c.connect(MPV_SOCK)
        c.sendall((json.dumps({"command": ["get_property", prop]}) + "\n").encode())
        data = b""
        while b'"error"' not in data:
            chunk = c.recv(65536)
            if not chunk:
                break
            data += chunk
        c.close()
        for line in data.decode("utf-8", "ignore").splitlines():
            j = json.loads(line)
            if "error" in j:
                return j.get("data") if j["error"] == "success" else None
    except Exception:
        pass
    return None


def focus_pkg():
    out = adb("dumpsys window | grep -m1 mCurrentFocus", 6)
    m = re.search(r" ([A-Za-z0-9_.]+)/", out)
    if m:
        return m.group(1)
    return "adb-err" if not out.strip() or out.startswith("ERR") else "none"


def container_state():
    out = sh(["waydroid", "status"], 8)
    m = re.search(r"Container:\s*(\S+)", out)
    return m.group(1) if m else "?"


def weston_alive():
    return "1" if sh(["pgrep", "-x", "weston"]).strip() else "0"


def load_free():
    try:
        load = open("/proc/loadavg").read().split()[0]
    except Exception:
        load = "?"
    free = "?"
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                free = str(int(line.split()[1]) // 1024)
    except Exception:
        pass
    return load, free


def state_tuple(pid, pkg, cont, weston):
    return (pid is not None, pkg, cont, weston)


def line_state(ts, pid, pos, pkg, cont, weston, load, free):
    return (f"{ts} mpv={pid or '-'} pos={'%.1f' % pos if isinstance(pos, (int, float)) else '-'} "
            f"focus={pkg} wd={cont} weston={weston} load={load} free={free}MB")


def snapshot(reason):
    ts = now()
    pid = mpv_pid()
    pos = mpv_get("time-pos") if pid else None
    pkg = focus_pkg()
    cont = container_state()
    weston = weston_alive()
    load, free = load_free()
    ime = adb("settings get secure default_input_method", 5).strip() if pkg != "adb-err" else "?"
    svc = " ".join(f"{u}={sh(['systemctl', 'is-active', u]).strip()}"
                   for u in ("tv-android", "tv-weston", "tv-remote"))
    rlast = ""
    try:
        rlast = open(REMOTE_LOG, encoding="utf-8").read().rstrip("\n").splitlines()[-1]
    except Exception:
        pass
    return (f"{ts} SNAP[{reason}] mpv={pid or '-'} pos={'%.1f' % pos if isinstance(pos, (int, float)) else '-'} "
            f"focus={pkg} wd={cont} weston={weston} ime={ime} {svc} load={load} free={free}MB "
            f"remote_last=[{rlast}]")


def append(line):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line.rstrip("\n") + "\n")
    except Exception as e:
        print(f"log write failed: {e}", file=sys.stderr)


def trim():
    """Keep 7 days and at most MAX_BYTES (newest kept)."""
    try:
        if not os.path.exists(LOG):
            return
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - KEEP_SECS))
        lines = open(LOG, encoding="utf-8", errors="replace").readlines()
        keep = [l for l in lines if l[:19] >= cutoff]
        while sum(len(l) for l in keep) > MAX_BYTES and len(keep) > 1000:
            keep = keep[len(keep) // 4:]
        if len(keep) != len(lines):
            tmp = LOG + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(keep)
            os.replace(tmp, LOG)
    except Exception as e:
        print(f"trim failed: {e}", file=sys.stderr)


def crash_since(last):
    """New crash-buffer and FATAL/ANR lines since `last` ('MM-DD HH:MM:SS.mmm'). Returns (lines, newest_ts)."""
    out = adb(f"logcat -d -v time -b crash -T '{last}' 2>/dev/null | tail -n 200; "
              f"logcat -d -v time -b main -T '{last}' 2>/dev/null | grep -E '{CRASH_GREP}' | tail -n 200", 15)
    fresh, newest = [], last
    for raw in out.splitlines():
        ts = raw[:18]
        if not re.match(r"\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}", ts):
            continue
        if ts < last:
            continue
        if re.search(r"^--------- beginning", raw):
            continue
        fresh.append(raw)
        if ts > newest:
            newest = ts
    return fresh, newest


def main_loop():
    append(f"{now()} BLACKBOX start (tick {TICK}s, crash check {CRASH_EVERY}s)")
    prev = None
    last_crash = time.strftime("%m-%d %H:%M:%S.000", time.localtime(time.time() - 5))
    seen_at_last = set()
    next_crash = 0
    n = 0
    cont = "?"
    while True:
        t0 = time.time()
        try:
            ts = now()
            pid = mpv_pid()
            pos = mpv_get("time-pos") if pid else None
            pkg = focus_pkg()
            if n % 5 == 0:                 # `waydroid status` is a heavy python call: refresh every 15 s
                cont = container_state()
            weston = weston_alive()
            load, free = load_free()
            append(line_state(ts, pid, pos, pkg, cont, weston, load, free))
            st = state_tuple(pid, pkg, cont, weston)
            if prev is not None and st != prev:
                append(snapshot("change"))
            prev = st

            if t0 >= next_crash:
                next_crash = t0 + CRASH_EVERY
                fresh, newest = crash_since(last_crash)
                for raw in fresh:
                    if raw[:18] == last_crash and raw in seen_at_last:
                        continue
                    append(f"{ts} CRASH {raw}")
                if newest != last_crash:
                    seen_at_last = set()
                last_crash = newest
                seen_at_last.update(r for r in fresh if r[:18] == newest)
            n += 1
            if n % 100 == 0:
                trim()
        except Exception as e:
            append(f"{now()} BLACKBOX error {type(e).__name__}: {e}")
            time.sleep(5)
        time.sleep(max(0.5, TICK - (time.time() - t0)))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--snap":
        print(snapshot("manual"))
    elif len(sys.argv) > 2 and sys.argv[1] == "--mark":
        append(f"{now()} MARK {sys.argv[2]}")
        append(snapshot(sys.argv[2]))
    else:
        main_loop()
