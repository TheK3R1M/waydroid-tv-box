@echo off
rem Shows the real TV output (channels included) in a PC window. Video only, silent.
rem Needs: ssh alias pve-tv (key login, see README section 11) and ffplay on PATH.
rem Closing the ffplay window stops ssh and the stream on the TV host.
start "" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0tv-hdmi-view.ps1"
