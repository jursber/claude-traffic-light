# ESP32-C3 固件 BLE 说明

固件在保留 **USB 串口 115200** 的同时，增加 **BLE GATT 服务**，与 PC 端 `bleak` 使用相同的 UUID。

## 依赖

1. **Arduino ESP32 开发板支持**（推荐 3.x，需支持 ESP32-C3）。
2. **库**：Arduino IDE → 工具 → 管理库 → 搜索 **NimBLE-Arduino**（作者 **h2zero**）→ 安装较新版本（建议 ≥ 2.x）。

## 板级选项（与串口一致）

- **USB CDC On Boot**：建议 **Enabled**（便于 USB 调试与串口命令）。
- 若编译报错与 **Bluetooth** 相关，在开发板菜单中确认已启用蓝牙/NimBLE 相关选项（不同 core 菜单名称略有差异）。

## 设备名与 UUID（勿随意修改，需与 `config.py` 一致）

| 项 | 值 |
|----|-----|
| 广播名 | `CC-TrafficLight` |
| Service UUID | `e52c12b6-7ac3-4636-9c17-3d608bcea796` |
| 可写特征 UUID | `e52c12b7-7ac3-4636-9c17-3d608bcea796` |

写入特征的数据为 **ASCII 单字节**（与 USB 串口相同），例如 `G`、`g`、`O` 等。

## 若 `onWrite` / `onDisconnect` 签名编译失败

NimBLE-Arduino 大版本间回调参数可能不同。请以当前库头文件为准，调整 `traffic_light.ino` 中：

- `NimBLECharacteristicCallbacks::onWrite`
- `NimBLEServerCallbacks::onDisconnect`（**2.x 一般为三参数**：`pServer, connInfo, int reason`；若你使用的旧库只有两参数，去掉 `int reason` 及 `override` 关键字试编译）

当前仓库内 `.ino` 按 **NimBLE-Arduino 2.x**（带 `reason`）编写。

## PC 侧验证

```text
pip install -r requirements.txt
python tests/test_ble.py
```

## 「系统里显示已配对 / 已连接，但灯没变」

这是正常现象：**配对或保持 BLE 连接并不会自动向灯发命令**。本固件只有在收到下面之一时才会改灯：

1. **USB 串口** 发来的单字节（例如守护进程默认走串口）；或  
2. **BLE 可写特征** 被写入单字节（例如 `python tests/test_ble.py` 写 `g`，或设置 `CC_TL_TRANSPORT=ble` 后由守护进程写入）。

仅打开 Windows「蓝牙」里看到「已配对」，**没有任何程序去写 GATT 特征**，灯就会一直保持上电后的状态（一般是全灭或上一次命令的状态）。

烧录带 `Serial` 提示的固件后，用 **USB 串口监视器 115200** 可在连接时看到一行 `[BLE] 已连接：...` 提示。

Windows 需打开 **蓝牙**，且部分环境需 **定位** 权限以便 BLE 扫描。

## 守护进程使用 BLE

设置环境变量后启动 `daemon.py` 或 `daemon_unified.py`：

```text
set CC_TL_TRANSPORT=ble
```

可选：自定义广播名（与固件 `BLE_DEVICE_NAME` 一致时再改固件）：

```text
set CC_TL_BLE_NAME=CC-TrafficLight
```

默认仍为 **USB 串口**（不设 `CC_TL_TRANSPORT` 或设为 `serial`）。
