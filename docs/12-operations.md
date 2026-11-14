# 12 · Operations runbook and troubleshooting

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


### 12.1 Health check (one command set)

```bash
for u in tv-base tv-weston tv-pipewire tv-pipewire-pulse tv-wireplumber tv-android tv-remote waydroid-container wifi-watchdog; do printf '%-24s %s\n' $u "$(systemctl is-active $u)"; done
systemctl is-active tv-android-heal.timer tv-net-isolate.timer
pgrep -c -x weston                                       # 1
waydroid shell -- getprop sys.boot_completed             # 1
waydroid shell -- sh -c 'dumpsys window | grep mCurrentFocus'
pactl -s unix:/run/tv/pulse/native list short sink-inputs   # HDMI stream RUNNING while playing
curl -s -o /dev/null -w '%{http_code}\n' http://__TV_HOST_IP__:8090/      # 200
```

Verify the user-visible result, not the process list: a running service does not mean the TV shows the right thing. For host mpv use `tvshot` (below); for Android use `screencap`.

### 12.2 Real HDMI frame (what the TV shows)

```bash
tvshot /tmp/tv.jpg          # kmsgrab on card1 → 960x540 JPEG
```

- Shows host mpv correctly. For Android frames it is **black** (Weston gives Android a DCC-compressed buffer that VA-API cannot map). Treat black as "unknown" for Android, not as "TV is black"; use `screencap` for Android.
- Needs `mesa-va-drivers` (without it VAAPI init fails silently).

### 12.3 Freeze triage (video stutter)

Measure first, for at least 30 s, before naming a cause. A single `dumpsys SurfaceFlinger --latency` sample lasts ~4 s and can "prove" a fix that is not one.

1. Restarts? `journalctl -t tv-heal -t wifi-watchdog --since -1h`.
2. Decoder: `waydroid shell -- getprop media.sf.hwaccel` must be `0`. Test with a known video (SmartTube VIEW intent to a public video). If that also stalls, the box is the cause.
3. Network vs source: `tcpdump -i waydroid0 -nn -q -tt 'tcp and src net not <waydroid0 subnet>'` for 30 s. Fast bursts with the player still stalling = not network.
4. Audio path: `pactl … list short sink-inputs` empty while `dumpsys audio` shows `state:started … USAGE_MEDIA` = wedged Android audio HAL. Manual fix only (see §12.4 below).
5. Load: `top -H` (scrcpy encoder, mediaswcodec, ffmpeg), `gpu_busy_percent`, `/proc/net/wireless`.
6. Only after 2–5: logcat `Response code: 403` = the stream host refused (expiring tokens on free live-TV sources).

Host mpv freezes (live channels): count them first with the `donmuştu` grep (9.4). Known state (Nov 2026): freezes ~4–34/day depending on the day, root cause **not** proven. Evidence so far: the box's WiFi download was clean on one day, one freeze was a dead source (playlist stopped), the PC fetched the same segments fine during box stalls on another day. Next experiment: `hermes-tvdiag.py` (optional, read-only, in `optional/`) with the same HLS playlist from the box and the PC in parallel, for hours, while the family watches.

### 12.4 Audio wedge (manual fix only)

Symptom: video stutters every few seconds, `PipeWire` has no sink-input, but Android says it is playing. Fix by hand:

```bash
waydroid shell -- sh -c 'kill $(pidof android.hardware.audio.service) $(pidof audioserver)'   # init respawns them
pactl -s unix:/run/tv/pulse/native list short sink-inputs                                    # a line should reappear
```

If `init.svc.vendor.audio-hal` stays at `stopping`, or logcat loops on `Audioserver died`, restart the Android session: `systemctl restart tv-android`.

⚠️ **Never automate this kill.** A timer version misfired during normal start/pause gaps, wedged the audio HAL and froze every channel. The owner's rule: auto-heal only for a condition that cannot occur in normal operation.

### 12.5 Stuck apps (black screen after ~1 h)

Symptom: new apps show black, logcat says `failed to attach` / `start timeout`. `tv-android-heal.timer` (1 min) restarts `tv-android` when the count of `failed to attach` rises (~45 s blip). The root cause is unknown (Waydroid/ATV13). Also check `logcat -b crash | grep Process:` and disable crash-loopers (6.2).

### 12.6 Restarts and what they break

- `systemctl restart tv-remote` kills the host mpv (same cgroup): the channel stops. Check nobody is watching first (`pgrep -x mpv`).
- `systemctl restart tv-android` restarts Android (~45 s): the family loses the current app. Use it only when broken or when they ask.
- Host reboot: everything comes back (tested), but the Android session takes a few minutes. Use the Proxmox UI reboot, or `ssh root@__TV_HOST_IP__ reboot`.
- **Never restart** services while someone is using the TV without a reason they agree to.

### 12.7 Known smells to avoid

- Two weston or pipewire processes → duplicate compositors (check `pgrep -c -x weston`).
- Numeric audio sink ids → use names.
- `chmod 777` on sockets → fix the runtime dir layout instead.
- adb 5555 open to the LAN → keep the DNAT to the admin PC.
- Universal APKs → x86 only.
