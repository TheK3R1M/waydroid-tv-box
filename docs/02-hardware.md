# 02 · Hardware, BIOS and known pitfalls

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


### 2.1 Hardware (this build)

| Item | Value (as built) | Check command |
|---|---|---|
| CPU | AMD Ryzen Embedded R2314 (Zen+, family 23 model 24), 4 cores | `grep -m1 'model name' /proc/cpuinfo` |
| RAM | 13 GB | `free -h` |
| iGPU | AMD Picasso/Raven 2 (Vega), `04:00.0`; HDMI audio `04:00.1` | `lspci -nn \| grep -iE 'vga\|audio'` |
| Ethernet | RTL8111 `nic0` (`02:00.0`), not used | `ip -br link` |
| WiFi | RTL8852BE `wlp3s0` (`03:00.0`, driver `rtw89`) = uplink | `lspci -k -s 03:00.0` |
| Storage | 68 GB root + 141 GB local-lvm | `pvesm status` |
| Output | HDMI on connector **DP-3** (name on this board, example from this hardware) | `for c in /sys/class/drm/card*-*/status; do echo "$c $(cat $c)"; done` |
| Audio sink | `alsa_output.pci-0000_04_00.1.hdmi-stereo-extra3` (example from this hardware) | `pactl list short sinks` ([§4.4](04-tv-stack.md)) |
| PVE | 9.2.2, kernel 7.0.2-6-pve, Debian 13 (trixie) | `pveversion` |

### 2.2 Pitfalls (read before buying / building)

1. **Zen+ RDRAND bug → use the Android TV 13 image, not ATV 16.** On Zen+ APUs (Ryzen 2000/3000, R2314) BoringSSL FIPS aborts on the broken RDRAND, zygote never starts, and ATV 16 builds do not boot. Use **WayDroid-ATV Android TV 13** (LineageOS 20, GAPPS). Check the CPU family/model first.
2. **No IOMMU on this BIOS.** Only SVM "Virtualization" exists, no IOMMU option → no GPU passthrough to a VM. The container setup is therefore final on this hardware. For a different box with IOMMU, a TV VM with passthrough is an option ([§10.5](10-security.md)).
3. **No CEC.** The AMD iGPU has no CEC; `ls /dev/cec*` is empty. The TV's own remote does not work. Use the web remote, scrcpy, or a USB air-mouse/keyboard. A USB CEC adapter is the proper fix if you need the TV remote.
4. **TV standby cannot be detected.** The Philips TV gives no standby signal (DP status, ELD and DDC/CI do not change). Do not design auto-sleep on it.
5. **WiFi RTL8852BE drops silently under power saving.** Apply the `rtw89` options ([§3.5](03-host-base.md)) and the watchdog. Use Ethernet for 24/7 roles when you can.
6. **Universal APKs crash here.** They resolve to arm64 libraries that run through libhoudini → `houdini: Fatal error`, ANR on splash, black screen. Always install the **x86 / x86_64** APK.
7. **Freeform split in Android does not work** (see [§1.2](01-overview.md)). Do not spend time on it.
8. **`waydroid shell -- am start` can return silently without launching.** Use a persistent `adb shell` from the host ([§7.3](07-adb.md)).
9. **`pm clear` on Google Play services/GSF after the GSF id was registered voids the uncertified-device registration.** Never run it ([§6.4](06-apps-and-signin.md)).
