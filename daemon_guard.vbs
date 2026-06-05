' Daemon guard - restarts daemon if it crashes
' Runs hidden at login via Startup folder

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

strDir = "E:\Cursor\claude_traffic_light"
strPython = Replace(WScript.FullName, "wscript.exe", "cscript.exe")
If InStr(WScript.FullName, "cscript.exe") > 0 Then
    strPython = "pythonw.exe"
End If

' Find pythonw.exe
strPythonW = objShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\hermes\hermes-agent\venv\Scripts\pythonw.exe"
If Not objFSO.FileExists(strPythonW) Then
    strPythonW = "pythonw.exe"
End If

objShell.CurrentDirectory = strDir

Do
    objShell.Run """" & strPythonW & """ daemon.py", 0, True
    WScript.Sleep 3000
Loop
