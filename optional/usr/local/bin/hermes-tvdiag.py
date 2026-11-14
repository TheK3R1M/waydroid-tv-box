#!/usr/bin/env python3
# Hermes read-only TV freeze diagnosis (2026-11-08 12:00-22:00). Touches nothing but its own logs.
import socket, json, time, subprocess, threading, urllib.request, urllib.parse, os, datetime
S = "/run/tv/mpv-split.sock"
D = "/var/tmp/tvdiag"; os.makedirs(D, exist_ok=True)
END = datetime.datetime(2026, 11, 8, 22, 0).timestamp()
FALLBACK = "https://tv-trt1.medya.trt.com.tr/master_1080.m3u8"
PROPS = ["time-pos", "avsync", "demuxer-cache-duration", "paused-for-cache", "frame-drop-count", "path", "idle-active"]
state = {"url": None}

def get(p):
    try:
        s = socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect(S)
        s.sendall((json.dumps({"command": ["get_property", p]}) + "\n").encode())
        b = b""
        while b"\n" not in b:
            c = s.recv(4096)
            if not c: break
            b += c
        s.close()
        for l in b.split(b"\n"):
            if l.strip():
                d = json.loads(l)
                if "error" in d: return d.get("data")
    except Exception:
        return None

def playing():
    return subprocess.run(["pgrep", "-x", "mpv"], capture_output=True).returncode == 0

def rx():
    return int(open("/sys/class/net/wlp3s0/statistics/rx_bytes").read())

def media_playlist(url):
    pl = urllib.request.urlopen(url, timeout=8).read().decode(errors="replace")
    if "#EXT-X-STREAM-INF" in pl:
        lines = pl.splitlines()
        best = None
        for i, l in enumerate(lines):
            if l.startswith("#EXT-X-STREAM-INF"):
                h = 0
                if "RESOLUTION=" in l:
                    try: h = int(l.split("RESOLUTION=")[1].split(",")[0].split("x")[1])
                    except Exception: pass
                if h <= 1080 and (best is None or h > best[0]) and i + 1 < len(lines):
                    best = (h, lines[i + 1].strip())
        if best:
            return media_playlist(urllib.parse.urljoin(url, best[1]))
    return url, pl

def prober():
    seen = set(); out = open(f"{D}/seg.log", "a")
    while time.time() < END:
        if not playing():
            time.sleep(10); continue
        u = state["url"]
        if not u or not u.startswith("http") or "m3u8" not in u:
            u = FALLBACK
        try:
            murl, pl = media_playlist(u)
            segs = [l.strip() for l in pl.splitlines() if l.strip() and not l.startswith("#")]
            for sname in segs[-2:]:
                full = urllib.parse.urljoin(murl, sname)
                if full in seen: continue
                seen.add(full); t = time.time()
                try:
                    r = urllib.request.urlopen(full, timeout=20)
                    cl = int(r.headers.get("Content-Length", 0) or 0); n = len(r.read())
                    out.write(json.dumps({"t": round(t, 1), "seg": sname[-24:], "cl": cl, "got": n, "sec": round(time.time() - t, 2)}) + "\n")
                except Exception as e:
                    out.write(json.dumps({"t": round(t, 1), "seg": sname[-24:], "err": str(e)[:100], "sec": round(time.time() - t, 2)}) + "\n")
                out.flush()
        except Exception as e:
            out.write(json.dumps({"t": round(time.time(), 1), "plerr": str(e)[:100], "url": u[-60:]}) + "\n"); out.flush()
        if len(seen) > 500: seen.clear()
        time.sleep(3)

def monitor():
    out = open(f"{D}/mpv.log", "a"); last = rx()
    while time.time() < END:
        t = time.time()
        if not playing():
            last = rx(); time.sleep(10); continue
        r = rx()
        row = {p: get(p) for p in PROPS}
        state["url"] = row.get("path")
        row["path"] = (row["path"] or "")[-50:]
        gw = subprocess.run(["ping", "-c1", "-W1", "__GATEWAY_IP__"], capture_output=True).returncode
        try:
            w = open("/proc/net/wireless").read().splitlines()[-1].split()
            wl = {"q": w[2], "lvl": w[3], "beacon": w[-2]}
        except Exception:
            wl = {}
        out.write(json.dumps({"t": round(t, 1), "rxKB": (r - last) // 1024, "gw": gw, **wl, **row}) + "\n"); out.flush()
        last = r
        time.sleep(max(0, 1 - (time.time() - t)))

threading.Thread(target=prober, daemon=True).start()
monitor()
