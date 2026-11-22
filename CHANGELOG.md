# Changelog

## 2026-11-22
- **TV Klavye 4.0.1:** `org.tvbox.klavye.SET` is a manifest receiver (`SetRx`, permission DUMP), so options apply before the keyboard was ever shown. Keyboard sources synced from the live tree.
- **Installer:** `install.sh` modular one-command installer (core, remote, live-tv, voice, keyboard, guard, backup), `--dry-run`, `--uninstall <module>`, per-module verify. Dry-run + verify tested on the reference box (all modules PASS). Fixed: module names with `-` (live-tv) broke the file lists.
- **TV Klavye 3.2:** square 8-column alphabetical grid + fixed right action column (Delete / Clear / Search / Mic) to cut left-right travel; word suggestions on top (MENU jumps there); next-letter chips above the typed key (UP types the centre letter, LEFT/RIGHT swap it within ~1.5 s); mic key = offline voice typing; offline Turkish dictionary + local learning.
- **Display reliability:** `tv-weston-watch` restarts the screen stack when Weston stops scanning out after the TV is switched on (`repaint delay abnormal`), only when nothing plays; `tv-weston.service.d/20-follow.conf` restarts Android after a Weston crash and keeps Weston logs; leaving live TV now sends HOME and verifies the launcher.
- **Host:** `tv-net-isolate.sh` waits for the xtables lock (no more failures / duplicate ip6tables rules).
- README English-first.
