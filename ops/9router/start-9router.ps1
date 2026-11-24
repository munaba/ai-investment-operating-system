# Starts 9router in the background at Windows logon (launched hidden by
# start-9router.vbs from the Startup folder). Same as typing `9router` in a
# terminal, minus the browser tab. Does nothing if 9router already answers,
# because starting a second 9router stops the first one.
param([int]$Port = 20128)

$log = Join-Path $PSScriptRoot 'autostart.log'
function Write-Log($msg) { "$(Get-Date -Format s) $msg" | Add-Content -Path $log -Encoding utf8 }

# A real TCP connect: Get-NetTCPConnection's Listen filter misses 9router's
# socket on this PC.
function Test-Listening([int]$p) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { return ($client.ConnectAsync('127.0.0.1', $p).Wait(1500) -and $client.Connected) }
    catch { return $false }
    finally { $client.Dispose() }
}

if (Test-Listening $Port) {
    Write-Log "port $Port already answering; nothing to do"
    exit 0
}

$cli = Join-Path $env:APPDATA 'npm\node_modules\9router\cli.js'
$node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
if (-not $node) { $node = 'C:\Program Files\nodejs\node.exe' }
if (-not (Test-Path $cli) -or -not (Test-Path $node)) {
    Write-Log "9router or node not found (cli=$cli node=$node)"
    exit 1
}

Start-Process -FilePath $node `
    -ArgumentList @("`"$cli`"", '--port', $Port, '--tray', '--no-browser', '--skip-update') `
    -WindowStyle Hidden

# Wait up to 60s for the server to answer, then record the result.
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Listening $Port) {
        Write-Log "started 9router on port $Port"
        exit 0
    }
}
Write-Log "9router did not answer on port $Port within 60s"
exit 1
