# Automatic forecast update: fetch polls, rerun the forecast, push to GitHub.
# Run by Windows Task Scheduler (task "Senate forecast update") every 2 days
# until 2 Nov 2026. Output is appended to logs\update.log.
#
# Run it by hand with:  powershell -ExecutionPolicy Bypass -File update.ps1
# Remove the schedule:  schtasks /Delete /TN "Senate forecast update" /F

# git writes normal progress messages to stderr, so judge success by each
# command's exit code rather than by whether it printed to stderr.
$ErrorActionPreference = "Continue"
$python = "C:\Users\willp_xb4xanl\AppData\Local\Programs\Python\Python312\python.exe"
$git = "C:\Program Files\Git\cmd\git.exe"

Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force logs | Out-Null
$log = "logs\update.log"
$today = Get-Date -Format "yyyy-MM-dd"

function Step($name, [scriptblock]$command) {
    & $command 2>&1 | ForEach-Object { "$_" } | Out-File -Append -Encoding utf8 $log
    if ($LASTEXITCODE -ne 0) {
        "FAILED at: $name (exit code $LASTEXITCODE)" | Out-File -Append -Encoding utf8 $log
        exit 1
    }
}

"`n===== $(Get-Date -Format 'yyyy-MM-dd HH:mm') =====" | Out-File -Append -Encoding utf8 $log
Step "fetch polls" { & $python fetch_polls.py }
Step "forecast" { & $python forecast.py }
if (Test-Path "data\electindex\races.csv") {
    Step "house forecast" { & $python house_forecast.py }
}
Step "git add" { & $git add -A }
& $git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    "Nothing changed - no commit." | Out-File -Append -Encoding utf8 $log
    exit 0
}
Step "git commit" { & $git commit -m "Automatic forecast update $today" }
Step "git push" { & $git push }
"Done." | Out-File -Append -Encoding utf8 $log
