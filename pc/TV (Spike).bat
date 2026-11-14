@echo off
rem Open the TV Android screen on the PC (watch + keyboard/mouse). Costs TV CPU while open: close when done.
rem Needs adb and scrcpy on PATH (winget install Genymobile.scrcpy puts both in its package folder).
adb connect __TV_HOST_IP__:5555 >nul
start "" scrcpy -s __TV_HOST_IP__:5555 --window-title "TV (Spike)" -m 1280 --max-fps 30 -b 4M --no-audio --shortcut-mod=lctrl,lalt
