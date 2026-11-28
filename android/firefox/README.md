# Firefox: D-pad navigation on web pages

Firefox for Android is built for touch. On a TV the remote's arrow keys only scroll; links and buttons inside a
page need a mouse. `tv-dpad-nav.user.js` fixes that with a small local userscript:

- Arrow keys jump to the nearest link, button or field in that direction (grid-like, like the rest of the TV UI).
  A blue frame shows the current item. When nothing is left in that direction the page scrolls.
- OK clicks. On a text field OK opens the keyboard; passing over a field does not.
- Inside a text field left/right move the cursor; at the edge they leave the field.
- Runs only in the page. No network access, no data collection (`@grant none`).

Release Firefox only installs Mozilla-signed add-ons, so the script runs inside **Violentmonkey** (open source,
on addons.mozilla.org).

## Install (on the box, once)

```bash
A="adb -s $ADB"     # see /etc/tv/env
# 1. Violentmonkey: open the AMO page, tap "Add to Firefox", tick "Allow in private browsing", Add
$A shell am start -a android.intent.action.VIEW -d https://addons.mozilla.org/android/addon/violentmonkey/ org.mozilla.firefox
# 2. serve the script to Firefox for a moment, through adb reverse (nothing opened on the LAN)
cd <kit>/android/firefox && timeout 300 python3 -m http.server 8765 --bind 127.0.0.1 &
$A reverse tcp:8765 tcp:8765
$A shell am start -a android.intent.action.VIEW -d http://127.0.0.1:8765/tv-dpad-nav.user.js org.mozilla.firefox
#    Violentmonkey shows its install page: tap "Install"
$A reverse --remove tcp:8765
```

3. Turkish pages pop up Firefox's "Translate this page?" sheet, which steals the arrow keys. Open any Turkish
   page, tap the translate icon in the toolbar, then *Translation options* and switch on **Never translate Turkish**.

Video players (film sites embed them as an `<iframe>` from another site): the frame is one stop; **OK enters
the player** (big play button first, hidden controls are woken up), arrows move inside it, on the video itself
left/right = -/+10 s, and moving past its edge or Back returns to the page.

Check: open a news site, press DOWN a few times: a blue frame moves over the headlines; OK opens one. ✅
(tested 2026-11-28 on ntv.com.tr and trthaber.com, Firefox 160)
