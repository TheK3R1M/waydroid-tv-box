# Changelog

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
