"""ww_app_shell — 应用外壳（Qt 界面部分），与 `ww_engine` 自动化内核分离。

2026-11-13 第三阶段从 `ww_engine` 拆出：只放“要开窗口/弹框/挂 overlay 才会用到”的 Qt 代码，

| 模块 | 作用 |
|---|---|
| `app.py` | `EngineApp`：创建/复用 QApplication、标题/图标、`ok_config`、`start_controller`、按需 overlay |
| `start_controller.py` | `StartController`：等待窗口就绪 → 拉前 → 启用任务 → 启动 executor |
| `overlay_window.py` / `overlay_widget.py` | 调试/覆盖层窗口（QWidget + win32 置顶） |
| `alert.py` | `show_alert`：`QMessageBox` 模态框（引擎侧的 `alert_info/alert_error` 走 `communicate`，与 QtWidgets 无关） |

**依赖方向**：`ww_app_shell` → `ww_engine`（communicate / Config / Logger / 设备与窗口接口）。
`ww_engine` 核心**不 import 本包**；唯一例外是组合根 `ww_engine/__init__.py`
（`OK.app` 与惰性导出 `EngineApp`）。

`communicate`（QtCore `Signal` 中心）刻意留在 `ww_engine/gui/Communicate.py`：engine 的
任务/设备/日志都直接 emit 它，搬走会让 engine→shell 变成到处都有的边。见 `docs/COUPLING.md` §6。
"""

from ww_app_shell.alert import show_alert
from ww_app_shell.app import EngineApp
from ww_app_shell.start_controller import StartController

__all__ = ["EngineApp", "StartController", "show_alert"]
