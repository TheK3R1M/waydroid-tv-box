#!/usr/bin/env python3
"""Understanding layer for the TV voice key: a small local LLM (llama-server, Qwen3-1.7B on this box) turns ONE
spoken Turkish sentence + the screen context into a structured decision

    {"eylem": <one of ACTIONS>, "uygulama": <installed app or "yok">, "hedef": <free text>}

A GBNF grammar forces valid JSON with only allowed actions/apps, so the model can't invent commands; the free
"hedef" (target) carries what the user named: a site, a search, a video, a channel, text to type.
Confidence = product of the probabilities of the tokens that spell the chosen action ("Jev"-style calibrated
selection): the caller acts, asks, or says "not understood" based on it.

The examples in the prompt are deliberately generic; they are not the household's own sentences, and the
held-out test set must never be copied into them."""
import http.client, json, math

ACTIONS = {
    "uygulama_ac": "bir uygulamayı aç (uygulama dolu)",
    "site_ac": "tarayıcıda bir web sitesine git (hedef = site adı veya adresi)",
    "web_ara": "tarayıcıda/internette arama yap, sonuçları göster (hedef = aranacak şey)",
    "uygulamada_ara": "bir uygulamanın içinde ara, sonuçları göster (uygulama + hedef)",
    "video_oynat": "YouTube'da bir videoyu/şarkıyı/diziyi bulup direkt oynat (hedef = ne izlenecek)",
    "kanal_ac": "canlı TV'de bir kanalı aç (hedef = kanal adı)",
    "kanal_sonraki": "sonraki kanala geç",
    "kanal_onceki": "önceki kanala geç",
    "kanal_listesi": "canlı TV kanal listesini göster",
    "ses_ac": "sesi yükselt",
    "ses_kis": "sesi azalt",
    "ses_kapat": "sesi tamamen kapat",
    "ses_ayarla": "sesi belirli bir seviyeye ayarla (hedef = sayı)",
    "yaz": "söylenen metni açık olan yazı alanına yaz (hedef = yazılacak metin, aynen)",
    "geri": "geri git / kapat",
    "ana_ekran": "ana ekrana dön",
    "duraklat": "oynatmayı duraklat veya devam ettir",
    "ekrani_bol": "ekranı ikiye böl, iki yayını birlikte izle",
    "anlasilmadi": "TV ile ilgisi yok veya anlaşılmıyor",
}

EXAMPLES = [  # (screen, field, sentence, eylem, uygulama, hedef) -- generic, NOT the household's test sentences
    ("Ana ekran", "hayır", "Chrome'da hava durumu ara", "web_ara", "Firefox", "hava durumu"),
    ("Ana ekran", "hayır", "vikipedi sitesini aç", "site_ac", "Firefox", "vikipedi"),
    ("Firefox", "hayır", "github'a gir", "site_ac", "Firefox", "github"),
    ("Firefox", "evet", "kırmızı elbise modelleri", "yaz", "yok", "kırmızı elbise modelleri"),
    ("Firefox", "evet", "tarayıcıdan haber sitesi aç", "site_ac", "Firefox", "haber sitesi"),
    ("Ana ekran", "hayır", "YouTube'u başlat", "uygulama_ac", "YouTube", ""),
    ("Firefox", "hayır", "YouTube uygulamasını aç", "uygulama_ac", "YouTube", ""),
    ("Ana ekran", "hayır", "YouTube'da kedi videoları ara", "uygulamada_ara", "YouTube", "kedi videoları"),
    ("Ana ekran", "hayır", "YouTube'dan Sezen Aksu dinlet", "video_oynat", "YouTube", "Sezen Aksu"),
    ("YouTube", "hayır", "son çıkan maç özetini aç", "video_oynat", "YouTube", "son maç özeti"),
    ("Ana ekran", "hayır", "Kodi'yi çalıştır", "uygulama_ac", "Kodi", ""),
    ("Ana ekran", "hayır", "TRT 1'e geç", "kanal_ac", "yok", "TRT 1"),
    ("Canlı TV", "hayır", "bir sonrakine geç", "kanal_sonraki", "yok", ""),
    ("Canlı TV", "hayır", "hangi kanallar var", "kanal_listesi", "yok", ""),
    ("Canlı TV", "hayır", "biraz daha sesli olsun", "ses_ac", "yok", ""),
    ("Ana ekran", "hayır", "sesi yüzde elliye getir", "ses_ayarla", "yok", "50"),
    ("YouTube", "hayır", "sessize al", "ses_kapat", "yok", ""),
    ("YouTube", "hayır", "bir dakika dursun", "duraklat", "yok", ""),
    ("Ana ekran", "hayır", "yarın yağmur yağacak mı", "anlasilmadi", "yok", ""),
]


def _q(s):
    return str(s).replace("\\", "").replace('"', "'").replace("\n", " ")


def grammar(apps):
    act = " | ".join(f'"{a}"' for a in ACTIONS)
    app = " | ".join(['"yok"'] + [f'"{_q(a)}"' for a in apps])
    return f'root ::= act " | " app " | " hedef "\\n"\nact ::= {act}\napp ::= {app}\n' 'hedef ::= [^\\n|]{0,70}\n'


def system_prompt(apps, channels):
    acts = "\n".join(f"- {k}: {v}" for k, v in ACTIONS.items())
    ex = "\n".join(f'Ekran: {c} | Yazı alanı: {f} | Cümle: "{s}"\n{e} | {a} | {h}' for c, f, s, e, a, h in EXAMPLES)
    return ("Sen bir televizyonun sesli asistanısın. Kullanıcının Türkçe cümlesini ve ekran durumunu okuyup TEK bir "
            "karar verirsin. Cevap biçimi: eylem | uygulama | hedef. Hedef, kullanıcının bu cümlede söylediği "
            "site/arama/video/kanal/metindir; yoksa boş bırak, örneklerden kopyalama.\n"
            "Kurallar: Cümlede bir uygulama adı geçiyorsa o uygulamayı kullan; ekranda açık olan uygulama sadece "
            "cümle uygulama söylemiyorsa ipucudur. 'ara' sonuç listesi demektir, 'aç/gir/git' doğrudan oraya gitmek. "
            "Yazı alanı açıkken cümle bir komut değilse eylem 'yaz' olur ve hedef cümlenin kendisidir. "
            "Konuşma tanıma hatalı olabilir: kulağa benzeyen uygulama/kanal adını seç (ör. 'fayır foks' = Firefox).\n\n"
            f"Eylemler:\n{acts}\n\nYüklü uygulamalar: {', '.join(apps)}\n"
            f"Kanallar: {', '.join(channels[:60])}\n\nÖrnekler:\n{ex}")


def understand(text, ctx, apps, channels, host="127.0.0.1", port=8179, timeout=20):
    """ctx = {"screen": "Firefox" | "YouTube" | "Canlı TV" | "Ana ekran" | ..., "field": bool}.
    Returns ({"eylem", "uygulama", "hedef"}, confidence 0..1 = product of the action tokens' probabilities)."""
    user = (f'Ekran: {_q(ctx.get("screen") or "Ana ekran")} | Yazı alanı: {"evet" if ctx.get("field") else "hayır"} | '
            f'Cümle: "{_q(text)[:200]}"')
    prompt = (f"<|im_start|>system\n{system_prompt(apps, channels)}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n"
              f"<|im_start|>assistant\n<think>\n\n</think>\n\n")
    c = http.client.HTTPConnection(host, port, timeout=timeout)
    c.request("POST", "/completion", json.dumps({"prompt": prompt, "grammar": grammar(apps), "n_predict": 40,
                                                 "temperature": 0, "n_probs": 1, "cache_prompt": True}).encode(),
              {"Content-Type": "application/json"})
    r = json.loads(c.getresponse().read()); c.close()
    out = r.get("content", "").strip()
    parts = [p.strip() for p in out.split("|")] + ["", "", ""]
    conf, acc = 1.0, ""
    for t in r.get("completion_probabilities") or []:
        acc += t.get("token", "")
        conf *= t["prob"] if "prob" in t else math.exp(t.get("logprob", 0))
        if "|" in acc:
            break
    return {"eylem": parts[0] if parts[0] in ACTIONS else "anlasilmadi", "uygulama": parts[1] or "yok",
            "hedef": parts[2]}, round(conf, 3)


if __name__ == "__main__":        # manual check / warm-up
    import sys, time, urllib.request
    for _ in range(90):
        try:
            urllib.request.urlopen("http://127.0.0.1:8179/health", timeout=1); break
        except Exception:
            time.sleep(1)
    t = time.time()
    print(understand(" ".join(sys.argv[1:]) or "ısınma", {"screen": "Ana ekran", "field": False},
                     ["Firefox", "YouTube", "Kodi"], ["TRT 1", "Kanal D"], timeout=300), f"{time.time() - t:.1f}s")
