"""
配置模块 - Claude Code 红绿灯项目

功能：
  1. 自动检测 ESP32C3 的串口号（通过 USB VID 识别）
  2. 定义所有灯光状态对应的串口指令
  3. 定义多终端并行时的优先级规则
"""

import os
import serial.tools.list_ports

# ============================================================
# 串口配置
# ============================================================

# Espressif（ESP32 芯片厂商）的 USB Vendor ID
# 所有 ESP32C3 开发板的 USB 设备都会携带这个 ID
ESP32_VID = 0x303A

# 如果自动检测失败，回退到 COM3
DEFAULT_PORT = "COM3"

# 串口波特率，必须和 Arduino 代码中的 Serial.begin() 一致
BAUD_RATE = 115200

# ============================================================
# BLE（可选，与固件 traffic_light.ino 中 UUID 保持一致）
# ============================================================
# 守护进程默认仍用 USB 串口；设置环境变量 CC_TL_TRANSPORT=ble 启用 BLE。
BLE_DEVICE_NAME = os.environ.get("CC_TL_BLE_NAME", "CC-TrafficLight")
BLE_SERVICE_UUID = "e52c12b6-7ac3-4636-9c17-3d608bcea796"
BLE_CHAR_UUID = "e52c12b7-7ac3-4636-9c17-3d608bcea796"


def detect_port() -> str:
    """
    自动扫描系统所有 COM 口，找到 ESP32C3 的串口号。

    原理：每个 USB 设备都有 Vendor ID（厂商ID）和 Product ID（产品ID），
    ESP32C3 的 VID 固定是 0x303A（Espressif 注册的）。
    遍历所有串口设备，匹配到就返回，否则返回默认值。
    """
    for port in serial.tools.list_ports.comports():
        if port.vid == ESP32_VID:
            return port.device  # 例如 "COM3"
    return DEFAULT_PORT


# 自动检测到的串口号，模块加载时执行一次
SERIAL_PORT = detect_port()

# ============================================================
# 状态文件目录（多终端 IPC 用）
# ============================================================

# 每个 CC 终端写自己的状态文件：{STATE_DIR}/{session_id}
# 所有终端的状态文件放同一个目录，守护进程统一读取
STATE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp", "cc_tl_states")

# ============================================================
# 串口指令映射
# ============================================================
# ESP32C3 收到单个字符后，根据字符点亮对应灯
# 大写 = 常亮，小写 = 闪烁（约定）

COMMANDS = {
    "model":       "G",   # 绿灯闪烁 - 正在调用模型，等 API 响应
    "working":     "g",   # 绿灯常亮 - 拿到响应，正在写代码/执行操作
    "thinking":    "y",   # 黄灯闪烁 - CC 在思考
    "alert":       "r",   # 红灯闪烁 - 需要用户授权 / 出错 / 问你问题
    "idle":        "R",   # 红灯常亮 - CC 完成回复，等你输入
    "off":         "O",   # 全灭     - 会话结束
}

# ============================================================
# 优先级（数字越小越优先）
# ============================================================
# 多个 CC 终端同时运行时，守护进程取优先级最高的状态显示
# 例如：终端 A 在干活（working=2），终端 B 需要授权（alert=1）
#       → 显示 alert（红灯闪烁），因为优先级 1 < 2

PRIORITY = {
    "alert":    1,   # 最高：需要立即关注（红灯闪烁）
    "thinking": 2,   # 思考中（黄灯闪烁）
    "model":    3,   # 等模型回复（绿灯闪烁）
    "working":  4,   # 正在干活（绿灯常亮）
    "idle":     5,   # 等用户输入（红灯常亮）
    "off":      6,   # 最低：会话结束（全灭）
}

# 注：心跳超时降级机制已移除。
# 状态文件忠实地反映 hook 写入的内容，daemon 不做篡改。
# 清理依赖 SessionEnd hook 写入 _global_off 文件。
