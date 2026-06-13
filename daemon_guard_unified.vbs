Option Explicit

Dim shell, fso, wmi, lockFile, projectDir, pythonw, scriptName
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")

lockFile = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Temp\cc_daemon_guard.lock"
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = "C:\Program Files\Python312\pythonw.exe"
scriptName = "daemon_unified.py"

If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw.exe"
End If

If IsAnotherGuardRunning(lockFile, wmi) Then
    WScript.Quit
End If

WriteCurrentPid lockFile, fso, wmi
shell.CurrentDirectory = projectDir

Do
    shell.Run """" & pythonw & """ """ & projectDir & "\" & scriptName & """", 0, True
    WScript.Sleep 3000
Loop

Function IsAnotherGuardRunning(path, wmiService)
    Dim oldPid, file, processes
    IsAnotherGuardRunning = False

    If Not fso.FileExists(path) Then
        Exit Function
    End If

    On Error Resume Next
    Set file = fso.OpenTextFile(path, 1)
    oldPid = Trim(file.ReadAll)
    file.Close
    On Error GoTo 0

    If oldPid = "" Then
        Exit Function
    End If

    Set processes = wmiService.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE ProcessId = " & oldPid)
    If processes.Count > 0 Then
        IsAnotherGuardRunning = True
    End If
End Function

Sub WriteCurrentPid(path, fileSystem, wmiService)
    Dim processes, process, currentPid, file
    currentPid = 0

    Set processes = wmiService.ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name = 'wscript.exe' OR Name = 'cscript.exe'")
    For Each process In processes
        If InStr(1, process.CommandLine, WScript.ScriptFullName, vbTextCompare) > 0 Then
            currentPid = process.ProcessId
            Exit For
        End If
    Next

    If currentPid = 0 Then
        Exit Sub
    End If

    Set file = fileSystem.CreateTextFile(path, True)
    file.Write CStr(currentPid)
    file.Close
End Sub
