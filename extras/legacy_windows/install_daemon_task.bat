@echo off
schtasks /Delete /TN "ClaudeTrafficLightDaemon" /F 2>nul
schtasks /Create /TN "ClaudeTrafficLightDaemon" /XML "C:\Users\Administrator\.claude\traffic_light\daemon_task.xml" /F
schtasks /Run /TN "ClaudeTrafficLightDaemon"
echo Done
