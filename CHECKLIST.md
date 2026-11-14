# TV box — verification checklist

Use after each phase (see [SKILL.md](SKILL.md) and the chapters in [docs/](docs/)). Tick only what you saw on the output.
✅ = verified on the reference box; the reference values are examples. Run `tools/privacy-scan.sh` before any commit.

## Before you start
- [ ] CPU is Zen+ R2314 (or other Zen/Zen+ APU): use the **ATV 13** image, not ATV 16 (`grep -m1 'model name' /proc/cpuinfo`) ([§2](docs/02-hardware.md))
- [ ] BIOS: SVM on; IOMMU absent is OK (container setup is final)
- [ ] Kit copied, placeholders filled in a **copy**, `tools/check-placeholders.sh <copy>` prints OK

## Host base ([§3](docs/03-host-base.md))
- [ ] `pveversion` shows PVE 9.x on Debian 13
- [ ] Packages installed (weston, pipewire, wireplumber, mpv, ffmpeg, mesa-va-drivers, adb, python3-evdev, iptables, ifupdown2, wpasupplicant, waydroid, conntrack)
- [ ] `/usr/local/bin/yt-dlp --version` works (standalone binary)
- [ ] `binder_linux` loaded; `/dev/uinput` exists
- [ ] WiFi: `CTRL-EVENT-CONNECTED` in `journalctl -u wpa_supplicant@wlp3s0`; `ip -br a show wlp3s0` shows the host IP
- [ ] rtw89 options: `cat /sys/module/rtw89_core/parameters/disable_ps_mode` → `Y` (after reboot too)
- [ ] `wifi-watchdog` active

## Power key and USB remote ([§14](docs/14-physical-remote.md))
- [ ] `busctl get-property org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager HandlePowerKey` → `ignore`
- [ ] `/proc/bus/input/devices` lists the remote; `REMOTE_MATCH` in `tv-remote.py` matches its name
- [ ] (nobody watching) a UP press during a live channel logs `Kumanda (fiziksel)` ❔

## TV stack without Android ([§4](docs/04-tv-stack.md))
- [ ] `tv-base tv-weston tv-pipewire tv-pipewire-pulse tv-wireplumber` all `active`
- [ ] `pgrep -c -x weston` → `1`
- [ ] `/sys/class/drm` shows your connected output; `weston.ini` `name=` matches it
- [ ] `TV_SINK` in `/etc/tv/env` equals a name from `pactl list short sinks`

## Waydroid ([§5](docs/05-waydroid.md))
- [ ] `waydroid init` finished (ATV 13, GAPPS); `config_nodes` has no `sys/kernel/debug`
- [ ] `waydroid status` shows Session/Container RUNNING
- [ ] `getprop sys.boot_completed` → `1`
- [ ] `getprop media.sf.hwaccel` → `0`
- [ ] `getprop ro.dalvik.vm.native.bridge` → `libndk_translation.so` ✅
- [ ] `dumpsys display` → 1920x1080
- [ ] `ls /sys/kernel/debug` inside Android is empty

## Apps and sign-in ([§6](docs/06-apps-and-signin.md))
- [ ] Projectivy is focused after HOME (`mCurrentFocus`), stock `tvlauncher` disabled
- [ ] SmartTube (x86): `primaryCpuAbi` = x86; plays a video; its player capped to 1080p/AVC (manual)
- [ ] Firefox (x86_64) opens a page from the remote's "Tarayıcı" button ❔
- [ ] ADBKeyboard release build is the IME (`settings get secure default_input_method`); test broadcast writes text
- [ ] GSF id noted; no `pm clear` run on gsf/gms/vending
- [ ] No stream-scraper apps installed (owner rule); the remote's `tv` shortcut is set by the owner or removed

## adb ([§7](docs/07-adb.md))
- [ ] Admin PC key authorized: `adb connect <TV_HOST_IP>:5555` → `device`
- [ ] From any other LAN IP, port 5555 is closed (test from a second PC or phone)
- [ ] `tv-adb-lan.sh` ran at boot (DNAT rule present: `iptables -t nat -S PREROUTING | grep 5555`)

## Channels and split ([§8](docs/08-live-channels.md))
- [ ] `/etc/tv/turkiye.m3u` exists with ≥ 25 entries (`grep -c EXTINF`)
- [ ] One channel plays fullscreen in host mpv (`tvshot` shows the channel, not black)
- [ ] Split on: both halves show; side switch changes sound with no picture stall
- [ ] Back returns to Android (`mCurrentFocus`)

## Web remote ([§9](docs/09-web-remote.md))
- [ ] `curl http://<TV_HOST_IP>:8090/` → 200 from a LAN phone/PC
- [ ] Evil `Host:` → 403; evil `Origin` on POST → 403; `X-TV: 1` POST passes (use an unknown key name, not HOME)
- [ ] Volume set/normal changes `pactl` sink volume and `/state` reports it
- [ ] `/log` shows the action with the device name (if the device list is filled)
- [ ] Version stamp on the page (Diğer) matches the deployed commit (`cat /usr/local/share/tv-remote/VERSION`)
- [ ] Phone "Add to home screen" opens fullscreen

## Security ([§10](docs/10-security.md), [§15](docs/15-tv-guard.md))
- [ ] `tv-net-isolate.timer` active; Android table: internet OPEN, host 8006/22 / modem / admin PC CLOSED (run inside Android, verdict printed inside)
- [ ] `iptables -S TV-GUARD` lists the drops; `iptables -S TV-ISOLATE | head -3` shows `-j TV-GUARD` at position 2 ❔
- [ ] `tv-guard.timer` active; `/var/lib/tv-guard/baseline.json` exists ❔
- [ ] No public DNS, port forward or certificate for the TV (owner approval recorded)
- [ ] `/etc/tv/tls` only if approved; mode 600 on privkey

## PC ([§11](docs/11-pc-viewer.md))
- [ ] `ssh pve-tv true` works without a password prompt
- [ ] `TV Ekran (HDMI).bat` opens a window with the live TV picture, no audio, closes cleanly (no leftover ssh/ffplay)
- [ ] `TV (Spike).bat` / `TV Kumanda (Spike).bat` connect (adb `device`)

## Repo hygiene (before any commit)
- [ ] `tools/privacy-scan.sh` → `OK: privacy scan clean`
- [ ] Filled copy: `tools/fill-placeholders.sh <copy>` → `check-placeholders` OK
- [ ] `python -m py_compile` on every `.py`; `bash -n` on every `.sh`
- [ ] Every relative link in the `.md` files resolves

## Final reboot test ([§12](docs/12-operations.md))
- [ ] `sudo reboot` (or Proxmox UI). After boot: all units active, one weston, Projectivy focused, `sys.boot_completed=1`, sink = HDMI, remote answers 200, power-key drop-in still `ignore`
- [ ] Check again after 60 min of use: no "failed to attach" storm (`logcat -d | grep -c "failed to attach"`)
