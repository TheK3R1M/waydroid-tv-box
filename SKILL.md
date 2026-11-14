---
name: waydroid-tv-box
description: Use when building or repairing a headless Linux/Proxmox box that drives a TV over HDMI with Waydroid Android TV, host mpv live TV and a LAN web remote. Phased install with verify gates.
---

# Waydroid TV box: agent entry point

Read this file first. It tells you the order of work, the verify gate that ends each phase, and the rules you must not break. The detailed how-to is in `docs/`; the tick list is `CHECKLIST.md`.

## When to use

- Building a TV box from scratch on Proxmox (or Debian) that shows Android TV on the living-room TV, with live channels in a host-side mpv window and a phone web remote.
- Repairing a box of this design: freezes, black screens after long uptime, typing that breaks search boxes, an app that will not start, remote keys that do nothing, power key shutting the box down.
- Reviewing the kit before publishing, or changing it.

Do not use it for a different architecture (for example, a VM with GPU passthrough). It can be a starting point; the hardware and rules differ.

## Ground rules that come before any phase

1. **Find out who is watching.** The TV is a family device. Before any action on Android or the screen, run the check in [docs/13-agent-rules.md](docs/13-agent-rules.md) rule 1 (`pgrep -x mpv`, `dumpsys audio`, the remote log). If someone is watching, diagnose read-only only.
2. **Never inject input** (keyevents, taps, text) into the foreground app while someone may be using it. Harmless probes such as `input keyevent 0` are the only exception.
3. **Verify on real output, not on self-reports.** Host mpv: `tvshot` (HDMI scanout). Android: `screencap` (note that `tvshot` is black for Android's own scanout, which means unknown, not "TV off"). Process up is not "working".
4. **No public exposure without the owner's explicit approval** for that exact exposure: no public DNS record, no port forward, no certificate (a certificate is written to public CT logs forever), no IPv6 firewall change. Probe exposure from inside the confined side and report an open/closed table.
5. **Never automate a kill of the audio HAL** or any other subsystem on a symptom. Manual fix only ([docs/12-operations.md](docs/12-operations.md) §12.4).
6. **APKs: x86 or x86_64 only.** Install with `adb install --abi x86` and check `primaryCpuAbi`. Universal APKs crash on this image (libhoudini). ARM-only apps need the ARM bridge and are still a risk.
7. **Ask the owner before installing any APK for the family**, show a screenshot or description first, and for an untrusted APK suggest a VirusTotal hash lookup. Never install stream-scraper or piracy apps. Remove apps the owner did not ask for.
8. **Never type, accept or store credentials.** Google sign-in: the owner types on the TV or in a browser. Never run `pm clear` on `com.google.android.gsf`, `com.google.android.gms` or `com.android.vending` after the GSF id is registered (it voids the registration).
9. **Back up before you replace** a script, a unit or Waydroid data (`.bak` / `.orig`). Keep the source of truth in the repo, not in scratch directories.
10. **Keep secrets and device data out of the repo and out of logs.** Tokens, PINs, Wi-Fi keys, device lists, certificate keys and router credentials stay on the admin PC or the owner's password store.
11. **Measure intermittent problems long enough.** Freezes need tens of minutes to hours. One short sample proves nothing.

## Phases (in order)

Each phase ends with a verify gate. Do not start the next phase until the gate passes, and record what you saw.

| # | Phase | Read | Verify gate (CHECKLIST section) |
|---|---|---|---|
| 0 | Hardware and BIOS check: CPU family 23 model 24 means use the ATV 13 image, not ATV 16. Check the connected DRM output and the GPU card index. | [docs/02-hardware.md](docs/02-hardware.md) | "Before you start" |
| 1 | Host base: Proxmox packages, WiFi uplink with the rtw89 options and watchdog, binder, uinput, conntrack, yt-dlp, Waydroid package. Run the copy of the kit with filled placeholders. | [docs/03-host-base.md](docs/03-host-base.md) | "Host base" |
| 2 | Power key and USB remote: install the logind drop-in before any USB remote is plugged in. | [docs/14-physical-remote.md](docs/14-physical-remote.md) §14.2 | "Power key and USB remote" |
| 3 | TV stack without Android: Weston kiosk, PipeWire, WirePlumber, HDMI sink by name. One weston only. | [docs/04-tv-stack.md](docs/04-tv-stack.md) | "TV stack without Android" |
| 4 | Waydroid Android TV 13 init and base properties (software video decode, ARM bridge, no BT pairing). Remove the debugfs bind. | [docs/05-waydroid.md](docs/05-waydroid.md) | "Waydroid" |
| 5 | Launcher, apps and typing: x86 APKs only, ADBKeyboard as the default input method, Firefox as browser. Google sign-in only when the owner asks. | [docs/06-apps-and-signin.md](docs/06-apps-and-signin.md) | "Apps and sign-in" |
| 6 | ADB: authorize the admin PC key without touching the TV screen; expose 5555 to the admin PC only. | [docs/07-adb.md](docs/07-adb.md) | "adb" |
| 7 | Live channels: curated channel list (probed from the box), persistent host mpv, split screen. Channel list needs a run while nobody watches. | [docs/08-live-channels.md](docs/08-live-channels.md) | "Channels and split" |
| 8 | Web remote: install `tv-remote.py` and the page, LAN-only access rules, audit log, version stamp. Deploy with `tools/deploy-remote.sh <filled-copy>`. | [docs/09-web-remote.md](docs/09-web-remote.md) | "Web remote" |
| 9 | Security: LAN isolation for Android, tv-guard firewall and checker. Run the inside-Android table. | [docs/10-security.md](docs/10-security.md), [docs/15-tv-guard.md](docs/15-tv-guard.md) | "Security" |
| 10 | Physical remote bridge (only if the owner has a USB remote): set `REMOTE_MATCH`, test only when nobody watches. | [docs/14-physical-remote.md](docs/14-physical-remote.md) §14.4–14.5 | "Power key and USB remote" |
| 11 | PC side: ssh alias, HDMI viewer, scrcpy shortcuts, certificate renewal (only if the owner approved a certificate). | [docs/11-pc-viewer.md](docs/11-pc-viewer.md) | "PC" |
| 12 | Final reboot test and a 60-minute soak. After boot: all units active, one weston, sink = HDMI, remote 200, power key still ignored. | [docs/12-operations.md](docs/12-operations.md) | "Final reboot test" |

Status marks: ✅ means verified on the reference box; ❔ means not verified. Treat ❔ items as things to test, not facts. The open list is in [docs/B-open-items.md](docs/B-open-items.md); the changes since the first kit are in [docs/16-changes-2026-11.md](docs/16-changes-2026-11.md).

## Filling placeholders

The kit uses `__TOKEN__` values for everything that is specific to a home network. Never fill the original; work on a copy:

```bash
cp -a tv-setup-kit tv-setup-kit-filled
TV_HOST_IP=... ADMIN_PC_IP=... LAN_CIDR=... GATEWAY_IP=... TV_HOSTNAME=... ANDROID_IP=... \
  [VPN_ROUTER_IP=...] [WIFI_SSID=...] [AIRPLAY_PIN=...] \
  tools/fill-placeholders.sh tv-setup-kit-filled
```

- `ANDROID_IP` is the Waydroid container address on `waydroid0` (read it with `waydroid status` after the first boot).
- `tools/check-placeholders.sh <copy>` must print OK before anything is copied to the host.
- The filled copy is the only thing that goes to the host, and it must never be committed. `.gitignore` covers the usual names.

## Before any commit or publish

- `tools/privacy-scan.sh` must print `OK`. It fails on owner names, home addresses, device names, Wi-Fi names, secrets, Windows home paths and piracy-app names.
- `python -m py_compile` on every `.py`; `bash -n` on every `.sh`; every relative link in the `.md` files must resolve.
- Do not push or publish anywhere without the owner's explicit instruction.

## Hard rules, short form (full list: docs/13-agent-rules.md)

- Family watching → read-only diagnosis only.
- No keys, taps or text into a foreground app that someone may be using.
- Verify on HDMI output (`tvshot`) for host video, on `screencap` for Android.
- No exposure (DNS, port, certificate, IPv6) without the owner's approval for that exposure.
- No automatic kills of subsystems. Auto-heal only for a clear, non-normal condition.
- x86/x86_64 APKs only. Ask before installing any APK for the family. No piracy or stream-scraper apps.
- No credentials typed or stored by the agent. No `pm clear` on gsf/gms/vending after the GSF id exists.
- Deploy only from a filled copy, through `tools/deploy-remote.sh`, and only when the restart rule allows it.
- Log every infrastructure change where the owner can read it.
