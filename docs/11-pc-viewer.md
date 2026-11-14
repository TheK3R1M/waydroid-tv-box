# 11 · PC HDMI viewer and PC controls

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


### 11.1 Files (in `pc/` of the kit)

| File | Use |
|---|---|
| `TV Ekran (HDMI).bat` | Opens `tv-hdmi-view.ps1` minimized: shows what the TV really shows (channels included), video only |
| `tv-hdmi-view.ps1` | ssh to the host → `tv-hdmi-stream` → ffplay. Closing the ffplay window kills the ssh and stops the stream on the host |
| `TV (Spike).bat` | Opens the TV Android screen with scrcpy (watch + keyboard/mouse). Costs TV CPU while open |
| `TV Kumanda (Spike).bat` | Keyboard-only scrcpy (`--no-video --no-audio`), near-zero cost. Ctrl+B = back. Written from the documented command (not copied from a desktop) |
| `renew-cert.sh` | Optional: certificate renewal ([§10.7](10-security.md)) |

### 11.2 Setup on the PC

1. ssh alias (`%USERPROFILE%\.ssh\config`), key login only:
   ```
   Host pve-tv
       HostName __TV_HOST_IP__
       User root
       IdentityFile ~/.ssh/<your-key>
       BatchMode yes
   ```
2. ffplay on PATH: `winget install Gyan.FFmpeg` (provides ffplay).
3. adb and scrcpy on PATH: `winget install Genymobile.scrcpy`, then add its package folder to PATH.
4. Copy the three `.bat` files and `tv-hdmi-view.ps1` to the same folder (the `.bat` uses `%~dp0`). Put a shortcut on the desktop if you want.

### 11.3 Shortcuts and controls

- scrcpy shortcut modifier is **Alt by default**. The `.bat` files pass `--shortcut-mod=lctrl,lalt`, so Ctrl+B and Ctrl+H work.
- Mouse left-click = select, right-click = back (only in the video window).
- Keep the scrcpy window closed while the family watches on the TV: a 1920p mirror costs about two cores on this box (no hardware video encoder). The `.bat` uses `-m 1280 --max-fps 30 -b 4M --no-audio`.

### 11.4 What the viewer shows

It captures the **HDMI scanout** (kmsgrab + VA-API H.264, about zero CPU). It shows host mpv channels correctly. scrcpy only sees Android, so when a channel plays full screen, scrcpy shows Android behind it. Use the HDMI viewer to see what the family sees.
