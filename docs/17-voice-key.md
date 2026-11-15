# 17. Voice key (offline speech -> commands / typing)

The remote's voice key works everywhere, without Google and without sending audio anywhere: hold the key, speak,
release. The phrase is turned into text on the box itself and either runs a command or is typed into the text
field that is open on the TV.

## 17.1 How it works

```
remote mic (USB audio in the dongle) --parecord--> tv-voice.py --WAV over unix socket--> whisper-server (tv-whisper)
        voice key (evdev, held) ------------------^                         |
                                                     text  <----------------+
tv-voice.py --POST /voice {text} (loopback only)--> tv-remote.py: command? run it : type into the focused field
```

- `tv-voice.service` (`/usr/local/bin/tv-voice.py`, system python3 + python3-evdev): finds the dongle by
  `REMOTE_MATCH` (devices that have `KEY_VOICECOMMAND`), records `MIC_MATCH` source while the key is held
  (cap 7 s; a press+release shorter than 0.35 s = fixed 5 s window for remotes without hold events), keeps audio
  in memory only, posts the text to tv-remote. Shows "● Dinliyorum…" on the TV while a channel plays.
- `tv-whisper.service`: whisper.cpp `whisper-server` on a **unix socket** (`/run/tv-whisper/whisper.sock`, no TCP
  port), model `ggml-small-q5_1` (190 MB), `-l tr -t 3 -ac 384 -bs 1`. `-ac 384` (audio context ~7.7 s) is what
  makes it fast enough: whisper otherwise always encodes a 30 s window.
- `tv-remote.py` `voice_cmd()`: `POST /voice` is accepted from loopback only (403 from the LAN).

## 17.2 Install

```bash
apt install build-essential cmake git
mkdir -p /opt/tv-voice && cd /opt/tv-voice
git clone --depth 1 https://github.com/ggml-org/whisper.cpp && cd whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j3
sh ./models/download-ggml-model.sh small-q5_1 /opt/tv-voice/models
install -m755 files/usr/local/bin/tv-voice.py /usr/local/bin/
cp files/etc/systemd/system/tv-{whisper,voice}.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now tv-whisper tv-voice
```

Set `REMOTE_MATCH` / `MIC_MATCH` in `tv-voice.py` for your remote (`grep '^N:' /proc/bus/input/devices`,
`pactl -s unix:/run/tv/pulse/native list short sources`). Remotes with a mic usually only deliver audio while the
voice key is held; use `parecord ... --latency-msec=40` (without it parecord may buffer and return nothing).

## 17.3 What you can say (Turkish)

| Phrase | Result |
|---|---|
| "TRT 1 aç", "Kanal D'yi aç", "Show TV", "Star" | channel by name (number words are converted: "bir" -> 1; longest name match wins) |
| "sonraki kanal", "önceki kanal", "kanal yukarı/aşağı" | channel ±1 |
| "sesi aç", "sesi kıs", "sesi kapat", "ses normal", "sesi yüzde 40 yap" | host volume |
| "YouTube'da kedi videoları ara" | opens SmartTube with that search ❔ (SmartTube handling of results URLs unverified) |
| "geri", "ana ekran", "durdur/devam", "ekranı böl", "tek ekran" | keys / split screen |
| anything else | typed into the open text field (search boxes); if no field is open: "anlaşılmadı" |

When a text field is open, a bare channel name ("show tv") is typed instead of switching channel; add a verb
("show tv aç") to switch. Every phrase is logged in the remote log as `sesli: «...» → action`.

## 17.4 Measured (Ryzen Embedded R2314, 4 cores) ✅

Synthetic Turkish speech: 2.4–2.7 s from release to text with `-ac 384 -t 3` (30 s window: ~4.5 s;
faster-whisper small int8: ~4.5 s; whisper base: 1.2 s but poor Turkish). Accuracy on the test phrases: correct
apart from "kıs" heard as "kız" (handled in the parser). Real-voice accuracy through the remote mic ❔.

## 17.5 Privacy

Audio never leaves the box and is never written to disk. The speech server has no network port. Do not swap in a
cloud speech API without the owner's consent.

## 17.6 Calibrated intent selection (local LLM) ✅ offline / ❔ by voice

Phrases the exact rules don't catch go to a small local model that **selects** one action from a fixed menu
(letters A–O); the next-token probability over the letters is the confidence:

| Confidence | Behaviour |
|---|---|
| ≥ 85 % | act |
| 45–85 % | while a channel plays: "Bunu mu demek istediniz?" list on the TV (▲▼ + OK, "Hiçbiri") |
| lower, or "not TV related" | "anlaşılmadı" (nothing happens) |

- `tv-llm.service`: llama.cpp `llama-server` on `127.0.0.1:8179` (loopback only), `Qwen3-1.7B-Q4_K_M` (1.3 GB),
  `-t 3`, CPUQuota 300 %. `files/usr/local/bin/tv-intent.py` builds the prompt (action menu, channel names,
  28 few-shot examples) and reads `n_probs`. The long prompt stays in llama-server's prompt cache; tv-remote
  re-warms it every 5 min (a cache miss = ~20 s on this CPU, a hit = ~1.3 s).
- If an intrusion checker watches host ports (docs/15), add `tcp 127.0.0.1:8179` to its baseline first.
- Build: `git clone --depth 1 https://github.com/ggml-org/llama.cpp && cmake -B build -DLLAMA_CURL=OFF &&
  cmake --build build -j3 --target llama-server`; model from `ggml-org/Qwen3-1.7B-GGUF`.

Benchmark on the reference box (46 Turkish phrases, 15 intents, model alone):

| Model | Correct | Median latency |
|---|---|---|
| Qwen3-1.7B Q4_K_M, few-shot | 35/46 | 1.2 s |
| Qwen3-1.7B Q4_K_M, zero-shot | 32/46 | 1.1 s |
| Qwen3-0.6B Q8_0 | 17/46 | 0.6 s |
| FunctionGemma 270M Q8_0 (no fine-tune) | 0/46 | 2.1 s |

Most model misses ("sesi kapat", "sustur", "YouTube", "Firefox", "durdur") are caught earlier by the rules, so
rules + model handle nearly all test phrases. FunctionGemma needs task fine-tuning before it is useful here.

## 17.7 Turkish parsing and recogniser prompt ✅ offline

- `files/usr/local/bin/tv-nlu.py` (pure functions, runs before the model): strips Turkish case suffixes glued
  to names (`YouTube'dan`, `youtubedan`, `yutuptan`, `Kanal D'ye`, `Netfly'ı`, `yediyi`), knows frequent
  mis-hearings of app names (`yutup`, `Smart TV` -> YouTube), and finds YouTube requests in any word order.
  - `YouTube'dan teneke kafalar aç` / `... izle` / `dinle` -> plays the **first result** (tv-remote reads the
    videoId from YouTube's results page on the host and sends a watch link to SmartTube).
  - `YouTube'da ... ara` / `bul` -> shows the results.
  - `Kodi aç`, `VLC aç`, `ayarları aç` -> launches the app (resolved via `cmd package resolve-activity`).
    Box-specific apps go in `/etc/tv/voice-apps.json` (`{"key": ["package", ["spoken", "forms"], "Name"]}`),
    not in the script.
  - While YouTube is in front, `teneke kafalar aç` alone also plays on YouTube.
- Whisper prompt = a natural Turkish command sentence. Measured with 25 TTS phrases (+ noise, band-limited):

| whisper.cpp config | similarity | exact | median |
|---|---|---|---|
| small q5_1, prompt = list of channel names | 0.914 | 11/25 | 3.7 s |
| small q5_1, prompt = natural command sentence | 0.958 | 17/25 | 4.1 s |
| large-v3-turbo q5_0, `-ac 384` | 0.693 (repeats) | 5/25 | 26 s |

  The channel-name list made whisper answer in capitals and invent channel names; turbo is too slow on a 4-core
  embedded Ryzen and repeats itself with a reduced audio context.
- Quiet mics: the clip is peak-normalised before recognition. The last 20 clips are kept in
  `/run/tv-voice/clips` (RAM only) to tune with real voices; delete the `keep_clip` call to disable.

## 17.8 Assistant bar, dictation and "<app>'dan …" commands ✅ (offline-tested, real voice ❔)

**Visible state (like Google Assistant).** `tv-voice` posts `/voice/listen` on key press and `/voice/think` on
release; tv-remote then shows a bar with four coloured dots: bouncing = listening, pulsing = thinking, still =
answer (the recognised sentence + what was done), red = not understood.
- On Android: `android/asistan/` builds a tiny overlay APK (`org.tvbox.asistan`, javac + d8 + aapt2 on the host,
  same key as the Kanallar tile). Its receiver is protected by `android.permission.DUMP` (only the adb shell
  holds it) and draws a `TYPE_APPLICATION_OVERLAY` window that is **not focusable**, so a search field keeps
  focus while you dictate. One-time setup: `appops set org.tvbox.asistan SYSTEM_ALERT_WINDOW allow` and
  `cmd deviceidle whitelist +org.tvbox.asistan`.
  Do not add `FLAG_NOT_TOUCHABLE`: Android 12+ caps pass-through overlays at 80 % opacity (unreadable on video).
- On live TV (host mpv): the same bar as an mpv osd-overlay.

**Dictation first.** When a text field is focused (search box, address bar), speech is typed verbatim. Only
these are commands there: `ara / tamam / git` (submit), `sil / temizle` (clear), `geri / kapat`, and explicit
`<app>'dan …` phrases. Saying "YouTube" in Firefox's search box types "YouTube" instead of opening an app.

**`<app>'dan / 'da <x> aç|ara`** (tv-nlu `_source_app`): the app name carries an ablative/locative suffix.
- Firefox: `Firefox'tan YouTube aç` = youtube.com in Firefox; `Firefox'tan Radio Garden aç` = first web result
  (DuckDuckGo `!`); `… ara` = web search. While Firefox is in front, "YouTube aç" also stays in Firefox.
  Set Firefox's *Open links in apps* to **Never** (`pref_key_open_links_in_apps` =
  `pref_key_open_links_in_apps_never` in `fenix_preferences.xml`), otherwise Firefox itself offers to hand
  youtube.com over to the YouTube app.
- Apps with a search deep link or add-on links are configured in `/etc/tv/voice-apps.json` (4th element:
  `{"search": "<scheme>:///search?search={q}", "addon_scheme": "<scheme>"}`), not in code.
- Apps that can't be driven from outside (no deep links, state-dependent menus) get the channel in the host's
  own channel list instead, and the bar says so. Blind D-pad automation of such apps paused and zapped the
  family's stream in tests; don't ship it.

**Add-on links.** The phone remote's "Link gönder" routes `…/manifest.json` (or `<addon_scheme>://…`) links to
the app configured with `addon_scheme`, which opens its own install page.

**Recogniser model check with real household clips** (20 clips kept in RAM, see 17.7): a Turkish fine-tune of
whisper-small was *not* better than stock small with the natural prompt (spelled names phonetically:
"Atevi", "Firefoks", "Yutup"); most real failures were parsing/context, fixed above.
