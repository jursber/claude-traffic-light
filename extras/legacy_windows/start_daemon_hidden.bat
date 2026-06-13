@echo off
cd /d "E:\Cursor\claude_traffic_light"
:loop
pythonw daemon.py
timeout /t 3 /nobreak >nul
goto loop
