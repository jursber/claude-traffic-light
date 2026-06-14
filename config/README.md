# 运行时配置目录

- **`tl_hook_light_gui.json`**：由 `tools/tl_hook_light_gui.py` 生成，勿提交含个人路径的敏感内容时可加入 `.gitignore`。
- **试灯 IPC**：GUI 在「测试模式」下点「发送」时，向 `%LOCALAPPDATA%\Temp\cc_tl_gui_proto.json` 写入 hex 帧，由**统一守护进程** `daemon_unified.py` 独占串口/BLE 写出（勿与 GUI 直连串口混用）。
