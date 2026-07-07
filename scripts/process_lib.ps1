# Helpers para encerrar processos do BybitBot no Windows.

function Stop-ListenersOnPorts {
    param(
        [Parameter(Mandatory = $true)][int[]]$Ports,
        [string]$Label = "listener"
    )
    $stopped = 0
    foreach ($port in $Ports) {
        $conns = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
        foreach ($conn in $conns) {
            $processId = [int]$conn.OwningProcess
            if ($processId -le 0) { continue }
            Write-Host "  Stopping $Label on :$port -> PID $processId"
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            $stopped++
        }
    }
    return $stopped
}
