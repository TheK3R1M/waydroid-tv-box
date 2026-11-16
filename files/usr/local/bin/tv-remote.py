#!/usr/bin/env python3
"""Spike TV web remote: http://<spike>:8090 and https://__TV_HOSTNAME__ (LAN-only, whitelisted actions,
no shell injection). v16: phone mouse (touchpad + gyro), HTTPS (gyro needs a secure page), latest-wins channel
changes, cached HLS variants, instant split side switch."""
import base64, http.server, ipaddress, json, os, re, socket, ssl, subprocess, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs

PORT = 8090
HTTPS_PORT = 443
TLS_CERT = "/etc/tv/tls/fullchain.pem"   # __TV_HOSTNAME__ (Let's Encrypt, renewed from the admin PC)
TLS_KEY = "/etc/tv/tls/privkey.pem"
VERSION_FILE = "/usr/local/share/tv-remote/VERSION"   # git commit written by deploy.sh


def version():
    try:
        return open(VERSION_FILE).read().strip()[:40]
    except Exception:
        return "?"
# Only these names may be used to reach the remote: blocks DNS-rebinding (attacker domain -> LAN IP).
ALLOWED_HOSTS = {"__TV_HOSTNAME__", "__TV_HOST_IP__", "localhost", "127.0.0.1"}
ALLOWED_NETS = [ipaddress.ip_network(n) for n in ("__LAN_CIDR__", "127.0.0.0/8")]
SINK = "alsa_output.pci-0000_04_00.1.hdmi-stereo-extra3"
NORMAL_VOL = 85
MAX_VOL = 150          # >100 = software boost (may distort)
PENV = dict(os.environ, XDG_RUNTIME_DIR="/run/tv", PULSE_SERVER="unix:/run/tv/pulse/native")
KEYS = {"up": 19, "down": 20, "left": 21, "right": 22, "ok": 23, "back": 4, "home": 3, "menu": 82,
        "play": 85, "rew": 89, "ff": 90, "settings": 176, "del": 67, "search": 84, "apps": 312, "enter": 66}
CHANNELS_FILE = "/etc/tv/turkiye.m3u"
KODI = "org.xbmc.kodi/.Splash"
SPLIT_APPS = {"tvkodi": None,  # filled from current channel
              "web": "org.mozilla.firefox/.App"}
BROWSER = "org.mozilla.firefox/org.mozilla.fenix.IntentReceiverActivity"   # replaces TV Bro (hard to drive with the remote)
_ch = {"i": 0}
TR = str.maketrans("çğıöşüÇĞİÖŞÜâîûÂÎÛ", "cgiosuCGIOSUaiuAIU")


EXTRA_FILE = "/etc/tv/extra.m3u"     # official/FAST channels from the community list (tv-channels-extra.py, daily)
_chcache = {"key": None, "v": []}


def _read_m3u(path):
    out, name = [], None
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("#EXTINF"):
                name = re.sub(r"\s*\[(Not 24/7|Geo-blocked)\]", "", line.split(",")[-1]).strip()
            elif line and not line.startswith("#") and name:
                out.append((name, line)); name = None
    except Exception:
        pass
    return out


def channels():
    """Curated list first (numbers stay stable), then extra channels whose name isn't already there."""
    try:
        key = tuple(os.path.getmtime(f) if os.path.exists(f) else 0 for f in (CHANNELS_FILE, EXTRA_FILE))
    except Exception:
        key = None
    if key is not None and key == _chcache["key"]:
        return _chcache["v"]
    out = _read_m3u(CHANNELS_FILE)
    seen = {re.sub(r"\W|\d+p", "", n.lower()) for n, _ in out}
    for n, u in _read_m3u(EXTRA_FILE):
        k = re.sub(r"\W|\d+p", "", n.lower())
        if k not in seen:
            seen.add(k); out.append((n, u))
    _chcache.update(key=key, v=out)
    return out


def play_channel(i, windowing=None):
    chs = channels()
    if not chs:
        return False
    i %= len(chs); _ch["i"] = i
    url = chs[i][1]
    if not re.match(r"^https?://[\w\-.:/?=&%~+@,;]+$", url):
        return False
    wm = f"--windowingMode {windowing} " if windowing else ""
    return android(f"am start {wm}-a android.intent.action.VIEW -d '{url}' -t video/mp2t -n {KODI}", timeout=8)


def adb_out(cmd, timeout=8):
    try:
        return subprocess.run(["adb", "-s", ADB, "shell", cmd], capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def task_of(pkg):
    m = re.search(r"taskId=(\d+): " + re.escape(pkg), adb_out("am stack list"))
    return m.group(1) if m else None


# ---- Split screen (v10): done on the HOST with one mpv window. Android's freeform mode is broken on the
# TV build (task surfaces are never offset, everything is drawn at x=0). mpv sits on top of Android in
# Weston kiosk-shell, decodes with VAAPI and composes two sources side by side. Sound = ACTIVE side only.
MPV_SOCK = "/run/tv/mpv-split.sock"
_split = {"on": False, "mode": "single", "proc": None, "side": "left",
          "src": {"left": None, "right": None}, "lock": threading.RLock()}


def tv_env():
    env = dict(os.environ)
    try:
        for line in open("/etc/tv/env"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.replace("export ", "").strip()] = v.strip().strip('"')
    except Exception:
        pass
    env.setdefault("XDG_RUNTIME_DIR", "/run/tv")
    env.setdefault("PULSE_SERVER", "unix:/run/tv/pulse/native")
    return env


_vcache = {}            # master url -> (time, media playlist url); saves one HTTP round trip per switch
VCACHE_TTL = 600


def best_variant(url):
    hit = _vcache.get(url)
    if hit and time.time() - hit[0] < VCACHE_TTL:
        return hit[1]
    r = _best_variant(url)
    if r:
        _vcache[url] = (time.time(), r)
    return r


def _best_variant(url):
    """HLS master -> one media playlist (<=1080p) so each side contributes exactly one video track."""
    try:
        import urllib.request, urllib.parse
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            # 9 s: the turknet CDN (ATV, A Spor) regularly needs 3-6 s to answer its long DVR playlist; 5 s made
            # ATV fail to open about half the time ("ATV hep bozuk").
            txt = urllib.request.urlopen(req, timeout=9).read(400000).decode("utf-8", "ignore")
        except Exception:
            return None
        if "#EXT-X-STREAM-INF" not in txt:
            return url
        # best = highest resolution <= 1080p; variants without RESOLUTION (some CDNs) or equal height are ranked
        # by BANDWIDTH. (v16 took the FIRST such variant: Euro D / Dream Turk played their 331 kb/s rendition.)
        best, key = None, None
        lines = txt.splitlines()
        for i, l in enumerate(lines):
            if l.startswith("#EXT-X-STREAM-INF"):
                m = re.search(r"RESOLUTION=\d+x(\d+)", l)
                b = re.search(r"[^-]BANDWIDTH=(\d+)", "," + l.split(":", 1)[-1])
                h = int(m.group(1)) if m else 0
                bw = int(b.group(1)) if b else 0
                if h > 1080 or (h == 0 and bw > 9_000_000):
                    continue
                nxt = next((x for x in lines[i + 1:] if x and not x.startswith("#")), None)
                k = (h, bw)
                if nxt and (key is None or k > key):
                    best, key = nxt, k
        return urllib.parse.urljoin(url, best) if best else url
    except Exception:
        return url


def resolve(src):
    """("ch", i) | ("url", u) -> list of files: one muxed file, or [video, audio] for YouTube."""
    kind, val = src
    if kind == "ch":
        chs = channels()
        u = best_variant(chs[val % len(chs)][1])
        return [u] if u else []
    if re.search(r"(youtube\.com|youtu\.be)/", val):
        r = subprocess.run(["/usr/local/bin/yt-dlp", "-q", "--no-warnings", "--no-playlist", "-g", "-f",
                            "bv*[height<=1080][fps<=30][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720]", val],
                           capture_output=True, text=True, timeout=60)
        return [x for x in r.stdout.split() if x.startswith("http")][:2]
    u = best_variant(val) if ".m3u8" in val else val
    return [u] if u else []


def mpv_ipc(cmd, timeout=3):
    import socket
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(timeout)
        c.connect(MPV_SOCK)
        c.sendall((json.dumps({"command": cmd}) + "\n").encode())
        data = b""
        while b"\n" not in data:
            chunk = c.recv(65536)
            if not chunk:
                break
            data += chunk
        c.close()
        for line in data.decode("utf-8", "ignore").splitlines():
            j = json.loads(line)
            if "error" in j:
                return j
    except Exception as e:
        return {"error": str(e)}
    return {"error": "no reply"}


def mpv_alive():
    p = _split["proc"]
    return p is not None and p.poll() is None


def mpv_stop():
    """Close the player window and give the screen back to Android."""
    p = _split["proc"]
    _split["proc"] = None
    if p and p.poll() is None:
        mpv_ipc(["quit"], timeout=1)
        try:
            p.wait(2)
        except Exception:
            p.kill()
    android("input keyevent 224", timeout=5)   # wake Android again


def mpv_ensure():
    """ONE persistent mpv window (idle + force-window). Channel / mode changes are loadfile calls inside
    the same window, so the window never unmaps and Android can never end up on top in between."""
    if mpv_alive():
        return True
    try:
        os.unlink(MPV_SOCK)
    except Exception:
        pass
    cmd = ["mpv", "--msg-level=all=warn,cplayer=info", "--idle=yes", "--force-window=yes", "--fs", "--no-osc",
           "--no-input-default-bindings", "--cursor-autohide=always", "--background-color=#000000",
           "--hwdec=vaapi-copy", "--vo=gpu", "--gpu-context=wayland", "--ao=pulse", "--cache=yes",
           "--demuxer-readahead-secs=5", "--network-timeout=15", f"--input-ipc-server={MPV_SOCK}"]
    _log = open("/var/log/tv-split.log", "ab")
    _split["proc"] = subprocess.Popen(cmd, env=tv_env(), stdout=_log, stderr=subprocess.STDOUT)
    for _ in range(40):
        time.sleep(0.15)
        if os.path.exists(MPV_SOCK) and mpv_ipc(["get_property", "idle-active"], 1).get("error") == "success":
            break
    # Android sleeps while the player is up: no redraws behind it (they could raise Android) and less CPU
    android("input keyevent 223", timeout=5)
    return mpv_alive()


PAD = "scale=960:540:force_original_aspect_ratio=decrease,pad=960:1080:-1:-1,setsar=1,fps=25"


def split_graph():
    # both sides' sound go into one 4-channel stream; the plain `af` chain picks the half you hear, so switching
    # sides only rebuilds the audio filter (instant) instead of the whole graph (which froze the picture ~4 s)
    af = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"   # mono / 44.1k sides too
    return f"[vid1]{PAD}[l];[vid2]{PAD}[r];[l][r]hstack[vo];[aid1]{af}[a1];[aid2]{af}[a2];[a1][a2]amerge=inputs=2[ao]"


def split_af():
    if _split["mode"] != "split":
        return ""
    if (_split.get("audio") or _split["side"]) == "left":
        return "lavfi=[pan=stereo|c0=c0|c1=c1]"
    return "lavfi=[pan=stereo|c0=c2|c1=c3]"


# latest-wins: every channel/mode request takes a ticket; a request whose ticket is no longer the newest when
# it gets the lock is skipped, and a load that is waiting for its first frame gives up the lock early.
_gen = [0]
_gen_lock = threading.Lock()


def ticket():
    with _gen_lock:
        _gen[0] += 1
        return _gen[0]


def _veil(src):
    """Zapping: mpv keeps the old frame frozen while the next stream loads, which looks like a hang. Cover the
    picture like a real TV does (dark screen + what is coming) until the first new frame arrives."""
    try:
        name = src_name(src) if src[0] != "ch" else re.sub(r"\s*\(\d+p\)", "", channels()[src[1] % len(channels())][0])
        num = str(src[1] % len(channels()) + 1) if src[0] == "ch" else ""
    except Exception:
        name, num = "", ""
    L = [_rect(0, 0, 1920, 1080, "000000", 0x00, 0),
         _text(960, 470, num, 90, ACCENT, True, an=5), _text(960, 580, _ass(name), 56, "FFFFFF", True, an=5),
         _text(960, 660, "açılıyor…", 30, "9A9A9A", an=5)]
    with _ui_lock:
        _ui.update(mode="veil", until=time.time() + 20)
    _overlay(L)


def mpv_start():
    """Load the current single/split sources into the persistent window."""
    my = _gen[0]
    if _split["mode"] == "single" and mpv_alive() and _ui["mode"] in (None, "banner", "veil", "voice"):
        _veil(_split["src"]["left"])
    ok = _mpv_start(my)
    if _ui["mode"] == "veil" and (not ok or _gen[0] == my):
        ui_hide()                 # success: the caller draws the channel banner right after
    return ok


def _mpv_start(my):
    if _split["mode"] == "single":
        files = resolve(_split["src"]["left"])
        if not files:
            return False
        opts = {"lavfi-complex": ""}
    else:
        files = []
        for side in ("left", "right"):
            urls = resolve(_split["src"][side])
            if not urls:
                return False
            files += urls
        opts = {"lavfi-complex": split_graph()}
    if not mpv_ensure():
        return False
    # list options must not contain separators -> pass each external file through a separate list option
    opts = {k: v for k, v in opts.items() if v}
    if _split["mode"] == "split" and len(files) > 1:
        mpv_ipc(["set_property", "external-files", files[1:]])
        mpv_ipc(["set_property", "audio-files", []])
    else:
        mpv_ipc(["set_property", "external-files", []])
        mpv_ipc(["set_property", "audio-files", files[1:]])
    if not opts.get("lavfi-complex"):
        mpv_ipc(["set_property", "lavfi-complex", ""])
    mpv_ipc(["set_property", "af", split_af()])
    r = mpv_ipc({"name": "loadfile", "url": files[0], "flags": "replace", "index": -1,
                 "options": {k: v for k, v in opts.items() if k not in ("external-files", "audio-files")}}, timeout=5)
    if r.get("error") != "success":
        return False
    _split["busy"] = True
    try:
        for _ in range(60):          # up to ~15 s for the first frame
            time.sleep(0.25)
            if _gen[0] != my:        # a newer channel request is waiting: let it run now
                return True
            if not mpv_alive():
                return False
            if mpv_ipc(["get_property", "estimated-vf-fps"], 1).get("error") == "success":
                return True
            if mpv_ipc(["get_property", "idle-active"], 1).get("data") is True:
                return False
        return False
    finally:
        _split["busy"] = False


def _apply(change):
    """Apply a change to _split, start it; if no picture comes, restore the previous state."""
    old = (_split["mode"], _split["side"], dict(_split["src"]), _split["on"], _split.get("audio"))
    change()
    if mpv_start():
        _split["on"] = True
        _split["err"] = None
        return True
    _vcache.clear()                  # maybe a stale cached variant (rotated token): retry once with fresh ones
    if mpv_start():
        _split["on"] = True
        _split["err"] = None
        return True
    _split["mode"], _split["side"], _split["src"], was_on = old[0], old[1], old[2], old[3]
    _split["audio"] = old[4]
    _split["err"] = "Kanal açılamadı (yayın kaynağı cevap vermiyor)"
    _split["err_t"] = time.time()
    if was_on and mpv_start():
        _split["on"] = True
    else:
        _split["on"] = False
        mpv_stop()
    return False


def run_latest(fn):
    """Run a channel/mode change unless a newer one was requested meanwhile (then that one wins)."""
    my = ticket()
    with _split["lock"]:
        if my != _gen[0]:
            return True
        try:
            return fn()
        finally:
            if my == _gen[0]:            # nothing newer is queued: targets are settled
                _want["left"] = _want["right"] = None


_want = {"left": None, "right": None}   # channel index a pending request is heading to (for fast ▲▲▲)


def base_idx(side):
    w = _want.get(side)
    if w is not None:
        return w
    if not _split["on"]:
        return _ch["i"]
    cur = _split["src"].get(side)
    return cur[1] if cur and cur[0] == "ch" else _ch["i"]


def watch_single(src):
    """Full-screen channel/link in mpv (no split)."""
    def go():
        if not _split["on"]:
            android("am force-stop org.xbmc.kodi", timeout=8)

        def ch():
            _split["mode"] = "single"; _split["side"] = "left"; _split["audio"] = "left"; _split["src"]["left"] = src
        return _apply(ch)
    return run_latest(go)


_probe_pool = ThreadPoolExecutor(max_workers=6)


def split_on():
    def go():
        n = max(1, len(channels()))
        left = _split["src"]["left"] if _split["on"] and _split["src"]["left"] else ("ch", _ch["i"] % n)
        first = (left[1] + 1) % n if left[0] == "ch" else (_ch["i"] + 1) % n
        cand = [(first + k) % n for k in range(6)]
        res = list(_probe_pool.map(lambda i: bool(resolve(("ch", i))), cand))   # probe in parallel, not 6x5 s
        nxt = next((i for i, ok in zip(cand, res) if ok), first)
        android("am force-stop org.xbmc.kodi; am force-stop com.phlox.tvwebbrowser", timeout=8)

        def ch():
            _split["src"]["left"] = left
            _split["src"]["right"] = ("ch", nxt)
            # new half = channel target (the list opens next), sound stays on what you were watching
            _split["side"] = "right"; _split["audio"] = "left"; _split["mode"] = "split"
        return _apply(ch)
    return run_latest(go)


def split_focus(side):
    """Pick a half: channel target AND its sound. Instant: only the filter graph changes, streams keep playing."""
    def go():
        same = side == _split["side"] and side == _split.get("audio")
        _split["side"] = side; _split["audio"] = side
        if same or not (_split["on"] and _split["mode"] == "split"):
            return True
        r = mpv_ipc(["set_property", "af", split_af()], 5)
        if r.get("error") == "success":
            return True
        return mpv_start()
    return run_latest(go)


def split_set(src, side=None):
    def go():
        sd = side or _split["side"]

        def ch():
            _split["src"][sd] = src
        return _apply(ch)
    return run_latest(go)


def split_off(to_single=True):
    """From split -> keep the half you LISTEN to full screen. From single -> close the player (back to Android)."""
    def go():
        if to_single and _split["on"] and _split["mode"] == "split":
            src = _split["src"][_split.get("audio") or _split["side"]]
            _split["mode"] = "single"; _split["side"] = "left"; _split["audio"] = "left"; _split["src"]["left"] = src
            _split["on"] = mpv_start()
            return _split["on"]
        _split["on"] = False
        mpv_stop()
        return True
    return run_latest(go)


def src_name(s):
    if s and s[0] == "ch":
        chs = channels()
        return chs[s[1] % len(chs)][0]
    return "YouTube" if s and "youtu" in s[1] else "Video"


def split_label():
    if not _split["on"]:
        return None
    def idx(x):
        return x[1] % max(1, len(channels())) if x and x[0] == "ch" else -1
    if _split["mode"] == "single":
        return {"single": src_name(_split["src"]["left"]), "chi_left": idx(_split["src"]["left"])}
    chs = channels()
    lab = {}
    for side in ("left", "right"):
        s = _split["src"][side]
        if s and s[0] == "ch":
            lab[side] = chs[s[1] % len(chs)][0]
        else:
            lab[side] = "YouTube" if s and "youtu" in s[1] else "Video"
    return {"left": lab["left"], "right": lab["right"], "side": _split["side"], "audio": _split.get("audio") or _split["side"],
            "chi_left": idx(_split["src"]["left"]), "chi_right": idx(_split["src"]["right"])}


def _frozen():
    """Picture stuck while sound goes on: in split mode one broken stream stalls the side-by-side
    filter, video falls behind audio (avsync grows) and/or the video clock stops."""
    r = mpv_ipc(["get_property", "avsync"], 2)
    a = r.get("data") if r.get("error") == "success" else None
    # time-pos follows the (composited) video; estimated-frame-number is always 0 with lavfi-complex
    v = mpv_ipc(["get_property", "time-pos"], 2).get("data")
    last = _split.get("_lastframe")
    _split["_lastframe"] = v
    stuck = v is not None and last is not None and abs(v - last) < 0.5
    return (a is not None and abs(a) > 3.0) or stuck


def _split_watch():
    bad = 0
    while True:   # mpv died / stream ended -> back to normal TV instead of a stuck screen
        time.sleep(5)
        p = _split["proc"]
        if _split.get("busy"):
            bad = 0
            continue
        if _split["on"] and mpv_alive():
            bad = bad + 1 if _frozen() else 0
            if bad >= 2:      # ~10 s frozen -> reload the same channels (2-3 s blip)
                bad = 0
                _split["_lastframe"] = None
                with _split["lock"]:
                    ok = mpv_start()
                log_action("127.0.0.1", "görüntü donmuştu → oynatıcı otomatik yenilendi" + ("" if ok else " (BAŞARISIZ)"))
                continue
        if _split["on"] and (p is None or p.poll() is not None
                             or mpv_ipc(["get_property", "idle-active"], 2).get("data") is True):
            time.sleep(10)   # give a slow stream a moment before giving up
            if _split["on"] and (not mpv_alive() or mpv_ipc(["get_property", "idle-active"], 2).get("data") is True):
                split_off(to_single=False)


threading.Thread(target=_split_watch, daemon=True).start()


ADB_IME = "com.android.adbkeyboard/.AdbIME"
TV_IME = "com.android.inputmethod.leanback/.service.LeanbackImeService"
_ime = {"on": False, "t": 0, "lock": threading.Lock()}
# While any phone has the remote page open (it polls /state every 4 s) Android uses ADBKeyboard,
# so typing on the phone never has to switch keyboards in the middle of a search (switching closed the TV's search).
# When no phone has been seen for 25 s the TV's own on-screen keyboard comes back (for the real remote / mouse).


def phone_seen():
    # v9: no automatic keyboard switching any more (it popped the Android keyboard up and closed searches).
    # ADBKeyboard is the permanent keyboard; it is invisible, so typing is done from the phone remote.
    _ime["t"] = time.time()


def ime_on():
    """Make sure ADBKeyboard is the keyboard WITHOUT re-selecting it when it already is:
    `ime set` re-binds the keyboard and some live-TV apps close their open search box when that happens."""
    with _ime["lock"]:
        if not _ime["on"]:
            cur = adb_out("settings get secure default_input_method", timeout=5).strip()
            if cur == ADB_IME:
                _ime["on"] = True
            else:
                _ime["on"] = android(f"ime enable {ADB_IME} >/dev/null; ime set {ADB_IME} >/dev/null")
    return _ime["on"]


def ime_off():
    with _ime["lock"]:
        _ime["on"] = False
        return android(f"ime set {TV_IME} >/dev/null")


def type_full(text, prev=None):
    """Mirror the phone field into the focused TV field (Unicode OK, incl. Turkish letters).
    v17: with `prev` (what the phone sent last time) only the change is typed: deleted letters as DEL keys,
    new letters appended. Clearing + retyping the whole field (v16) emptied the field for a moment on every
    letter, and some live-TV apps close their search box when its field gets empty -> 'first letter only'."""
    phone_seen()
    if not _ime["on"]:
        ime_on()
    if prev is None:
        b64 = base64.b64encode(text.encode("utf-8")).decode()
        cmd = "am broadcast -a ADB_CLEAR_TEXT >/dev/null"
        if text:
            cmd += f"; am broadcast -a ADB_INPUT_B64 --es msg {b64} >/dev/null"
        return android(cmd)
    n = 0
    while n < min(len(prev), len(text)) and prev[n] == text[n]:
        n += 1
    dels, add = len(prev) - n, text[n:]
    cmds = ["am broadcast -a ADB_INPUT_CODE --ei code 67 >/dev/null"] * min(dels, 300)
    if add:
        cmds.append(f"am broadcast -a ADB_INPUT_B64 --es msg {base64.b64encode(add.encode('utf-8')).decode()} >/dev/null")
    return android("; ".join(cmds), timeout=3 + 0.15 * len(cmds)) if cmds else True


_typed = {}   # (ip, device) -> what this phone already typed into the TV field (server-side, so even an old
              # cached page that sends only {text} gets diff typing instead of clear+retype)


def type_key(ip):
    return (ip, getattr(_req, "dev", ""))


def type_log(ip, text, prev, src):
    try:
        with open("/var/log/tv-remote-type.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%F %T')}\t{ip}\t{getattr(_req, 'dev', '')}\t{src}\tprev={prev!r}\ttext={text!r}\n")
        if os.path.getsize("/var/log/tv-remote-type.log") > 200_000:
            os.remove("/var/log/tv-remote-type.log")
    except Exception:
        pass


def type_clear():
    phone_seen()
    if not _ime["on"]:
        ime_on()
    return android("am broadcast -a ADB_CLEAR_TEXT >/dev/null")


def current_action():
    """imeOptions action of the most recent real text field (inputType != 0)."""
    out = adb_out("dumpsys input_method")
    action = 0
    for m in re.finditer(r"inputType=0x([0-9a-f]+) imeOptions=0x([0-9a-f]+)", out):
        if int(m.group(1), 16) != 0:
            action = int(m.group(2), 16) & 0xff
    return action


def ime_confirm():
    """Press the field's own action (Search/Go/Done...) exactly like the on-screen keyboard's action key."""
    phone_seen()
    action = current_action()
    if 2 <= action <= 7:
        return android(f"am broadcast -a ADB_EDITOR_CODE --ei code {action} >/dev/null")
    return android("am broadcast -a ADB_INPUT_CODE --ei code 66 >/dev/null")


_ime["on"] = False  # ime_on() below makes sure ADBKeyboard is set once at start


MEDIA_HOST = "/var/tmp/tv-media"
MEDIA_DEV = "/sdcard/Movies/Telefon"
MIME = {".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska", ".webm": "video/webm",
        ".avi": "video/x-msvideo", ".3gp": "video/3gpp", ".m4v": "video/mp4", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
        ".heic": "image/heic", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}


def open_on_tv(path_on_device, mime):
    return android(f"am start -a android.intent.action.VIEW -d 'file://{path_on_device}' -t {mime} -n {KODI}", timeout=8)


def prune(keep=6):
    files = sorted((os.path.join(MEDIA_HOST, f) for f in os.listdir(MEDIA_HOST)), key=os.path.getmtime)
    for f in files[:-keep]:
        name = os.path.basename(f)
        try:
            os.remove(f)
        except Exception:
            pass
        android(f"rm -f '{MEDIA_DEV}/{name}'")


def open_link(url):
    url = url.strip()
    try:                                    # add-on links ("<scheme>://.../manifest.json") -> the app that installs them
        addon = next(((k, x["addon_scheme"]) for k, x in _nlu().APP_EXTRA.items() if x.get("addon_scheme")), None)
    except Exception:
        addon = None
    if addon and re.match(r"^[a-z]+://[\w\-.:/?=&%~+@,;#!]+$", url) and (
            url.startswith(addon[1] + "://") or re.search(r"/manifest\.json(\?|$)", url)):
        su = re.sub(r"^https?://", addon[1] + "://", url)
        name = _nlu().APPS[addon[0]][2]
        return android(f"am start -a android.intent.action.VIEW -d '{su}' {_nlu().APPS[addon[0]][0]}", timeout=8), f"{name} eklentisi"
    if not re.match(r"^https?://[\w\-.:/?=&%~+@,;#!]+$", url):
        return False, "geçersiz link"
    if re.search(r"(youtube\.com|youtu\.be)/", url):
        return android(f"am start -a android.intent.action.VIEW -d '{url}' org.smarttube.stable", timeout=8), "YouTube"
    if re.search(r"\.(m3u8|mp4|mkv|webm|mov|ts|mp3)(\?|$)", url, re.I):
        return android(f"am start -a android.intent.action.VIEW -d '{url}' -t video/* -n {KODI}", timeout=8), "Kodi"
    return android(f"am start -a android.intent.action.VIEW -d '{url}' -n {BROWSER}", timeout=8), "Tarayıcı"
APPS = {"youtube": "org.smarttube.stable/com.liskovsoft.smartyoutubetv2.tv.ui.main.SplashActivity",
        "tv": "com.example.livetv/.MainActivity",     # placeholder: set a legal live-TV app of your choice, or delete
        "web": "org.mozilla.firefox/.App"}
BROWSER = "org.mozilla.firefox/org.mozilla.fenix.IntentReceiverActivity"   # replaces TV Bro (hard to drive with the remote)
APP_NAMES = {"org.tvbox.kanallar": "Kanallar", "org.smarttube.stable": "YouTube", "com.example.livetv": "Canlı TV",
             "com.phlox.tvwebbrowser": "Tarayıcı (eski)", "org.mozilla.firefox": "Tarayıcı", "com.spocky.projengmenu": "Ana ekran",
             "org.xbmc.kodi": "Canlı TV (Kodi)", "com.android.tv.settings": "Ayarlar"}
ADB = "__ANDROID_IP__:5555"
DEVICES_FILE = "/etc/tv/devices.json"     # mac -> name, exported from the home router (see docs/07, docs/09)
LOG_FILE = "/var/log/tv-remote.log"
# Phones on the family's headscale/tailscale network reach the TV through this subnet router, so they all
# arrive with its IP (shown as the router's name). Those phones name themselves once on the page (X-TV-Device header).
ROUTER_IPS = {"__VPN_ROUTER_IP__"}
_req = threading.local()
LOG_KEEP = 3000

_lock = threading.Lock()
_sh = None
_focus = {"t": 0, "v": ""}
_last = {"who": "", "what": "", "t": 0}
_seq = [0]


def shell():
    """Persistent adb shell with a reader thread; each command is acked with a marker line."""
    global _sh
    if _sh is None or _sh.poll() is not None:
        subprocess.run(["adb", "connect", ADB], capture_output=True, timeout=10)
        p = subprocess.Popen(["adb", "-s", ADB, "shell"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, bufsize=1)
        p.acks = set(); p.cv = threading.Condition()

        def reader(proc=p):
            for line in proc.stdout:
                m = re.match(r"__ACK(\d+)__", line.strip())
                if m:
                    with proc.cv:
                        proc.acks.add(int(m.group(1))); proc.cv.notify_all()
        threading.Thread(target=reader, daemon=True).start()
        _sh = p
    return _sh


def android(cmd, timeout=3.0):
    """Run a command in Android; return True only if Android acknowledged it. Reconnect on stall."""
    global _sh
    with _lock:
        for _ in range(2):
            try:
                p = shell(); _seq[0] += 1; n = _seq[0]
                p.stdin.write(f"{cmd}; echo __ACK{n}__\n"); p.stdin.flush()
                with p.cv:
                    if p.cv.wait_for(lambda: n in p.acks, timeout=timeout):
                        p.acks.discard(n); return True
            except Exception:
                pass
            try:
                _sh.kill()
            except Exception:
                pass
            _sh = None
    return False


def device_name(ip):
    try:
        names = json.load(open(DEVICES_FILE, encoding="utf-8"))
        out = subprocess.run(["ip", "neigh", "show", ip], capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"lladdr ([0-9a-f:]{17})", out)
        if m and m.group(1) in names:
            return names[m.group(1)]
    except Exception:
        pass
    return ip


def log_action(ip, what):
    who = device_name(ip)
    dev = getattr(_req, "dev", "")
    if dev:
        who = dev + (" (VPN)" if ip in ROUTER_IPS else "")
    _last.update(who=who, what=what, t=time.time())
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{who}\t{ip}\t{what}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
        if os.path.getsize(LOG_FILE) > 400_000:
            lines = open(LOG_FILE, encoding="utf-8").readlines()[-LOG_KEEP:]
            open(LOG_FILE, "w", encoding="utf-8").writelines(lines)
    except Exception:
        pass


def read_log(n=150):
    try:
        return [l.rstrip("\n").split("\t") for l in open(LOG_FILE, encoding="utf-8").readlines()[-n:]][::-1]
    except Exception:
        return []


def pactl(*a):
    return subprocess.run(["pactl", *a], env=PENV, capture_output=True, text=True, timeout=5).stdout


def vol_state():
    v = re.search(r"(\d+)%", pactl("get-sink-volume", SINK))
    m = "yes" in pactl("get-sink-mute", SINK)
    return {"vol": int(v.group(1)) if v else None, "muted": m, "max": MAX_VOL, "normal": NORMAL_VOL}


def volume(arg, val=None):
    clamp = lambda x: max(0, min(MAX_VOL, x))
    if arg == "set" and val is not None:
        pactl("set-sink-volume", SINK, f"{clamp(val)}%")
    elif arg in ("up", "down"):
        cur = vol_state()["vol"] or 0
        pactl("set-sink-volume", SINK, f"{clamp(cur + (5 if arg == 'up' else -5))}%")
    elif arg == "mute":
        pactl("set-sink-mute", SINK, "toggle")
    elif arg == "normal":
        pactl("set-sink-mute", SINK, "0"); pactl("set-sink-volume", SINK, f"{NORMAL_VOL}%")


def focus_app():
    if time.time() - _focus["t"] < 3:
        return _focus["v"]
    try:
        out = subprocess.run(["adb", "-s", ADB, "shell", "dumpsys window | grep -m1 mCurrentFocus"],
                             capture_output=True, text=True, timeout=4).stdout
        m = re.search(r" ([a-z0-9_.]+)/", out)
        name = APP_NAMES.get(m.group(1), m.group(1).split(".")[-1]) if m else ""
    except Exception:
        name = ""
    _focus.update(t=time.time(), v=name)
    return name


# ---- Phone mouse (v16): one virtual USB mouse on the host (uinput). Weston hands it to Android like a real
# mouse (pointer, hover, click, wheel). Moves come from the phone touchpad or its gyroscope (HTTPS page).
_mouse = {"ui": None, "lock": threading.Lock(), "logged": {}}


def mouse_dev():
    if _mouse["ui"] is None:
        from evdev import UInput, ecodes as E
        _mouse["E"] = E
        _mouse["ui"] = UInput({E.EV_REL: [E.REL_X, E.REL_Y, E.REL_WHEEL, E.REL_HWHEEL],
                               E.EV_KEY: [E.BTN_LEFT, E.BTN_RIGHT, E.BTN_MIDDLE]}, name="TV Kumanda Fare")
        time.sleep(0.3)          # let Weston pick the new device up
    return _mouse["ui"], _mouse["E"]


def mouse_event(dx=0, dy=0, wheel=0, btn=None):
    """btn: 'l' click, 'r' right click (= Back in Android), 'ld'/'lu' left down/up (drag)."""
    clamp = lambda v, m: max(-m, min(m, int(v)))
    with _mouse["lock"]:
        ui, E = mouse_dev()
        dx, dy, wheel = clamp(dx, 400), clamp(dy, 400), clamp(wheel, 10)
        if dx:
            ui.write(E.EV_REL, E.REL_X, dx)
        if dy:
            ui.write(E.EV_REL, E.REL_Y, dy)
        if wheel:
            ui.write(E.EV_REL, E.REL_WHEEL, wheel)
        if dx or dy or wheel:
            ui.syn()
        b = {"l": E.BTN_LEFT, "ld": E.BTN_LEFT, "lu": E.BTN_LEFT, "r": E.BTN_RIGHT}.get(btn)
        if b is not None:
            if btn in ("l", "r", "ld"):
                ui.write(E.EV_KEY, b, 1); ui.syn()
            if btn in ("l", "r"):
                time.sleep(0.03)
            if btn in ("l", "r", "lu"):
                ui.write(E.EV_KEY, b, 0); ui.syn()
    return True


MANIFEST = json.dumps({"name": "TV Kumanda", "short_name": "TV Kumanda", "start_url": "/", "display": "fullscreen",
                       "orientation": "portrait", "background_color": "#0e0e10", "theme_color": "#0e0e10",
                       "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]})
ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="22" fill="#3d6df2"/>'
        '<rect x="20" y="28" width="60" height="38" rx="6" fill="none" stroke="#fff" stroke-width="7"/>'
        '<path d="M38 76h24" stroke="#fff" stroke-width="7" stroke-linecap="round"/></svg>')

PAGE = r"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,minimum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="/manifest.json"><link rel="icon" href="/icon.svg"><link rel="apple-touch-icon" href="/icon.svg">
<meta name="theme-color" content="#0e0e10"><title>TV Kumanda</title><style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
html,body{margin:0;background:#0e0e10;color:#eee;font-family:system-ui,-apple-system,sans-serif;overscroll-behavior:none;touch-action:none}
body{position:fixed;inset:0;display:flex;flex-direction:column;gap:10px;
  padding:calc(8px + env(safe-area-inset-top)) 12px calc(10px + env(safe-area-inset-bottom));max-width:480px;margin:0 auto;overflow:hidden}
button{background:#202024;color:#eee;border:0;border-radius:16px;font-size:17px;font-family:inherit;touch-action:none}
button.hit{background:#3d6df2}
.top{display:flex;justify-content:space-between;align-items:center;font-size:13px;opacity:.75}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#555;margin-right:6px}.dot.on{background:#3ecf6e}
.vol{background:#18181b;border-radius:18px;padding:8px 10px;display:grid;grid-template-columns:52px 1fr 52px;gap:8px;align-items:center}
.vol button{height:46px;font-size:24px}
.vmid{display:flex;flex-direction:column;align-items:center;gap:2px}
#vp{font-size:24px;font-weight:600;font-variant-numeric:tabular-nums}#vp.m{color:#f06262}#vp.b{color:#f0a020}
#vbar{position:relative;width:100%;height:30px;touch-action:none}
#vtrack{position:absolute;left:0;right:0;top:12px;height:6px;border-radius:3px;background:#2c2c31}
#vfill{position:absolute;left:0;top:12px;height:6px;border-radius:3px;background:#3d6df2}
#v100{position:absolute;top:6px;width:2px;height:18px;background:#777}
#vknob{position:absolute;top:4px;width:22px;height:22px;border-radius:50%;background:#fff;transform:translateX(-50%)}
.vrow2{grid-column:1/4;display:grid;grid-template-columns:1fr 1fr;gap:8px}
.vrow2 button{height:40px;font-size:14px}
.mid{flex:1;display:flex;align-items:center;justify-content:center;min-height:0}
#dpad{position:relative;width:min(84vw,46vh,340px);aspect-ratio:1;border-radius:50%;background:#1b1b1f;touch-action:none}
#dpad .seg{position:absolute;display:flex;align-items:center;justify-content:center;font-size:30px;color:#bbb;pointer-events:none}
#dpad .u{top:4%;left:30%;width:40%;height:26%}#dpad .d{bottom:4%;left:30%;width:40%;height:26%}
#dpad .l{left:4%;top:30%;width:26%;height:40%}#dpad .r{right:4%;top:30%;width:26%;height:40%}
#dpad .seg.hit{color:#fff;background:radial-gradient(circle,#3d6df2aa 0,#3d6df200 70%)}
#ok{position:absolute;left:31%;top:31%;width:38%;height:38%;border-radius:50%;background:#3d6df2;display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:600;pointer-events:none}
#ok.hit{background:#5a85ff;transform:scale(.95)}
.media{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.media button{height:46px;font-size:18px}
.apps{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.apps button{height:44px;font-size:15px}
.bottom{display:grid;grid-template-columns:1.6fr 1fr;gap:10px}
.bottom button{height:74px;font-size:22px;font-weight:600}
#back{background:#2b2b31}
#s{position:absolute;left:0;right:0;top:calc(30px + env(safe-area-inset-top));text-align:center;font-size:12px;color:#f06262;pointer-events:none}
#kb{position:fixed;left:12px;right:12px;bottom:calc(10px + env(safe-area-inset-bottom));display:none;gap:8px;grid-template-columns:1fr 80px;background:#18181b;padding:8px;border-radius:16px}
#kb.on{display:grid}
#kb input{background:#0e0e10;color:#eee;border:1px solid #333;border-radius:12px;padding:0 12px;font-size:16px;height:48px;user-select:text;-webkit-user-select:text;touch-action:auto}
</style></head><body>
<div class="top"><span><span class="dot" id="dot"></span><span id="app">Bağlanıyor…</span></span><a href="/log" id="last" style="color:#aaa;text-decoration:none">📜 Kayıt</a></div>
<div id="s"></div>

<div class="vol">
<button data-v="down">－</button>
<div class="vmid"><div id="vp">–%</div><div id="vbar"><div id="vtrack"></div><div id="vfill"></div><div id="v100"></div><div id="vknob"></div></div></div>
<button data-v="up">＋</button>
<div class="vrow2"><button data-v="mute">🔇 Sessiz</button><button data-v="normal">Normal ses</button></div>
</div>

<div class="apps"><button id="chbtn">📺 Kanallar</button><button data-a="youtube">YouTube</button><button id="sendbtn">📱 Gönder</button></div>
<div id="sendpanel" style="display:none;position:fixed;inset:0;background:#0e0e10;z-index:6;flex-direction:column;padding:calc(14px + env(safe-area-inset-top)) 14px calc(14px + env(safe-area-inset-bottom));gap:12px">
<div style="display:flex;justify-content:space-between;align-items:center"><b style="font-size:18px">📱 Telefondan TV'ye</b><button id="sendclose" style="height:44px;padding:0 16px">✕ Kapat</button></div>
<label style="display:flex;align-items:center;justify-content:center;height:90px;border-radius:16px;background:#202024;font-size:18px">🎞 Video / 🖼 Fotoğraf seç<input id="file" type="file" accept="video/*,image/*,audio/*" style="display:none"></label>
<div id="upbar" style="height:10px;border-radius:5px;background:#2c2c31;overflow:hidden"><div id="upfill" style="height:100%;width:0;background:#3d6df2"></div></div>
<div id="upmsg" style="font-size:14px;opacity:.8;min-height:18px"></div>
<div style="font-size:14px;opacity:.7;margin-top:8px">veya link yapıştır (YouTube, video, site):</div>
<input id="link" type="text" placeholder="https://…" style="background:#18181b;color:#eee;border:1px solid #2a2a2e;border-radius:12px;padding:0 12px;font-size:16px;height:50px;user-select:text;-webkit-user-select:text;touch-action:auto">
<button id="linkgo" style="height:56px;background:#3d6df2">TV'de aç</button>
<div style="font-size:13px;opacity:.55;line-height:1.5;margin-top:auto">Ekranı yansıtmak için: telefonda bildirim panelini aç → <b>Yayınla / Ekranı yansıt (Cast)</b> → <b>Salon TV</b>.<br>Bitince telefonda "Yayını durdur" de, TV kaldığı yere döner.</div>
</div>
<div id="chpanel" style="display:none;position:fixed;inset:0;background:#0e0e10;z-index:5;flex-direction:column;padding:calc(10px + env(safe-area-inset-top)) 12px calc(10px + env(safe-area-inset-bottom));gap:8px">
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px"><button id="chprev" style="height:48px">◀ Önceki</button><button id="chclose" style="height:48px">✕ Kapat</button><button id="chnext" style="height:48px">Sonraki ▶</button></div>
<input id="chq" type="text" placeholder="Kanal ara…" style="background:#18181b;color:#eee;border:1px solid #2a2a2e;border-radius:12px;padding:0 12px;font-size:16px;height:44px;user-select:text;-webkit-user-select:text;touch-action:auto">
<div id="chlist" style="flex:1;overflow-y:auto;touch-action:pan-y;display:flex;flex-direction:column;gap:6px"></div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
<button class="spl" data-s="on" style="height:46px;font-size:14px">◧ Ekranı böl</button><button class="spl" data-s="left" style="height:46px;font-size:14px">⬅ Sol (ses+kanal)</button><button class="spl" data-s="right" style="height:46px;font-size:14px">Sağ (ses+kanal) ➡</button></div>
<button class="spl" data-s="off" style="height:42px;font-size:14px">Tek ekrana dön</button>
</div>

<div class="mid"><div id="dpad">
<div class="seg u">▲</div><div class="seg d">▼</div><div class="seg l">◀</div><div class="seg r">▶</div><div id="ok">OK</div>
</div></div>

<div class="media">
<button data-k="rew">⏪</button><button data-k="play">⏯</button><button data-k="ff">⏩</button><button id="kbtn">⌨</button><button id="fixbtn">🛠</button>
</div>
<div id="fix" style="display:none;grid-template-columns:1fr 1fr;gap:8px">
<button class="hold" data-sys="tvrestart" style="height:52px;font-size:14px">TV'yi düzelt<br><small style="opacity:.6">2 sn basılı tut</small></button>
<button class="hold" data-sys="reboot" style="height:52px;font-size:14px;background:#3a1f22">Cihazı yeniden başlat<br><small style="opacity:.6">2 sn basılı tut</small></button>
</div>
<div class="bottom"><button id="back" data-k="back">↩ Geri</button><button data-k="home">⌂ Ana</button></div>

<div id="kb"><input id="tx" placeholder="Yaz: TV'de anında görünür" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"><button id="tsend">🔍 Ara</button></div>

<script>
const $=id=>document.getElementById(id), S=$('s');
['gesturestart','gesturechange','dblclick'].forEach(ev=>document.addEventListener(ev,e=>e.preventDefault(),{passive:false}));
document.addEventListener('touchmove',e=>{if(!e.target.closest('#kb,#chlist'))e.preventDefault()},{passive:false});
let lastTouch=0;document.addEventListener('touchend',e=>{const n=Date.now();if(n-lastTouch<350&&!e.target.closest('#kb'))e.preventDefault();lastTouch=n},{passive:false});

function buzz(n){if(navigator.vibrate)navigator.vibrate(n||12)}
function err(m){S.textContent=m||'';}
function post(u){return fetch(u,{method:'POST'}).then(r=>{err(r.ok?'':'Hata '+r.status);return r}).catch(()=>err('TV\'ye ulaşılamıyor'))}
function key(k){buzz();return post('/key/'+k)}
function flash(el){el.classList.add('hit');setTimeout(()=>el.classList.remove('hit'),140)}

// generic key buttons (+ hold-repeat for rew/ff, max 4 s)
const ALLREP=new Set();
function stopAllRepeats(){ALLREP.forEach(f=>f());}
['visibilitychange','blur','pagehide'].forEach(ev=>window.addEventListener(ev,stopAllRepeats));
document.addEventListener('visibilitychange',stopAllRepeats);
document.querySelectorAll('[data-k]').forEach(b=>{
  let t1,t2,t3;const k=b.dataset.k,rep=['rew','ff'].includes(k);
  const end=()=>{b.classList.remove('hit');clearTimeout(t1);clearInterval(t2);clearTimeout(t3)};ALLREP.add(end);
  b.addEventListener('pointerdown',e=>{e.preventDefault();b.classList.add('hit');key(k);if(rep){t1=setTimeout(()=>{t2=setInterval(()=>key(k),200);t3=setTimeout(end,4000)},450)}});
  ['pointerup','pointerleave','pointercancel','lostpointercapture'].forEach(ev=>b.addEventListener(ev,end));
});
document.querySelectorAll('[data-a]').forEach(b=>b.addEventListener('pointerdown',e=>{e.preventDefault();flash(b);buzz(25);post('/app/'+b.dataset.a).then(()=>setTimeout(state,1500))}));

// D-pad: tap a sector = that direction, tap center = OK, hold = repeat, swipe also works (short)
const dp=$('dpad'),OK=$('ok'),SEG={up:dp.querySelector('.u'),down:dp.querySelector('.d'),left:dp.querySelector('.l'),right:dp.querySelector('.r')};
let rptT,rptI,rptX,sx,sy,swiped,startDir;
function stopRep(){clearTimeout(rptT);clearInterval(rptI);clearTimeout(rptX)}
ALLREP.add(stopRep);
function zone(e){const r=dp.getBoundingClientRect(),x=e.clientX-r.left-r.width/2,y=e.clientY-r.top-r.height/2,d=Math.hypot(x,y);
  if(d<r.width*0.2)return'ok';return Math.abs(x)>Math.abs(y)?(x>0?'right':'left'):(y>0?'down':'up')}
function press(z){key(z);flash(z==='ok'?OK:SEG[z])}
dp.addEventListener('pointerdown',e=>{e.preventDefault();dp.setPointerCapture(e.pointerId);sx=e.clientX;sy=e.clientY;swiped=false;startDir=zone(e);stopRep();
  if(startDir!=='ok'){press(startDir);rptT=setTimeout(()=>{rptI=setInterval(()=>press(startDir),170);rptX=setTimeout(stopRep,4000)},550)}});
dp.addEventListener('pointermove',e=>{const dx=e.clientX-sx,dy=e.clientY-sy,TH=24;
  if(Math.abs(dx)<TH&&Math.abs(dy)<TH)return;
  const d=Math.abs(dx)>Math.abs(dy)?(dx>0?'right':'left'):(dy>0?'down':'up');
  stopRep();swiped=true;press(d);sx=e.clientX;sy=e.clientY});
dp.addEventListener('pointerup',e=>{stopRep();if(startDir==='ok'&&!swiped){press('ok');buzz(20)}});
['pointercancel','lostpointercapture'].forEach(ev=>dp.addEventListener(ev,stopRep));

// troubleshooting (hold 2 s)
$('fixbtn').addEventListener('pointerdown',e=>{e.preventDefault();const f=$('fix');f.style.display=f.style.display==='grid'?'none':'grid'});
document.querySelectorAll('.hold').forEach(b=>{let t;
  b.addEventListener('pointerdown',e=>{e.preventDefault();b.classList.add('hit');t=setTimeout(()=>{buzz(80);b.classList.remove('hit');
    post('/sys/'+b.dataset.sys).then(r=>{if(r&&r.ok)err(b.dataset.sys==='reboot'?'Cihaz yeniden başlıyor (~2 dk)':'TV yeniden başlıyor (~1 dk)')})},2000)});
  ['pointerup','pointerleave','pointercancel'].forEach(ev=>b.addEventListener(ev,()=>{clearTimeout(t);b.classList.remove('hit')}))});

// volume bar (custom, 0..max with 100% marker)
let VMAX=150,VNORM=85,dragging=false;
const vb=$('vbar'),vf=$('vfill'),vk=$('vknob'),vp=$('vp');
function drawVol(v,m){const p=Math.max(0,Math.min(1,v/VMAX))*100;vf.style.width=p+'%';vk.style.left=p+'%';vf.style.background=v>100?'#f0a020':'#3d6df2';
  vp.textContent=m?'Sessiz':(v+'%'+(v>100?' güçlü':''));vp.className=m?'m':(v>100?'b':'')}
$('v100').style.left=(100/VMAX*100)+'%';
function showVol(st){if(st.vol==null)return;if(st.max){VMAX=st.max;$('v100').style.left=(100/VMAX*100)+'%'}if(!dragging)drawVol(st.vol,st.muted)}
function vol(a,v){buzz();return fetch('/vol/'+a+(v!=null?'?v='+v:''),{method:'POST'}).then(r=>r.json()).then(showVol).catch(()=>err('TV\'ye ulaşılamıyor'))}
document.querySelectorAll('[data-v]').forEach(b=>b.addEventListener('pointerdown',e=>{e.preventDefault();flash(b);vol(b.dataset.v)}));
function vAt(e){const r=vb.getBoundingClientRect();return Math.round(Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))*VMAX/5)*5}
vb.addEventListener('pointerdown',e=>{e.preventDefault();vb.setPointerCapture(e.pointerId);dragging=true;drawVol(vAt(e),false)});
vb.addEventListener('pointermove',e=>{if(dragging)drawVol(vAt(e),false)});
vb.addEventListener('pointerup',e=>{if(!dragging)return;const v=vAt(e);dragging=false;vol('set',v)});

// keyboard
$('kbtn').addEventListener('pointerdown',e=>{e.preventDefault();$('kb').classList.toggle('on');if($('kb').classList.contains('on'))setTimeout(()=>$('tx').focus(),50)});
// live typing: the whole phone field is mirrored into the focused TV field (Turkish letters OK)
let sent=null,tq=Promise.resolve(),tTimer;
function syncText(){const cur=$('tx').value;if(cur===sent)return;sent=cur;
  tq=tq.then(()=>fetch('/type',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:cur})}).then(r=>err(r.ok?'':'Yazı gitmedi')).catch(()=>err('TV\'ye ulaşılamıyor')))}
$('tx').addEventListener('input',()=>{clearTimeout(tTimer);tTimer=setTimeout(syncText,120)});
function closeKb(){$('tx').value='';sent=null;$('kb').classList.remove('on');$('tx').blur()}
function sendText(){clearTimeout(tTimer);syncText();tq=tq.then(()=>post('/kb/enter'));closeKb()}
$('tsend').onclick=sendText;$('tx').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();sendText()}});
$('kbtn').addEventListener('pointerdown',()=>{if($('kb').classList.contains('on')){sent=null;$('tx').value='';post('/kb/on')}else{tq=tq.then(()=>post('/kb/off'))}});

// send from phone
$('sendbtn').addEventListener('pointerdown',e=>{e.preventDefault();$('sendpanel').style.display='flex'});
$('sendclose').onclick=()=>{$('sendpanel').style.display='none';$('link').blur()};
$('file').addEventListener('change',()=>{const f=$('file').files[0];if(!f)return;
  const x=new XMLHttpRequest();x.open('POST','/upload?name='+encodeURIComponent(f.name));
  x.upload.onprogress=e=>{if(e.lengthComputable){const p=Math.round(e.loaded/e.total*100);$('upfill').style.width=p+'%';$('upmsg').textContent='Yükleniyor %'+p+' ('+Math.round(f.size/1048576)+' MB)'}};
  x.onload=()=>{$('upmsg').textContent=x.status===200?'✅ TV\'de açıldı':'❌ Olmadı: '+(x.responseText||x.status);$('file').value=''};
  x.onerror=()=>{$('upmsg').textContent='❌ TV\'ye ulaşılamadı'};
  $('upmsg').textContent='Yükleniyor…';x.send(f)});
$('linkgo').onclick=()=>{const v=$('link').value.trim();if(!v)return;buzz(25);
  fetch('/link',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:v})}).then(r=>{$('upmsg').textContent=r.ok?'✅ TV\'de açıldı':'❌ Link açılamadı';if(r.ok)$('link').value=''})};

// channels
let CH=[];
function renderCh(){const q=$('chq').value.toLowerCase();$('chlist').innerHTML='';
  CH.forEach((c,i)=>{if(q&&!c.toLowerCase().includes(q))return;const b=document.createElement('button');b.textContent=(i+1)+'. '+c;
    b.style.cssText='height:50px;text-align:left;padding:0 14px;font-size:16px;flex:none';b.onclick=()=>{buzz(25);post('/ch/'+i);};$('chlist').appendChild(b)})}
$('chbtn').addEventListener('pointerdown',e=>{e.preventDefault();$('chpanel').style.display='flex';
  if(!CH.length)fetch('/channels').then(r=>r.json()).then(j=>{CH=j;renderCh()})});
$('chclose').onclick=()=>{$('chpanel').style.display='none';$('chq').blur()};
$('chq').addEventListener('input',renderCh);
$('chprev').onclick=()=>{buzz();post('/ch/prev')};$('chnext').onclick=()=>{buzz();post('/ch/next')};
document.querySelectorAll('.spl').forEach(b=>b.addEventListener('click',()=>{buzz(25);err(b.dataset.s==='on'?'Ekran bölünüyor (~10 sn)…':'');post('/split/'+b.dataset.s).then(r=>{if(r&&r.ok&&b.dataset.s==='on')err('')})}));

function ago(s){s=Math.round(s);return s<60?s+' sn':s<3600?Math.round(s/60)+' dk':Math.round(s/3600)+' sa'}
function state(){fetch('/state').then(r=>r.json()).then(st=>{$('dot').classList.add('on');$('app').textContent=(st.split&&st.split.single)?('📺 '+st.split.single):st.split?('◧ '+(st.split.side==='left'?'🔊':'')+st.split.left+' | '+(st.split.side==='right'?'🔊':'')+st.split.right):(st.app||'TV');showVol(st);if(st.err)err(st.err);
    if(st.last&&st.last.who)$('last').textContent='📜 '+st.last.who+' · '+ago(st.last.ago)})
  .catch(()=>{$('dot').classList.remove('on');$('app').textContent='Bağlantı yok'})}
state();setInterval(()=>{if(!document.hidden)state()},4000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)state()});
</script></body></html>"""


def _ass(t):
    return str(t).replace("\\", "/").replace("{", "(").replace("}", ")").replace("$", "$$")


# ---- On-TV overlay (drawn by the host mpv with `osd-overlay`, ASS events in 1920x1080 coordinates).
# Banner = TV-style info bar on every channel change; List = channel browser opened with OK, moved with ▲▼
# (no zapping while browsing), OK tunes, ◀/Back closes. Auto-hides (banner 4 s, list 6 s idle).
ACCENT = "F26D3D"          # BGR of #3d6df2 (same blue as the phone remote)
PANEL = "141210"
FONT = "DejaVu Sans"
_ui = {"mode": None, "cur": 0, "until": 0.0}
_ui_lock = threading.Lock()


def _disp(name):
    return _ass(re.sub(r"\s*\(\d+p\)", "", name))


def _rect(x, y, w, h, color, alpha, r=16):
    r = min(r, w // 2, h // 2)
    d = (f"m {r} 0 l {w - r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h - r} b {w} {h} {w} {h} {w - r} {h} "
         f"l {r} {h} b 0 {h} 0 {h} 0 {h - r} l 0 {r} b 0 0 0 0 {r} 0")
    return f"{{\\an7\\pos({x},{y})\\bord0\\shad0\\1c&H{color}&\\1a&H{alpha:02X}&\\p1}}{d}{{\\p0}}"


def _text(x, y, t, size, color="FFFFFF", bold=False, an=7, alpha=0):
    return (f"{{\\an{an}\\pos({x},{y})\\fn{FONT}\\fs{size}\\b{1 if bold else 0}\\1c&H{color}&\\1a&H{alpha:02X}&"
            f"\\bord0\\shad2\\4c&H000000&\\4a&H90&}}{t}")


_ovc = {"sock": None, "pid": None}
_ovc_lock = threading.Lock()


def _ovc_drain(sock):
    try:
        while sock.recv(65536):
            pass
    except Exception:
        pass


_vol_ui = {"until": 0.0, "base": [], "shown": False}


def _vol_elems():
    st = vol_state(); v = st["vol"] or 0; muted = st["muted"]
    x, y, w, h = 1786, 250, 96, 560
    L = [_rect(x, y, w, h, PANEL, 0x18, 48)]
    bx, by, bw, bh = x + 36, y + 96, 24, h - 190
    L.append(_rect(bx, by, bw, bh, "5A5A5A", 0x40, 12))
    fill = int(bh * min(v, 100) / 100)
    if fill > 0:
        col = "8C8C8C" if muted else ("3D9BFF" if v > 100 else ACCENT)
        L.append(_rect(bx, by + bh - fill, bw, fill, col, 0, 12))
    L.append(_text(x + w // 2, y + 28, "Sessiz" if muted else str(v), 26 if muted else 40, "FFFFFF", True, an=8))
    L.append(_text(x + w // 2, y + h - 64, "SES", 24, "A0A0A0", True, an=8))
    return L


def ui_volume():
    """Volume changed while live TV is up: Android's own volume panel is hidden behind mpv, so draw one."""
    _vol_ui["until"] = time.time() + 2.5; _vol_ui["shown"] = True
    _overlay(_vol_ui["base"])


def _overlay(lines):
    _vol_ui["base"] = list(lines or [])
    if time.time() < _vol_ui["until"]:
        try:
            lines = list(lines or []) + _vol_elems()
        except Exception as e:
            print("vol ui:", e, flush=True)
    _overlay_raw(lines)


def _overlay_raw(lines):
    """osd-overlay belongs to the IPC client that created it: mpv deletes it when that connection closes, so a
    connect-send-close call (mpv_ipc) shows nothing. Keep one persistent connection (reader thread discards
    mpv's replies/events so the socket never fills); reconnect when mpv was restarted."""
    import socket
    data = "\n".join(lines) if lines else ""
    msg = (json.dumps({"command": {"name": "osd-overlay", "id": 7, "format": "ass-events" if lines else "none",
                                   "data": data, "res_x": 1920, "res_y": 1080, "z": 10}}) + "\n").encode()
    p = _split["proc"]
    with _ovc_lock:
        for attempt in (1, 2):
            try:
                if _ovc["sock"] is None or _ovc["pid"] != (p.pid if p else None):
                    if _ovc["sock"]:
                        _ovc["sock"].close()
                    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); c.settimeout(2); c.connect(MPV_SOCK)
                    c.settimeout(None)
                    threading.Thread(target=_ovc_drain, args=(c,), daemon=True).start()
                    _ovc.update(sock=c, pid=p.pid if p else None)
                _ovc["sock"].sendall(msg)
                return
            except Exception:
                try:
                    _ovc["sock"] and _ovc["sock"].close()
                except Exception:
                    pass
                _ovc["sock"] = None


def ui_hide():
    with _ui_lock:
        _ui["mode"] = None
    _overlay([])


def _side():
    return _split["side"] if _split["mode"] == "split" else "left"


def _playing_idx():
    sd = _side()
    i = _want.get(sd)
    if i is None:
        src = _split["src"][sd]
        i = src[1] if src and src[0] == "ch" else None
    return i


def ui_banner(ms=4000):
    try:
        chs = channels(); i = _playing_idx()
        if not chs or i is None:
            name = _ass(src_name(_split["src"][_side()])); num = ""; sub = ""
        else:
            n = len(chs); i %= n
            name, num = _disp(chs[i][0]), str(i + 1)
            sub = f"▲  {_disp(chs[(i - 1) % n][0])}        ▼  {_disp(chs[(i + 1) % n][0])}"
        tag = ("SOL EKRAN  ·  " if _side() == "left" else "SAĞ EKRAN  ·  ") if _split["mode"] == "split" else ""
        L = [_rect(60, 846, 980, 176, PANEL, 0x1C, 22), _rect(60, 846, 12, 176, ACCENT, 0x00, 6),
             _text(110, 868, num, 78, ACCENT, True), _text(250, 872, name, 60, "FFFFFF", True),
             _text(252, 958, tag + sub, 30, "C8C8C8"),
             _text(1010, 868, "OK  ·  Kanal listesi", 24, "9A9A9A", an=9)]
        with _ui_lock:
            _ui.update(mode="banner", until=time.time() + ms / 1000)
        _overlay(L)
    except Exception as e:
        print("banner:", e, flush=True)


ROWS = 11


def ui_list_draw():
    chs = channels()
    if not chs:
        return
    n = len(chs); cur = _ui["cur"] % n; playing = _playing_idx()
    top = max(0, min(cur - ROWS // 2, n - ROWS)) if n > ROWS else 0
    L = [_rect(60, 60, 760, 960, PANEL, 0x1C, 26),
         _text(110, 92, "Kanallar", 50, "FFFFFF", True),
         _text(112, 160, "▲▼ seç     OK izle     ◀ / Geri kapat", 26, "A0A0A0")]
    if _split["mode"] == "split":
        L.append(_text(780, 100, "SOL EKRAN" if _side() == "left" else "SAĞ EKRAN", 26, ACCENT, True, an=9))
    y0 = 222
    for k in range(min(ROWS, n)):
        j = top + k; y = y0 + k * 70
        sel = j == cur
        if sel:
            L.append(_rect(84, y - 8, 712, 64, ACCENT, 0x00, 14))
        L.append(_text(112, y, str(j + 1), 32, "FFFFFF" if sel else "8C8C8C", sel))
        L.append(_text(200, y - 2, _disp(chs[j][0]), 38, "FFFFFF", sel, alpha=0 if sel else 0x20))
        if playing is not None and j == playing % n:
            L.append(_text(776, y, "● izleniyor", 24, "FFFFFF" if sel else ACCENT, True, an=9))
    if top > 0:
        L.append(_text(440, 196, "▲", 24, "8C8C8C", an=8))
    if top + ROWS < n:
        L.append(_text(440, 1002, "▼", 24, "8C8C8C", an=2))
    _overlay(L)


def ui_list_open():
    i = _playing_idx()
    with _ui_lock:
        _ui.update(mode="list", cur=i if i is not None else _ch["i"], until=time.time() + 6)
    ui_list_draw()


def ui_list_move(step):
    n = len(channels()) or 1
    with _ui_lock:
        _ui.update(cur=(_ui["cur"] + step) % n, until=time.time() + 6)
    ui_list_draw()


def _ui_timer():
    while True:
        time.sleep(0.5)
        if _ui["mode"] and time.time() > _ui["until"]:
            ui_hide()
        if _vol_ui["shown"] and time.time() > _vol_ui["until"]:
            _vol_ui["shown"] = False
            if _split["on"]:
                _overlay(_vol_ui["base"])


threading.Thread(target=_ui_timer, daemon=True).start()


def osd_now(ms=4000):
    """Channel changed: show the TV-style banner (kept as a name for the older call sites)."""
    ui_banner(ms)


def tv_open():
    """Start live TV on the last channel (from Android) and open the channel list."""
    chs = channels()
    if not chs:
        return False
    if not _split["on"]:
        i = _ch["i"] % len(chs); _want["left"] = i
        if not watch_single(("ch", i)):
            return False
    ui_list_open()
    return True


# ---- Voice key (tv-voice.service records the remote's mic while its voice key is held, transcribes it
# offline on this box and posts the text here over loopback). Commands first, else type into the focused field.
_NUMW = {"sıfır": "0", "bir": "1", "iki": "2", "üç": "3", "dört": "4", "beş": "5", "altı": "6", "yedi": "7",
         "sekiz": "8", "dokuz": "9", "on": "10", "yirmi": "20", "otuz": "30", "kırk": "40", "elli": "50",
         "altmış": "60", "yetmiş": "70", "seksen": "80", "doksan": "90", "yüz": "100"}


def _norm(t):
    t = str(t).replace("I", "ı").replace("İ", "i").lower()
    t = re.sub(r"[^\wçğıöşü%' ]+", " ", t)
    t = re.sub(r"(\w)'(\w+)", r"\1 \2", t)            # "youtube'da" -> "youtube da"
    def num(w):                                         # "otuza", "elliye", "yirmi beşe" -> digits
        if w in _NUMW:
            return _NUMW[w]
        for suf in ("ya", "ye", "yı", "yi", "a", "e", "ı", "i", "u", "ü"):
            if w.endswith(suf) and w[: -len(suf)] in _NUMW and len(w) - len(suf) >= 2:
                return _NUMW[w[: -len(suf)]]
        return w
    t = " ".join(num(w) for w in t.split())
    return re.sub(r"\b([1-9]0) ([1-9])\b", lambda m: str(int(m.group(1)) + int(m.group(2))), t)   # "yirmi beş" -> 25


def _chkey(name):
    return _norm(re.sub(r"\s*\(\d+p\)", "", name)).replace(" ", "")


def field_focused():
    """True when Android has a real text field connected to the (invisible) keyboard right now."""
    out = adb_out("dumpsys input_method")
    m = re.search(r"mInputStarted=(\w+)", out)
    e = re.search(r"mInputEditorInfo:\s*\n\s*inputType=0x([0-9a-f]+)", out)
    return bool(m and m.group(1) == "true" and e and int(e.group(1), 16) != 0)


def voice_feedback(msg):
    if _split["on"]:
        _overlay([_rect(60, 60, 900, 96, PANEL, 0x30, 22), _rect(60, 60, 12, 96, ACCENT, 0, 6),
                  _text(100, 82, _ass(msg), 38, "FFFFFF", True)])
        with _ui_lock:
            _ui.update(mode="voice", until=time.time() + 3)


_VERB = r"(?:\s+(?:kanalını|kanalı|kanal))?(?:\s+(?:aç|açar mısın|izle|izleyelim|koy|başlat))\s*(?:lütfen)?$"


APPS_PKG_YT = "org.smarttube.stable"
_nlu_mod = {"m": None, "mt": 0}


def _nlu():
    f = "/usr/local/bin/tv-nlu.py"
    mt = os.path.getmtime(f)
    if _nlu_mod["m"] is None or mt != _nlu_mod["mt"]:
        import importlib.util
        spec = importlib.util.spec_from_file_location("tv_nlu", f)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        _nlu_mod.update(m=m, mt=mt)
    return _nlu_mod["m"]


def yt_first(q):
    """videoId of the first normal result (no Shorts/ads) from YouTube's own results page, or None."""
    from urllib.parse import quote
    try:
        req = urllib.request.Request("https://www.youtube.com/results?hl=tr&gl=TR&search_query=" + quote(q),
                                     headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124 Safari/537.36",
                                              "Accept-Language": "tr-TR,tr;q=0.9"})
        html = urllib.request.urlopen(req, timeout=6).read(1_500_000).decode("utf-8", "ignore")
        m = re.search(r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})"', html)
        return m.group(1) if m else None
    except Exception as e:
        print("yt_first:", e, flush=True); return None


def yt_go(q, play=True):
    """'YouTube'dan X aç' -> play the first result; 'YouTube'da X ara' -> show the results."""
    from urllib.parse import quote
    if _split["on"]:
        split_off(to_single=False)
    _focus["t"] = 0
    vid = yt_first(q) if play else None
    url = f"https://www.youtube.com/watch?v={vid}" if vid else "https://www.youtube.com/results?search_query=" + quote(q)
    ok = android(f"am start -a android.intent.action.VIEW -d '{url}' {APPS_PKG_YT}", timeout=8)
    return ok, (f"YouTube'da oynat: {q}" if vid else f"YouTube'da ara: {q}")


def app_open(pkg):
    if not re.fullmatch(r"[A-Za-z0-9_.]+", pkg):
        return False
    if _split["on"]:
        split_off(to_single=False)
    _focus["t"] = 0
    out = adb_out(f"cmd package resolve-activity --brief -c android.intent.category.LEANBACK_LAUNCHER {pkg}")
    comp = next((l.strip() for l in out.splitlines() if l.strip().startswith(pkg + "/")), None)
    if not comp:
        out = adb_out(f"cmd package resolve-activity --brief -c android.intent.category.LAUNCHER {pkg}")
        comp = next((l.strip() for l in out.splitlines() if l.strip().startswith(pkg + "/")), None)
    return android(f"am start -n {comp}", timeout=8) if comp else False


# ---- Assistant bar: shows that the voice key is listening / thinking and what was understood.
# Live TV (host mpv) -> mpv overlay; Android -> org.tvbox.asistan overlay (non-focusable, keeps the app's focus).
ASSIST_RCV = "org.tvbox.asistan/.Bar"
GDOTS = ("F48542", "3543EA", "05BCFB", "53A834")      # Google-ish blue, red, yellow, green (ASS = BGR)


def _assist_ass(state, title, sub):
    w = 1040; x = (1920 - w) // 2; y = 1080 - 60 - (150 if sub else 110)
    h = 150 if sub else 110
    L = [_rect(x, y, w, h, "1E1816", 0x08, 55)]
    for k, c in enumerate(GDOTS):
        cy = y + h // 2 + (-10 if state == "listen" and k % 2 == 0 else 0)
        L.append(_rect(x + 46 + k * 30, cy - 9, 18, 18, "3543EA" if state == "err" else c, 0, 9))
    tx = x + 190
    L.append(_text(tx, y + (26 if sub else 30), _ass(title[:60]), 38, "FFFFFF", True))
    if sub:
        L.append(_text(tx + 2, y + 84, _ass(sub[:80]), 28, "C8CCD2"))
    return L


def assist(state, title, sub="", ms=None):
    """state: listen | think | say | err | hide"""
    try:
        if _split["on"]:
            if state == "hide":
                if _ui["mode"] == "voice":
                    ui_hide()
                return
            with _ui_lock:
                _ui.update(mode="voice", until=time.time() + (ms or (9 if state == "listen" else 20 if state == "think" else 4)))
            _overlay(_assist_ass(state, title, sub))
            return
        import shlex
        cmd = f"am broadcast -f 0x20 -n {ASSIST_RCV} --es state {'say' if state == 'ask' else state}"
        if state != "hide":
            cmd += f" --es text {shlex.quote(title[:120])}"
            if sub:
                cmd += f" --es sub {shlex.quote(sub[:160])}"
            if ms:
                cmd += f" --ei ms {int(ms * 1000)}"
        android(cmd + " >/dev/null", timeout=4)
    except Exception as e:
        print("assist:", e, flush=True)


def _human(what):
    w = re.sub(r"\s*\[model [^\]]*\]|\s*\(\d+p\)", "", what)
    for a, b in (("kanal ", "Kanal açılıyor: "), ("uygulama ", "Açılıyor: "), ("YouTube'da oynat: ", "YouTube'da oynatılıyor: "),
                 ("YouTube'da ara: ", "YouTube'da aranıyor: "), ("yazdı: ", "Yazıldı: "), ("ses ", "Ses: ")):
        if w.startswith(a):
            return b + w[len(a):]
    return w[:1].upper() + w[1:]


def _fg_pkg():
    out = adb_out("dumpsys window | grep -m1 mCurrentFocus", timeout=4)
    m = re.search(r" ([A-Za-z0-9_.]+)/", out)
    return m.group(1) if m else ""


def web_open(q, search=False, youtube=False):
    """Open something IN Firefox: a site name/domain, YouTube's website, or a web search."""
    from urllib.parse import quote
    k = q.lower().replace(" ", "")
    if youtube:                                              # "YouTube'dan X aç" while Firefox is in front
        url = "https://www.youtube.com/results?search_query=" + quote(q)
    elif re.fullmatch(r"(youtube|yutup|yutub|youtub)\w*", k):
        url = "https://www.youtube.com/"
    elif re.fullmatch(r"[a-z0-9\-]+(\.[a-z0-9\-]+)+(/\S*)?", k):
        url = "https://" + k
    elif search:
        url = "https://duckduckgo.com/?q=" + quote(q)
    else:                                                    # "Radio Garden aç" -> first result (DuckDuckGo !ducky)
        url = "https://duckduckgo.com/?q=" + quote("! " + q)
    if _split["on"]:
        split_off(to_single=False)
    _focus["t"] = 0
    return android(f"am start -a android.intent.action.VIEW -d '{url}' -n {BROWSER}", timeout=8), f"Firefox: {q}"


def in_app(r):
    """'<app>'dan <q> aç' — do it inside that app where the app allows it."""
    app, q = r["app"], r["q"]
    if app == "web":
        return web_open(q, r.get("search"))
    tpl = _nlu().APP_EXTRA.get(app, {}).get("search")
    if tpl:                                                  # app with a search deep link
        from urllib.parse import quote
        return android(f"am start -a android.intent.action.VIEW -d '{tpl.format(q=quote(q))}' {r['pkg']}",
                       timeout=8), f"{r['name']}'da ara: {q}"
    if r.get("ch") is not None:                              # Beleş TiVi etc. can't be driven from outside:
        hit = r["ch"]; chs = channels()                      # play the same channel in our own Kanallar
        _want["left"] = hit; _ch["i"] = hit
        ok = watch_single(("ch", hit)); osd_now()
        return ok, f"kanal {chs[hit][0]} (Kanallar'da; {r['name']} dışarıdan kanal seçtirmiyor)"
    return app_open(r["pkg"]), f"uygulama {r['name']}"


VOICE_FIELD_CTRL = {"ara": "submit", "arat": "submit", "tamam": "submit", "gönder": "submit", "git": "submit",
                    "sil": "clear", "temizle": "clear", "hepsini sil": "clear", "yazıyı sil": "clear",
                    "geri": "back", "geri dön": "back", "vazgeç": "back"}


def voice_cmd(text, ip):
    """Spoken sentence -> action, in three layers:
    1. tv-nlu.py: Turkish grammar (case suffixes, '<app>'dan/üzerinde X aç|ara', 'X sitesine gir', '<engine>'da X
       ara', '... çal/dinle', channel names). Structural rules, not a list of remembered sentences.
    2. tv-intent.py: local model picks the most likely action for anything else; its probability decides
       (act / ask on the TV with OK=yes / 'not understood').
    3. A focused text field means dictation unless the sentence is an explicit '<app>'dan ...' command."""
    raw = str(text).strip()[:200]
    n = _norm(raw)
    if not n:
        return False, "boş"
    field = not _split["on"] and field_focused()
    c = VOICE_FIELD_CTRL.get(n) if field else None
    if c == "submit":
        return ime_confirm(), "aramayı başlattı"
    if c == "clear":
        return type_clear(), "yazıyı sildi"
    if n in ("geri", "geri dön", "geri git", "vazgeç"):
        return (split_off(to_single=True) if _split["on"] else android("input keyevent 4")), "geri"
    if re.fullmatch(r"ana (ekran|sayfa|menü)(a|ya|ye|e)?( git| aç| dön)?", n):
        if _split["on"]:
            split_off(to_single=False)
        return android("input keyevent 3"), "ana ekran"
    if not field and n in ("sessiz", "sessize al", "sustur", "sesi kapat", "sesi kes"):
        pactl("set-sink-mute", SINK, "1"); return True, "ses kapatıldı"
    m = re.search(r"\bses\w*\b.*?\b(\d{1,3})\b|\b(\d{1,3})\b.*\bses", n)
    if m and not field:
        pactl("set-sink-mute", SINK, "0"); volume("set", int(m.group(1) or m.group(2)))
        return True, f"ses {vol_state()['vol']}%"
    chs = channels()
    try:
        r = _nlu().parse(raw, [ch[0] for ch in chs],
                         APPS_PKG_YT if (not _split["on"] and _fg_pkg() == APPS_PKG_YT) else None)
    except Exception as e:
        print("nlu:", e, flush=True); r = {"act": None}
    explicit = r["act"] == "in_app" or (r["act"] in ("yt_play", "yt_search") and
                                        re.search(r"(youtube|yutup)\S*\s?(dan|den|tan|ten|da|de|ta|te)\b", n))
    if field and not explicit:
        t = _clean_dictation(raw)
        return type_full(t, ""), f"yazdı: {t}"
    if r["act"] == "in_app":
        return in_app(r)
    if r["act"] in ("yt_play", "yt_search"):
        return yt_go(r["q"], play=r["act"] == "yt_play")
    if r["act"] == "app":
        return app_open(r["pkg"]), f"uygulama {r['name']}"
    if r["act"] == "channel":
        return _zap(r["i"])
    if re.fullmatch(r"(kanallar|kanal listesi|canlı tv|canlı yayın|televizyon|tv)( aç| göster| listesi)?", n):
        return tv_open(), "kanal listesi"
    return voice_model(raw)


LETTER_TO_DECISION = {"channel": ("kanal_ac", ""), "ch_next": ("kanal_sonraki", ""), "ch_prev": ("kanal_onceki", ""),
                      "ch_list": ("kanal_listesi", ""), "vol_up": ("ses_ac", ""), "vol_down": ("ses_kis", ""),
                      "mute": ("ses_kapat", ""), "yt_search": ("video_oynat", ""), "yt_open": ("uygulama_ac", "YouTube"),
                      "web": ("uygulama_ac", "Firefox"), "back": ("geri", ""), "home": ("ana_ekran", ""),
                      "play": ("duraklat", ""), "split": ("ekrani_bol", "")}


def _letter_decision(kind, raw):
    e, app = LETTER_TO_DECISION[kind]
    h = raw
    if e == "video_oynat":
        mm = _nlu()
        toks = mm.norm(raw).split()
        h = mm._clean_query([t for t in toks if not mm.stem(t, mm.YOUTUBE)]) or raw
    if app == "Firefox":
        app = next((k for k, v in apps_cached().items() if v == "org.mozilla.firefox"), "Firefox")
    return {"eylem": e, "uygulama": app or "yok", "hedef": h}


def voice_model(raw):
    try:
        ranked, mass = _intent_mod().classify(raw, [ch[0] for ch in channels()], timeout=10)
    except Exception as e:
        print("intent:", e, flush=True)
        return False, f"anlaşılmadı: {raw}"
    if not ranked or ranked[0][0] == "none":
        return False, f"anlaşılmadı: {raw}" + (f" [none %{int(ranked[0][1] * 100)}]" if ranked else "")
    top, p = ranked[0]
    d = _letter_decision(top, raw)
    tag = f" [model {top} %{int(p * 100)}]"
    if p >= ACT_P:
        ok, what = run_decision(d, raw)
        return ok, what + tag
    if p >= ASK_P:
        confirm_ask(d, raw)
        return True, "emin değilim, soruldu: " + describe(d) + tag
    return False, f"anlaşılmadı: {raw}" + tag


_intent = {"mod": None}


def _intent_mod():
    if _intent["mod"] is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("tv_intent", "/usr/local/bin/tv-intent.py")
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        _intent["mod"] = m
    return _intent["mod"]


# ---- Understanding (local LLM, tv-llm.service = llama-server on 127.0.0.1:8179, tv-understand.py)
ACT_P, ASK_P = 0.85, 0.45
_und = {"mod": None, "mt": 0}


def _und_mod():
    f = "/usr/local/bin/tv-understand.py"
    mt = os.path.getmtime(f)
    if _und["mod"] is None or mt != _und["mt"]:
        import importlib.util
        spec = importlib.util.spec_from_file_location("tv_understand", f)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        _und.update(mod=m, mt=mt)
    return _und["mod"]


def app_table():
    """Display name -> package for every installed app the assistant may open (names from tv-nlu + config)."""
    t = {"Kanallar": TILE_PKG}
    try:
        for _k, (pkg, _f, name) in _nlu().APPS.items():
            t[name] = pkg
    except Exception:
        pass
    inst = set(re.findall(r"package:(\S+)", adb_out("pm list packages", timeout=6)))
    return {k: v for k, v in t.items() if v in inst or v == TILE_PKG} or t


_apps_cache = {"t": 0, "v": {}}


def apps_cached():
    if time.time() - _apps_cache["t"] > 600 or not _apps_cache["v"]:
        _apps_cache.update(t=time.time(), v=app_table())
    return _apps_cache["v"]


def screen_name():
    if _split["on"]:
        return "Canlı TV"
    pkg = _fg_pkg()
    for name, p in apps_cached().items():
        if p == pkg:
            return name
    return APP_NAMES.get(pkg, "Ana ekran" if not pkg else pkg.split(".")[-1])


def understand(raw, field):
    apps = apps_cached()
    return _und_mod().understand(raw, {"screen": screen_name(), "field": field}, list(apps),
                                 [re.sub(r"\s*\(\d+p\)", "", c[0]) for c in channels()], timeout=25)


def _clean_dictation(t):
    return re.sub(r"[\s.,!?…]+$", "", t.strip())


def describe(d):
    e, a, h = d.get("eylem"), d.get("uygulama", "yok"), d.get("hedef", "")
    return {"uygulama_ac": f"{a} uygulamasını aç", "site_ac": f"Tarayıcıda '{h}' sitesini aç",
            "web_ara": f"İnternette '{h}' ara", "uygulamada_ara": f"{a} içinde '{h}' ara",
            "video_oynat": f"YouTube'da '{h}' oynat", "kanal_ac": f"'{h}' kanalını aç", "kanal_sonraki": "Sonraki kanal",
            "kanal_onceki": "Önceki kanal", "kanal_listesi": "Kanal listesi", "ses_ac": "Sesi aç", "ses_kis": "Sesi kıs",
            "ses_kapat": "Sesi kapat", "ses_ayarla": f"Sesi %{h} yap", "yaz": f"'{h}' yaz", "geri": "Geri",
            "ana_ekran": "Ana ekran", "duraklat": "Duraklat / devam", "ekrani_bol": "Ekranı böl"}.get(e, e)


def _zap(i):
    sd = _side() if _split["on"] else "left"
    chs = channels(); i %= len(chs)
    _want[sd] = i; _ch["i"] = i
    ok = split_set(("ch", i), sd) if _split["on"] else watch_single(("ch", i)); osd_now()
    return ok, f"kanal {chs[i][0]}"


def run_decision(d, raw):
    e, app, h = d.get("eylem"), d.get("uygulama") or "yok", (d.get("hedef") or "").strip()
    apps = apps_cached()
    if e == "yaz":
        txt = h if h and h.lower() in raw.lower() else _clean_dictation(raw)
        return type_full(txt, ""), f"yazdı: {txt}"
    if e == "uygulama_ac":
        if app == "Kanallar":
            return tv_open(), "kanal listesi"
        if app in apps:
            return app_open(apps[app]), f"uygulama {app}"
        return False, f"'{app}' yüklü değil"
    if e == "site_ac":
        return web_open(h or raw)
    if e == "web_ara":
        return web_open(h or raw, search=True)
    if e == "uygulamada_ara":
        if apps.get(app) == APPS_PKG_YT:
            return yt_go(h or raw, play=False)
        key = next((k for k, v in _nlu().APPS.items() if v[2] == app), None)
        tpl = _nlu().APP_EXTRA.get(key, {}).get("search") if key else None
        if tpl:
            from urllib.parse import quote
            return android(f"am start -a android.intent.action.VIEW -d '{tpl.format(q=quote(h))}' {apps[app]}",
                           timeout=8), f"{app}'da ara: {h}"
        if apps.get(app) == "org.mozilla.firefox" or app == "yok":
            return web_open(h or raw, search=True)
        return app_open(apps[app]), f"uygulama {app} (içinde arama yapılamıyor)"
    if e == "video_oynat":
        return yt_go(h or raw, play=True)
    if e == "kanal_ac":
        chs = channels()
        i = _nlu().find_channel(_nlu().norm(h or raw).split(), [c[0] for c in chs])
        return _zap(i) if i is not None else (tv_open(), f"kanal listesi ('{h}' bulunamadı)")
    if e in ("kanal_sonraki", "kanal_onceki"):
        sd = _side() if _split["on"] else "left"
        return _zap(base_idx(sd) + (1 if e == "kanal_sonraki" else -1))
    if e == "kanal_listesi":
        return tv_open(), "kanal listesi"
    if e in ("ses_ac", "ses_kis"):
        pactl("set-sink-mute", SINK, "0")
        for _ in range(2):
            volume("up" if e == "ses_ac" else "down")
        return True, f"ses {vol_state()['vol']}%"
    if e == "ses_kapat":
        pactl("set-sink-mute", SINK, "1"); return True, "ses kapatıldı"
    if e == "ses_ayarla":
        m = re.search(r"\d{1,3}", _norm(h) + " " + _norm(raw))
        if m:
            pactl("set-sink-mute", SINK, "0"); volume("set", int(m.group(0)))
            return True, f"ses {vol_state()['vol']}%"
        return False, "ses seviyesi anlaşılmadı"
    if e == "geri":
        return (split_off(to_single=True) if _split["on"] else android("input keyevent 4")), "geri"
    if e == "ana_ekran":
        if _split["on"]:
            split_off(to_single=False)
        return android("input keyevent 3"), "ana ekran"
    if e == "duraklat":
        return android(f"input keyevent {KEYS['play']}"), "oynat/duraklat"
    if e == "ekrani_bol":
        return split_on(), "bölünmüş ekran"
    return False, f"anlaşılmadı: {raw}"


# ---- Confirmation ("Bunu mu demek istediniz?"): while it is open the physical remote is GRABBED by the bridge
# (keys reach only us, not Android/mpv): OK = do it, anything else = cancel. Phone remote: OK/Back the same.
_confirm = {"d": None, "raw": "", "until": 0.0}


def confirm_ask(d, raw):
    _confirm.update(d=d, raw=raw, until=time.time() + 8)
    assist("ask", "Bunu mu demek istediniz?", describe(d) + "   ·   OK = evet, Geri = hayır", ms=8)


def confirm_key(key):
    """Returns (handled, log text)."""
    if not _confirm["d"] or time.time() > _confirm["until"]:
        _confirm["d"] = None
        return False, None
    d, raw = _confirm["d"], _confirm["raw"]
    _confirm["d"] = None
    if key in ("ok", "play"):
        assist("think", "Yapılıyor…", describe(d), ms=3)
        ok, what = run_decision(d, raw)
        assist("say" if ok else "err", f"«{raw[:60]}»", _human(what), ms=3)
        return True, "sesli onay: " + what
    assist("hide", "")
    return True, "sesli onay: iptal"


def _und_warm():
    """Keep llama-server's prompt cache filled with the exact prompt (a miss costs ~20 s on this CPU)."""
    time.sleep(20)
    while True:
        try:
            _intent_mod().classify("ısınma", [ch[0] for ch in channels()], timeout=300)
        except Exception as e:
            print("understand warm:", e, flush=True)
        time.sleep(300)


threading.Thread(target=_und_warm, daemon=True).start()


# ---- "Kanallar" tile on the Android home screen (org.tvbox.kanallar, a code-less APK): Android stays isolated
# from the host network, so the host watches Android's activity log over adb and opens live TV + the channel
# list when that tile is started, then closes the (transparent) tile app again.
TILE_PKG = "org.tvbox.kanallar"


def _tile_watch():
    last = 0
    while True:
        try:
            subprocess.run(["adb", "connect", ADB], capture_output=True, timeout=10)
            p = subprocess.Popen(["adb", "-s", ADB, "logcat", "-T", "1", "-s", "ActivityTaskManager:I"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="ignore")
            for line in p.stdout:
                if "START u0" in line and f"cmp={TILE_PKG}/" in line and time.time() - last > 3:
                    last = time.time()
                    def go():
                        _req.dev = "Kanallar uygulaması"
                        ok = tv_open()
                        log_action("127.0.0.1", "Kanallar uygulaması → canlı TV + kanal listesi" + ("" if ok else " (BAŞARISIZ)"))
                        android(f"am force-stop {TILE_PKG}", timeout=5)
                    threading.Thread(target=go, daemon=True).start()
            p.wait()
        except Exception as e:
            print("tile watch:", e, flush=True)
        time.sleep(5)


threading.Thread(target=_tile_watch, daemon=True).start()


# Physical USB remote (air mouse) while a live channel plays: the fullscreen host mpv has keyboard focus and
# ignores keys (--no-input-default-bindings), so its keys never reach Android. Read the remote's evdev nodes
# (shared, not grabbed: Weston still gets them) and replay them as remote-page actions over loopback, so they
# behave exactly like the phone buttons and are logged as "Kumanda (fiziksel)". Only active while mpv is up.
REMOTE_MATCH = ("XING WEI 2.4G",)          # dongle name prefix(es) from /proc/bus/input/devices
_BRIDGE_KEYS = {"KEY_UP": "/key/up", "KEY_DOWN": "/key/down", "KEY_LEFT": "/key/left", "KEY_RIGHT": "/key/right",
                "KEY_ENTER": "/key/ok", "KEY_KPENTER": "/key/ok", "KEY_SELECT": "/key/ok",
                "KEY_BACK": "/key/back", "KEY_ESC": "/key/back", "KEY_HOMEPAGE": "/key/home",
                "KEY_PAGEUP": "/ch/prev", "KEY_PAGEDOWN": "/ch/next",          # same direction as the list on screen
                "KEY_CHANNELUP": "/ch/prev", "KEY_CHANNELDOWN": "/ch/next",
                "KEY_VOLUMEUP": "/vol/up", "KEY_VOLUMEDOWN": "/vol/down", "KEY_MUTE": "/vol/mute"}
_REPEAT_OK = {"/vol/up", "/vol/down"}       # held volume repeats freely
_REPEAT_STEP = {"/key/up", "/key/down", "/key/left", "/key/right", "/ch/next", "/ch/prev"}   # held: 1 step / 0.35 s


def _bridge_post(path):
    import http.client
    try:
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        c.request("POST", path, b"", {"Host": "127.0.0.1", "X-TV": "1", "X-TV-Device": "Kumanda%20(fiziksel)"})
        c.getresponse().read(); c.close()
    except Exception as e:
        print("bridge:", e, flush=True)


_CH_ONLY = set()


def _remote_bridge():
    try:
        import evdev, select
        from evdev import ecodes
    except Exception as e:
        print("bridge off (no evdev):", e, flush=True)
        return
    codes = {getattr(ecodes, k): v for k, v in _BRIDGE_KEYS.items() if hasattr(ecodes, k)}
    global _CH_ONLY
    _CH_ONLY = {getattr(ecodes, k) for k in ("KEY_CHANNELUP", "KEY_CHANNELDOWN") if hasattr(ecodes, k)}
    devs, last_scan, last_sent, grabbed = {}, 0, {}, False
    pool = ThreadPoolExecutor(max_workers=1)     # keeps key order, never blocks reading
    while True:
        if time.time() - last_scan > 5:          # hot-plug: dongle re-plugged / new event numbers
            last_scan = time.time()
            for path in evdev.list_devices():
                if path in devs:
                    continue
                try:
                    d = evdev.InputDevice(path)
                except Exception:
                    continue
                if d.name.startswith(REMOTE_MATCH) and not d.name.endswith("Mouse") and ecodes.EV_KEY in d.capabilities():
                    devs[path] = d
                else:
                    d.close()
        if not devs:
            time.sleep(5); continue
        want = bool(_confirm["d"]) and time.time() < _confirm["until"]
        if want != grabbed:                      # confirmation open: keys go only to us (not Android / mpv)
            for d in list(devs.values()):
                try:
                    d.grab() if want else d.ungrab()
                except Exception:
                    pass
            grabbed = want
        try:
            r, _, _ = select.select(list(devs.values()), [], [], 0.3 if grabbed else 1.0)
        except Exception:
            r = []
        for d in r:
            try:
                evs = list(d.read())
            except OSError:
                devs.pop(d.path, None); continue
            for ev in evs:
                if ev.type != ecodes.EV_KEY or ev.value not in (1, 2) or ev.code not in codes:
                    continue
                path = codes[ev.code]
                if grabbed:
                    if ev.value == 1:
                        pool.submit(_bridge_post, "/key/ok" if path == "/key/ok" else "/key/back")
                    continue
                if not _split["on"]:
                    # Android has focus and handles every key itself. PageUp/PageDown scroll pages there
                    # (Kerim: they must not jump to live TV); only dedicated CH keys open the channel list.
                    if ev.code in _CH_ONLY and ev.value == 1:
                        pool.submit(_bridge_post, "/tv/open")
                    continue
                now = time.time()
                if ev.value == 2 and path not in _REPEAT_OK and path not in _REPEAT_STEP:
                    continue                        # held OK / Back / Home = one press, never a stream
                if ev.value == 2 and path in _REPEAT_STEP and now - last_sent.get(path, 0) < 0.35:
                    continue
                last_sent[path] = now
                pool.submit(_bridge_post, path)


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"     # keep-alive: the mouse sends ~30 small posts/s (one TLS handshake, not 30)
    timeout = 120

    def allowed(self):
        ip = ipaddress.ip_address(self.client_address[0])
        if not any(ip in n for n in ALLOWED_NETS):
            return False
        host = (self.headers.get("Host") or "").strip().lower()
        host = host[1:host.index("]")] if host.startswith("[") else host.rsplit(":", 1)[0]
        return host in ALLOWED_HOSTS

    def same_origin(self):
        """Actions only from the remote page itself: a web page on another site (opened on any phone/PC in the
        house) must not be able to press keys / move the mouse (CSRF). Browsers always send Origin on POST."""
        if ipaddress.ip_address(self.client_address[0]).is_loopback:
            return True
        o = self.headers.get("Origin")
        if o:
            return (urlparse(o).hostname or "").lower() in ALLOWED_HOSTS
        return self.headers.get("X-TV") == "1"

    def send(self, code, body=b"", ctype="text/plain"):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY"); self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers(); self.wfile.write(body)

    def send_json(self, obj):
        self.send(200, json.dumps(obj).encode(), "application/json")

    def take_dev(self):
        d = re.sub(r"[^\w .\-çğıöşüÇĞİÖŞÜ]", "", __import__("urllib.parse").parse.unquote(self.headers.get("X-TV-Device") or ""))[:24].strip()
        _req.dev = d

    def do_GET(self):
        if not self.allowed():
            return self.send(403)
        self.take_dev()
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            try:
                body = open("/usr/local/share/tv-remote/index.html", "rb").read()
            except Exception:
                body = PAGE.encode()
            return self.send(200, body, "text/html; charset=utf-8")
        if p == "/manifest.json":
            return self.send(200, MANIFEST.encode(), "application/manifest+json")
        if p == "/icon.svg":
            return self.send(200, ICON.encode(), "image/svg+xml")
        if p == "/state":
            phone_seen()
            ip0 = self.client_address[0]
            return self.send_json({**vol_state(), "via_router": ip0 in ROUTER_IPS, "version": version(), "you": _req.dev or device_name(ip0), "app": focus_app(), "split": split_label(), "err": _split.get("err") if time.time() - _split.get("err_t", 0) < 8 else None,
                                   "last": {"who": _last["who"], "what": _last["what"], "ago": time.time() - _last["t"]}})
        if p == "/channels":
            return self.send_json([c[0] for c in channels()])
        if p == "/log":
            import html
            rows = "".join(f"<tr><td>{html.escape(r[0][5:])}</td><td>{html.escape(r[1])}</td><td>{html.escape(r[3] if len(r) > 3 else '')}</td></tr>"
                           for r in read_log(200))
            page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                    "<title>Kumanda kaydı</title><style>body{background:#0e0e10;color:#ddd;font:14px system-ui;margin:10px}"
                    "a{color:#7aa2ff}table{border-collapse:collapse;width:100%}td{padding:5px 6px;border-bottom:1px solid #222;white-space:nowrap}"
                    "td:nth-child(2){color:#fff;font-weight:600}</style>"
                    f"<p><a href='/'>← Kumanda</a> · son 200 işlem (en yeni üstte)</p><table>{rows}</table>")
            return self.send(200, page.encode(), "text/html; charset=utf-8")
        self.send(404)

    def do_POST(self):
        if not self.allowed() or not self.same_origin():
            self.close_connection = True
            return self.send(403)
        self.take_dev()
        u = urlparse(self.path)
        parts = u.path.strip("/").split("/")
        ip = self.client_address[0]
        if parts and parts[0] == "voice":
            if not ipaddress.ip_address(ip).is_loopback:
                return self.send(403)
            if parts == ["voice", "listen"]:
                assist("listen", "Dinliyorum…", "Konuşun, bitince tuşu bırakın"); return self.send(200)
            if parts == ["voice", "think"]:
                assist("think", "Anlıyorum…"); return self.send(200)
            if parts == ["voice", "fail"]:
                assist("err", "Sesi duyamadım", "Tuşa basılı tutup konuşun", ms=3)
                log_action(ip, "sesli komut: duyulmadı"); return self.send(200)
            try:
                n = int(self.headers.get("Content-Length", "0"))
                text = str(json.loads(self.rfile.read(min(n, 4000)) or b"{}").get("text", ""))
                ok, what = voice_cmd(text, ip)
            except Exception as e:
                ok, what = False, f"hata {e}"
            if what.startswith("anlaşılmadı") or not ok:
                assist("err", f"«{text.strip()[:60]}»", "Anlaşılmadı, tekrar deneyin" if what.startswith("anlaşılmadı") else "Yapılamadı: " + _human(what), ms=4)
            elif what.startswith("emin değilim"):
                pass                                          # the on-TV choice list is showing
            else:
                assist("say", f"«{text.strip()[:60]}»", _human(what), ms=3.5)
            log_action(ip, f"sesli: «{text[:80]}» → {what}" + ("" if ok else " (BAŞARISIZ)"))
            return self.send_json({"ok": bool(ok), "what": what})
        if parts == ["mouse"]:
            m = {}
            try:
                n = int(self.headers.get("Content-Length", "0"))
                m = json.loads(self.rfile.read(min(n, 2000)) or b"{}")
                ok = mouse_event(m.get("dx", 0), m.get("dy", 0), m.get("w", 0), m.get("b"))
            except Exception:
                ok = False
            if m.get("b") or time.time() - _mouse["logged"].get(ip, 0) > 120:   # log clicks, moves once per 2 min
                _mouse["logged"][ip] = time.time()
                log_action(ip, "fare " + {"l": "tık", "r": "sağ tık (geri)", "ld": "sürükle", "lu": "bırak"}.get(m.get("b"), "kullandı"))
            return self.send(200 if ok else 400)
        if len(parts) == 2 and parts[0] == "vol" and parts[1] in ("up", "down", "mute", "normal", "set"):
            v = parse_qs(u.query).get("v", [None])[0]
            volume(parts[1], int(v) if v and v.isdigit() else None)
            if _split["on"]:
                ui_volume()
            st = vol_state(); log_action(ip, f"ses {parts[1]} → {st['vol']}%{' (sessiz)' if st['muted'] else ''}")
            return self.send_json(st)
        ok = False
        handled = False
        if len(parts) == 2 and parts[0] == "key" and _confirm["d"]:
            handled, what = confirm_key(parts[1])
            if handled:
                ok = True; log_action(ip, what)
        if handled:
            pass
        elif len(parts) == 2 and parts[0] == "key" and _split["on"] and parts[1] == "back" and _ui["mode"] == "list":
            ui_hide(); ok = True
            log_action(ip, "kanal listesi kapandı")
        elif len(parts) == 2 and parts[0] == "key" and _split["on"] and parts[1] in ("back", "home"):
            ui_hide()
            was = _split["mode"]
            ok = split_off(to_single=(parts[1] == "back"))
            log_action(ip, f"tuş {parts[1]} → " + ("bölme kapandı" if was == "split" and parts[1] == "back" else "oynatıcı kapandı"))
        elif len(parts) == 2 and parts[0] == "key" and _split["on"] and parts[1] in ("up", "down", "left", "right", "ok", "play"):
            chs = channels()
            if _ui["mode"] == "list" and chs:
                if parts[1] in ("up", "down"):
                    ui_list_move(-1 if parts[1] == "up" else 1); ok = True
                elif parts[1] in ("ok", "play"):
                    sd = _side(); i = _ui["cur"] % len(chs)
                    _want[sd] = i; _ch["i"] = i
                    log_action(ip, f"listeden kanal {chs[i][0]}")
                    ok = split_set(("ch", i), sd)
                    ui_banner()
                else:
                    ui_hide(); ok = True
            elif parts[1] == "ok":
                ui_list_open(); ok = True
            elif parts[1] in ("up", "down") and chs:
                sd = _split["side"] if _split["mode"] == "split" else "left"
                i = (base_idx(sd) + (-1 if parts[1] == "up" else 1)) % len(chs)   # ▲ = up the list (towards no. 1), like the phone list
                _want[sd] = i; _ch["i"] = i
                log_action(ip, f"kanal {chs[i][0]}")
                ok = split_set(("ch", i), sd)
            elif parts[1] in ("left", "right") and _split["mode"] == "split":
                ok = split_focus(parts[1])
                log_action(ip, f"bölme: {parts[1]} taraf seçildi")
            else:
                ok = True
            if _ui["mode"] != "list":
                osd_now()
        elif len(parts) == 2 and parts[0] == "key" and parts[1] in KEYS:
            ok = android(f"input keyevent {KEYS[parts[1]]}")
            log_action(ip, f"tuş {parts[1]}" + ("" if ok else " (BAŞARISIZ)"))
        elif len(parts) == 2 and parts[0] == "app" and parts[1] in APPS:
            split_off(to_single=False)
            ok = android(f"am start -n {APPS[parts[1]]}", timeout=8); _focus["t"] = 0
            log_action(ip, f"uygulama {parts[1]}" + ("" if ok else " (BAŞARISIZ)"))
        elif parts == ["upload"]:
            self.close_connection = True
            q = parse_qs(u.query)
            raw = os.path.basename(q.get("name", ["dosya"])[0])
            ext = os.path.splitext(raw)[1].lower()
            mime = MIME.get(ext)
            n = int(self.headers.get("Content-Length", "0"))
            if not mime or n <= 0 or n > 4 * 1024 ** 3:
                return self.send(400, "desteklenmeyen dosya".encode())
            os.makedirs(MEDIA_HOST, exist_ok=True)
            name = time.strftime("%m%d-%H%M%S") + ext
            hp = os.path.join(MEDIA_HOST, name)
            with open(hp, "wb") as f:
                left = n
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    f.write(chunk); left -= len(chunk)
            split_off(to_single=False)
            r = subprocess.run(["adb", "-s", ADB, "push", hp, f"{MEDIA_DEV}/{name}"], capture_output=True, timeout=900)
            ok = r.returncode == 0 and open_on_tv(f"{MEDIA_DEV}/{name}", mime)
            log_action(ip, f"telefondan {mime.split('/')[0]} gönderdi ({n // (1 << 20)} MB)" + ("" if ok else " (BAŞARISIZ)"))
            prune()
        elif parts == ["link"]:
            try:
                n = int(self.headers.get("Content-Length", "0"))
                url = json.loads(self.rfile.read(min(n, 4000)) or b"{}").get("url", "")
                if _split["on"] and re.match(r"^https?://", url.strip()):
                    ok, where = split_set(("url", url.strip())), "bölünmüş ekran " + _split["side"]
                elif re.search(r"(youtube\.com|youtu\.be)/|\.(m3u8|mp4|mkv|webm|mov|ts)(\?|$)", url.strip(), re.I):
                    ok, where = watch_single(("url", url.strip())), "oynatıcı (tam ekran)"
                else:
                    split_off(to_single=False)
                    ok, where = open_link(url)
                log_action(ip, f"link açtı → {where}" + ("" if ok else " (BAŞARISIZ)"))
            except Exception:
                ok = False
        elif parts == ["type"]:
            try:
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(min(n, 4000)) or b"{}")
                text = str(body.get("text", ""))[:300]
                prev = body.get("prev")
                src = "page"
                if prev is None:                      # old page: use what the server remembers for this phone
                    prev, src = _typed.get(type_key(ip), ""), "server"
                prev = str(prev)[:300]
                type_log(ip, text, prev, src)
                ok = type_full(text, prev)
                if ok:
                    _typed[type_key(ip)] = text
            except Exception:
                ok = False
        elif parts == ["kb", "clear"]:
            ok = type_clear()
            _typed[type_key(ip)] = ""
            log_action(ip, "TV'deki yazıyı sildi")
        elif parts == ["kb", "on"] or parts == ["kb", "off"]:
            _typed[type_key(ip)] = ""         # sheet opened/closed: the phone field starts empty again
            phone_seen(); ok = True
        elif parts == ["kb", "reset"]:
            _ime["on"] = False
            ok = ime_on()
            log_action(ip, "klavye sıfırlandı")
        elif parts == ["kb", "enter"]:
            _typed[type_key(ip)] = ""
            ok = ime_confirm()
            log_action(ip, "yazı gönderdi (onay)" + ("" if ok else " (BAŞARISIZ)"))
        elif len(parts) == 2 and parts[0] == "ch":
            chs = channels()
            i = {"next": _ch["i"] + 1, "prev": _ch["i"] - 1}.get(parts[1])
            if i is None and parts[1].isdigit():
                i = int(parts[1])
            if i is not None and chs and _split["on"]:
                sd = _split["side"] if _split["mode"] == "split" else "left"
                if parts[1] in ("next", "prev"):
                    i = base_idx(sd) + (1 if parts[1] == "next" else -1)
                i %= len(chs)
                _want[sd] = i; _ch["i"] = i
                log_action(ip, f"kanal ({sd}) {chs[i][0]}")
                ok = split_set(("ch", i), sd)
                osd_now()
            elif i is not None and chs:
                if parts[1] in ("next", "prev"):
                    i = base_idx("left") + (1 if parts[1] == "next" else -1)
                i %= len(chs)
                _want["left"] = i; _ch["i"] = i
                ok = watch_single(("ch", i))
                log_action(ip, f"kanal {chs[i][0]}" + ("" if ok else " (BAŞARISIZ)"))
        elif parts == ["tv", "open"]:
            ok = tv_open()
            log_action(ip, "canlı TV + kanal listesi açıldı" + ("" if ok else " (BAŞARISIZ)"))
        elif len(parts) == 2 and parts[0] == "split" and parts[1] in ("on", "off", "left", "right"):
            ok = {"on": split_on, "off": split_off}.get(parts[1], lambda: split_focus(parts[1]))()
            log_action(ip, f"bölünmüş ekran {parts[1]}" + ("" if ok else " (BAŞARISIZ)"))
        elif parts == ["text"]:
            q = parse_qs(u.query).get("q", [""])[0][:200]
            q = re.sub(r"[^A-Za-z0-9 .,@\-]", "", q).replace(" ", "%s")
            ok = bool(q) and android(f"input text '{q}'")
            log_action(ip, "yazı gönderdi")
        elif parts == ["sys", "tvrestart"]:
            log_action(ip, "TV'Yİ DÜZELT (Android yeniden başlatıldı)")
            subprocess.Popen(["systemctl", "restart", "tv-android"]); ok = True
        elif parts == ["sys", "reboot"]:
            log_action(ip, "CİHAZ YENİDEN BAŞLATILDI")
            subprocess.Popen(["sh", "-c", "sleep 2; systemctl reboot"]); ok = True
        self.send(200 if ok else 400)

    def log_message(self, *a):
        pass


class TLSServer(http.server.ThreadingHTTPServer):
    """HTTPS for https://__TV_HOSTNAME__ (DNS points to Spike's LAN IP). The handshake runs in the request thread,
    and the certificate is re-read when the file changes (renewed from the PC), no restart needed."""
    daemon_threads = True
    _ctx = None
    _mt = 0

    def ctx(self):
        mt = os.path.getmtime(TLS_CERT)
        if self._ctx is None or mt != self._mt:
            c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            c.minimum_version = ssl.TLSVersion.TLSv1_2
            c.load_cert_chain(TLS_CERT, TLS_KEY)
            self._ctx, self._mt = c, mt
        return self._ctx

    def finish_request(self, request, client_address):
        try:
            request.settimeout(15)
            tls = self.ctx().wrap_socket(request, server_side=True)
            tls.settimeout(None)
        except Exception:
            return
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            try:
                tls.close()
            except Exception:
                pass


def serve_https():
    while True:
        try:
            if os.path.exists(TLS_CERT) and os.path.exists(TLS_KEY):
                TLSServer(("0.0.0.0", HTTPS_PORT), H).serve_forever()
        except Exception as e:
            print("https:", e, flush=True)
        time.sleep(30)


if __name__ == "__main__":
    threading.Thread(target=serve_https, daemon=True).start()
    threading.Thread(target=_remote_bridge, daemon=True).start()
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H)
    srv.daemon_threads = True
    srv.serve_forever()
