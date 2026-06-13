# VibeLight 呼吸 / PWM 观感 — 排查与调参

**调试过程里的问题与经验**（为何引入 PWM 任务、esp_timer、感知整形、串口抢占等）已单独写在 **[DEBUGGING_EXPERIENCE.md](DEBUGGING_EXPERIENCE.md)**，建议与本文一起读。

本文面向「不想反复试错」的场景：你**只用 USB 串口**测 GUI、**没连蓝牙**，仍可能遇到「平顶、慢灭快亮、像一直最亮」等现象。下面按**优先级**列出常见根因与对策。

---

## 1. 同一串口被多个程序占用（最常见）

固件里 **ASCII 单字节**（`G/g/y/Y/r/R/O`）与 **v1 二进制帧**并存。任意合法 ASCII 会调用 `applyLegacyCommand()`，把引擎切到 **`ENGINE_LEGACY`**，此后 **PWM 刷新任务不再调用 `updateProtoLeds()`**，PROTO 呼吸包络**不再更新**；若此时 Legacy 模式是某路 **常亮 255**，观感就是「长时间顶在最亮」。

本仓库的 **Claude/Codex 红绿灯守护进程**（`daemon_unified.py`、`start_daemon*.py` 等）默认向 **同一 ESP32 USB COM** 写 **`G/g/R/...`**。  
**结论**：用 `vibelight_gui.py` 测呼吸前，请确认：

- 已退出 **统一守护进程 / 旧守护进程**（任务管理器里无相关 `python` 常驻写灯，或先停掉计划任务）；
- **没有**第二个终端在跑 `set_state.py` / hook 写同一端口；
- **Arduino 串口监视器**不要和 GUI **同时**打开同一 COM（监视器若每秒发心跳也会干扰，一般监视器只读不写，但若装了插件自动发字符仍会抢）。

**自检**：发一帧 PROTO 呼吸后，若灯突然变「某色常亮」，多半是随后又收到了 ASCII。

---

## 2. 只用 USB，BLE 仍在跑

`setup()` 里仍会 **`initBle()`**（NimBLE）。未用手机连 BLE 时，协议栈仍会占 **RAM/CPU** 与部分任务优先级。  
若你要做「是否 BLE 影响 PWM」的对比，只能 **临时注释 `initBle()`** 重编译（需接受 NimBLE 相关代码可能需 `#if` 包一层，否则链接/编译报错以你本机 Arduino-ESP32 版本为准）。

固件里已用 **独立 FreeRTOS 任务** 约 **1 ms** 调用 `updateProtoLeds()`，与 `loop()` 解耦；若仍偶发卡顿，可在 `traffic_light.ino` 里调 **`TL_PWM_TASK_PRIO`**（默认 **8**，须低于 NimBLE 主机任务，高于 `loopTask`）。

---

## 3. 主机发帧过快：4 ms 节流

固件对 **成功解析的 v1 帧**有 **`PROTO_MIN_INTERVAL_MS`（4 ms）** 节流：更短的间隔会**丢弃**该次应用（避免被洪水刷屏）。  
快速拖动 GUI 连续发多帧时，**周期/模式**可能不是每一帧都生效，属设计行为。调呼吸周期时以「发一帧或低速发」为准。

---

## 4. 模式与曲线帧

- **`CMD_SET_LIGHTING`（cmd=1）**里 `mode=MODE_BREATH(3)`：**三角呼吸**；**上升半周** 默认 **`TL_BREATH_RISE_PERCEPTUAL`**（`lin²/255`），**下降**线性。若要正弦等形状，用 **`cmd=2`** 画曲线（固件已不再内置正弦 LUT）。
- **`CMD_SET_BREATH_CURVE`（cmd=2）**：自定义曲线；需固件已收到有效曲线且 `mode=MODE_BREATH_CURVE(4)` 才会走曲线分支（详见 `docs/VIBELIGHT_PROTOCOL.md`）。

若误以为在测三角呼吸，实际设备仍在 **SOLID** 或 **Legacy 常亮**，观感也会像「一直最亮」。

---

## 5. 数学与硬件边界

- 包络用 **`esp_timer_get_time()`** 取相位，避免 `micros()` 在射频忙时异常。
- **暗→亮「不对称」**：数学线性 PWM 下人眼仍觉不对称时，用 **`TL_BREATH_RISE_PERCEPTUAL`**（上升 `lin²/255`）。示波器要严格对称三角可置 `0`。内置 sin 半拱已弃用（观感仍易怪），圆滑包络请 **`cmd=2`**。
- 低亮度段 **`dutyScaledRound`** 仍可能让某几档占空比为 0，肉眼像「突然亮起」——属 8 位 PWM 量化；可把 `period` 略拉长或提高环境光对比度观察。

若怀疑**不是软件**：用逻辑分析仪 / 示波器量 **GPIO0/1/2** 上 PWM 占空比随时间是否平滑变化，可一眼区分「协议状态错」与「灯板/电源」问题。

---

## 6. 固件侧可调宏（`traffic_light.ino`）

| 宏 | 默认 | 含义 |
|----|------|------|
| `TL_PWM_TASK_PRIO` | 8 | PWM 刷新任务优先级 |
| `TL_SERIAL_DRAIN_MAX` | 64 | 每圈 `loop` 最多从 USB 读入环缓的字节数，减轻「单圈读爆」拖慢 `processRingBuffer` |
| `TL_BREATH_RISE_PERCEPTUAL` | 1 | `MODE_BREATH` 上升半周 `lin²` 整形；`0` 为全程线性三角 |

---

## 7. 建议的最小复现流程

1. 停掉所有会向 COM 写 `G/g/R/...` 的进程。  
2. 只开 `python tools/vibelight_gui.py`，选正确 COM。  
3. 先发 **`O`**（全灭，Legacy）或发一帧 **PROTO OFF**，再发 **BREATH** + 较长周期（如 3000 ms），观察整周期。  
4. 仍异常 → 示波器看 PWM；同时可临时提高 `TL_PWM_TASK_PRIO` 或关 BLE 做 A/B。
