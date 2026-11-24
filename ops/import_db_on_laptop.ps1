<#
.SYNOPSIS
    Install the handed-over AIOS database on the laptop and start its jobs.

.DESCRIPTION
    Checks the SHA-256 written by export_db_from_pc.ps1, keeps any existing
    database as a dated copy, installs the new one, runs an integrity check
    and one harmless scheduler tick, then resumes the laptop's AIOS jobs.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File ops\import_db_on_laptop.ps1 -From E:\aios-handover
#>
param(
    [Parameter(Mandatory = $true)][string]$From,
    [string]$RepoDir = $(if ($env:AIOS_REPO) { $env:AIOS_REPO } else { Join-Path $env:USERPROFILE 'AIOS' })
)
$ErrorActionPreference = 'Stop'
$source = Join-Path $From 'investment_platform.db'
$expected = (Get-Content (Join-Path $From 'investment_platform.db.sha256') -Raw).Trim()
if ((Get-FileHash $source -Algorithm SHA256).Hash -ne $expected) { throw 'Hash mismatch: the copy is damaged. Export again.' }
if (-not (Test-Path (Join-Path $RepoDir '.env'))) { throw '.env is missing in the repository. Copy it first.' }

$dataDir = Join-Path $RepoDir 'data'
New-Item -ItemType Directory -Force $dataDir | Out-Null
$db = Join-Path $dataDir 'investment_platform.db'
if (Test-Path $db) {
    $keep = "$db.before-import-$(Get-Date -Format yyyyMMddHHmmss)"
    Move-Item $db $keep
    Write-Host "  previous database kept as $keep"
}
Copy-Item $source $db
if ((Get-FileHash $db -Algorithm SHA256).Hash -ne $expected) { throw 'Installed file hash differs; nothing resumed.' }
Write-Host "== Database installed ($expected)"

$python = Join-Path $RepoDir '.venv\Scripts\python.exe'
$check = & $python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('pragma integrity_check').fetchone()[0])" $db
if ($check -ne 'ok') { throw "Integrity check failed: $check" }
Write-Host '== Integrity ok; one scheduler tick (outside market hours it only checks data health)'
Push-Location $RepoDir
try { $env:PYTHONPATH = '.'; & $python main.py scheduler idx-tick | Select-String 'IDX SCHEDULER TICK|  - ' } finally { Pop-Location }

Import-Module (Join-Path $RepoDir 'ops\AiosHermesJobs.psm1') -Force
Write-Host '== Resuming AIOS jobs on this laptop'
$resumed = Set-AiosJobsState -Action resume
Write-Host "  $resumed job(s) resumed. Watch %LOCALAPPDATA%\AIOS\idx_tick.log on the next trading day."
