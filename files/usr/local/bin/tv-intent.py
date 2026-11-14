#!/usr/bin/env python3
"""Intent selector for the TV voice key: a small local LLM picks ONE letter from a fixed action menu.
The next-token probabilities over the letters are the confidence (calibrated selection, 'Jev'-style):
  >= HIGH  -> act,  >= MID -> show the top choices on the TV,  else -> 'anlaşılmadı'.
The long fixed prompt is cached in llama-server (cache_prompt), so only the spoken sentence is evaluated."""
import http.client, json, socket

ACTIONS = [  # letter, id, Turkish description shown to the model (and to the user in the choice list)
    ("A", "channel", "Belirli bir TV kanalını aç / o kanala geç"),
    ("B", "ch_next", "Sonraki kanala geç"),
    ("C", "ch_prev", "Önceki kanala dön"),
    ("D", "ch_list", "Kanal listesini göster"),
    ("E", "vol_up", "Sesi aç / yükselt"),
    ("F", "vol_down", "Sesi kıs / azalt"),
    ("G", "mute", "Sesi tamamen kapat / sessize al"),
    ("H", "yt_search", "YouTube'da bir şey ara veya bir video aç"),
    ("I", "yt_open", "YouTube uygulamasını aç"),
    ("J", "web", "İnternet tarayıcısını aç"),
    ("K", "back", "Geri git / bu ekranı kapat"),
    ("L", "home", "Ana ekrana dön"),
    ("M", "play", "Videoyu duraklat veya devam ettir"),
    ("N", "split", "Ekranı ikiye böl, iki yayını birlikte izle"),
    ("O", "none", "TV ile ilgisi yok / anlaşılmadı"),
]
LETTERS = [a[0] for a in ACTIONS]


EXAMPLES = [  # phrasings differ from the benchmark set on purpose
    ("Fox'u aç", "A"), ("NOW TV'ye geçelim", "A"), ("TRT haber koy", "A"),
    ("diğer kanala geç", "B"), ("kanalı değiştir", "B"), ("geri kanala dön", "C"),
    ("hangi kanallar var bakalım", "D"), ("biraz daha sesli olsun", "E"), ("hiç duyulmuyor", "E"),
    ("ses çok fazla", "F"), ("biraz alçalt", "F"), ("sesi tamamen kes", "G"), ("sessiz olsun", "G"),
    ("YouTube'da tarkan şarkıları", "H"), ("youtube'dan yemek tarifi bul", "H"), ("YouTube'a gir", "I"),
    ("SmartTube'u aç", "I"), ("internette bir şeye bakalım", "J"), ("Chrome aç", "J"),
    ("vazgeç kapat", "K"), ("bir önceki ekrana dön", "K"), ("başa dön ana sayfa", "L"),
    ("bekle bir saniye durdur", "M"), ("oynatmaya devam", "M"), ("iki yayını yan yana aç", "N"),
    ("yarın hava yağmurlu mu", "O"), ("annem nerede", "O"), ("eee", "O"),
]


def build_prompt(text, channels, chatml=True):
    menu = "\n".join(f"{l}) {d}" for l, _, d in ACTIONS)
    shots = "\n".join(f'"{u}" -> {a}' for u, a in EXAMPLES)
    sys_ = ("Sen bir televizyon kumandasının sesli komut seçicisisin. Kullanıcının söylediği cümleye en uygun "
            "TEK eylemin harfini yaz. Sadece harfi yaz. Cümle bir kanal adı içeriyorsa ve kanal açmak istiyorsa A. "
            "TV ile ilgisi olmayan sorular O.\n\nEylemler:\n" + menu +
            "\n\nKanallar: " + ", ".join(channels[:45]) + "\n\nÖrnekler:\n" + shots)
    if chatml:
        return (f"<|im_start|>system\n{sys_}<|im_end|>\n<|im_start|>user\n\"{text}\"<|im_end|>\n"
                f"<|im_start|>assistant\n<think>\n\n</think>\n\n")
    return (f"<start_of_turn>user\n{sys_}\n\n\"{text}\" -> <end_of_turn>\n<start_of_turn>model\n")


def classify(text, channels, host="127.0.0.1", port=8179, unix=None, chatml=True, timeout=20):
    body = json.dumps({"prompt": build_prompt(text, channels, chatml), "n_predict": 1, "n_probs": 40,
                       "temperature": 0, "cache_prompt": True}).encode()
    if unix:
        class C(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX); self.sock.settimeout(timeout); self.sock.connect(unix)
        c = C("localhost", timeout=timeout)
    else:
        c = http.client.HTTPConnection(host, port, timeout=timeout)
    c.request("POST", "/completion", body, {"Content-Type": "application/json"})
    r = json.loads(c.getresponse().read()); c.close()
    probs = {}
    for t in r["completion_probabilities"][0]["top_logprobs" if "top_logprobs" in r["completion_probabilities"][0] else "top_probs"]:
        tok = t["token"].strip()
        p = t["prob"] if "prob" in t else __import__("math").exp(t["logprob"])
        if tok in LETTERS:
            probs[tok] = probs.get(tok, 0) + p
    tot = sum(probs.values()) or 1
    ranked = sorted(((p / tot, l) for l, p in probs.items()), reverse=True)
    return [(dict((a[0], a[1]) for a in ACTIONS)[l], round(p, 3)) for p, l in ranked], round(tot, 3)


if __name__ == "__main__":       # warm-up after tv-llm starts: fills the prompt cache with the channel list
    import re, sys, time, urllib.request
    for _ in range(90):
        try:
            urllib.request.urlopen("http://127.0.0.1:8179/health", timeout=1); break
        except Exception:
            time.sleep(1)
    names = []
    for f in ("/etc/tv/turkiye.m3u", "/etc/tv/extra.m3u"):
        try:
            names += [re.sub(r"\s*\[(Not 24/7|Geo-blocked)\]", "", l.split(",")[-1]).strip()
                      for l in open(f, encoding="utf-8") if l.startswith("#EXTINF")]
        except Exception:
            pass
    t = time.time(); print(classify("ısınma", names, timeout=300), f"{time.time() - t:.1f}s")
