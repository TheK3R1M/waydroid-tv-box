# Waydroid TV box: one-command installer and agent kit

Turn a mini PC on Proxmox VE into a living-room TV box: Android TV 13 (Waydroid) for apps, a host-side
player for live channels with split screen, and a web remote your family opens in a phone browser on the
LAN. Built and tested on one real box; the installer is modular, so you install only what you want.

> Status: the installer is new. Its module steps are not yet re-tested end to end on a clean host, and
> the kit files are not yet re-synced with the live source. The reference box is the source of truth.
> Items marked ❔ in [docs/](docs/) are not verified.

## What you get

- **Core:** Weston kiosk on HDMI, PipeWire audio, Waydroid Android TV 13 with software video decode, a
  heal timer for the "failed to attach" storms, and the power key ignored (a USB remote's power key no
  longer shuts the box down).
- **Remote:** a single-screen web remote on `http://<box>:8090` (add it to the home screen): volume with a
  visible boost, D-pad with tap, hold and slide, typing, app shortcuts, an audit log.
- **Live TV:** a curated Turkish channel list (probed from your box) played in a host mpv above Android,
  with split screen. The installer adds no piracy or stream-scraper apps.
- **Voice (optional):** offline Turkish speech-to-text for a remote with a microphone (whisper.cpp).
- **TV Klavye (optional):** an on-screen Turkish keyboard built from source, set as default input method.
- **Guard (optional):** Android cannot reach your LAN, but the internet stays open; a per-minute checker
  quarantines apps that behave like bots.
- **Backup (optional):** nightly rsync of Android data.

## Hardware

| Need | Minimum | Reference box |
|---|---|---|
| CPU | 4 cores, x86-64, AMD or Intel iGPU | AMD Ryzen Embedded R2314 (Zen+), 4 cores |
| RAM | 8 GB (live TV and voice are heavy) | 13 GB |
| Disk | 20 GB free on `/` | 68 GB root |
| Display | one HDMI or DisplayPort output to the TV | DP to HDMI passive cable (no CEC) |
| Network | host on the LAN (Ethernet or WiFi) | WiFi RTL8852BE (`rtw89`) |

Proxmox VE 9 on Debian 13 is the tested host. The installer runs as root on the Proxmox host.

## Install (one command)

On the Proxmox host, as root:

```bash
curl -fsSL https://raw.githubusercontent.com/TheK3R1M/waydroid-tv-box/main/install.sh | bash
```

Or from a checkout:

```bash
bash install.sh                                              # interactive: pick modules
bash install.sh --modules core,remote,live-tv,voice,keyboard,guard,backup --yes
bash install.sh --modules core,remote --dry-run              # print the plan, change nothing
```

Preflight detects the CPU family (Zen+ gets the Android TV 13 image), the connected display connector,
RAM, disk, the uplink and the LAN subnet. It asks for the admin PC address (the only machine allowed to
use adb and the HDMI viewer) and the name the remote answers to. Everything is logged to
`/var/log/tvbox-install.log`; installed modules are recorded in `/etc/tvbox/installed`.

Environment overrides for unattended runs: `TV_HOST_IP`, `GATEWAY_IP`, `LAN_CIDR`, `ADMIN_PC_IP`
(required with `remote`), `TV_HOSTNAME`, `ANDROID_IP`, `VPN_ROUTER_IP`.

### Modules

| Module | What it installs | Default |
|---|---|---|
| `core` | Weston kiosk, PipeWire, Waydroid Android TV 13, heal timer, power-key drop-in | always |
| `remote` | Phone web remote (port 8090), adb LAN rule for the admin PC | yes |
| `live-tv` | Host mpv live channels, split screen, `yt-dlp`, channel list (needs `remote`) | yes |
| `voice` | whisper.cpp voice key (needs `remote` and a remote with a microphone) | no |
| `keyboard` | TV Klavye keyboard, built from source, default input method | yes |
| `guard` | LAN isolation for Android, tv-guard watchdog | yes |
| `backup` | Nightly Android data backup at 04:40 | yes |

Each module has install, verify and uninstall steps. Verify runs at the end of every install and prints
PASS or FAIL per check. Remove one module with `bash install.sh --uninstall <module>`; apt packages and the
Waydroid image stay.

## Agent install

Open Claude Code (or another coding agent) in this repository and say: **"install the TV box"**. The agent
reads [SKILL.md](SKILL.md), runs the installer with preflight, asks the plain-language questions (admin PC
address, modules, the remote's name), runs each module's verify step and reports what passed. It does not
install apps for your family and does not type credentials.

## Compatibility

| Platform | Image | Result |
|---|---|---|
| Ryzen Embedded R2314 (Zen+, family 23 model 24), Proxmox VE 9 / Debian 13 | Android TV 13 (LineageOS 20 + GApps) | ✅ works (reference box) |
| Same CPU | Android TV 16 | ❌ does not boot (BoringSSL FIPS aborts on the RDRAND bug; zygote never starts) |
| Other CPUs and GPUs | Android TV 13 | ❔ not tested |

## Privacy and safety defaults

- Nothing is exposed to the internet. The remote listens on the LAN and checks the Host header and origin.
  The installer creates no public DNS record, port forward or certificate.
- Android is isolated from the LAN; the internet stays open. adb is reachable only from the admin PC.
- Software video decode is set by default; the power key is ignored.
- The installer installs no streaming apps that scrape pirated sources and sets up no VPN routing.
- Secrets (the keyboard signing key, adb keys) stay on the box in root-only paths and never go into the repo.
- Untrusted APKs can run on this box. Check them first (for example by VirusTotal hash) and never install
  apps for other people without asking.

## Repository layout

| Path | Content |
|---|---|
| `install.sh` | Modular installer: preflight, modules, verify, uninstall |
| [SKILL.md](SKILL.md) | Agent entry point: phases, verify gates, rules |
| [docs/](docs/) | Notes per phase; open items in `docs/B-open-items.md`; Turkish architecture notes in `docs/00-architecture-tr.md` |
| [CHECKLIST.md](CHECKLIST.md) | Verification list |
| `files/` | Config and scripts, installed to the same path under `/` (placeholders filled at install) |
| `android/` | APK sources: TV Klavye, assistant bar, Kanallar tile |
| `optional/` | Not installed by default: AirPlay, diagnostics |
| `pc/` | Windows helpers: HDMI viewer, scrcpy shortcuts, certificate renewal |
| `tools/` | Placeholder check, privacy scan, remote sync and deploy helpers |

## Credits

- Turkish word list for TV Klavye: [FrequencyWords](https://github.com/hermitdave/FrequencyWords)
  (Turkish subtitle corpus), licensed CC-BY-SA 4.0. The derived list in `android/klavye/assets/` keeps that licence.
- Channel discovery: [iptv-org](https://github.com/iptv-org/iptv) public playlists, plus broadcasters' own
  players, all probed before use.
- [Waydroid](https://waydro.id) and the WayDroid-ATV Android TV 13 build; [whisper.cpp](https://github.com/ggml-org/whisper.cpp);
  [yt-dlp](https://github.com/yt-dlp/yt-dlp); [mpv](https://mpv.io); [Weston](https://gitlab.freedesktop.org/wayland/weston).

## License

MIT. See [LICENSE](LICENSE). Provided as is: you are responsible for your network, your TV and every app you install.

---

## Türkçe (kısa)

Bu depo, Proxmox üzerindeki bir mini PC'yi salon TV kutusuna çevirir: Waydroid ile Android TV 13,
canlı kanallar için host mpv (bölünmüş ekran dahil) ve ailenin telefon tarayıcısından açtığı LAN kumandası.

```bash
curl -fsSL https://raw.githubusercontent.com/TheK3R1M/waydroid-tv-box/main/install.sh | bash
```

Modüller: `core` (zorunlu), `remote`, `live-tv`, `voice`, `keyboard`, `guard`, `backup`. Her modülün kurulum,
doğrulama ve kaldırma adımı var: `bash install.sh --uninstall <modül>`. Ryzen Embedded R2314 üzerinde
Android TV 13 çalışır; TV 16 açılmaz. Korsan yayın uygulaması kurulmaz. Mimari notlar:
[docs/00-architecture-tr.md](docs/00-architecture-tr.md).
