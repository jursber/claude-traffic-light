# 运行时配置目录

- **`tl_hook_light_gui.json`**：由 `tools/tl_hook_light_gui.py` 生成，勿提交含个人路径的敏感内容时可加入 `.gitignore`。
- **`.gui_serial_test_mode`**：GUI 开启「测试模式」时写入的空标志文件，供后续守护进程扩展识别（当前守护进程未必读取）。
