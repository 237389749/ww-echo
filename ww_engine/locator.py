"""`og` — 运行时全局命名空间（服务定位器）。

2026-11-13 第三阶段从 `ww_engine/__init__.py` 拆出：应用外壳（`ww_app_shell`）需要 `og`，
而根包又要能按需拉起外壳（`EngineApp`），两边直接互相 import 会形成模块级环。
把 `og` 放到这个**不依赖根包**的子模块后：shell → `ww_engine.locator`，根包 → shell（仅组合根），
静态依赖图不再有环（`tool/analysis/import_coupling.py` 的 SCC 检查会看着这条）。

命名注意：**不要**叫 `ww_engine/globals.py` —— 子模块会成为父包的属性，`ww_engine.globals`
会把根包里的内置 `globals()` 遮蔽掉（踩过：`TypeError: 'module' object is not callable`）。

`from ww_engine import og` 仍然可用（根包 re-export 同一个对象）。
"""

from ww_engine.util.file import get_path_relative_to_exe
from ww_engine.util.logger import Logger

logger = Logger.get_logger('ww_engine')


class OkGlobals:
    """Global namespace (same shape as ok-script's `og`)."""

    def __init__(self):
        self.app = None
        self.executor = None
        self.device_manager = None
        self.handler = None
        self.main_window = None
        self.my_app = None
        self.dpi_scaling = 1.0
        self.ok = None
        self.config = None
        self.task_manager = None
        self.app_path = get_path_relative_to_exe()
        self.use_dml = False
        self.global_config = None
        self.exit_event = None
        logger.info(f'app path {self.app_path}')

    def get_overlay_view(self):
        if self.app and hasattr(self.app, 'get_overlay_view'):
            return self.app.get_overlay_view()
        return None

    def set_use_dml(self):
        # 本项目 OCR 固定走 onnxocr + OpenVINO；DirectML 分支已移除。
        self.use_dml = False

    def set_dpi_scaling(self, window):
        try:
            self.dpi_scaling = window.windowHandle().screen().devicePixelRatio()
        except Exception:
            self.dpi_scaling = 1.0


og = OkGlobals()
