<#
.SYNOPSIS
    Hand the AIOS database over from the PC: pause the PC's AIOS jobs,
    take a verified backup and copy the database with its SHA-256 hash.

.DESCRIPTION
    Run on the PC after the market closes (it refuses 08:00-16:00 WIB on
    weekdays unless -Force). Pausing first means the PC stops writing, so
    the copy is the final state. The jobs stay paused: the laptop takes
    over. To roll back, run: Import-Module ops\AiosHermesJobs.psm1;
    Set-AiosJobsState resume

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File ops\export_db_from_pc.ps1 -OutDir E:\aios-handover
#>
param(
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$RepoDir = $(if ($env:AIOS_REPO) { $env:AIOS_REPO } else { 'F:\My Son' }),
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$wib = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'SE Asia Standard Time')
if (-not $Force -and $wib.DayOfWeek -notin 'Saturday', 'Sunday' -and $wib.Hour -ge 8 -and $wib.Hour -lt 16) {
    throw "It is $($wib.ToString('HH:mm')) WIB on a weekday; the scheduler may be writing. Run after 16:00 or use -Force."
}

Import-Module (Join-Path $RepoDir 'ops\AiosHermesJobs.psm1') -Force
Write-Host '== Pausing AIOS jobs on this PC'
$paused = Set-AiosJobsState -Action pause
Write-Host "  $paused job(s) paused"

Write-Host '== Verified backup'
$python = Join-Path $RepoDir '.venv\Scripts\python.exe'
Push-Location $RepoDir
try { & $python main.py backup --keep 14 } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Backup failed; nothing was copied. Jobs remain paused.' }

Write-Host "== Copying the database to $OutDir"
$db = Join-Path $RepoDir 'data\investment_platform.db'
New-Item -ItemType Directory -Force $OutDir | Out-Null
$target = Join-Path $OutDir 'investment_platform.db'
Copy-Item $db $target -Force
$hashSource = (Get-FileHash $db -Algorithm SHA256).Hash
$hashCopy = (Get-FileHash $target -Algorithm SHA256).Hash
if ($hashSource -ne $hashCopy) { throw 'Copy hash differs from the source; try again.' }
Set-Content -Path (Join-Path $OutDir 'investment_platform.db.sha256') -Value $hashCopy -Encoding ascii
Write-Host "  SHA256 $hashCopy"
Write-Host 'Done. Now run ops\import_db_on_laptop.ps1 -From <this folder> on the laptop.'
