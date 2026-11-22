#!/usr/bin/env python3
"""Daily EPG for the TV remote: XMLTV -> /var/lib/tv-epg/now.json (window: now-6 h .. now+24 h).

  tv-epg.py                          fetch the default source, match the channel lists on the box, write JSON
  tv-epg.py --xml FILE --m3u FILE    offline (tests): read a local XMLTV file and M3U list(s)
  tv-epg.py --report                 print coverage only (no write)

Source: iptv-epg.org public Turkish XMLTV (legal public EPG feed). Matching is by normalised display name, with
a small alias table for the few channels whose guide name differs. Channel keys use the same rule as the
server's chan_id(), so the remote can look a programme up by the stable channel id.
"""
import argparse, gzip, io, json, os, re, sys, time, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

DEFAULT_SRC = "https://iptv-epg.org/files/epg-tr.xml.gz"
DEFAULT_M3U = ["/etc/tv/turkiye.m3u", "/etc/tv/extra.m3u"]
DEFAULT_OUT = "/var/lib/tv-epg/now.json"
TR = str.maketrans("çğıöşüÇĞİÖŞÜâîûÂÎÛ", "cgiosucgiosuaiuaiu")
# guide name -> list name (normalised on both sides); extend when a channel shows "yok" in the report
ALIAS = {   # list name (normalised) -> guide name (normalised); the guide calls these by a different name
    "now": "nowtv", "haberturktv": "haberturk", "trthaber": "trthaber", "ntv": "ntv", "tr360": "360",
    "minikacocuk": "minikago", "trtspor2": "trtspor", "trtgenc": "trtgenc", "tvtr": "tv",
}

def norm(name):
    """Turkish-insensitive key: drop quality tags and punctuation, fold Turkish letters, lower case."""
    n = re.sub(r"\(.*?\)|\[.*?\]", "", name or "")
    n = re.sub(r"\d+p\b", "", n).translate(TR).lower()
    return re.sub(r"[^a-z0-9]", "", n)


def chan_id(name):
    """Same rule as server chan_id(): the stable id used by the phone and the TV."""
    return re.sub(r"\W|\d+p", "", name.lower())


def read_m3u_names(paths):
    out = []
    for p in paths:
        try:
            for line in open(p, encoding="utf-8"):
                if line.startswith("#EXTINF"):
                    name = re.sub(r"\s*\[(Not 24/7|Geo-blocked)\]", "", line.split(",")[-1]).strip()
                    out.append(name)
        except FileNotFoundError:
            pass
    seen, uniq = set(), []
    for n in out:                       # same dedupe rule as the server channels()
        k = re.sub(r"\W|\d+p", "", n.lower())
        if k not in seen:
            seen.add(k); uniq.append(n)
    return uniq


def fetch(src):
    req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def parse_time(s):
    # XMLTV: 20261122070000 +0300 (the offset is optional)
    m = re.match(r"(\d{14})\s*([+-]\d{4})?", s or "")
    if not m:
        return None
    dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    off = m.group(2) or "+0000"
    tz = timezone(timedelta(hours=int(off[:3]), minutes=int(off[0] + off[3:5])))
    return int(dt.replace(tzinfo=tz).timestamp())


def build(xml_bytes, names, now=None, back_h=6, ahead_h=24):
    now = int(now or time.time())
    lo, hi = now - back_h * 3600, now + ahead_h * 3600
    # guide channel ids keyed by normalised display name (first wins) and by normalised id
    gid = {}
    for _, el in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if el.tag == "channel":
            cid = el.get("id", "")
            dn = re.sub(r"^TR\s*-\s*", "", el.findtext("display-name") or "")   # guide names read "TR - ATV"
            for k in (norm(dn), norm(cid.split(".")[0])):
                if k:
                    gid.setdefault(k, cid)
            el.clear()
    match, miss = {}, []
    for n in names:
        k = norm(n)
        k = ALIAS.get(k, k)
        g = gid.get(k)
        if g is None:
            miss.append(n)
        else:
            match[n] = g
    want = {}
    for n, g in match.items():
        want.setdefault(g, []).append(n)
    progs = {g: [] for g in want}
    for _, el in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if el.tag != "programme":
            continue
        g = el.get("channel")
        if g in progs:
            s, e = parse_time(el.get("start")), parse_time(el.get("stop"))
            if s and e and e > lo and s < hi:
                progs[g].append([s, e, (el.findtext("title") or "").strip()])
        el.clear()
    out = {}
    for g, names_for in want.items():
        rows = sorted(progs[g])
        for n in names_for:
            out[chan_id(n)] = rows
    total = len(names)
    return {"generated": now, "window": [lo, hi], "channels": out,
            "coverage": {"matched": len(match), "total": total,
                         "pct": round(100.0 * len(match) / total, 1) if total else 0.0},
            "unmatched": miss}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--xml", help="local XMLTV (gz or plain) instead of --src")
    ap.add_argument("--m3u", action="append", help="channel list(s); default: the box lists")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    xml = open(a.xml, "rb").read() if a.xml else fetch(a.src)
    if xml[:2] == b"\x1f\x8b":
        xml = gzip.decompress(xml)
    names = read_m3u_names(a.m3u or DEFAULT_M3U)
    res = build(xml, names)
    cov = res["coverage"]
    print(f"coverage {cov['matched']}/{cov['total']} = {cov['pct']} %  programmes for "
          f"{sum(len(v) for v in res['channels'].values())} rows")
    print("unmatched:", "; ".join(res["unmatched"]))
    if a.report:
        return 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    os.replace(tmp, a.out)
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
