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

' 守护进程所在的目录
strDir = "E:\Cursor\claude_traffic_light"

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
