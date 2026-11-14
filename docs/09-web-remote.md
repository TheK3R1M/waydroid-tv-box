# 09 · Web remote (tv-remote)

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


### 9.1 Install

Files (installed by 3.8):
- `/usr/local/bin/tv-remote.py` (stdlib `ThreadingHTTPServer`, Python 3.13 on the host)
- `/usr/local/share/tv-remote/index.html` (the page; read per request, so an edit needs no restart)
- `/etc/systemd/system/tv-remote.service`

```bash
systemctl enable --now tv-remote
journalctl -u tv-remote -n 20 --no-pager
curl -s -o /dev/null -w '%{http_code}\n' http://__TV_HOST_IP__:8090/      # 200
```

The service listens on `0.0.0.0:8090` (HTTP) and, if `/etc/tv/tls/fullchain.pem` and `privkey.pem` exist, on `0.0.0.0:443` (HTTPS). Without the cert files the HTTPS thread just retries every 30 s and HTTP keeps working. ✅ (read in the code; HTTPS was verified only with the real cert.)

Phones open `http://__TV_HOST_IP__:8090` and choose "Add to home screen" (the manifest is `display: fullscreen`, so it opens without browser bars).

### 9.2 Access rules (enforced in code)

- Only `__LAN_CIDR__` and loopback may connect. Other source IPs get 403.
- Host header allowlist: `__TV_HOSTNAME__`, `__TV_HOST_IP__`, `localhost`, `127.0.0.1`. Blocks DNS rebinding.
- Every POST needs `Origin` equal to an allowed host (browsers always send Origin on POST: blocks CSRF from other sites), or the header `X-TV: 1` (non-browser clients). Loopback is exempt.
- `X-Frame-Options: DENY`, `nosniff`, `no-referrer`.
- Actions are a whitelist. Keys map to fixed keycodes; apps map to fixed components; no request data reaches a shell unfiltered.

Test from the admin PC (expected results):
```bash
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example' http://__TV_HOST_IP__:8090/      # 403
# Use a non-existent key name: it is rejected (400) and sends nothing to Android. Never test with a real key while someone watches.
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Origin: https://evil.example' http://__TV_HOST_IP__:8090/key/nosuchkey   # 403
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'X-TV: 1' http://__TV_HOST_IP__:8090/key/nosuchkey                       # 400 (allowed, unknown key)
```

### 9.3 Endpoints

| Method | Path | Action |
|---|---|---|
| GET | `/` | the remote page |
| GET | `/manifest.json`, `/icon.svg` | PWA manifest and icon |
| GET | `/state` | `{vol, muted, app, split, …}` (polled every 4 s by the page) |
| GET | `/channels` | channel list (JSON) |
| GET | `/log` | last 200 audit lines, newest first (HTML) |
| POST | `/key/<name>` | `up down left right ok back home menu play rew ff settings del search apps enter`. In split mode `left/right` pick a side, `up/down` change channel, `back/home` leave split |
| POST | `/app/<youtube\|tv\|web>` | open the app (closes mpv first) |
| POST | `/vol/<up\|down\|mute\|normal\|set?v=N>` | volume on the HDMI sink, clamped 0–150 (above 100 = software boost, shown in orange). Returns the new state |
| POST | `/ch/<i\|next\|prev>` | channel by index or step |
| POST | `/split/<on\|off\|left\|right>` | split screen control |
| POST | `/kb/on`, `/kb/off`, `/kb/reset`, `/kb/enter` | keyboard mode (ADBKeyboard) and "Ara"/Enter on the focused field |
| POST | `/kb/clear` | empty the focused TV field (explicit only) |
| POST | `/type` | JSON `{"text": "...", "prev": "..."}` (v17): only the change is typed (DEL keys + appended text). Never clear+retype: some live-TV apps close their search box when the field becomes empty. Without `prev` the old clear+retype path is used |
| POST | `/mouse` | JSON `{"dx","dy","w","b"}`: phone touchpad / gyro → uinput mouse (§9.5) |
| POST | `/upload?name=` | raw body → `/var/tmp/tv-media`, then `adb push` and open in Kodi |
| POST | `/link` | JSON `{"url"}`: YouTube → SmartTube, video → Kodi, other → Firefox (browser) |
| POST | `/sys/tvrestart`, `/sys/reboot` | recovery buttons (2 s hold on the page, logged) |

Unknown paths and bad values return 400/404.

Every POST must come from the page itself: `Host` must be in `ALLOWED_HOSTS` (blocks DNS rebinding) and `Origin` must be the remote's own origin (blocks CSRF from any other website opened on a household phone/PC); non-browser LAN clients need the `X-TV: 1` header; loopback is exempt. Optional header `X-TV-Device` (URL-encoded name) names the device in the log.

### 9.4 Audit log

Every action appends `time \t device \t ip \t action` to `/var/log/tv-remote.log` (trimmed to 3000 lines). `GET /log` shows the last 200 entries. The device name comes from `ip neigh show <ip>` → MAC → `/etc/tv/devices.json`. Keep that file's MAC list current when new phones show up as bare IPs. Phones that come in through a Tailscale/Headscale subnet router all carry the router's IP: put it in `ROUTER_IPS` (`__VPN_ROUTER_IP__`); the page then asks such a phone for a name once and sends it as `X-TV-Device` (logged with " (VPN)"). This is a convenience label, not authentication.

Freeze count (per day): `grep 'donmuştu' /var/log/tv-remote.log | cut -c1-10 | uniq -c`.

### 9.5 Phone mouse (Fare sheet)

- Touchpad: drag = move (with mild acceleration), tap < 300 ms = click, two fingers = wheel (one step per 28 px), hold 450 ms + drag = drag.
- Gyro: works only on a secure page (https), and only if the owner grants motion permission. Rotation rates are deg/s around device X/Y/Z; yaw = rate projected on gravity; ~25 px/deg. A finger on the pad pauses the gyro.
- The host creates a uinput device **`TV Kumanda Fare`** (python3-evdev). Weston passes it to Android as a Wayland pointer. Hover works in Android; the pointer sprite is not in `screencap`.
- ✅ Verified with CDP sensor overrides and posted events. ❔ Real-phone gyro feel not tested.

### 9.5b PC mode (v17)

On a wide screen with a real mouse (`min-width:1000px and pointer:fine`) the page switches to PC mode: remote on the left, channel list and mouse pad always open next to it. Keyboard: arrows = D-pad, Enter = OK, Esc/Backspace = back, Home, Space = play/pause, +/- volume, M mute, K channel search, any letter opens "Yaz" and types it. Click the mouse pad to lock the PC mouse to the TV (Pointer Lock): moves, left/right click, wheel and drag go to Android; Esc releases.

### 9.5c Channel quality

`best_variant()` picks the highest resolution <= 1080p, ties and playlists without `RESOLUTION` by `BANDWIDTH` (not `AVERAGE-BANDWIDTH`). Before v17 the first listed variant won when `RESOLUTION` was missing, which played the lowest bitrate on some CDNs. Audit with a script that prints each master's variants and the pick.

### 9.6 Remote UI rules (keep these when editing the page)

- One screen, no tabs: status line → volume → D-pad → Back/Play/Home → dock (Kanallar · Yaz · Ekranı böl · Diğer). Secondary things open as bottom sheets.
- D-pad gestures (the owner relies on them): tap a sector = one step, centre = OK, hold = repeat (450 ms delay, 150 ms interval, capped at 4 s), slide = one step per ~26 px. A slide that starts on OK must not send OK.
- Auto-repeat stops on `visibilitychange`, `blur`, `pagehide`, `pointercancel`, `lostpointercapture`.
- Layout height locked in JS; `interactive-widget=overlays-content` so the phone keyboard does not resize the page.
- Every adb command is acked ([§7.3](07-adb.md)); a silent shell is reconnected, not ignored.
- Test any UI change on a local mock at 360x640, 390x780, 412x915 before deploying to the live box.

### 9.7 Deploy an update without interrupting the family

Copy the new file in place (Python has the old one loaded), then restart when nobody is using the TV:

```bash
cp /root/new/tv-remote.py /usr/local/bin/tv-remote.py
systemd-run --unit=tv-remote-deploy --collect /usr/local/bin/tv-remote-restart-when-idle.sh
```

The helper restarts `tv-remote` after 20 minutes without a log entry **and** with no `mpv` running, or at 05:00 at the latest, and writes "kumanda güncellendi" to the log. Files read per request (index.html, turkiye.m3u, devices.json) need no restart.
