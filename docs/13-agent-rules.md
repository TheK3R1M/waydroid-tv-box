# 13 · Rules for an AI agent working on this box

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


These rules come from the owner's household experience. Follow them even when a shortcut looks faster.

1. **The family is watching.** Before any action, check whether the TV is in use: `pgrep -x mpv`, `waydroid shell -- dumpsys audio | grep state:started`, the remote's log for recent actions. If in use, diagnose read-only (`top`, `logcat -d`, `dumpsys`, `screencap`) and do not inject keys, touch the foreground app or restart anything.
2. **No keyevents, taps or blind navigation** into the foreground app. The family can lose a show. Test only harmless input (`input keyevent 0`) and restore any value a test changed (volume, foreground app) immediately.
3. **Never type or accept credentials.** Google sign-in: the owner types on the TV or in a browser. Never `pm clear` gsf/gms/vending after the GSF id is registered.
4. **Do not install stream-scraper or piracy apps.** Ask the owner before installing any app for the family, and show a screenshot of the candidate first. Remove apps the owner did not ask for.
5. **Only x86/x86_64 APKs** (`adb install --abi x86`). Check `primaryCpuAbi`. Check APKs on virustotal.com before installing them for anyone. Do not install untrusted APKs on your own initiative.
6. **Verify on the real output.** For host mpv, use `tvshot`. For Android, use `screencap` and remember that tvshot cannot see Android. A process being up is not "working". Confirm by reading `sys.boot_completed`, `mCurrentFocus`, `PlaybackState` and `pactl sink-inputs`.
7. **Measure intermittent problems long enough.** Freezes need a window several times longer than the symptom period (tens of minutes to hours). Do not say "fixed" from one short sample. When the owner says it is still broken, assume your test was too narrow and re-measure.
8. **Do not automate kills.** Auto-heal may only run a recovery that cannot trigger in normal operation (e.g. a full session restart on a clear condition). Never a timer that kills the audio HAL or any subsystem on a symptom.
9. **Do not expand exposure.** No public DNS, port, certificate or IPv6 firewall change without the owner's explicit approval. Probe exposure from the inside of the confined side and report an open/closed table.
10. **Keep secrets out of the kit and out of logs.** Passwords, tokens, PINs, MAC lists and router credentials stay on the admin PC or in the owner's password store. The kit uses `__PLACEHOLDER__` tokens; `tools/check-placeholders.sh` must pass before deployment.
11. **Back up before replacing** a service script or the Waydroid data (`.bak`/`.orig`), and keep the source of truth on the admin PC (the scratch directory is pruned after 24 h idle).
13. **Deploy from a filled copy, never from the unfilled kit.** `tools/deploy-remote.sh <filled-copy>` refuses placeholders and keeps the previous release on the host.
14. **Physical remote and firewall guard.** Set the logind power-key drop-in before any new USB remote ([§14.2](14-physical-remote.md)). Do not quarantine or disable an app without the owner's word; tv-guard's `WATCH` list is an owner decision ([§15.6](15-tv-guard.md)).
12. **Log your changes** where the owner can read them: the remote's audit log for household actions, and the vault/change log for infrastructure changes.
