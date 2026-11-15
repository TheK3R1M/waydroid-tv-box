# 14 · Physical remote (USB air mouse) and the live-TV bridge

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)

Status legend: ✅ verified on the reference box · ❔ not verified / partly verified · ⚠️ danger.

## 14.1 Why this exists

The living-room TV has no CEC (see [§2.2 item 3](02-hardware.md)), so the TV's own remote cannot control the box.
The reference build uses a cheap 2.4 GHz USB air-mouse remote with a dongle. It shows up as three Linux input
devices: a keyboard interface, a mouse interface and a consumer-control interface.

## 14.2 The power key shuts the box down ✅ (fixed)

The remote's power key sends `KEY_POWER` on the consumer interface. systemd-logind treats it as "power off"
and the box shut itself down (`journalctl -b -1`: "Power key pressed short. Powering off..."). The fix is a
logind drop-in, shipped in the kit as `files/etc/systemd/logind.conf.d/10-tv-no-powerkey.conf`:

```ini
[Login]
HandlePowerKey=ignore
HandlePowerKeyLongPress=ignore
HandleSuspendKey=ignore
HandleSuspendKeyLongPress=ignore
HandleHibernateKey=ignore
HandleRebootKey=ignore
HandleRebootKeyLongPress=ignore
```

Install and verify:

```bash
install -m 644 10-tv-no-powerkey.conf /etc/systemd/logind.conf.d/
systemctl kill -s HUP systemd-logind
busctl get-property org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager HandlePowerKey   # ignore
```

Rule: on any headless box, set this **before** you plug in a new USB remote or keyboard.
Shut the box down from the Proxmox UI or the web remote's recovery button, never from the remote.

## 14.3 Key map (from evtest) ✅

| Input | Keys seen |
|---|---|
| keyboard interface (`event3`) | UP, DOWN, LEFT, RIGHT, ENTER, COMPOSE (menu), PAGEUP, PAGEDOWN |
| mouse interface (`event4`) | pointer |
| consumer interface (`event5`) | BACK, HOMEPAGE, VOLUMEUP, VOLUMEDOWN, MUTE, VOICECOMMAND |

Find yours with `grep -A4 -i remote /proc/bus/input/devices` or `evtest` (read-only). Event numbers change
between boots; the bridge matches by device name, not number.

Many of these remotes also have a **learnable IR power key** (hold until the LED blinks, then teach it the
TV's own remote). That gives TV on/off without CEC. ❔ Not tested on the reference box.

## 14.4 The live-TV bridge in `tv-remote.py` ❔ (deployed; behaviour not recorded as verified)

While the host mpv plays live TV, mpv is fullscreen and has keyboard focus (`--no-input-default-bindings`).
Remote keys therefore never reach Android or the web remote. The bridge fixes that:

- `_remote_bridge()` runs in a daemon thread. It opens the remote's evdev nodes **shared** (not grabbed), so
  Weston still receives the keys. Devices are found by name prefix: `REMOTE_MATCH = ("XING WEI 2.4G",)`. Set this
  to your own dongle's name (from `/proc/bus/input/devices`).
- Keys are mapped to the same actions the web page sends (`_BRIDGE_KEYS`):

| Remote key | Action (same as the page button) |
|---|---|
| UP / DOWN | `/key/up`, `/key/down`: move UP/DOWN the channel list as it is shown (UP = towards no. 1). In split: the chosen side |
| LEFT / RIGHT | `/key/left`, `/key/right` (split: choose side) |
| ENTER / KPENTER / SELECT | `/key/ok` |
| BACK / ESC | `/key/back` |
| HOMEPAGE | `/key/home` |
| PAGEUP / CHANNELUP, PAGEDOWN / CHANNELDOWN | `/ch/prev`, `/ch/next` (same direction as the list) |
| VOLUMEUP / VOLUMEDOWN / MUTE | `/vol/up`, `/vol/down`, `/vol/mute` (host volume on the HDMI sink) |

- Actions are posted to `127.0.0.1` with `X-TV: 1` and logged as device **"Kumanda (fiziksel)"**, so the family
  sees them in the audit log.
- Only active while split/mpv is up (`_split["on"]`). Otherwise the bridge drops the key and Android handles it.
- Key repeat: volume repeats; channel keys are throttled to one step per 0.35 s.
- Hot-plug: the device list is rescanned every 5 s, so a re-plugged dongle is picked up.

**On-TV channel list (`osd_now()`):** on every channel change and on OK, mpv `show-text` draws a short list
with ASS tags: 2 channels above, the current one (yellow, bold, ▶), 3 below, numbered like the phone list; in split
it shows the chosen side and sits on that half. Without it, people using only the physical remote cannot see what
comes next. ✅ owner confirmed the bridge changes channels; direction fix + list ❔ (rendering checked with libass).

Direction rule: UP must move up the list the user sees (no. 1 at the top). An earlier version used UP = next
number, which felt inverted to the owner.

## 14.5 Verify (only when nobody is watching) ❔

The bridge only runs while a channel plays, and a test changes the channel, so test when the family is not
watching:

1. `grep -c . /proc/bus/input/devices` and find the dongle name; set `REMOTE_MATCH` if it differs.
2. Start a channel from the web remote, press UP once, and check `/var/log/tv-remote.log` for a
   `Kumanda (fiziksel)` line. No line = the name prefix does not match, or the bridge thread died (check
   `journalctl -u tv-remote`).
3. Check that the channel changed on the HDMI output (`tvshot`), not only in the log.
4. Volume: press VOLUMEUP, then VOLUMEDOWN, and read `/state` each time (restore the previous level).

## 14.6 Ideas that were NOT built

- A USB-CEC adapter would give real TV power control (`cec-ctl`), see [§2.2 item 3](02-hardware.md).
- An on-screen keyboard for the physical remote (for "Yaz" without the phone) is open. Ask the owner first; do
  not re-add automatic IME switching ([§7](07-adb.md)).

Next: [§15 tv-guard](15-tv-guard.md) · Changes: [§16](16-changes-2026-11.md)

## 14.6 On-TV channel UI (banner + list) ✅

Drawn by the host mpv with `osd-overlay` (ASS events in 1920x1080 coordinates: rounded panels via `\p1`
drawings, DejaVu Sans), not `show-text` (which looks like terminal text).

- **Banner** on every channel change (4 s): number, name, the channel above (▲) and below (▼), side in split.
- **Channel list**: OK while watching opens it; ▲▼ move the highlight without zapping; OK tunes and closes;
  ◀ / Back closes; closes itself after 12 s idle. "● izleniyor" marks the playing channel.
- **From Android**: the remote's CH/Page keys (or saying "kanallar") start live TV on the last channel and open
  the list.
- **Pitfall:** an `osd-overlay` belongs to the IPC client that created it and disappears when that connection
  closes. A connect-send-close helper shows nothing; keep one persistent IPC connection (with a reader thread that
  discards replies/events) and reconnect when mpv restarts. Verified on the real HDMI output (`tvshot`).

## 14.7 "Kanallar" tile on the Android home screen ✅

Live TV runs in the host mpv, so Android has no app for it. `android/kanallar/` builds a tiny **code-less** APK
(`org.tvbox.kanallar`: manifest + banner + icon, activity = the framework's own `android.app.Activity` with a
transparent theme, `hasCode=false`). It shows up as a normal TV app tile (Projectivy "TV Apps" row).

- Build on the host: `sh android/kanallar/build.sh /path/to/android/kanallar` (aapt2 + zipalign + apksigner +
  `android.jar` from Google's platform-33 zip; signing key generated once in `/root/tv-keys`, never committed),
  then `adb install -r kanallar.apk`.
- tv-remote `_tile_watch()` follows `adb logcat -s ActivityTaskManager:I`; a `START u0 ... cmp=org.tvbox.kanallar/`
  line opens live TV (last channel) with the channel list and force-stops the tile app.
- Android never connects to the host for this, so the LAN isolation (docs/10) stays closed.
- Verified: starting the tile -> channel playing + list open on the HDMI output in ~9 s; Back, Back -> home.

## 14.8 Volume and list timing on live TV ✅

- Android's own volume panel is hidden behind the host mpv, so volume keys during live TV draw an Android-TV-style
  vertical bar on the right (mpv overlay, 2.5 s, composed on top of whatever overlay is showing; orange above 100 %).
- The channel list closes after 6 s without a key (was 12 s, felt too long).
