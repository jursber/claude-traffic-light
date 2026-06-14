# 独立绿色应用与守护进程：目标架构说明

本文回答：**「打包成一个完整的绿色 exe，用户只点这一个程序就完成前后台」** 时，与当前 **`unified_daemon`（守护进程）** 的关系，以及推荐实现顺序。

---

## 1. 现在为什么要有守护进程？

- **串口 / BLE 独占**：同一时刻只能有一个进程稳定持有 ESP32 的 USB 串口或 BLE 连接。  
- **Hook 极薄、极快**：Claude / Codex 的 hook 只跑短命令，写 **`%TEMP%` 下小状态文件**；**重活（轮询、重连、写硬件）** 放在常驻的 **`daemon_unified.py`** 里，避免每个 hook 都去 `open(COM)`。  
- **多会话合并**：多个 IDE 会话各写自己的 `session_id` 文件，daemon 按 `config.PRIORITY` 合成一盏灯。

因此「绿色单应用」**不等于**删掉 daemon 逻辑，而是把 **daemon 进程的生命周期** 收进安装包/主程序里管理。

---

## 2. 目标形态（建议）

**一个主进程（Tk GUI）+ 一个子进程（或同 exe 二次启动的 daemon）**：

| 能力 | 说明 |
|------|------|
| 启动 | 主程序 `main()` 里在 UI 就绪后 **`subprocess.Popen`** 启动 `pythonw -m claude_tl ...` 或内嵌的 `daemon_unified` 入口，**工作目录与 `CC_TL_HOME` 与 exe 旁配置一致**。 |
| 单实例 | 复用现有 **`cc_traffic_light_daemon.lock`**，避免用户双击 exe 起两个 daemon。 |
| 监控 | GUI 线程定时读 **PID 文件** + `os.kill(pid, 0)`；若子进程退出则 **自动重启**（可加退避，避免死循环刷日志）。 |
| 退出 | 托盘「退出」或主窗口真正退出时，**先 terminate 子进程**，再删 PID/或保留由下次启动覆盖。 |
| 试灯 | 继续走 **`cc_tl_gui_proto.json`** 或 **GUI 直连串口**（二选一占口，与现在一致）。 |

可选：用 **PyInstaller `onedir`** 把 `tcl/tk`、`src`、入口脚本打在一起；daemon 用 **同一解释器** `sys.executable` 拉起，避免用户再装 Python。

---

## 3. 与「完全在独立应用程序里完成」的对应关系

- **前台**：仍是当前 **VibeCodingLight**（配置、Agent 切换、试灯、托盘）。  
- **后台**：用户无感知的 **daemon 子进程**；不必再让用户手动跑 `daemon_unified.py` 或改启动文件夹（可把「开机启动」改成写注册表/任务计划程序指向 **单 exe**，由 exe 内部起 daemon）。  
- **Hooks / Claude**：仍写状态文件到用户机器；与 exe 是否绿色无关，只要 **`set_state_unified` 路径** 与 **`active_agent.json`** 在发布时写对（`CC_TL_REPO_ROOT` / 安装目录）。

---

## 4. 实现顺序（建议迭代）

1. 在 **`tools/tl_hook_light_gui.py` 同级或 `src`** 增加 **`embedded_daemon_supervisor`**：启动、查活、重启、退出清理（先 Windows）。  
2. **`main()`** 里在创建托盘前调用 supervisor；托盘退出时停 supervisor。  
3. PyInstaller **spec**：把 `daemon_unified` 入口或 `python -m claude_tl` 打进去；验证 **锁文件、日志路径** 在 exe 场景仍指向 `%TEMP%`。  
4. 最后再把 **开机启动** 从 `.bat` 改为 **指向单 exe**（exe 内再起 daemon）。

当前仓库尚未内嵌 supervisor；本文作为 **与需求对齐的规格说明**，便于后续 PR 按步骤落地。
