@echo off
schtasks /Delete /TN "ClaudeTrafficLightWatchdog" /F 2>nul
schtasks /Create /TN "ClaudeTrafficLightWatchdog" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\Users\Administrator\.claude\traffic_light\daemon_watchdog.ps1" /SC MINUTE /MO 1 /F /RL HIGHEST
schtasks /Run /TN "ClaudeTrafficLightWatchdog"
echo Done
