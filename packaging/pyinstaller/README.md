# 将 V3 打成 exe（仅包含 `src/claude_tl`）

## 前置

```bash
pip install -r requirements.txt pyinstaller
```

在**仓库根目录**执行：

```bash
pyinstaller packaging/pyinstaller/claude_tl.spec
```

产出：`dist/claude-tl/claude-tl.exe`（目录模式，含依赖 DLL）。

## 运行

```text
dist\claude-tl\claude-tl.exe daemon-unified
dist\claude-tl\claude-tl.exe set-state-unified thinking
```

把 `active_agent.json` 放在 **exe 同目录**（或设置环境变量 `CC_TL_HOME` 指向配置目录）。

## 注意

- 默认 **console=True**，守护进程会有黑色窗口；若要完全无窗需改 spec 为 `console=False` 并单独处理日志。
- 打包前确认 `hiddenimports` 已包含你实际用到的库（当前含 `bleak`、`serial`）。
