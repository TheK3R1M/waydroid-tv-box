# 05 · Waydroid Android TV 13 init and base properties

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


### 5.1 Clean install (from a previous Waydroid)

Back up first, then start clean. Skip the backup on a truly new host.

```bash
systemctl stop tv-android 2>/dev/null; waydroid session stop 2>/dev/null; waydroid container stop 2>/dev/null
tar czf /root/backup-waydroid-$(date +%F).tgz /var/lib/waydroid/images /var/lib/waydroid/waydroid.cfg /var/lib/waydroid/waydroid_base.prop /root/.local/share/waydroid 2>/dev/null || true
rm -rf /root/.local/share/waydroid /var/lib/waydroid/overlay_rw /var/lib/waydroid/overlay_work
```

### 5.2 Init with the ATV 13 image

```bash
waydroid init -f -c https://waydroid-atv.github.io/ota/system -v https://waydroid-atv.github.io/ota/vendor -r lineage -s GAPPS
```

- `-r lineage -s GAPPS`: LineageOS 20 base with Google apps, Android TV 13 (WayDroid-ATV build; ✅ this host used the 20260105 build).
- Do **not** use the phone (LineageOS) image or an ATV 16 image on Zen+ ([§2.2](02-hardware.md)).
- Init downloads a few GB. Wait for it to finish before continuing.

After init, the generated `config_nodes` contains a `/sys/kernel/debug` bind. Remove it ([§10.2](10-security.md) explains why):

```bash
sed -i '/sys\/kernel\/debug/d' /var/lib/waydroid/lxc/waydroid/config_nodes
/usr/local/bin/waydroid-no-debugfs.sh      # neutralizes the same bind in waydroid's lxc.py (idempotent)
```

### 5.3 Base properties (`waydroid_base.prop`)

The kit's `files/var/lib/waydroid/waydroid_base.prop` (installed in 3.8 by `cp -a`; if you ran init afterwards, copy it again and restart the container):

| Property | Value | Why |
|---|---|---|
| `media.sf.hwaccel` | `0` | Software video decode. VA-API copy path is ~10–16 fps on Raven2 ([§1.2](01-overview.md)) |
| `atv.setup.bt_remote_pairing` | `false` | Skip the BT remote pairing screen (no BT remote here) |
| `ro.adb.secure` | `1` | adb keys required ([§7](07-adb.md)) |
| `ro.debuggable` | `0` | Production-like build props (the image itself is `userdebug`) |
| `stop_on_session_exit` | `false` | Keep the container up when the session stops |
| `gralloc.gbm.device`, `ro.hardware.egl=mesa`, `ro.hardware.vulkan=radeon`, `ro.opengles.version=196610` | as in file | Mesa/radeon GPU path |
| `waydroid.system_ota`, `waydroid.vendor_ota` | ATV13 GAPPS URLs | Keeps updates on the ATV 13 channel |

Check after the first boot (§5.4):

```bash
waydroid shell -- getprop media.sf.hwaccel      # 0
waydroid shell -- getprop atv.setup.bt_remote_pairing   # false
```

❔ The file's exact apply path (copy before first session vs after) was not re-verified on a clean install; the final state was verified on this host. Check with `getprop` after boot.

`waydroid.cfg` in the kit is the sanitized host copy; it only contains OTA URLs and mount options.

### 5.4 Start and verify

```bash
systemctl start waydroid-container
systemctl start tv-android
sleep 60
waydroid status
waydroid shell -- getprop sys.boot_completed     # 1
waydroid shell -- sh -c 'dumpsys window | grep -E "mCurrentFocus"'
waydroid shell -- sh -c 'dumpsys display | grep -m2 DisplayDeviceInfo'    # should be 1920x1080, not 1048
```

Expect: `sys.boot_completed=1`, display 1920x1080, Leanback home screen (or the launcher you pick in [§6](06-apps-and-signin.md)).
If the display shows 1048 high, the Weston shell is not kiosk-shell: re-check `weston.ini`.

Android container IP (needed for `ANDROID_IP` in the kit): `waydroid status | grep -i 'ip address'`.
