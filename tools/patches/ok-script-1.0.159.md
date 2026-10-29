# ok-script 1.0.159 的 ww-echo 补丁（规格 + 自检）

> 为什么单独存一份：补丁只存在于本机 `site-packages`，**`pip install --upgrade ok-script` 会全部丢失**。
> 以前只有 `CLAUDE.md` 里的一张表（"意图"），没有可执行的校验；重装后是否打全只能靠人肉回忆。
> 现在：本文件 = 每处的**判定标记 + 行为规格 + 现状代码**；`check_patches.py` = 一键自检。
>
> 补丁一律带 `[ww-echo ... patch]` 注释标记 —— 校验脚本只认标记，所以手工重打时**务必保留注释**。

## 0. 自检

```powershell
python tools/patches/check_patches.py          # 4 处全在 → 退出码 0
python tools/patches/check_patches.py -v       # 打印每个文件的命中位置
```

退出码：`0` 全在；`1` 有缺失；`2` 找不到 ok-script。

## 1. `ok/gui/StartController.py`（3 个标记）

**行为**：点"开始"（`do_start(task=...)`）后，等待设备就绪的每一轮都把游戏窗口切前台（含从最小化恢复）；
**纯启动 app（task 为 None）不抢前台**。云模式下 `windows.start_exe=False` 时不去启动 exe，但仍等窗口就绪。

| 位置 | 标记 | 现状代码 |
|---|---|---|
| `__init__` | `# [ww-echo cloud patch] only auto-bring the game window to the foreground` | `self._auto_bring_to_front = False` |
| `do_start` | `# [ww-echo cloud patch] auto-bring-to-front only when a task start was requested` | `self._auto_bring_to_front = task is not None` |
| `_wait_until_device_ready` 循环内 | `# [ww-echo cloud patch] when the user pressed start (task), auto bring` | `if self._auto_bring_to_front and hwnd_window ...: hwnd_window.bring_to_front()` |
| `windows.start_exe is False` 分支 | `# [ww-echo patch] cloud mode: never auto-launch the game exe, but still` | 仍调用 `self._wait_until_device_ready()` |

**上游原行为**：启动时不区分"用户点了开始"还是"app 刚起来"，也没有每轮拉前；`start_exe=False` 分支不去等设备就绪
（云游戏场景下线程直接往下走，抓屏窗口尚未可用）。

## 2. `ok/device/capture_methods/hwnd_window.py`（1 个标记）

| 位置 | 标记 | 现状代码 |
|---|---|---|
| `_check_visible`（或同类可见性判定） | `# [ww-echo patch] visible = window is not minimized (capturable),` | `visible = not win32gui.IsIconic(self.hwnd)` |

**上游原行为**：`visible = self.is_foreground()`（或等价）→ 被遮挡/后台窗口判"不可用"，导致 BitBlt_RenderFull
明明能抓到却被拒。改后 `visible=False` 只在**真最小化**时出现。

## 3. `ok/device/interaction_methods/pynput.py`（2 个标记）

| 位置 | 标记 | 现状代码 |
|---|---|---|
| 新增方法 `_ensure_clickable()` | `""" [ww-echo cloud patch] ensure the target window is in the foreground before` | 先 `clickable()`；否则 `bring_to_front()` + `sleep(0.2)` 再判 |
| `should_capture()` | `# [ww-echo patch] do not gate the whole task loop on the window being in the` | `return True` |

**上游原行为**：`should_capture()` 返回 `is_foreground()` → 用户切走窗口时整个任务循环被门控/卡死。
`clickable()` 保持原样（纯前台判定）—— 只在实际动作前用 `_ensure_clickable()` 拉前。

**接入点**：`click` / `send_key` / `scroll` 等动作入口调用 `self._ensure_clickable()`（若上游无此调用点，需一并加）。

## 4. `ok/util/window.py`（1 个标记）

| 位置 | 标记 | 现状代码 |
|---|---|---|
| `find_hwnd` 开头 | `# [ww-echo patch] empty exe entries mean "no process filter"` | `exe_names = [e for e in (exe_names or []) if e]` |

**上游原行为**：云模式 `selected_exe=''` 时，空字符串会作为 exe 名参与匹配 → **所有**窗口都在 exe 处被判不匹配 →
找不到"鸣潮"窗口（表现为"自动锁定失败/手动选窗也没有列表"）。

## 5. 本项目内的一处（不属于 site-packages）

| 文件 | 改动 | 为什么 |
|---|---|---|
| `ui/run_tab.py` | 评估分支起线程前也 `bring_to_front()` | 评估模式与强化一致地切前台 |
