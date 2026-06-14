# 多会话、优先级与灯效合并（核实说明）

本文回答：**多个 Claude Code 终端同时跑**时灯怎么合并；**`tl_hook_light_gui.json` 里两行优先级数字相同**时怎么办；以及「**同一盏灯多种效果谁优先**」在当前架构下的真实情况。

---

## 1. 多个 Claude 同时开，每个能触发灯吗？

**能。**每个会话有独立的 **session id**，`set_state_unified.py` 会在当前 agent 的 **状态目录**（默认 `%LOCALAPPDATA%\Temp\cc_tl_states\` 等）下写入：

`{state_dir}/{session_id}`

因此 **N 个 Claude 实例 ≈ N 个状态文件**，每个实例里跑的 hook 只改自己的那份；**不会互相覆盖对方会话文件**。

---

## 2. 守护进程怎么从多份文件合成「一盏灯」？

`unified_daemon` 会扫描该目录下所有会话状态，取出每个文件里的 **状态名字符串**（如 `model` / `working` / `alert` / …），再用 `config.PRIORITY` 里 **数字更小 = 更优先** 的规则，选出 **全局一个**「当前最该显示的状态」，然后通过 **单字节 ASCII**（`COMMANDS` 映射）发到硬件。

也就是说：**多会话在「状态名」层面做优先级合并**，不是按 GUI 里每行 hook 单独发灯。

---

## 3. 两个会话状态相同（或 GUI 里两行 priority 相同）

- **两个会话都写 `working`**：对 daemon 来说两个值一样，`highest_priority` 仍得到 `working`，灯表现与 **一个** 会话在 `working` 相同，**没有冲突**。
- **GUI `tl_hook_light_gui.json` 里两行 `priority` 相同**：当前 **`unified_daemon` 不读取该 JSON**，灯仍只由 **hook 写入的状态名 + `config.PRIORITY`** 决定。GUI 里的 `priority` 是为 **后续「按 hook 映射 v1 协议灯效」** 预留的；在那套逻辑落地之前，**相同数字不会改变 daemon 行为**。

---

## 4. 「同一盏灯同时多种状态」——闪烁 / 常亮 / 呼吸 谁赢？

在 **当前 V2 兼容路径**（daemon 只发 **一个** ASCII 字符）下：

- **硬件某一时刻只执行一条灯控命令**，不存在「同一颗 LED 同时既闪烁又常亮」的物理叠加。
- 因此 **没有** 在 daemon 里实现「闪烁 > 常亮 > 呼吸」的**逐灯通道**合成顺序；合并规则就是上一节的 **状态名优先级**（`alert` 高于 `thinking` 高于 `model` …）。

若将来 hook 驱动改为只走 **`SET_LIGHTING` 等 v1 协议**、并在软件里对多 hook **按通道合并** multiple 效果，才需要单独实现「同灯多效果」的优先级表；**那不属于当前 `unified_daemon` 主循环的行为**。

---

## 5. 与 GUI 默认表的关系

`hook_light_catalog.default_hook_gui_row()` 把目录里的 `wire_state`（`prompt` / `auto` / `thinking` / …）映射到 GUI 的 **效果 + 掩码 + 数字优先级**，其中 **数字优先级** 与 `config.PRIORITY` 中该状态对应数值一致，便于日后与 daemon 扩展对齐；**与当前 ASCII daemon 是否读 JSON无关**。
