# 08 · Live channels, host mpv, split screen

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


### 8.1 Channel list (`tv-channels.py`)

The remote's channel list is a curated list, not the raw iptv-org dump. `tv-channels.py` builds `/etc/tv/turkiye.m3u`:
- a fixed `WANT` order (Ulusal → Haber → Spor → Belgesel → Çocuk → Müzik → Diğer);
- candidates from the broadcasters' own web players first (an `EXTRA` dict), then iptv-org `countries/tr.m3u` + `languages/tur.m3u`;
- each candidate is **probed from the box** (master and first variant must answer with `#EXTINF`, two tries). A small `KEEP` set stays even when briefly down;
- writes the file only with `--write` and only if ≥ 25 channels pass; keeps the old file as `.bak`.

Procedure:

```bash
printf '#EXTM3U\n' > /etc/tv/turkiye.m3u                        # first run only: the script reads it as a source
curl -fL https://iptv-org.github.io/iptv/countries/tr.m3u -o /tmp/tr_new.m3u    # ❔ URL is the standard iptv-org path; check it
python3 /usr/local/bin/tv-channels.py            # report only (OK / YOK per channel)
python3 /usr/local/bin/tv-channels.py --write    # writes /etc/tv/turkiye.m3u
```

Notes:
- The probe takes minutes. Run it while nobody is watching (it loads the box).
- The report lists `YOK` channels honestly. Some official CDNs time out for hours; do not add restreams from random GitHub accounts.
- Some turknet CDN 1080p variants answer in 6–10 s or time out while 720p is instant; the script pins those to `_720p`.
- ❔ In the kit, three EXTRA entries (Show TV, Teve2, Habertürk) carry the placeholder `app=<APP_UUID_FROM_BROADCASTER_PAGE>`. The probe reports them as YOK until you fill the static `app=` value from that broadcaster's live page (see "Finding a missing channel's stream" below). The app IDs are per-site web-player values, so they are not in the repo.
- ✅ Last run (2026-11-04) had 44 working channels; list stored on the host as `/etc/tv/turkiye.m3u` (not in the kit: it contains per-session stream tokens).

`/etc/tv/devices.json` (used for the audit log, [§9.4](09-web-remote.md)) is also not in the kit. Create it empty first (`echo '{}' > /etc/tv/devices.json`) and fill it with `{"<MAC address>": "Phone name"}` entries from your router's client list. Do not put router credentials on this host.

### 8.2 The persistent mpv window

`tv-remote.py` starts one mpv that stays open (`--idle=yes`); every channel change is an IPC `loadfile`, never a new mpv process. Restarting mpv per change made kiosk-shell put Android back on top about half the time.

The exact command (from `tv-remote.py`):

```bash
mpv --msg-level=all=warn,cplayer=info --idle=yes --force-window=yes --fs --no-osc \
    --no-input-default-bindings --cursor-autohide=always --background-color=#000000 \
    --hwdec=vaapi-copy --vo=gpu --gpu-context=wayland --ao=pulse --cache=yes \
    --demuxer-readahead-secs=5 --network-timeout=15 \
    --input-ipc-server=/run/tv/mpv-split.sock
```

Environment: `/etc/tv/env` (Wayland, PulseAudio socket). Log: `/var/log/tv-split.log` (mpv's own output, no timestamps).

While mpv is up, Android is put to sleep (`input keyevent 223`) to save CPU and to stop Android redraws from raising it over mpv; `224` wakes it on close. Do not send HOME while mpv is up (it wakes Android).

IPC rules:
- JSON named args, e.g. `{"command":["loadfile", url, "replace", -1, {"lavfi-complex": "..."}]}` (or the named form the code uses).
- Set list options (`external-files`, `audio-files`) with `set_property` and a JSON array. Never comma-join URLs.
- **Never change `lavfi-complex` at runtime** — it froze the picture for 4+ seconds. Build the graph at load time.

### 8.3 Split screen design

Left and right are two inputs in one `lavfi-complex` graph (set at load time):

```
[vid1]P[l];[vid2]P[r];[l][r]hstack[vo];[aid1]...amerge...[ao]
P = scale=960:540:force_original_aspect_ratio=decrease,pad=960:1080:-1:-1,setsar=1,fps=25
```

- `fps=25` on **both** inputs. Without it, a 25 fps TV + 30/60 fps YouTube dropped ~49 frames/s.
- Each side must contribute exactly one video and one audio track. Resolve HLS masters to one ≤1080p variant yourself, or mpv lists every variant as a track and `vid2` becomes the wrong stream.
- YouTube: `yt-dlp -g -f 'bv*[height<=1080][fps<=30][vcodec^=avc1]+ba[ext=m4a]/...'` → one video URL + one audio URL.
- **Sound switch is instant:** both audios are mixed (`amerge`), and the runtime `af` filter picks the side: `pan=stereo|c0=c0|c1=c1` for left, `c0=c2|c1=c3` for right. Verified with 440/1000 Hz test tones. Switching sides no longer reloads.
- **A dead source kills the whole split** (`Can not open external file`, `Pad vid2 is not connected`). The code probes each source (master fetch, 5 s timeout), picks the next answering channel, waits for `estimated-vf-fps` after `loadfile`, and restores the previous sources on failure ("Kanal açılamadı" on the remote).
- Split state: `side` (which half the channel list targets) and `audio` (which half you hear). After "Ekranı böl" the list targets the new right half, sound stays left. Back keeps the half you hear.

Remote semantics (owner's model): tapping a channel plays it full screen; up/down = channel ±1; "Ekranı böl" = split (left = current, right = next); in split, left/right choose the side; Back = leave split on the heard half; Back again = Android; app buttons and uploads close mpv first. A watchdog (`_split_watch`) reloads mpv if `time-pos` is stuck for ~10 s or `avsync` is off by > 3 s twice in a row, and logs `görüntü donmuştu → oynatıcı otomatik yenilendi`.

Measured on this hardware: single channel ~10 % CPU (VA-API copy path), split ~40 % of the box, 0 dropped frames.
