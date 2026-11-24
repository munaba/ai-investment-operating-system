# Shared helpers for the AIOS ops scripts: find, pause and resume the AIOS
# Hermes cron jobs by name.

$Script:AiosJobNames = @('AIOS idx-tick', 'AIOS v2 rank IDX', 'AIOS v2 rank US', 'AIOS daily audit')

function Get-AiosJobIds {
    <# Map of job name -> Hermes job id for every AIOS job on this machine. #>
    $ids = @{}
    $current = $null
    foreach ($line in (& hermes cron list 2>&1)) {
        if ($line -match '^\s{2}([0-9a-f]{12})\s+\[') {
            $current = $Matches[1]
        } elseif ($current -and $line -match '^\s+Name:\s+(.+?)\s*$') {
            if ($Script:AiosJobNames -contains $Matches[1]) { $ids[$Matches[1]] = $current }
            $current = $null
        }
    }
    return $ids
}

function Set-AiosJobsState {
    <# Pause or resume every AIOS job found on this machine. #>
    param([ValidateSet('pause', 'resume')][string]$Action)
    $ids = Get-AiosJobIds
    foreach ($name in $ids.Keys) {
        & hermes cron $Action $ids[$name] | Out-Null
        Write-Host "  $Action $name ($($ids[$name]))"
    }
    return $ids.Count
}

Export-ModuleMember -Function Get-AiosJobIds, Set-AiosJobsState -Variable AiosJobNames
