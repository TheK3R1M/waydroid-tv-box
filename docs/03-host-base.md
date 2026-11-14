# 03 · Host base install (Proxmox, packages, network)

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


Everything below runs as **root on the Proxmox host**. Use Proxmox VE 9.x on Debian 13 (trixie).

### 3.1 Update and install the stack

```bash
apt update && apt full-upgrade -y
apt install -y \
  weston pipewire pipewire-bin pipewire-pulse wireplumber gstreamer1.0-pipewire \
  pulseaudio-utils mpv ffmpeg mesa-va-drivers adb socat python3-evdev \
  iptables ifupdown2 dbus-daemon wpasupplicant
```

Versions this build was verified with (for reference, not pins): weston 14.0.2, pipewire 1.4.2, wireplumber 0.5.8, mpv 0.40.0, ffmpeg 7.1.5, mesa-va-drivers 25.0.7, adb 34.0.5, python3-evdev 1.9.1, socat 1.8.0.3, python 3.13.5. ✅

`mesa-va-drivers` is required: without it VA-API init fails (`-1 unknown libva error`) and mpv silently decodes on the CPU. ✅

### 3.2 yt-dlp (standalone binary, not the Debian package)

The Debian package (2025.04) is too old for current YouTube. Put the standalone binary from the yt-dlp GitHub releases in place:

```bash
curl -fL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
chmod +x /usr/local/bin/yt-dlp && /usr/local/bin/yt-dlp --version
```

❔ The download URL is the standard yt-dlp release path, not re-checked on this host. The host runs a 2026.10 build.

### 3.3 Waydroid package

Waydroid is packaged from the Waydroid repository (this host: waydroid 1.6.3).

```bash
curl -fsSL https://repo.waydro.id/waydroid.gpg -o /usr/share/keyrings/waydroid.gpg   # ❔ key URL from the Waydroid docs, check it
echo "deb [signed-by=/usr/share/keyrings/waydroid.gpg] https://repo.waydro.id/ trixie main" > /etc/apt/sources.list.d/waydroid.list
apt update && apt install -y waydroid
```

Kernel module for binder (host file `/etc/modules-load.d/modules.conf` contains `binder_linux`):

```bash
echo binder_linux >> /etc/modules-load.d/modules.conf
modprobe binder_linux
```

`/dev/uinput` is needed for the phone mouse ([§9](09-web-remote.md)). On this host it is built in (`crw------- root root 10,223`). If it is missing: `modprobe uinput` and add `uinput` to `/etc/modules-load.d/modules.conf`.

### 3.4 Network: WiFi uplink (RTL8852BE)

The host uses WiFi as its uplink. Layout:
- `wlp3s0` = static host IP `__TV_HOST_IP__/24`, gateway `__GATEWAY_IP__`.
- `vmbr0` = NAT bridge `10.10.10.0/24` (lab guests, not used by the TV stack), MASQUERADE out through `wlp3s0`.
- `nic0` = `inet manual`, no IP, so a cable cannot cause an IP conflict.

Use the kit file as the template:

```bash
cp /root/tv-kit/files/etc/network/interfaces /etc/network/interfaces   # after placeholder fill (§3.8)
```

Create the WPA config **without putting the password in a command line or in this kit**. `read -s` keeps it out of shell history:

```bash
read -rsp "WiFi password (not echoed): " P; echo
umask 077
printf 'ctrl_interface=/run/wpa_supplicant\nupdate_config=0\n' > /etc/wpa_supplicant/wpa_supplicant-wlp3s0.conf
wpa_passphrase "__WIFI_SSID__" "$P" | grep -v '#psk' >> /etc/wpa_supplicant/wpa_supplicant-wlp3s0.conf
unset P
chmod 600 /etc/wpa_supplicant/wpa_supplicant-wlp3s0.conf
systemctl enable --now wpa_supplicant@wlp3s0
journalctl -u wpa_supplicant@wlp3s0 --no-pager | grep -E 'CONNECTED|DISCONNECTED' | tail -3
```

Look for `CTRL-EVENT-CONNECTED` before changing the IP config. Then apply the interfaces file:

```bash
ifreload -a          # ifupdown2; on failure restore the backup you made first
ip -br a show wlp3s0 ; ip route | head -2 ; ping -c3 __GATEWAY_IP__
```

Keep a backup of `/etc/network/interfaces` before the switch. If you are working over WiFi (remote session), run the switch as a detached, rollback-armed job: copy the new file, `ifreload -a`, ping the gateway for ~90 s, and restore the backup plus `ifreload -a` if the ping fails. Do not run a network change as the only foreground step while connected over WiFi.

Important: a static `wlp3s0` IP must be reserved in the router DHCP table for the WiFi MAC, or the router may hand the same address to another device. ❔ Reservation is a router change; ask the owner.

### 3.5 rtw89 stability (WiFi)

Copy `files/etc/modprobe.d/rtw89-stable.conf` to `/etc/modprobe.d/rtw89-stable.conf`. It contents:

```
options rtw89_pci disable_aspm_l1=y disable_aspm_l1ss=y
options rtw89_core disable_ps_mode=y
```

Apply live, then reboot for the PCI options to take effect:

```bash
echo Y > /sys/module/rtw89_core/parameters/disable_ps_mode
cat /sys/module/rtw89_core/parameters/disable_ps_mode         # Y
```

Gateway watchdog: `files/usr/local/bin/wifi-watchdog.sh` + `files/etc/systemd/system/wifi-watchdog.service` (ping gateway every 10 s, three misses → `ifdown --force wlp3s0; ifup wlp3s0`).

```bash
systemctl enable --now wifi-watchdog
```

✅ Reboot-tested on this hardware (params read `Y`, watchdog active, gateway ping 20/20 after reboot).

### 3.6 Host firewall basics

`ip_forward` is turned on by the `vmbr0` `post-up` line. Verify: `sysctl net.ipv4.ip_forward` → `1`.
Android isolation ([§10](10-security.md)) is added later by its own units; do not add rules to INPUT/FORWARD manually.

### 3.7 Directories

```bash
mkdir -p /etc/tv /etc/tv/tls /usr/local/share/tv-remote /var/tmp/tv-media /var/tmp/tvdiag
touch /var/log/tv-remote.log /var/log/tv-split.log
```

### 3.8 Put the kit on the host (filled copy)

On the admin PC:

1. Copy the kit folder somewhere safe (do not edit the original):
   `cp -a <kit-folder> <your-copy-folder>`
2. Fill the placeholders in the **copy** (git-bash on the PC; the values below are examples from a documentation range, use your own):
   ```bash
   cd <your-copy-folder>
   TV_HOST_IP=192.168.10.5 ADMIN_PC_IP=192.168.10.9 LAN_CIDR=192.168.10.0/24 \
   GATEWAY_IP=192.168.10.1 TV_HOSTNAME=tv.example.lan ANDROID_IP=192.168.240.<n> \
   WIFI_SSID=<your SSID> AIRPLAY_PIN=<4 digits> \
   tools/fill-placeholders.sh .
   ```
   `tools/fill-placeholders.sh` requires `TV_HOST_IP ADMIN_PC_IP LAN_CIDR GATEWAY_IP TV_HOSTNAME ANDROID_IP` and then runs `check-placeholders.sh`, which fails if any `__TOKEN__` is left. `ANDROID_IP` must match the Android container IP on `waydroid0` (check `waydroid status` after the first boot; the Waydroid DHCP lease is `192.168.240.x`). The default `192.168.240.1` (waydroid0 gateway) and `192.168.0.0/16` in the isolation script are not placeholders on purpose.
3. Copy the filled files to the host:
   ```bash
   scp -r files pve-tv:/root/tv-kit/
   ```
4. On the host, install (copies with the right paths; executable bits set explicitly because Windows copies lose them):
   ```bash
   cp -a /root/tv-kit/files/. /
   chmod +x /usr/local/bin/tv-*.sh /usr/local/bin/tv-hdmi-stream /usr/local/bin/tvshot \
            /usr/local/bin/waydroid-no-debugfs.sh /usr/local/bin/wifi-watchdog.sh \
            /usr/local/bin/setup-binderfs.sh /usr/local/bin/tv-remote-restart-when-idle.sh \
            /usr/local/bin/tv-remote.py /usr/local/bin/tv-channels.py
   systemctl daemon-reload
   ```
   This copies `files/` only. The `optional/` folder (AirPlay, diagnostics) is not installed by this step.
