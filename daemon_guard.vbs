' ============================================================
' 守护进程守护脚本 (daemon_guard.vbs)
' ============================================================
' 功能：循环监控守护进程，如果崩溃了就自动重启
' 放在 Windows 启动文件夹，开机自动运行
' 用 VBScript 是因为可以完全隐藏窗口（.bat 会闪一下）
'
' 运行逻辑：
'   1. 用 pythonw.exe（无窗口）启动 daemon.py
'   2. pythonw.exe 退出后（崩溃或正常退出），等 3 秒
'   3. 回到步骤 1，重新启动
'   4. 无限循环，永远不停
' ============================================================

Dim objShell, objFSO
Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' ============================================================
' 防重复运行：用 lock 文件 + WMI 检查
' ============================================================
strLockFile = objShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Temp\cc_daemon_guard.lock"
Dim bAlreadyRunning
bAlreadyRunning = False

If objFSO.FileExists(strLockFile) Then
    Dim strOldPID
    strOldPID = ""
    On Error Resume Next
    strOldPID = Trim(objFSO.OpenTextFile(strLockFile).ReadAll)
    On Error GoTo 0

    If strOldPID <> "" Then
        ' 检查该 PID 是否还在运行
        Dim objWMIService, colProcesses
        Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")
        Set colProcesses = objWMIService.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE ProcessId = " & strOldPID)
        If colProcesses.Count > 0 Then
            bAlreadyRunning = True
        End If
    End If
End If

If bAlreadyRunning Then
    WScript.Quit
End If

' 获取当前进程 PID 并写入 lock 文件
' 通过 WMI 查找最新的 wscript.exe 进程
Dim myPID
Set colWmi = GetObject("winmgmts:\\.\root\cimv2").ExecQuery( _
    "SELECT ProcessId FROM Win32_Process WHERE Name = 'wscript.exe' ORDER BY ProcessId DESC")
myPID = 0
For Each p In colWmi
    myPID = p.ProcessId
    Exit For  ' 取最新的
Next

Dim objLockFile
Set objLockFile = objFSO.CreateTextFile(strLockFile, True)
objLockFile.Write CStr(myPID)
objLockFile.Close

' 守护进程所在的目录
strDir = "C:\Users\Administrator\.claude\traffic_light"

' pythonw.exe 的路径（hermes venv 中的无窗口 Python）
strPythonW = objShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\hermes\hermes-agent\venv\Scripts\pythonw.exe"

' 如果 hermes venv 的 pythonw 不存在，尝试系统 PATH 中的
If Not objFSO.FileExists(strPythonW) Then
    strPythonW = "pythonw.exe"
End If

' 切换到项目目录
objShell.CurrentDirectory = strDir

' 无限循环：启动 → 等退出 → 重启
Do
    ' Run 参数说明：
    '   第1个参数：要运行的命令
    '   第2个参数 0：隐藏窗口
    '   第3个参数 True：等待命令结束后再继续（这样崩溃后才能重启）
    objShell.Run """" & strPythonW & """ daemon.py", 0, True

    ' 守护进程退出后等 3 秒再重启（避免疯狂重启）
    WScript.Sleep 3000
Loop
