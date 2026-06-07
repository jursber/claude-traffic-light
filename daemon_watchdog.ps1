# daemon_watchdog.ps1 - restart daemon if not running
$python = "C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
$workDir = "C:\Users\Administrator\.claude\traffic_light"
$pidFile = Join-Path $env:LOCALAPPDATA "Temp\cc_traffic_light_daemon.pid"
$lockFile = Join-Path $env:LOCALAPPDATA "Temp\cc_daemon_watchdog.lock"

# prevent duplicate runs
if (Test-Path $lockFile) {
    $lockAge = (Get-Date) - (Get-Item $lockFile).LastWriteTime
    if ($lockAge.TotalSeconds -lt 40) {
        exit 0
    }
}
Set-Content $lockFile (Get-Date).ToString("o")

# check if daemon is running via PID file
$alive = $false
if (Test-Path $pidFile) {
    $pidStr = (Get-Content $pidFile -Raw).Trim()
    $pidNum = 0
    if ([int]::TryParse($pidStr, [ref]$pidNum)) {
        $proc = Get-Process -Id $pidNum -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -match "python") {
            $alive = $true
        }
    }
}

# start daemon if not alive
if (-not $alive) {
    Start-Process -FilePath $python -ArgumentList "daemon.py" -WorkingDirectory $workDir -WindowStyle Hidden
}

Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
