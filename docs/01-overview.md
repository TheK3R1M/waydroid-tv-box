# 01 · What it is, architecture, design decisions

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


Spike is a Proxmox VE node (standalone, not clustered) whose only job is to drive the living-room TV over HDMI. It runs a headless Weston kiosk on the AMD iGPU, shows Waydroid (Android TV 13) fullscreen, plays live channels in a host-side mpv window that sits above Android, and is controlled from family phones through a LAN-only web page.

### 1.1 Architecture

```
  Family phones (Android, LAN)          Admin PC (Windows)
  ───────────────────────────           ──────────────────
  http://__TV_HOST_IP__:8090            adb / scrcpy  (TCP 5555, DNAT from admin PC only)
  https://__TV_HOSTNAME__ (optional)    ffplay "TV Ekran (HDMI)" (ssh → tv-hdmi-stream)
            │                                   │
            ▼                                   ▼
 ┌──────────────────────── Proxmox VE 9.2 "Spike" (Debian 13, host = root) ─────────────────┐
 │                                                                                            │
 │  tv-remote.py  (:8090 http, :443 https, stdlib)                                            │
 │     ├─ adb shell (persistent, acked) ──────────────┐                                       │
 │     ├─ pactl (HDMI sink volume)                    │                                       │
 │     └─ mpv IPC  /run/tv/mpv-split.sock ──┐         │                                       │
 │                                          ▼         ▼                                       │
 │  tv-weston  (kiosk-shell, DRM, DP-3 1920x1080, socket wayland-tv)                          │
 │     ├─ mpv (host, fullscreen above Android: live channels + split)                         │
 │     └─ Waydroid Android TV 13 (fullscreen, privileged LXC, binder)  ── waydroid0 bridge    │
 │                                                                  <waydroid0 subnet>        │
 │  tv-pipewire → tv-pipewire-pulse + tv-wireplumber → HDMI audio sink (alsa…hdmi-stereo-extra3)│
 │                                                                                            │
 │  tv-net-isolate: Android → internet only (RFC1918/CGNAT/link-local DROP, DNS/DHCP kept)   │
 │  tv-android-heal (1 min timer): restart Android on "failed to attach" storms               │
 │                                                                                            │
 │  NIC: RTL8852BE wlp3s0 = uplink (static __TV_HOST_IP__)   |  vmbr0 NAT 10.10.10.0/24 (lab) │
 │       RTL8111 nic0 = unused (no IP)                                                        │
 └────────────────────────────────────────────────────────────────────────────────────────────┘
                       │ HDMI (DP-3 on this board)
                       ▼
                 Living-room TV (Philips, no CEC)
```

### 1.2 Why it is built this way (keep these reasons when you change things)

- **Waydroid in a privileged LXC on the host.** Waydroid needs binder, a Wayland session and the GPU; running it in an unprivileged guest was not practical on this hardware. Consequence: container root = host root. That is why [§10](10-security.md) (network isolation, debugfs removal) exists.
- **kiosk-shell on Weston.** The desktop-shell panel steals 32 px (1920x1048 instead of 1920x1080). kiosk-shell gives a true fullscreen and only one owner for the display.
- **One owner per daemon.** Each daemon is one systemd unit with `BindsTo=tv-base`. Earlier layouts ran several start scripts that all killed and restarted Weston/PipeWire, producing duplicate compositors and orphaned processes (ppid 1). Do not add a second start script for any of these daemons.
- **Host mpv for live channels and split screen.** Android freeform split does not work on this Waydroid image: task bounds are correct but SurfaceFlinger never offsets the task surfaces, so every window draws at x=0. A single persistent host mpv window above Android does the split reliably.
- **Software video decode in Android (`media.sf.hwaccel=0`).** On ATV13 + Raven2 the VA-API path decodes on the GPU but copies every frame back to CPU (`use-drm-prime=0`), which caps 1080p H.264 at ~10–16 fps. Software ffmpeg gives ~48 fps on about one core. Zero-copy gives a black screen on this image — do not use it.
- **Android is LAN-isolated.** Android runs third-party APKs. The isolation keeps it from reaching the LAN, the host, or the modem. Only the admin PC can reach adb (DNAT, see [§7](07-adb.md)).
- **Web remote instead of a phone app.** Phone TV-remote apps need mDNS and direct LAN reach to Android, which the isolation forbids. The host serves the remote page, and Android stays closed to the LAN.
- **Household rules.** The family watches this TV. Diagnose read-only while someone watches; never inject keys into a foreground app they are using.
