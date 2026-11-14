# 04 · Weston, PipeWire and WirePlumber units

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


### 4.1 What each unit does

| Unit | Role | Owner rule |
|---|---|---|
| `tv-base.service` | Creates `/run/tv` (RuntimeDirectory) and a session D-Bus | Root of the TV stack; others `BindsTo` it |
| `tv-weston.service` | Weston kiosk on DRM (`--socket=wayland-tv`, `weston.ini`) | Only compositor. Never start a second weston |
| `tv-pipewire.service` | PipeWire core | Only PipeWire core |
| `tv-pipewire-pulse.service` | PulseAudio socket `/run/tv/pulse/native` | `Requires=tv-pipewire` |
| `tv-wireplumber.service` | Session manager; `ExecStartPost` sets the HDMI sink default, unmute, 85 % | Sets the default by **name** (not numeric id, ids change) |
| `tv-android.service` | `waydroid show-full-ui` (fullscreen Android) | Enabled. Restart it to recover Android |
| `tv-remote.service` | Web remote ([§9](09-web-remote.md)) | Restarting it kills the host mpv |

### 4.2 Environment and weston config (installed in 3.8)

`/etc/tv/env` (installed from the kit):

```
XDG_RUNTIME_DIR=/run/tv
WAYLAND_DISPLAY=wayland-tv
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/tv/bus
PULSE_SERVER=unix:/run/tv/pulse/native
TV_SINK=alsa_output.pci-0000_04_00.1.hdmi-stereo-extra3
```

`TV_SINK` is an example from this hardware. Find your own sink name in 4.4 and change it.

`/etc/tv/weston.ini`:

```
[core]
shell=kiosk-shell.so
idle-time=0
require-input=false

[output]
name=DP-3
mode=1920x1080@60
```

`name=DP-3` is the connector on this board. Find yours:

```bash
for c in /sys/class/drm/card*-*/status; do echo "$c $(cat $c)"; done   # the one that says "connected"
ls /dev/dri                                                             # card index (tvshot/tv-hdmi-stream assume card1)
```

If your connected output is not `DP-3`, edit `weston.ini`. If your GPU is not `card1`, edit `/usr/local/bin/tvshot` and `/usr/local/bin/tv-hdmi-stream` (`/dev/dri/card1`).

### 4.3 Unit files

All of these are in `files/etc/systemd/system/` (installed by 3.8):
`tv-base.service`, `tv-weston.service`, `tv-pipewire.service`, `tv-pipewire-pulse.service`, `tv-wireplumber.service`, `tv-android.service` (+ `tv-android.service.d/adb.conf`, `isolate.conf`), `tv-remote.service`, `tv-android-heal.service/.timer`, `tv-net-isolate.service/.timer`, `wifi-watchdog.service`, and the drop-ins `waydroid-container.service.d/no-debugfs.conf` and `override.conf`.

Start order, first time (after the Waydroid init in [§5](05-waydroid.md) has created the container):

```bash
systemctl enable --now tv-base tv-weston tv-pipewire tv-pipewire-pulse tv-wireplumber
systemctl enable --now waydroid-container
systemctl enable --now tv-net-isolate.timer tv-android-heal.timer
systemctl enable --now tv-android tv-remote
```

Do **not** enable `tv-android` before the Waydroid image exists ([§5](05-waydroid.md)); it will restart-loop.

### 4.4 Find the HDMI sink name (after pipewire is up)

```bash
systemctl start tv-base tv-pipewire tv-pipewire-pulse
set -a; . /etc/tv/env; set +a
pactl list short sinks        # look for "...hdmi-stereo..." and copy its exact name into TV_SINK
```

Put that name into `/etc/tv/env` and into the `TV_SINK` default in `tv-remote.py` (search for `SINK =`) before enabling `tv-wireplumber`.

### 4.5 Verify the TV stack (no Android yet)

```bash
for u in tv-base tv-weston tv-pipewire tv-pipewire-pulse tv-wireplumber; do printf '%-22s %s\n' $u "$(systemctl is-active $u)"; done
pgrep -c -x weston        # must be 1
pactl -s unix:/run/tv/pulse/native get-default-sink     # the HDMI sink name
```
