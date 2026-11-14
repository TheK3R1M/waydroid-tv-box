# 07 · ADB: from the host and from the PC

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


Android has `ro.adb.secure=1`, so new adb clients must be authorized. The host and the PC both use their own key.

### 7.1 Authorize keys without touching the TV screen

Append the public key of the client (PC `~/.android/adbkey.pub`, host `/root/.android/adbkey.pub`) to Android's `adb_keys`. Copy only the **public** key over the secure channel:

```bash
cat >> /root/.local/share/waydroid/data/misc/adb/adb_keys < /root/pc-adbkey.pub    # the PC key you copied in
waydroid shell -- sh -c 'chown system:shell /data/misc/adb/adb_keys; chmod 640 /data/misc/adb/adb_keys; restorecon /data/misc/adb/adb_keys; stop adbd; start adbd'
```

Do this for the **admin PC key only** (and the host key). Anyone with an authorized key controls the TV.

### 7.2 Expose adb to the admin PC only

`files/usr/local/bin/tv-adb-lan.sh` (ExecStartPost of `tv-android`, via `adb.conf` drop-in) does this at each start:
- sets `service.adb.tcp.port 5555`, restarts `adbd`;
- DNAT `tcp 5555` **only from `__ADMIN_PC_IP__`** to the Android IP;
- removes older 5555 rules first (idempotent);
- closes the boot notification panel and goes HOME.

Never widen this to the whole LAN. ⚠️ Port 5555 on the LAN is full device control for anyone on the network (smell checklist in the original notes).

### 7.3 Persistent adb from the host (for `tv-remote`)

`tv-remote.py` keeps one `adb -s __ANDROID_IP__:5555 shell` open and sends each command followed by `echo __ACKn__`, waits up to 3 s for the ack (8 s for `am start`), and reconnects on silence. From a shell on the host, the same connection:

```bash
adb connect __ANDROID_IP__:5555
adb -s __ANDROID_IP__:5555 shell getprop sys.boot_completed
```

Restarting `tv-remote` kills the host adb server (same cgroup). The next key reconnects it; a `device not found` right after a restart is expected.

### 7.4 From the admin PC

1. Install adb and scrcpy (winget package `Genymobile.scrcpy` ships both; put them on PATH).
2. `adb connect __TV_HOST_IP__:5555` (works only from `__ADMIN_PC_IP__`).
3. The first connect shows "unauthorized" on the TV unless the PC key was pre-authorized (7.1). Accept it on the TV once.
4. Screenshots: `adb -s __TV_HOST_IP__:5555 shell screencap -p /sdcard/p.png` then `adb pull`. Check `file p.png` says PNG before viewing; `exec-out screencap` can be mangled on Windows.
