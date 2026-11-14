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
