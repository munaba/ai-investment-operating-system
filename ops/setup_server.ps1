<#
.SYNOPSIS
    Prepare a Windows machine (the laptop) to be the AIOS server.

.DESCRIPTION
    Run once on the new machine, in PowerShell, after installing Git,
    Python 3.14, Node.js, 9router (npm i -g 9router) and Hermes. With
    -NoNineRouter, 9router and Node.js are not needed: the audit job then
    uses Hermes's own main model (set it first with `hermes model`). It:
      1. clones the repository (or reuses an existing checkout),
      2. creates .venv and installs requirements.txt,
      3. sets AIOS_REPO for this user,
      4. installs the Hermes wrapper scripts and (unless -NoNineRouter)
         the 9router autostart,
      5. keeps the machine awake on AC power with the lid closed,
      6. creates the audit worktree,
      7. creates the four AIOS Hermes jobs PAUSED (resumed by
         import_db_on_laptop.ps1 once the database is in place).
    It never copies secrets: copy .env yourself (see ops/README.md).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File ops\setup_server.ps1 -RepoDir C:\AIOS

.EXAMPLE
    # Hermes's built-in model instead of 9router (run `hermes model` first)
    powershell -ExecutionPolicy Bypass -File ops\setup_server.ps1 -RepoDir C:\AIOS -NoNineRouter
#>
param(
    [string]$RepoDir = (Join-Path $env:USERPROFILE 'AIOS'),
    [string]$AuditDir = '',
    [string]$RepoUrl = 'https://github.com/munaba/ai-investment-operating-system.git',
    [switch]$SkipPower,
    [switch]$SkipJobs,
    [switch]$NoNineRouter
)
$ErrorActionPreference = 'Stop'
if (-not $AuditDir) { $AuditDir = "$RepoDir-hermes" }

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Require($command, $hint) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "$command not found. $hint" }
}

Step 'Checking prerequisites'
Require git 'Install Git for Windows.'
Require py 'Install Python 3.14 from python.org (includes the py launcher).'
if (-not $NoNineRouter) {
    Require node 'Install Node.js LTS.'
    Require 9router 'Run: npm install -g 9router, then start it once and sign in.'
}
Require hermes 'Install Hermes and sign in to Telegram there first.'
# Hermes keeps job scripts under its home: $env:HERMES_HOME, else
# %LOCALAPPDATA%\hermes (the PC), else ~\.hermes. The scripts folder itself
# may not exist yet on a fresh install, so it is created.
$hermesHome = @($env:HERMES_HOME, (Join-Path $env:LOCALAPPDATA 'hermes'), (Join-Path $env:USERPROFILE '.hermes')) |
    Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $hermesHome) { throw 'Hermes home not found. Start Hermes once (hermes model) so it creates its folder, then run this again.' }
$hermesScripts = Join-Path $hermesHome 'scripts'
New-Item -ItemType Directory -Force $hermesScripts | Out-Null
Write-Host "  Hermes scripts folder: $hermesScripts"

Step "Repository at $RepoDir"
if (-not (Test-Path (Join-Path $RepoDir '.git'))) {
    git clone $RepoUrl $RepoDir
} else {
    git -C $RepoDir fetch origin
    git -C $RepoDir status -sb | Select-Object -First 1
}

Step 'Python environment'
$python = Join-Path $RepoDir '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { py -3.14 -m venv (Join-Path $RepoDir '.venv') }
& $python -m pip install --upgrade pip | Out-Null
& $python -m pip install -r (Join-Path $RepoDir 'requirements.txt')
[Environment]::SetEnvironmentVariable('AIOS_REPO', $RepoDir, 'User')
$env:AIOS_REPO = $RepoDir
if (-not (Test-Path (Join-Path $RepoDir '.env'))) {
    Write-Warning '.env is missing. Copy it from the PC by hand (USB or password manager), never through git or chat.'
}

Step 'Hermes wrapper scripts'
Copy-Item (Join-Path $RepoDir 'ops\hermes\*.py') $hermesScripts -Force
Get-ChildItem (Join-Path $RepoDir 'ops\hermes\*.py') | ForEach-Object { Write-Host "  $($_.Name)" }

if (-not $NoNineRouter) {
Step '9router autostart at logon'
$autostart = Join-Path $env:LOCALAPPDATA '9router-autostart'
New-Item -ItemType Directory -Force $autostart | Out-Null
Copy-Item (Join-Path $RepoDir 'ops\9router\*') $autostart -Force
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) '9router.lnk'))
$link.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
$link.Arguments = '"' + (Join-Path $autostart 'start-9router.vbs') + '"'
$link.WorkingDirectory = $autostart
$link.Save()
Write-Host '  Startup shortcut created. For restarts without anyone logging in, enable auto-login (netplwiz).'
}

if (-not $SkipPower) {
    Step 'Power: never sleep on AC, lid close does nothing'
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
    powercfg /setactive SCHEME_CURRENT
    Write-Host '  Done. Also set Windows Update active hours to cover 08:00-23:00.'
}

Step "Audit worktree at $AuditDir"
if (-not (Test-Path $AuditDir)) {
    git -C $RepoDir fetch origin
    git -C $RepoDir worktree add --detach $AuditDir origin/master
}

if (-not $SkipJobs) {
    Step 'Hermes jobs (created paused)'
    Import-Module (Join-Path $RepoDir 'ops\AiosHermesJobs.psm1') -Force
    $existing = Get-AiosJobIds
    $common = @('--workdir', $RepoDir, '--interpreter', $python, '--timezone', 'Asia/Jakarta', '--paused')
    $jobs = @(
        @{ Name = 'AIOS idx-tick'; Args = @('--script', 'aios_idx_tick.py', '--no-agent', '--deliver', 'local') + $common + @('*/5 8-15 * * 1-5') },
        @{ Name = 'AIOS v2 rank IDX'; Args = @('--script', 'aios_v2_rank_idx.py', '--no-agent', '--deliver', 'local', '--failure-deliver', 'telegram', '--catch-up', 'on') + $common + @('30 8 * * 1-5') },
        @{ Name = 'AIOS v2 rank US'; Args = @('--script', 'aios_v2_rank_us.py', '--no-agent', '--deliver', 'local', '--failure-deliver', 'telegram', '--catch-up', 'on') + $common + @('45 20 * * 1-5') }
    )
    foreach ($job in $jobs) {
        if ($existing.ContainsKey($job.Name)) { Write-Host "  exists: $($job.Name)"; continue }
        & hermes cron create --name $job.Name @($job.Args)
        if ($LASTEXITCODE -ne 0) { Write-Warning "FAILED to create: $($job.Name) (exit $LASTEXITCODE). Fix the error above, then run this script again."; continue }
        Write-Host "  created: $($job.Name)"
    }
    if (-not $existing.ContainsKey('AIOS daily audit')) {
        $prompt = (Get-Content (Join-Path $RepoDir 'ops\hermes\daily_audit_prompt.txt') -Raw)
        $prompt = $prompt.Replace('F:\AIOS-hermes', $AuditDir).Replace('F:\My Son', $RepoDir)
        # 9router: pin the HERMES route. Otherwise pin Hermes's current main
        # model (`hermes model`), so a later default change does not move it.
        $modelArgs = if ($NoNineRouter) { @('--pin') } else { @('--model', 'HERMES', '--provider', 'custom:9router') }
        & hermes cron create --name 'AIOS daily audit' --deliver telegram --catch-up off --timezone Asia/Jakarta `
            --workdir $AuditDir @modelArgs --no-wrap-response --paused `
            '30 7,12,20 * * *' $prompt
        if ($LASTEXITCODE -ne 0) { Write-Warning "FAILED to create: AIOS daily audit (exit $LASTEXITCODE). Fix the error above, then run this script again." }
        else { Write-Host "  created: AIOS daily audit ($(if ($NoNineRouter) { 'Hermes main model, pinned' } else { 'HERMES via 9router' }))" }
    }
}

Step 'Next'
Write-Host '  1. Copy .env from the PC by hand.'
Write-Host '  2. On the PC, after 16:00 WIB: ops\export_db_from_pc.ps1 -OutDir <USB or share>'
Write-Host '  3. Here: ops\import_db_on_laptop.ps1 -From <that folder>  (checks the hash, resumes the jobs)'
