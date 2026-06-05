# 踩坑记录

开发过程中遇到的问题和解决方案。

## 1. Python 版本冲突

**现象**：`pip install pyserial` 成功，但 `import serial` 报 ModuleNotFoundError。

**原因**：系统装了多个 Python（3.11 和 3.14），`pip` 默认装到了 3.14 的 site-packages，但 `python` 命令解析到 hermes venv 的 3.11。

**解决**：用 `pip3.exe`（hermes venv 目录下）安装：`C:\...\hermes-agent\venv\Scripts\pip3.exe install pyserial`

## 2. 串口打开卡死 / Semaphore Timeout

**现象**：Python 打开 COM3 后 `write()` 卡住，报 "The semaphore timeout period has expired"。

**原因**：ESP32C3 的 **USB CDC On Boot** 默认是 Disabled，USB 虚拟串口功能没启用。

**解决**：Arduino IDE → Tools → USB CDC On Boot → **Enabled**，重新烧录。

## 3. DTR 复位导致灯闪烁即灭

**现象**：Python 发送指令后灯闪一下就灭了，或者完全不亮。

**原因**：`serial.Serial()` 打开串口时会拉高 DTR 信号，触发 ESP32C3 复位。复位后程序重新初始化，之前的指令丢失。

**解决**：打开串口时禁用 DTR：
```python
ser = serial.Serial(port, baud, dsrdtr=False)
ser.dtr = False
ser.rts = False
```

## 4. Arduino IDE 串口监视器占用 COM 口

**现象**：Python 报 PermissionError，无法打开 COM3。

**原因**：Arduino IDE 的串口监视器打开了 COM3，独占端口。

**解决**：关闭 Arduino IDE 串口监视器（关掉窗口即可，不用关 IDE）。

## 5. Hook 延迟过大

**现象**：每次 hook 触发后灯要等几百毫秒才亮。

**原因**：每次 hook 都启动一个新 Python 进程（~300ms 启动时间），加上串口开关耗时。

**解决**：改用守护进程模式。`daemon.py` 常驻后台持有串口连接，hook 只需写一个几字节的状态文件（<1ms）。

## 6. ESP32C3 引脚和电平

**现象**：按文档写的 GPIO2/3/4 不亮。

**原因**：不同开发板引脚定义不同。本项目的板子用 GPIO0/1/2，且 LED 是有源低电平（LOW=亮）。

**解决**：以实际跑通的跑马灯代码为准，确认引脚和电平逻辑后再写控制代码。

## 7. Settings 修改不即时生效

**现象**：修改 `~/.claude/settings.json` 的权限配置后，当前会话不生效。

**原因**：CC 在会话启动时加载配置，运行中不会热更新。

**解决**：修改 settings.json 后需要重启 CC 会话。
