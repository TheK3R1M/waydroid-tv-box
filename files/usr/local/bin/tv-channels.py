#!/usr/bin/env python3
"""Build a curated Turkish channel list: wanted national channels in a fixed order, every stream tested from
this box (Turkish IP, so 'geo-blocked' streams are fine). Sources: iptv-org tr + current list.
Output: /etc/tv/turkiye.m3u (old one kept as .bak) + report on stdout."""
import re, sys, urllib.request, urllib.parse, concurrent.futures as cf, shutil, time

SRC = ["/tmp/tr_new.m3u", "/etc/tv/turkiye.m3u"]
# (display name, [regex on source name], group)
WANT = [
    ("TRT 1", [r"^TRT 1\b"], "Ulusal"), ("ATV", [r"^ATV( \(Turkiye\))?\b(?! Alanya| Avrupa)"], "Ulusal"),
    ("Show TV", [r"^Show TV\b"], "Ulusal"), ("Kanal D", [r"^Kanal D\b"], "Ulusal"), ("Star TV", [r"^Star TV\b"], "Ulusal"),
    ("NOW", [r"^NOW\b", r"^Fox( TV)?\b"], "Ulusal"), ("TV8", [r"^TV ?8\b(?!\.5|,5| Bucuk)"], "Ulusal"),
    ("Kanal 7", [r"^Kanal 7\b(?! Avrupa)", r"^Kanal 7 Avrupa"], "Ulusal"), ("Beyaz TV", [r"^Beyaz TV"], "Ulusal"),
    ("TV8.5", [r"^TV ?8[.,]5", r"^TV8 Bucuk"], "Ulusal"), ("Teve2", [r"^Teve ?2"], "Ulusal"), ("360", [r"^360\b"], "Ulusal"),
    ("TRT 2", [r"^TRT 2\b"], "Ulusal"), ("A2", [r"^A2( ?TV)?\b"], "Ulusal"), ("DMAX", [r"^DMAX"], "Ulusal"),
    ("TLC", [r"^TLC"], "Ulusal"), ("Show Max", [r"^Show ?Max"], "Ulusal"), ("Euro D", [r"^Euro D\b"], "Ulusal"),
    ("TRT Haber", [r"^TRT Haber"], "Haber"), ("NTV", [r"^NTV\b"], "Haber"), ("CNN Türk", [r"^CNN T[uü]rk"], "Haber"),
    ("Habertürk", [r"^Habert[uü]rk"], "Haber"), ("Halk TV", [r"^Halk TV"], "Haber"), ("Sözcü TV", [r"^S[oö]zc[uü]"], "Haber"),
    ("Tele 1", [r"^Tele ?1\b"], "Haber"), ("tv100", [r"^tv ?100", r"^TV 100"], "Haber"), ("Haber Global", [r"^Haber Global"], "Haber"),
    ("A Haber", [r"^A Haber"], "Haber"), ("TGRT Haber", [r"^TGRT Haber"], "Haber"), ("24 TV", [r"^24 ?TV\b"], "Haber"),
    ("Ekol TV", [r"^Ekol"], "Haber"), ("Bloomberg HT", [r"^Bloomberg"], "Haber"), ("Ekotürk", [r"^Ekot[uü]rk"], "Haber"),
    ("TRT Spor", [r"^TRT Spor\b(?! Y)"], "Spor"), ("TRT Spor 2", [r"^TRT Spor 2"], "Spor"), ("TRT Spor Yıldız", [r"^TRT Spor Y"], "Spor"), ("A Spor", [r"^A Spor"], "Spor"),
    ("HT Spor", [r"^HT ?Spor"], "Spor"), ("Sports TV", [r"^Sports TV"], "Spor"),
    ("TRT Belgesel", [r"^TRT Belgesel"], "Belgesel"), ("TGRT Belgesel", [r"^TGRT Belgesel"], "Belgesel"),
    ("TRT Çocuk", [r"^TRT [CÇ]ocuk"], "Çocuk"), ("Minika Çocuk", [r"^Minika [CÇ]ocuk"], "Çocuk"), ("Minika Go", [r"^Minika Go"], "Çocuk"),
    ("TRT Müzik", [r"^TRT M[uü]zik"], "Müzik"), ("Kral Pop", [r"^Kral Pop"], "Müzik"), ("Power Türk", [r"^PowerT[uü]rk TV", r"^Power ?T[uü]rk\b"], "Müzik"),
    ("Number 1", [r"^Number 1 TV"], "Müzik"), ("Dream Türk", [r"^Dream T[uü]rk"], "Müzik"),
    ("TRT 3", [r"^TRT 3\b"], "Diğer"), ("TRT Türk", [r"^TRT T[uü]rk"], "Diğer"), ("TRT Avaz", [r"^TRT Avaz"], "Diğer"),
    ("TRT World", [r"^TRT World"], "Diğer"), ("TBMM TV", [r"^TBMM"], "Diğer"), ("Diyanet TV", [r"^Diyanet TV"], "Diğer"),
]


# Broadcasters' own public web-player streams (from their live pages / official CDNs). Tried FIRST.
EXTRA = {
    "ATV": "https://rnttwmjcin.turknet.ercdn.net/lcpmvefbyo/atv/atv_720p.m3u8",  # 1080p variant slow/flaky
    "Show TV": "https://ciner.daioncdn.net/showtv/showtv.m3u8?ce=3&app=<APP_UUID_FROM_BROADCASTER_PAGE>",
    "NOW": "https://uycyyuuzyh.turknet.ercdn.net/nphindgytw/nowtv/nowtv.m3u8",
    "Star TV": "https://dogus.daioncdn.net/startv/startv.m3u8?app=startv_web",
    "Teve2": "https://demiroren.daioncdn.net/teve2/teve2.m3u8?ce=3&app=<APP_UUID_FROM_BROADCASTER_PAGE>",
    "A Spor": "https://rnttwmjcin.turknet.ercdn.net/lcpmvefbyo/aspor/aspor_720p.m3u8",  # 1080p slow
    "Beyaz TV": "https://beyaztv-live.daioncdn.net/beyaztv/beyaztv.m3u8",
    "DMAX": "https://dogus.daioncdn.net/dmax/dmax.m3u8?app=dmax_web",
    "TLC": "https://dogus.daioncdn.net/tlc/tlc.m3u8?app=tlc_web",
    "Habertürk": "https://ciner.daioncdn.net/haberturktv/haberturktv.m3u8?app=<APP_UUID_FROM_BROADCASTER_PAGE>&ce=3",
    "Bloomberg HT": "https://ciner.daioncdn.net/bloomberght/bloomberght.m3u8?app=web",
    "TRT Spor": "https://tv-trtspor1.medya.trt.com.tr/master.m3u8",
    "TRT Spor 2": "https://tv-trtspor2.medya.trt.com.tr/master.m3u8",
    "TRT World": "https://tv-trtworld.medya.trt.com.tr/master.m3u8",
}


KEEP = {"ATV", "Show TV", "NOW", "Star TV", "TRT Spor"}


def parse(path):
    out, inf = [], None
    try:
        for l in open(path, encoding="utf-8", errors="ignore"):
            l = l.strip()
            if l.startswith("#EXTINF"):
                inf = l
            elif l and not l.startswith("#") and inf:
                name = inf.split(",")[-1].strip()
                out.append((name, l)); inf = None
    except FileNotFoundError:
        pass
    return out


def res(name):
    m = re.search(r"\((\d+)p\)", name)
    return int(m.group(1)) if m else 0


def alive(url):
    """Two tries: a single slow answer must not drop a channel."""
    for _ in range(2):
        t = _alive(url)
        if t is not None:
            return t
    return None


def _alive(url):
    """Real check: playlist (and one level of variant) answers and contains media."""
    try:
        h = {"User-Agent": "Mozilla/5.0"}
        t0 = time.time()
        txt = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=6).read(300000).decode("utf-8", "ignore")
        if "#EXTM3U" not in txt:
            return None
        if "#EXT-X-STREAM-INF" in txt:
            v = next((x for x in txt.splitlines() if x and not x.startswith("#")), None)
            if not v:
                return None
            txt = urllib.request.urlopen(urllib.request.Request(urllib.parse.urljoin(url, v), headers=h), timeout=6).read(300000).decode("utf-8", "ignore")
        if "#EXTINF" not in txt:
            return None
        return round(time.time() - t0, 2)
    except Exception:
        return None


cands = []
for p in SRC:
    cands += parse(p)
plain = lambda n: re.sub(r"\s*\[.*?\]", "", n).strip()

chosen, report = [], []
jobs = {}
with cf.ThreadPoolExecutor(16) as ex:
    for disp, pats, grp in WANT:
        opts, seen = ([(disp + " [resmi]", EXTRA[disp])] if disp in EXTRA else []), set()
        for pat in pats:
            for n, u in cands:
                if re.search(pat, plain(n), re.I) and u not in seen:
                    seen.add(u); opts.append((n, u))
        opts.sort(key=lambda x: (0 if "[resmi]" in x[0] else 1, -res(x[0])))
        jobs[disp] = (grp, [(n, u, ex.submit(alive, u)) for n, u in opts])
    for disp, pats, grp in WANT:
        grp, lst = jobs[disp]
        ok = [(n, u, f.result()) for n, u, f in lst]
        good = [x for x in ok if x[2] is not None]
        if good:
            n, u, t = good[0]
            q = res(n) or next((res(x[0]) for x in ok if res(x[0])), 0)
            q = 720 if disp in ("ATV", "A Spor") else q
            chosen.append((disp + (f" ({q}p)" if q else ""), u, grp))
            report.append(f"OK    {disp:18} {q or '?':>5}  {t}s  ({len(good)}/{len(ok)} kaynak çalışıyor)")
        elif disp in KEEP and disp in EXTRA:
            chosen.append((disp, EXTRA[disp], grp))
            report.append(f"GEÇİCİ {disp:17} resmi yayın şu an cevap vermiyor, listede tutuldu")
        else:
            report.append(f"YOK   {disp:18} ({len(ok)} kaynak, hiçbiri çalışmıyor)")

print("\n".join(report))
print(f"\nToplam: {len(chosen)} kanal")
if "--write" in sys.argv and len(chosen) >= 25:
    shutil.copy("/etc/tv/turkiye.m3u", "/etc/tv/turkiye.m3u.bak")
    with open("/etc/tv/turkiye.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, u, grp in chosen:
            f.write(f'#EXTINF:-1 group-title="{grp}",{name}\n{u}\n')
    print("yazıldı: /etc/tv/turkiye.m3u (eski: .bak)")
