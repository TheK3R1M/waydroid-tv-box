# 06 · Launcher, apps, Google sign-in

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


### 6.1 Launcher (home screen)

Picked launcher: **Projectivy Launcher** (official GitHub release, `spocky/miproja1`; package `com.spocky.projengmenu`). Alternative considered: FLauncher (removed, the owner wanted fewer apps). Ask the owner before picking another.

Install the x86 APK via adb from the host ([§7.3](07-adb.md)):

```bash
adb -s __ANDROID_IP__:5555 install -r --abi x86 ProjectivyLauncher-<version>.apk
```

Make the third-party launcher HOME (`set-home-activity` alone loses to the stock launcher):

```bash
waydroid shell -- pm disable-user --user 0 com.google.android.tvlauncher     # undo: pm enable
waydroid shell -- cmd package query-activities --brief -a android.intent.action.MAIN -c android.intent.category.HOME
waydroid shell -- input keyevent 3       # HOME; check mCurrentFocus shows com.spocky.projengmenu
```

Boot lands on the notification side panel. The fix is already in `tv-adb-lan.sh` (closes the panel with BACK, then HOME, 8 s after boot). ✅

### 6.2 Apps the family uses

| App | Package | How to install | Notes |
|---|---|---|---|
| **SmartTube** (YouTube for TV) | `org.smarttube.stable` | `SmartTube_stable_<v>_x86.apk` with `adb install --abi x86` | Check `dumpsys package org.smarttube.stable \| grep primaryCpuAbi` = `x86`. Set the player to **1080p / AVC** inside SmartTube (software decode cannot do 4K). This is a manual step in the UI |
| **Firefox** (web browser, replaces TV Bro) | `org.mozilla.firefox` | official Mozilla x86_64 APK: `fenix-<v>-android-x86_64` from `archive.mozilla.org/pub/fenix/releases/<v>/android/` | Used by the "Tarayıcı" shortcut and link fallback. ❔ Install path taken from the current deployment; not re-verified on a clean install. TV Bro was dropped because it was hard to drive with the remote. Add D-pad navigation on web pages: [android/firefox](../android/firefox/README.md) |
| **Kodi** 21.3 x86 (32-bit) | `org.xbmc.kodi` | `kodi-21.3…x86…apk` | Used by the phone upload panel ("Gönder"). Not used for live channels any more. Grant media permissions once: `pm grant org.xbmc.kodi android.permission.READ_MEDIA_VIDEO` (and `READ_MEDIA_IMAGES`/`AUDIO` as the build asks) |
| **ADBKeyboard** (release build) | `com.android.adbkeyboard` | `keyboardservice-debug.apk` from the senzhk/ADBKeyBoard **release** page (v2.5-dev) | See 6.3. Not the old `ADBKeyboard.apk` in the repo root |

Never install `universal` APKs. `adb install --abi x86` on the host or PC is the rule.

Apps that were disabled after crash-looping on this image (keep them off unless you retest):
`com.google.android.katniss` (voice search, ARM lib via houdini; crashed ~8× a night), `com.google.android.apps.mediashell` (Cast receiver; not usable on an uncertified build). Disable with `pm disable-user --user 0 <pkg>`. ✅

Content rules (owner's standing preferences, do not change without asking):
- Free legal catalogues: tabii (TRT), SmartTube, Plex free, Crunchyroll free tier, Jellyfin for his own library.
- Do **not** install stream-scraper addons — piracy and malware risk on a box that runs untrusted APKs.
- ⚠️ The web remote's `tv` app shortcut is a placeholder (`com.example.livetv/.MainActivity` in `tv-remote.py`). Point it at a legal live-TV app the owner chooses, or delete the entry. Many free live-TV apps scrape third-party hosts: ask before installing one. The kit installs none.

### 6.3 ADBKeyboard (the typing path)

The remote's "Yaz" field mirrors text through ADBKeyboard broadcasts. It must be the **default** input method and must never be switched automatically (switching closes open search boxes on the TV).

```bash
adb -s __ANDROID_IP__:5555 uninstall com.android.adbkeyboard      # signatures differ from the old build
adb -s __ANDROID_IP__:5555 install -r keyboardservice-debug.apk   # v2.5-dev release
adb -s __ANDROID_IP__:5555 shell ime enable com.android.adbkeyboard/.AdbIME
adb -s __ANDROID_IP__:5555 shell ime set com.android.adbkeyboard/.AdbIME
```

Test (run the Turkish test from Python or the phone, not from git-bash: the shell mangles non-ASCII):

```bash
adb -s __ANDROID_IP__:5555 shell am broadcast -a ADB_INPUT_B64 --es msg "$(printf 'deneme' | base64)"
adb -s __ANDROID_IP__:5555 shell uiautomator dump /sdcard/u.xml   # read text= of the focused field
```

Why the **release** build: the old repo-root APK registers its broadcast receiver only after its input view is created. In fields that never show a soft keyboard (SmartTube search) every broadcast returns `result=0` and the text never changes. The v2.5-dev release registers in `onCreate`. ✅ Verified on SmartTube search with Turkish letters.

Caveat (accepted by the owner): while ADBKeyboard is the IME, any app on Android can inject text by broadcast.

### 6.4 Google sign-in on an uncertified device

The TV is not Google-certified. Google sign-in is optional (apps can run without it).

1. Get the GSF id (the device identifier for the registration):
   ```bash
   waydroid shell -- sh -c "sqlite3 /data/data/com.google.android.gsf/databases/gservices.db \"select value from main where name='android_id';\""
   ```
2. The owner registers that id at `google.com/android/uncertified` (captcha and login are the owner's job). Never type the owner's credentials for them.
3. **Never run `pm clear` on `com.google.android.gsf`, `com.google.android.gms` or `com.android.vending` after the id was given.** It regenerates the id and voids the registration. ✅ This happened once on this host (agent error); the old id was lost.
4. Open the sign-in screen remotely if the owner asks: `adb shell am start -a android.settings.ADD_ACCOUNT_SETTINGS --esa account_types com.google`.
5. Passkey-only accounts cannot sign in from this TV: the passkey lives on the PC only. Options: add a password to the account (`myaccount.google.com/signinoptions/password`), or skip Google and use **Aurora Store** (anonymous open-source Play client).
6. Propagation takes 10–30 min to hours. `dumpsys account` shows `Accounts: 0` until sign-in is complete.
