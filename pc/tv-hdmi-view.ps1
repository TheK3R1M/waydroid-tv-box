# TV'nin gercek HDMI goruntusu -> PC penceresi. "TV Ekran (HDMI).bat" bunu calistirir.
# ssh (Spike: GPU yakalama + VAAPI H.264) -> ffplay. Pencere kapaninca ssh de kapatilir (Spike'ta da durur).
$ErrorActionPreference = 'Stop'
$ffplay = (Get-Command ffplay -ErrorAction Stop).Source   # ffplay must be on PATH (winget install Gyan.FFmpeg)

$s = New-Object System.Diagnostics.ProcessStartInfo
$s.FileName = 'ssh.exe'
$s.Arguments = '-o BatchMode=yes -o ConnectTimeout=8 -o ServerAliveInterval=5 pve-tv /usr/local/bin/tv-hdmi-stream 1280'
$s.UseShellExecute = $false; $s.RedirectStandardOutput = $true; $s.CreateNoWindow = $true

$f = New-Object System.Diagnostics.ProcessStartInfo
$f.FileName = $ffplay
$f.Arguments = '-loglevel error -fflags nobuffer -flags low_delay -framedrop -window_title "TV Ekran (HDMI)" -x 1280 -y 720 -'
$f.UseShellExecute = $false; $f.RedirectStandardInput = $true

$sp = [System.Diagnostics.Process]::Start($s)
$fp = [System.Diagnostics.Process]::Start($f)
$copy = $sp.StandardOutput.BaseStream.CopyToAsync($fp.StandardInput.BaseStream)
while (-not $fp.HasExited -and -not $sp.HasExited) { Start-Sleep -Milliseconds 300 }
if (-not $sp.HasExited) { $sp.Kill() }
if (-not $fp.HasExited) { Start-Sleep -Seconds 2; if (-not $fp.HasExited) { $fp.Kill() } }
