# Appendix B · Known gaps and open items

[← Index](../README.md)

Honest state at the time of writing (November 2026). ❔ = not verified.

- ❔ **Freeze root cause (live channels)** is not proven. Candidates: WiFi bulk transfer stalls, mpv's persistent HTTP connection hanging, dead source playlists. Use `hermes-tvdiag.py` for a long, controlled measurement.
- ❔ **Android stuck-attach root cause** unknown; the heal timer is a workaround.
- ❔ **Google sign-in** depends on the owner's registration and password/passkey decision. Add an account only when the owner asks.
- ❔ **Search-box typing in a live-TV app end to end** was tested on one app only; re-test after changes.
- ❔ **Phone gyro and touchpad feel** on a real phone not yet confirmed by the owner.
- ❔ **Phone screen mirroring is not solved.** The built-in Cast receiver cannot get Google's device certificate on an uncertified build, so phones do not list it. Options: scrcpy over wireless debugging, ScreenStream (image only), or a certified Cast dongle. The owner chooses.
- ❔ **TV standby/sleep** is not automated (no signal from the TV). An inactivity rule was planned, not built.
- ❔ **Audio wedge** has no safe automatic recovery; manual fix only ([§12.4](12-operations.md)).
- ❔ **Isolation table** ([§10.2](10-security.md)) must be re-run after changes; check that `nc` exists in the Android image.
- ❔ **Host WiFi static IP** needs a router DHCP reservation (owner approval). Without it the router can reuse the address.
- ❔ **TV remote (CEC)** absent; the USB air-mouse is the workaround ([§14](14-physical-remote.md)). A USB-CEC adapter is the proper fix.
- ❔ **Physical remote bridge** ([§14.4](14-physical-remote.md)) and **tv-guard** ([§15](15-tv-guard.md)) are deployed but their behaviour is not recorded as verified.
- ❔ **Firefox install path** and **HLS / PC-mode / VPN-name** changes ([§16](16-changes-2026-11.md)) need a clean-install test.
- ⚠️ **Live-TV apps and stream-scraper apps** are not part of this kit. Any third-party APK runs in a container that is not isolated from the host ([§10.1](10-security.md)). Accepted risk for the apps the owner chose.
