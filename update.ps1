# Automatic forecast update: fetch polls, rerun the forecast, push to GitHub.
# Run by Windows Task Scheduler (task "Senate forecast update") every 2 days
# until 2 Nov 2026. Output is appended to logs\update.log.
#
# Run it by hand with:  powershell -ExecutionPolicy Bypass -File update.ps1
# Remove the schedule:  schtasks /Delete /TN "Senate forecast update" /F

$ErrorActionPreference = "Stop"
$python = "C:\Users\willp_xb4xanl\AppData\Local\Programs\Python\Python312\python.exe"
$git = "C:\Program Files\Git\cmd\git.exe"

Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force logs | Out-Null
$log = "logs\update.log"
$today = Get-Date -Format "yyyy-MM-dd"

"`n===== $(Get-Date -Format 'yyyy-MM-dd HH:mm') =====" | Out-File -Append -Encoding utf8 $log
try {
    & $python fetch_polls.py 2>&1 | Out-File -Append -Encoding utf8 $log
    & $python forecast.py 2>&1 | Out-File -Append -Encoding utf8 $log
    & $git add -A 2>&1 | Out-File -Append -Encoding utf8 $log
    & $git commit -m "Automatic forecast update $today" 2>&1 | Out-File -Append -Encoding utf8 $log
    & $git push 2>&1 | Out-File -Append -Encoding utf8 $log
    "Done." | Out-File -Append -Encoding utf8 $log
} catch {
    "FAILED: $_" | Out-File -Append -Encoding utf8 $log
    exit 1
}
