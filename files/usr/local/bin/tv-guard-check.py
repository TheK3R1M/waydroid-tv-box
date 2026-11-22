#!/usr/bin/env python3
"""tv-guard: watches Android (Waydroid) for bot-like behaviour every minute and reacts.

Checks (all against a calm baseline; normal TV use never reaches these):
  - upload from Android > UPLOAD_MBIT sustained over the minute   (DDoS / data theft)
  - firewall TV-GUARD drops (bad ports / connection flood) grew        (scan, spam, flood)
  - Android conntrack entries > MAX_CONN or distinct destinations > MAX_DST
  - new listening ports on the host (vs. the baseline taken at install)
  - new executable ELF files in Android user data outside app dirs
Reaction ("quarantine", proven safe: only touches the suspect apps, never the TV stack):
  force-stop + disable the WATCH apps (pm disable-user), log to /var/log/tv-guard.log and the remote's log so
  the family sees it. Undo: adb shell pm enable <pkg>.
"""
import json, os, re, subprocess, time

STATE = "/var/lib/tv-guard/state.json"
BASE = "/var/lib/tv-guard/baseline.json"
LOG = "/var/log/tv-guard.log"
REMOTE_LOG = "/var/log/tv-remote.log"
ANDROID_IP = "__ANDROID_IP__"
ADB = ["adb", "-s", ANDROID_IP + ":5555"]
WATCH = []          # apps that get quarantined on an anomaly
UPLOAD_MBIT = 15
MAX_CONN, MAX_DST = 1500, 250
DATA = "/root/.local/share/waydroid/data"
# ELF files that are known and expected (checked by hand): NETFLY's 360-Jiagu packer libs, byte-identical to the
# copies inside the APK . Anything else that appears is still treated as an anomaly.
ELF_ALLOW = {
    "5653c9f2d92a77fbeaeb0685e4e865edb1cdf51cac1564ba6e92b853884648a4",
    "30b7ecf0a8df7bf5f9e2b104e6a0584f7b6fad1b658cbe349d1076c72959ffe8",
    "614e232fb247595d0518e8dbd8b26601e73ad5d27d18ff0059588125af943046",
    "8afe2db847cf08df851e281e920a188e52dce804951386c4d2d981cf628a75dc",
}


def sh(cmd, t=20):
    try:
        return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=t).stdout
    except Exception:
        return ""


def log(msg, remote=False):
    line = time.strftime("%F %T") + "\t" + msg
    open(LOG, "a").write(line + "\n")
    if remote:
        open(REMOTE_LOG, "a", encoding="utf-8").write(f"{time.strftime('%F %T')}\tGüvenlik\t-\t{msg}\n")


def fw_drops():
    n = 0
    for l in sh("iptables -L TV-GUARD -v -x -n").splitlines():
        if " DROP " in f" {l} ":
            try:
                n += int(l.split()[0])
            except Exception:
                pass
    return n


def listen_ports():
    out = set()
    for l in sh("ss -H -tuln").splitlines():
        p = l.split()
        if len(p) >= 5:
            out.add(p[0] + " " + re.sub(r"%\w+", "", p[4]))
    return sorted(out)


def new_elfs(since):
    hits = []
    for root, dirs, files in os.walk(DATA):
        if any(x in root for x in ("/app/", "/dalvik-cache", "/data/app", "/system/", "com.google.android.gms/app_chimera")):
            continue
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
                if st.st_mtime < since or st.st_size < 4096:
                    continue
                with open(p, "rb") as fh:
                    if fh.read(4) == b"\x7fELF":
                        import hashlib
                        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
                        if h not in ELF_ALLOW:          # may be mid-extraction: re-hash once after it settles
                            time.sleep(4)
                            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
                        if h not in ELF_ALLOW:
                            hits.append(p)
            except Exception:
                pass
    return hits[:10]


def quarantine(reason):
    done = []
    for pkg in WATCH:
        if pkg in sh(ADB + ["shell", "pm", "list", "packages", pkg]):
            sh(ADB + ["shell", "am", "force-stop", pkg]); sh(ADB + ["shell", "pm", "disable-user", "--user", "0", pkg])
            done.append(pkg)
    log(f"ANORMAL: {reason} -> önlem: {', '.join(done) or 'izlenen uygulama yok'} durduruldu/devre dışı", remote=True)


def main():
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    now = time.time()
    rx = int(open("/sys/class/net/waydroid0/statistics/rx_bytes").read())   # host rx on waydroid0 = Android upload
    drops = fw_drops()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    if not os.path.exists(BASE):
        json.dump({"ports": listen_ports(), "t": now}, open(BASE, "w"))
        log("baseline alındı")
    base = json.load(open(BASE))
    problems = []
    if st:
        dt = max(1, now - st["t"])
        mbit = (rx - st["rx"]) * 8 / dt / 1e6
        if mbit > UPLOAD_MBIT:
            problems.append(f"Android {mbit:.0f} Mbit/s yükleme yapıyor")
        if drops - st["drops"] > 20:
            problems.append(f"güvenlik duvarı {drops - st['drops']} şüpheli bağlantı engelledi (tarama/flood)")
    ct = sh(f"conntrack -L -s {ANDROID_IP} -o extended 2>/dev/null")
    conns = [l for l in ct.splitlines() if "src=" in l]
    dsts = {m.group(1) for l in conns for m in [re.search(r"dst=(\S+)", l)] if m}
    if len(conns) > MAX_CONN or len(dsts) > MAX_DST:
        problems.append(f"Android {len(conns)} bağlantı / {len(dsts)} farklı hedef açmış")
    # new listening sockets; UDP high ports (client sockets of avahi/chrony etc.) are noise
    newp = [p for p in listen_ports() if p not in base["ports"]
            and not (p.startswith("udp") and re.search(r":\d{5}$", p))]
    if newp:
        problems.append("hostta yeni dinleyen port: " + ", ".join(newp[:5]))
    elfs = new_elfs(st.get("t", now - 60) - 5)
    if elfs:
        problems.append("Android verisinde yeni çalıştırılabilir dosya: " + ", ".join(e.replace(DATA, "") for e in elfs[:3]))
    st = {"t": now, "rx": rx, "drops": drops, "conns": len(conns), "dsts": len(dsts)}
    json.dump(st, open(STATE, "w"))
    if problems:
        quarantine("; ".join(problems))
    elif int(now) % 3600 < 60:
        log(f"ok conns={len(conns)} dsts={len(dsts)} drops={drops}")


if __name__ == "__main__":
    main()
