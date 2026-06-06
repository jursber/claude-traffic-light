"""
计划任务安装脚本 - 将守护进程注册为 Windows 计划任务

功能：
  1. 创建 Windows 计划任务，登录时自动启动守护进程
  2. 使用 pythonw.exe（无窗口 Python）运行，不弹控制台
  3. 使用 InteractiveToken 登录类型，确保能访问 COM 端口
  4. 支持卸载（--uninstall 参数）

必须以管理员身份运行！
用法：
  python install_service.py           # 安装
  python install_service.py --uninstall  # 卸载
"""

import subprocess
import sys
import os
import tempfile

# ============================================================
# 配置
# ============================================================

# 计划任务名称（在任务计划程序中显示的名称）
TASK_NAME = "ClaudeTrafficLightDaemon"

# 守护进程脚本的绝对路径
DAEMON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon.py")

# pythonw.exe 路径（无窗口版本的 Python，不会弹出控制台）
# 把 python.exe 替换为 pythonw.exe
PYTHONW = sys.executable.replace("python.exe", "pythonw.exe")

# ============================================================
# 计划任务 XML 配置
# ============================================================
# 为什么用 XML 而不是 schtasks 命令行？
# 因为需要设置 <Hidden>true</Hidden> 来隐藏窗口，
# schtasks 命令行不支持这个参数。

TASK_XML = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Settings>
    <!-- 接通电源时也运行（笔记本用电池时不运行） -->
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <!-- 如果已经在运行，忽略新的启动请求 -->
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <!-- 不限制运行时长（默认会限制 72 小时） -->
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <!-- 隐藏窗口，不在任务栏显示 -->
    <Hidden>true</Hidden>
  </Settings>
  <Triggers>
    <!-- 用户登录时触发 -->
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>"{PYTHONW}"</Command>
      <Arguments>"{DAEMON_PATH}"</Arguments>
    </Exec>
  </Actions>
  <Principals>
    <Principal id="Author">
      <!-- InteractiveToken：在用户会话中运行（能访问 COM 端口） -->
      <!-- S4U 类型无法访问 COM 端口，所以不能用 -->
      <LogonType>InteractiveToken</LogonType>
      <!-- 以最高权限运行 -->
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
</Task>"""


def install():
    """
    安装计划任务。

    步骤：
    1. 删除已有的同名任务（如果有）
    2. 把 XML 配置写到临时文件
    3. 用 schtasks 命令导入 XML 创建任务
    4. 立即启动一次
    5. 清理临时文件
    """
    # 先删除旧任务（忽略错误，可能不存在）
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
                    capture_output=True)

    # 写 XML 到临时文件
    xml_path = os.path.join(tempfile.gettempdir(), "cc_tl_task.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(TASK_XML)

    # 创建计划任务
    result = subprocess.run(
        ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/XML", xml_path],
        capture_output=True, text=True,
    )
    os.remove(xml_path)  # 清理临时文件

    if result.returncode == 0:
        # 创建成功，立即启动一次
        subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True)
        print(f"计划任务 '{TASK_NAME}' 已创建并启动。")
    else:
        print(f"创建失败: {result.stderr}", file=sys.stderr)
        sys.exit(1)


def uninstall():
    """卸载计划任务。"""
    result = subprocess.run(
        ["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"计划任务 '{TASK_NAME}' 已删除。")
    else:
        print(f"删除失败: {result.stderr}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install()
