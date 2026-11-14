#!/usr/bin/env python3
"""Extra channels from any community M3U list (set TV_EXTRA_M3U_URL), filtered to OFFICIAL / FAST sources only.
Community lists usually mix free official feeds with unlicensed restreams (pay channels, 24/7 film channels on
proxies and bare IPs); only hosts on ALLOW are kept, everything else is dropped and counted.
Runs daily from tv-channels-extra.timer; writes /etc/tv/extra.m3u (previous copy .bak) only if >= 5 work.
tv-remote reads it after /etc/tv/turkiye.m3u (names already in the curated list are skipped there)."""
import concurrent.futures, os, re, sys, urllib.parse, urllib.request

SRC = os.environ.get("TV_EXTRA_M3U_URL", "")   # e.g. in /etc/tv/env; empty = do nothing
OUT = "/etc/tv/extra.m3u"
# official broadcaster CDNs and FAST (free ad-supported) platforms
ALLOW = re.compile(r"(^|\.)(stingray\.com|ottera\.tv|bloomberg\.com|turknet\.ercdn\.net|amazonaws\.com|3qsdn\.com|"
                   r"duhnet\.tv|daioncdn\.net|fast\.nbcuni\.com|amagi\.tv|nhkworld\.jp|tubi\.io|"
                   r"rbmn-live\.akamaized\.net|medya\.trt\.com\.tr|cdn-euronews\.akamaized\.net|"
                   r"dwamdstream\d+\.akamaized\.net|cgtn\.com|cbsnstream\.cbsnews\.com)$")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
GROUP_ORDER = ["ULUSAL", "Ulusal - Yurt Dışı", "HABER", "Belgesel", "BELGESEL", "Çocuk", "ÇOCUK", "Spor", "Dünya", "Müzik"]


def get(url, n=200000, t=8):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t) as r:
        return r.read(n).decode("utf-8", "ignore")


def works(url):
    for _ in range(2):
        try:
            body = get(url, 60000)
            if "#EXTM3U" not in body:
                continue
            if "#EXT-X-STREAM-INF" in body:              # master: check the first variant too
                v = next(l for l in body.splitlines() if l and not l.startswith("#"))
                body = get(urllib.parse.urljoin(url, v), 60000)
            if "#EXTINF" in body:
                return True
        except Exception:
            pass
    return False


def main():
    if not SRC:
        sys.exit("set TV_EXTRA_M3U_URL")
    lines = get(SRC, 2_000_000, 20).splitlines()
    entries, dropped = [], 0
    for i, l in enumerate(lines):
        if not l.startswith("#EXTINF"):
            continue
        url = next((x.strip() for x in lines[i + 1:i + 4] if x.strip() and not x.startswith("#")), "")
        host = urllib.parse.urlparse(url).hostname or ""
        if not url.startswith("https://") or not ALLOW.search(host):
            dropped += 1; continue
        if not re.match(r"^https://[\w\-.:/?=&%~+@,;]+$", url):
            dropped += 1; continue
        name = re.sub(r"[^\w .'&+\-çğıöşüÇĞİÖŞÜ]", "", l.split(",")[-1]).strip()[:40]
        group = (re.search(r'group-title="([^"]*)"', l) or [None, "Diğer"])[1]
        entries.append((group, name, url))
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        ok = list(ex.map(lambda e: works(e[2]), entries))
    good = [e for e, k in zip(entries, ok) if k]
    good.sort(key=lambda e: GROUP_ORDER.index(e[0]) if e[0] in GROUP_ORDER else 99)
    print(f"source {len(entries) + dropped} | not official/FAST (dropped) {dropped} | candidates {len(entries)} | "
          f"working {len(good)}")
    for e, k in zip(entries, ok):
        print(("OK  " if k else "YOK ") + f"{e[0]:<18} {e[1]}")
    if "--write" in sys.argv and len(good) >= 5:
        if os.path.exists(OUT):
            os.replace(OUT, OUT + ".bak")
        with open(OUT, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for g, n, u in good:
                f.write(f'#EXTINF:-1 group-title="{g}",{n}\n{u}\n')
        print("written", OUT)


if __name__ == "__main__":
    main()
