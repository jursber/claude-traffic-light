# V3 目录说明 + Git 小白概念

## 仓库里现在有什么

| 路径 | 含义 |
|------|------|
| `src/claude_tl/` | **V3 唯一源码包**：守护进程、状态写入、BLE/串口、切换 agent。打 exe 时**只打这一块**。 |
| 根目录 `*.py`（如 `daemon_unified.py`） | **薄启动器**：把 `src/` 塞进 `sys.path` 后调用包内 `main()`。兼容旧 hook 路径、VBS `cwd`。 |
| `tests/` | 手动/冒烟测试，**默认不**打进 PyInstaller。 |
| `extras/legacy_windows/` | 旧 Windows 安装脚本等，**与 exe 无关**。 |
| `packaging/pyinstaller/` | 打包规格与入口，详见同目录说明。 |
| `arduino/` | ESP32 固件，与 Python 包分离。 |
| `active_agent.json` | 运行时配置（与仓库根绑定，或通过 `CC_TL_HOME` 重定向）。 |

## Git 里几个概念（小白向）

1. **提交（commit）**  
   某一时刻整个项目的快照，带说明文字。像游戏存档。

2. **分支（branch）**  
   平行时间线。默认常在 `master` / `main` 上开发。

3. **标签（tag）**  
   给某个提交起「永久别名」。你的 **`V2.0`** 就是：以后随时能 `git checkout V2.0` 看到当时整棵树，**不必**在磁盘再拷一份 `.old`。

4. **远程（origin）**  
   GitHub 上的同名仓库。`git push` 把本地提交送上去。

5. **为什么不让 2.0 干扰 3.0 exe**  
   - 源码上：exe 只收集 `src/claude_tl`。  
   - 历史上：V2.0 在 **tag**，不在你日常要维护的包里。  
   - `extras/` 里的脚本若不用，就不会进 spec 的 `Analysis`。

## 归档分支 `archive/v2.0`

建议在本地创建并与 tag 对齐（与 `V2.0` 同一提交），便于在 GitHub 上点分支浏览：

```bash
git branch archive/v2.0 V2.0
git push -u origin archive/v2.0
```

## PyInstaller 与「包」

- **Python 包**：含 `__init__.py` 的目录，可被 `import`。  
- **可编辑安装**：`pip install -e .` 后，改 `src` 立刻生效，且可用 `python -m claude_tl`。  
- **PyInstaller**：把解释器 + 依赖 + 你的脚本打成 `exe`；spec 里写清**只分析哪些入口**，避免把整仓库测试文件打进去。
