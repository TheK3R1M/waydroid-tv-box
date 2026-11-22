"""TV programme scheduling: reminders, sleep timer, scheduled recordings.

Pure logic + a JSON store (/var/lib/tv-remote/schedule.json). Used in-process by tv-remote.py and by
tv-rec.py (the recorder runs as its own transient systemd unit, so it survives a tv-remote restart).
No network, no mpv here: those live in tv-remote.py, which keeps the tests offline."""
import glob
import json
import os
import re
import time
import unicodedata

STORE = "/var/lib/tv-remote/schedule.json"
REC_DIR = "/var/lib/tv-rec"
REC_CAP = 20 * 1024 ** 3      # disk cap for recordings; oldest files go first
PRE_REC = 120                 # record from 2 min before the programme start
POST_REC = 300                # ... and 5 min after its end
WARN_BEFORE = 60              # reminder toast this many seconds before the start
FIRE_GRACE = 900              # a reminder more than 15 min late (host was off) is dropped silently


def slug(text, n=40):
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return (s or "x")[:n]


def rec_window(start, stop):
    return start - PRE_REC, stop + POST_REC


def rec_filename(chan_name, title, start):
    return f"{time.strftime('%Y%m%d-%H%M', time.localtime(start))}_{slug(chan_name, 24)}_{slug(title, 40)}.ts"


def rem_id(cid, start):
    return f"r{slug(cid, 30)}-{int(start)}"


def rec_id(cid, start):
    return f"k{slug(cid, 30)}-{int(start)}"


def unit_name(rid):
    return "tv-rec-" + rid


def local_cal(ts):
    """systemd --on-calendar wants local wall-clock time."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def best_variant_from_text(txt, base):
    """HLS master text -> URL of the best media playlist <= 1080p (same rule as tv-remote's _best_variant).
    Returns `base` when the text is not a master playlist. None when nothing usable."""
    if "#EXT-X-STREAM-INF" not in txt:
        return base
    import urllib.parse
    best, key = None, None
    lines = txt.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        m = re.search(r"RESOLUTION=\d+x(\d+)", line)
        b = re.search(r"[^-]BANDWIDTH=(\d+)", "," + line.split(":", 1)[-1])
        h = int(m.group(1)) if m else 0
        bw = int(b.group(1)) if b else 0
        if h > 1080 or (h == 0 and bw > 9_000_000):
            continue
        nxt = next((x for x in lines[i + 1:] if x and not x.startswith("#")), None)
        k = (h, bw)
        if nxt and (key is None or k > key):
            best, key = nxt, k
    return urllib.parse.urljoin(base, best) if best else None


def prune(rec_dir=REC_DIR, cap=REC_CAP, reserve=0):
    """Delete the oldest finished recordings until the directory plus `reserve` bytes fits under `cap`."""
    files = []
    for p in glob.glob(os.path.join(rec_dir, "*.ts")):
        try:
            st = os.stat(p)
            files.append((st.st_mtime, p, st.st_size))
        except OSError:
            pass
    total = sum(sz for _, _, sz in files)
    removed = []
    for _, p, sz in sorted(files):
        if total + reserve <= cap:
            break
        try:
            os.remove(p)
            total -= sz
            removed.append(p)
        except OSError:
            pass
    return removed


class Store:
    def __init__(self, path=STORE):
        self.path = path
        self.d = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        d.setdefault("reminders", [])
        d.setdefault("recordings", [])
        d.setdefault("auto", False)          # "otomatik geç": reminders switch the channel at start
        return d

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    @staticmethod
    def _find(lst, rid):
        return next((x for x in lst if x["id"] == rid), None)

    def toggle_reminder(self, cid, name, start, stop, title, chan_index=None):
        """OK on a future programme. Returns (on, entry)."""
        rid = rem_id(cid, start)
        x = self._find(self.d["reminders"], rid)
        if x:
            self.d["reminders"].remove(x)
            self.save()
            return False, x
        x = dict(id=rid, cid=cid, name=name, start=float(start), stop=float(stop), title=title,
                 idx=chan_index, warned=False, fired=False)
        self.d["reminders"].append(x)
        self.save()
        return True, x

    def toggle_recording(self, cid, name, start, stop, title):
        """OK+record on a future programme. Returns (on, entry, removed_entry_or_None)."""
        rid = rec_id(cid, start)
        x = self._find(self.d["recordings"], rid)
        if x:
            self.d["recordings"].remove(x)
            self.save()
            return False, x, x
        x = dict(id=rid, cid=cid, name=name, start=float(start), stop=float(stop), title=title,
                 file=rec_filename(name, title, start), state="scheduled")
        self.d["recordings"].append(x)
        self.save()
        return True, x, None

    def due_reminders(self, now):
        """[(kind, entry)] with kind 'warn' (1 min before) or 'start'. Each fires once."""
        out = []
        for r in self.d["reminders"]:
            if not r["warned"] and r["start"] - WARN_BEFORE <= now < r["start"]:
                r["warned"] = True
                out.append(("warn", r))
            if not r["fired"] and now >= r["start"]:
                r["fired"] = True
                if now - r["start"] <= FIRE_GRACE:
                    out.append(("start", r))
        if out:
            self.save()
        return out

    def drop_old(self, now):
        before = len(self.d["reminders"]) + len(self.d["recordings"])
        self.d["reminders"] = [r for r in self.d["reminders"] if not r["fired"] or r["start"] + FIRE_GRACE > now]
        self.d["recordings"] = [r for r in self.d["recordings"] if r["stop"] + POST_REC + 3600 > now]
        if before != len(self.d["reminders"]) + len(self.d["recordings"]):
            self.save()


class Sleep:
    """Sleep timer: stops live TV and sends the TV to sleep when the time is up; warns 1 min before."""

    def __init__(self):
        self.until = 0.0
        self.warned = False

    def set(self, minutes, now):
        if minutes <= 0:
            self.until, self.warned = 0.0, False
        else:
            self.until, self.warned = now + minutes * 60, False

    def left(self, now):
        return max(0, int(self.until - now)) if self.until else 0

    def tick(self, now):
        """None | 'warn' (once, 60 s before) | 'off' (time is up; the timer is then cleared)."""
        if not self.until:
            return None
        if not self.warned and now >= self.until - 60 and now < self.until:
            self.warned = True
            return "warn"
        if now >= self.until:
            self.until = 0.0
            return "off"
        return None


def rec_playable(name, rec_dir=REC_DIR):
    """Safe path for a recording name from the phone (basename only, must exist)."""
    if not name or os.path.basename(name) != name or not name.endswith(".ts"):
        return None
    p = os.path.join(rec_dir, name)
    return p if os.path.isfile(p) else None
