# 注册计划任务：每 1 分钟检查 daemon 是否在运行
$taskName = "ClaudeTrafficLightWatchdog"
$scriptPath = "C:\Users\Administrator\.claude\traffic_light\daemon_watchdog.ps1"

# 删除旧任务
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# 创建任务
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $scriptPath"
$trigger = New-ScheduledTaskTrigger -Once -At ([datetime]::Now.AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -DontStopOnIdleEnd

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Watchdog task '$taskName' registered (every 1 minute)"

# 立即运行一次
Start-ScheduledTask -TaskName $taskName
Write-Host "Watchdog started"
