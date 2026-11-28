# Changelog

## 2026-11-28 (browser remote + restart fix)
- **Firefox D-pad navigation:** local userscript (`android/firefox/tv-dpad-nav.user.js`, runs in Violentmonkey) moves a blue frame between links, buttons and fields with the arrow keys; OK clicks; scrolls when nothing is left in that direction. No network access. Turkish pages: *Never translate Turkish* so the translate sheet does not steal the keys.
- **Live TV closes when Android restarts:** the remote watches `tv-android`'s start stamp and stops the host player, so no channel audio keeps playing behind the home screen.

## 2026-11-22 (options menu + zap watchdog)
- **MENU = options panel** (TV-style, right side, live TV only): channel context (favourite, programme guide, channel list, split screen, sound side, sleep timer with value, recordings, settings); guide context (remind, record, go to channel); Settings (auto switch for reminders, browse favourites only, language, reload channel list); Recordings (play / delete). Long OK still toggles the favourite. Hold-MENU no longer cycles the sleep timer.
- **Channel list navigation:** LEFT from any row jumps to the category tabs; tab change updates the list live; DOWN/OK returns to the remembered row; opens on the playing channel; last tab remembered; PageUp/PageDown 10 rows.
- **Zap watchdog:** HLS master lookup has a hard 3 s deadline (stale variant or master URL used); no first frame within 8 s shows "Kanal açılamadı", retries once with the master URL, then restores the previous channel; every zap writes a line to `/var/log/tv-zap.log` (superseded ones flagged).
- Tests: `tools/test_zap.py` (slow-CDN simulation), `tools/test_menu.py`; `tools/render_menu.py` renders every panel state for visual QA.

## 2026-11-22 (zapping + scheduling)
- **Zapping latency:** channel changes run on one latest-wins worker; the remote/HTTP call returns at once, superseded presses never load, first-frame poll 0.1 s, unchanged mpv properties are not re-sent (fewer IPC round trips). Every change is timed in `/var/log/tv-zap.log` (lock / resolve / cache / load / frame).
- **Scheduling (new `tvsched.py` + `tv-rec.py`):** OK on a future programme in the on-TV guide = reminder (toast 1 min before; switches by itself only if "otomatik geç" is on, else OK switches); MENU on a future programme = scheduled recording (`systemd-run --on-calendar`, ffmpeg `-c copy`, 2 min before to 5 min after, disk cap 20 GB, oldest deleted); MENU held = sleep timer 30/60/90/120/off (stops live TV, screen off, warning 1 min before); phone "Diğer" sheet has the sleep buttons and the recordings list (play / delete / cancel).
- **On-TV list layout:** rows 76 px apart, highlight bar holds the name and the EPG line; watching tag and favourite star inside the bar; guide marks on the programme line. `tools/render_overlay.py` renders the real overlay over a test frame for visual checks.
- Tests: `tools/test_sched.py` (scheduler, guide keys, zap coalescing, timing log).

## 2026-11-22 (live TV)
- **Live TV:** timeshift (physical LEFT/RIGHT -10/+10 s in single channel, phone ⏪10 · Canlı · ⏩30); on-TV list PageUp/Down = 10 rows and group jump; held-key acceleration; neighbour HLS prefetch; zap time logged in ms.
- **EPG:** `tv-epg.py` daily XMLTV (public iptv-epg.org feed) -> now/next on the remote and the on-TV banner, phone guide grid (-1 h .. +6 h). Coverage on a real Turkish list: about 19 % of curated channels (most local channels are not in the public guide).
- **i18n:** `LANG` in /etc/tv/env (en default); page + server OSD have en/tr tables.
- Offline tests: `tools/test_server.py`, `tools/test_epg.py`.

## 2026-11-22
- **TV Klavye 4.0.1:** `org.tvbox.klavye.SET` is a manifest receiver (`SetRx`, permission DUMP), so options apply before the keyboard was ever shown. Keyboard sources synced from the live tree.
- **Installer:** `install.sh` modular one-command installer (core, remote, live-tv, voice, keyboard, guard, backup), `--dry-run`, `--uninstall <module>`, per-module verify. Dry-run + verify tested on the reference box (all modules PASS). Fixed: module names with `-` (live-tv) broke the file lists.
- **TV Klavye 3.2:** square 8-column alphabetical grid + fixed right action column (Delete / Clear / Search / Mic) to cut left-right travel; word suggestions on top (MENU jumps there); next-letter chips above the typed key (UP types the centre letter, LEFT/RIGHT swap it within ~1.5 s); mic key = offline voice typing; offline Turkish dictionary + local learning.
- **Display reliability:** `tv-weston-watch` restarts the screen stack when Weston stops scanning out after the TV is switched on (`repaint delay abnormal`), only when nothing plays; `tv-weston.service.d/20-follow.conf` restarts Android after a Weston crash and keeps Weston logs; leaving live TV now sends HOME and verifies the launcher.
- **Host:** `tv-net-isolate.sh` waits for the xtables lock (no more failures / duplicate ip6tables rules).
- README English-first.
- **One volume:** host sink 0-150 % (boost >100, orange OSD) drives Android apps, live TV and the remote volume keys; Android media volume pinned to max.
