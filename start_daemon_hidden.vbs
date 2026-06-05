Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "E:\Cursor\claude_traffic_light"
objShell.Run "pythonw daemon.py", 0, False
