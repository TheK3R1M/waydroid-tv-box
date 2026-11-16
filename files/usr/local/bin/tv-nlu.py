#!/usr/bin/env python3
"""Turkish voice-command understanding for the TV box (pure functions, no I/O; tested offline).

parse(text, channel_names, current_app=None) -> dict:
  {"act": "yt_play"|"yt_search", "q": "..."}          YouTube: play first result / show results
  {"act": "app", "pkg": "...", "name": "..."}          open an installed app
  {"act": "channel", "i": index}                        live channel by name
  {"act": None}                                         not handled here (caller: other rules / model)

Turkish is agglutinative: "YouTube'dan", "youtubedan", "yutuptan", "Kanal D'ye", "Netfly'ı" all carry a case
suffix glued to (or after an apostrophe on) the name. Names are matched on the stem after stripping known
suffixes, so the recogniser's spelling (apostrophe or not, capitals or not) doesn't matter. Common
mis-hearings of the app names are listed explicitly; fuzzy matching is only used on whole short phrases."""
import difflib, re

# case/possessive suffixes that follow a name (longest first)
SUFFIXES = sorted("da de ta te dan den tan ten an en ı i u ü yı yi yu yü ya ye a e yla yle la le nın nin nun nün "
                  "ın in un ün yı yi ndan nden na ne nı ni nu nü nda nde".split(), key=len, reverse=True)
PLAY_VERBS = {"aç", "açar", "açarmısın", "açsana", "açın", "izle", "izleyelim", "izlet", "izlemek", "oynat", "oynatır",
              "gir", "git", "girer", "dinlet", "çalar", "çalsana",
              "koy", "koyar", "başlat", "dinle", "dinleyelim", "çal", "çalar", "göster", "getir"}
SEARCH_VERBS = {"ara", "arat", "arar", "bul", "bulur", "listele", "aratır"}
FILLER = {"lütfen", "mısın", "misin", "musun", "bana", "şu", "şunu", "biraz", "hadi", "bakalım", "tamam",
          "uygulama", "uygulamalar", "uygulamalardan", "uygulamayı", "uygulamasını", "uygulaması", "uygulamasından",
          "uygulamasında", "üzerinde", "üzerinden", "içinde", "içinden", "ile", "sitesi", "sitesini", "sitesine",
          "aç", "acaba", "istiyorum", "ister", "yap", "da", "de", "dan", "den", "ta", "te", "tan", "ten"}
VIDEO_WORDS = re.compile(r"^(video|videosu|videosunu|videoyu|videoları|videolarını|videolar|klip|klibi|klibini)$")

YOUTUBE = {"youtube", "yutup", "yutub", "yutüp", "youtub", "yotube", "yutube", "youtubu", "smarttube", "smarttub"}
# app key -> (package, spoken forms incl. frequent mis-hearings, display name)
APPS = {
    "youtube": ("org.smarttube.stable", YOUTUBE | {"smarttv"}, "YouTube"),
    "kodi": ("org.xbmc.kodi", {"kodi", "kodiyi", "kodu"}, "Kodi"),
    "vlc": ("org.videolan.vlc", {"vlc", "velece", "vilisi"}, "VLC"),
    "web": ("org.mozilla.firefox", {"firefox", "tarayıcı", "internet", "web", "fayrfoks", "chrome", "krom", "firefoks",
                                    "firebox", "fireboks", "firepoks", "fayırfoks"}, "Tarayıcı"),
    "settings": ("com.android.tv.settings", {"ayarlar", "ayarları", "ayar"}, "Ayarlar"),
    "playstore": ("com.android.vending", {"playstore", "googleplay", "markete", "market"}, "Play Store"),
    "lemuroid": ("com.swordfish.lemuroid", {"lemuroid", "oyunlar", "emülatör"}, "Lemuroid"),
    "files": ("com.lonelycatgames.Xplore", {"xplore", "dosyalar", "dosya"}, "Dosyalar"),
}
# Box-specific apps (not shipped): /etc/tv/voice-apps.json  {"key": ["package", ["spoken", "forms"], "Name"]}
# Optional 4th element: {"search": "<scheme>:///search?search={q}", "addon_scheme": "<scheme>"} for apps that take
# a search deep link or install add-ons from "<scheme>://.../manifest.json" links.
APP_EXTRA = {}
try:
    import json as _json
    for _k, _v in _json.load(open("/etc/tv/voice-apps.json", encoding="utf-8")).items():
        APPS[_k] = (_v[0], set(_v[1]), _v[2])
        if len(_v) > 3:
            APP_EXTRA[_k] = _v[3]
except (OSError, ValueError, IndexError):
    pass
_NUMW = {"sıfır": "0", "bir": "1", "iki": "2", "üç": "3", "dört": "4", "beş": "5", "altı": "6", "yedi": "7",
         "sekiz": "8", "dokuz": "9", "on": "10"}


def norm(t):
    t = str(t).replace("I", "ı").replace("İ", "i").lower()
    t = re.sub(r"[’`´]", "'", t)
    t = re.sub(r"[^\wçğıöşü' ]+", " ", t)
    t = re.sub(r"(\w)'(\w+)", r"\1 '\2", t)          # "youtube'dan" -> "youtube 'dan" (suffix marked)
    t = re.sub(r"\byou tube\b|\byu tub\b|\byu tube\b", "youtube", t)
    t = re.sub(r"\bsmart (tube|tub|tv)\b", r"smart\1", t)
    t = re.sub(r"\bgoogle play\b|\bplay store\b", "playstore", t)
    t = re.sub(r"\b(beleş|bereş|beles|belleş) ?(ti ?vi|tivi|tv|tevi|televizyon)", "beleştivi", t)
    return " ".join(t.split())


def stem(tok, vocab):
    """'youtubedan' -> 'youtube' if 'youtube' in vocab (glued suffix); returns None if no vocab stem."""
    tok = tok.lstrip("'")
    if tok in vocab:
        return tok
    for s in SUFFIXES:
        if tok.endswith(s) and tok[: -len(s)] in vocab:
            return tok[: -len(s)]
    # consonant softening: "yutubu"/"yutuptan" -> yutup/yutub
    for v in vocab:
        if len(v) >= 4 and tok.startswith(v[:-1]) and tok[len(v) - 1:] in [v[-1] + s for s in SUFFIXES] + \
                [{"p": "b", "t": "d", "k": "ğ", "ç": "c"}.get(v[-1], v[-1]) + s for s in SUFFIXES]:
            return v
    return None


def _app_of(tokens):
    """Index + app key of the first token naming an app (suffix-tolerant)."""
    for i, t in enumerate(tokens):
        for key, (_p, forms, _n) in APPS.items():
            if stem(t, forms):
                return i, key
    return None, None


def _clean_query(tokens):
    out = []
    for t in tokens:
        if t.startswith("'"):                         # a suffix split off by the apostrophe ("şarkı 'sını")
            if out and t[1:] not in ("da", "de", "dan", "den", "ta", "te", "tan", "ten"):
                out[-1] += t[1:]
            continue
        if t in PLAY_VERBS or t in SEARCH_VERBS or t in FILLER or VIDEO_WORDS.match(t):
            continue
        out.append(t)
    if out and out[0] == "bir":                       # "bir video aç" (but keep "Sıfır Bir")
        out = out[1:]
    return " ".join(out).strip()


def _num(tok):
    """'yedi' / 'yediyi' / '7yi' -> '7'."""
    tok = tok.lstrip("'")
    if tok in _NUMW:
        return _NUMW[tok]
    for s in SUFFIXES:
        if tok.endswith(s) and tok[: -len(s)] in _NUMW:
            return _NUMW[tok[: -len(s)]]
    return tok


def _chkey(name):
    return re.sub(r"\s*\(\d+p\)|\s*\[.*?\]", "", name).replace("I", "ı").replace("İ", "i").lower().replace(" ", "")


def find_channel(tokens, channel_names, fuzzy=True):
    """Longest channel name formed by 1-4 consecutive tokens (last token may carry a suffix)."""
    keys = [_chkey(n) for n in channel_names]
    toks = [_num(t) for t in tokens if not (t.startswith("'") and len(t) <= 5)]
    best, bl = None, 0
    for a in range(len(toks)):
        for b in range(a + 1, min(len(toks), a + 4) + 1):
            cand = "".join(toks[a:b])
            forms = {cand} | {cand[: -len(s)] for s in SUFFIXES if cand.endswith(s) and len(cand) - len(s) >= 2}
            for i, k in enumerate(keys):
                if k in forms and len(k) > bl:
                    best, bl = i, len(k)
    if best is None and fuzzy:                         # "kanaldi" / "habertürkü" / "sho tv"
        cand = "".join(t for t in toks if t not in PLAY_VERBS and t not in FILLER and t not in {"kanal", "kanalı",
                                                                                              "kanalını", "geç"})
        if 3 <= len(cand) <= 16:
            for c in [cand] + [cand[: -len(x)] for x in SUFFIXES if cand.endswith(x) and len(cand) - len(x) >= 3]:
                m = difflib.get_close_matches(c, keys, n=1, cutoff=0.8)
                if m:
                    best = keys.index(m[0]); break
    return best


WEB_ENGINES = {"google", "gugıl", "yandex", "bing", "internet", "web", "duckduckgo"}
MUSIC_VERBS = {"çal", "çalar", "çalsana", "dinle", "dinlet", "dinleyelim"}
SRC_WORDS = {"üzerinde", "üzerinden", "içinde", "içinden", "ile", "uygulamasında", "uygulamasından", "üstünde",
             "uygulamasıyla", "tarayıcısında", "tarayıcısından"}      # "Firefox üzerinde X ara"
SRC_SUFFIX = ("dan", "den", "tan", "ten", "da", "de", "ta", "te", "an", "en", "ndan", "nden", "nda", "nde")


def _source_app(tokens):
    """'Firefox'tan YouTube aç' / 'Kodi'den film aç' -> (app key, query tokens) when an app name carries an
    ablative/locative suffix (glued or after an apostrophe) and something follows."""
    for i, t in enumerate(tokens[:-1]):
        for key, (_p, forms, _n) in APPS.items():
            base = stem(t, forms)
            if not base:
                continue
            nxt = tokens[i + 1]
            glued = t.lstrip("'") != base and t.lstrip("'")[len(base):] in SRC_SUFFIX
            split_suffix = nxt.startswith("'") and nxt[1:] in SRC_SUFFIX or nxt in SRC_SUFFIX or nxt in SRC_WORDS
            if glued or split_suffix:
                rest = tokens[i + (2 if split_suffix else 1):]
                return key, rest
    return None, None


def parse(text, channel_names=(), current_app=None):
    n = norm(text)
    tokens = n.split()
    if not tokens:
        return {"act": None}
    has_play = any(t in PLAY_VERBS for t in tokens)
    has_search = any(t in SEARCH_VERBS for t in tokens)
    src, rest = _source_app(tokens)
    if src and src != "youtube":
        q = _clean_query(rest)
        if q:
            return {"act": "in_app", "app": src, "pkg": APPS[src][0], "name": APPS[src][2], "q": q,
                    "search": has_search and not has_play, "ch": find_channel(rest, channel_names)}
    i, key = _app_of(tokens)
    if key == "youtube":
        q = _clean_query(tokens[:i] + tokens[i + 1:])
        if q:
            return {"act": "yt_search" if has_search and not has_play else "yt_play", "q": q}
        return {"act": "app", "pkg": APPS["youtube"][0], "name": "YouTube"}
    if key and len(_clean_query(tokens[:i] + tokens[i + 1:])) <= 3:
        return {"act": "app", "pkg": APPS[key][0], "name": APPS[key][2]}
    ch = find_channel(tokens, channel_names, fuzzy=has_play or len(tokens) <= 3)
    if ch is not None:
        return {"act": "channel", "i": ch}
    if current_app == APPS["youtube"][0] and (has_play or has_search):    # "teneke kafalar aç" inside YouTube
        q = _clean_query(tokens)
        if q:
            return {"act": "yt_search" if has_search and not has_play else "yt_play", "q": q}
    # generic web phrases (no app named): "<engine>'da X ara", "X sitesini aç / sitesine gir"
    eng = next((k for k, t in enumerate(tokens) if stem(t, WEB_ENGINES)), None)
    if eng is not None and has_search:
        q = _clean_query(tokens[:eng] + tokens[eng + 1:])
        if q:
            return {"act": "in_app", "app": "web", "pkg": APPS["web"][0], "name": APPS["web"][2], "q": q,
                    "search": True, "ch": None}
    if any(t.lstrip("'").startswith("site") for t in tokens):
        q = _clean_query([t for t in tokens if not t.lstrip("'").startswith("site")])
        if q:
            return {"act": "in_app", "app": "web", "pkg": APPS["web"][0], "name": APPS["web"][2], "q": q,
                    "search": False, "ch": None}
    if any(t in MUSIC_VERBS for t in tokens):          # "X'in son şarkısını çal" -> play it on YouTube
        q = _clean_query(tokens)
        if q:
            return {"act": "yt_play", "q": q}
    if len(tokens) <= 2:                              # whole short phrase close to an app name ("Metafy")
        flat = "".join(t.lstrip("'") for t in tokens if t not in PLAY_VERBS)
        for key, (pkg, forms, name) in APPS.items():
            if difflib.get_close_matches(flat, list(forms), n=1, cutoff=0.75):
                return {"act": "app", "pkg": pkg, "name": name}
    return {"act": None}


if __name__ == "__main__":
    import sys
    chs = ["TRT 1 (1440p)", "TRT 2 (1440p)", "Kanal D (720p)", "Show TV", "Star TV", "ATV", "Habertürk (720p)",
           "Beyaz TV (720p)", "Euro D", "Now", "TV8", "Kanal 7 (720p)", "TRT Haber (720p)", "TRT Spor 2"]
    for t in sys.argv[1:]:
        print(repr(t), "->", parse(t, chs))
