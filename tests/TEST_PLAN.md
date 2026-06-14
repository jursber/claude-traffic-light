# 上线前测试清单

## 自动回归

- `python -m compileall -q ...`：全量 Python 语法/导入编译检查。
- `python -m pytest -q --tb=short`：协议、配置、hook 生成、状态文件、daemon 选择逻辑。
- `python tools/e2e_selftest.py --batch`：非交互端到端冒烟，覆盖切换 agent、写状态、daemon 锁、pytest 嵌套回归。
- `python tests/release_validation.py`：上线前总入口，生成 `reports/release_validation_report.json` 与 `reports/RELEASE_VALIDATION_REPORT.md`。

## 手动/硬件验证

- `python tools/e2e_selftest.py`：带人工确认的灯态检查，适合插着 ESP32 时跑。
- `python tests/test_all.py`：逐状态写入，观察 model/working/thinking/alert/idle/off。
- `python tests/test_ble.py`：BLE 写入冒烟，仅在使用 BLE 传输时执行。

## 覆盖维度

- Hook 配置：Claude/Codex/Cursor 默认事件、wired 子集、`--event` 参数。
- 状态写入：`session_id`、`conversation_id`、Cursor 缺会话兜底 `_anon`、无效状态拒绝。
- 灯效渲染：per-hook `effect/mask/priority`、全局亮度、闪烁/呼吸周期、默认状态回退。
- Daemon：多 session 优先级、metadata/tmp 文件忽略、active agent 状态目录、单实例锁。
- 打包准备：当前 `packaging/build_win.ps1` 与 `packaging/vibelight.spec` 存在并通过基础语法检查。
