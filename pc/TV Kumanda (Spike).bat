@echo off
rem Keyboard-only remote for the TV: no video stream, almost zero cost. Ctrl+B = back. Look at the TV, not the PC.
rem Needs adb and scrcpy on PATH.
adb connect __TV_HOST_IP__:5555 >nul
start "" scrcpy -s __TV_HOST_IP__:5555 --window-title "TV Kumanda (Spike)" --no-video --no-audio --shortcut-mod=lctrl,lalt
