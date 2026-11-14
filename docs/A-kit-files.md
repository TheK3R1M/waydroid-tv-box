# Appendix A · Kit file list

[← Index](../README.md)

```
README.md                         front page (short)
SKILL.md                          agent entry point (phases with verify gates, hard rules)
CHECKLIST.md                      verification checklist (print it)
LICENSE                           MIT
docs/                             full guide, one file per chapter (01-16, A, B)
tools/
  fill-placeholders.sh            fill __TOKENS__ in a COPY of the kit
  check-placeholders.sh           fail if any __TOKEN__ is left in config/script files
  privacy-scan.sh                 fail if owner, network, device, secret or piracy strings are in the repo
  deploy-remote.sh                deploy tv-remote from a FILLED copy to the TV host (backup, py_compile, restart-when-idle)
  mock.py                         mock of the remote API for UI tests (serves the page, fakes /state, /channels)
files/                            mirrors target paths on the host (cp -a files/. /)
  etc/tv/env                      environment (TV_SINK = example from the reference hardware)
  etc/tv/weston.ini               kiosk shell, output DP-3 1920x1080
  etc/modprobe.d/rtw89-stable.conf
  etc/network/interfaces          WiFi uplink + vmbr0 NAT (placeholders)
  etc/systemd/logind.conf.d/10-tv-no-powerkey.conf   ignore the remote's power key (§14.2)
  etc/systemd/system/             tv-base, tv-weston, tv-pipewire, tv-pipewire-pulse, tv-wireplumber,
                                  tv-android (+ .d/adb.conf, isolate.conf), tv-remote, tv-android-heal (.service/.timer),
                                  tv-net-isolate (.service/.timer), tv-guard (.service/.timer), wifi-watchdog,
                                  waydroid-container.service.d/{no-debugfs,override}.conf
  usr/local/bin/                  tv-adb-lan.sh, tv-android-heal.sh, tv-net-isolate.sh, tv-guard-fw.sh,
                                  tv-guard-check.py, tv-hdmi-stream, tvshot, waydroid-no-debugfs.sh,
                                  wifi-watchdog.sh, setup-binderfs.sh, tv-remote-restart-when-idle.sh,
                                  tv-remote.py, tv-channels.py
  usr/local/share/tv-remote/index.html   web remote page
  var/lib/waydroid/waydroid_base.prop, waydroid.cfg
  var/lib/waydroid/overlay/system/etc/hosts   127.0.0.1 localhost waydroid (live-TV app fix)
optional/                         NOT installed by default
  etc/systemd/system/tv-airplay.service (+ .d/avahi.conf)   AirPlay (UxPlay), disabled unless an iPhone is in the house
  usr/local/bin/hermes-tvdiag.py  read-only freeze diagnosis (dated, one-off)
pc/                               Windows helpers (copy to the PC)
  TV Ekran (HDMI).bat, tv-hdmi-view.ps1, TV (Spike).bat, TV Kumanda (Spike).bat, renew-cert.sh
```

NOT in the kit, on purpose: `/etc/tv/devices.json` (device list), `/etc/tv/tls/*` (certificate and private key),
`/etc/tv/turkiye.m3u` (stream URLs with session data; regenerate with `tv-channels.py`), `/etc/wpa_supplicant/*`
(WiFi secret), `/var/log/*`, adb keys, Google account data, anything under `~/.local/share/waydroid/data`,
`/var/lib/waydroid/images` (multi-GB image; re-init), `/usr/local/bin/yt-dlp` (binary; §3.2), tv-guard state files,
and the obsolete start scripts.
