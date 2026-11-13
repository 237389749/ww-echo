"""Application shell（应用外壳）— 与 `ww_engine` 自动化内核分离的 Qt 部分。

2026-11-13 第三阶段从 `ww_engine/app.py` 拆出：外壳只负责
  - 创建/复用 QApplication、设置标题/图标/版本
  - 保存 ok_config（覆盖层开关）
  - 提供 start_controller（拉前窗口 + 启动链路）
  - 按需创建 OverlayWindow
  - 退出时设置 exit_event 并关闭 Qt
不再包含 ok-script 的 MainWindow / About / Tabs / i18n / resources。

依赖方向：**shell → engine**（communicate/Config/Logger/设备接口），engine 核心不 import 本包
（唯一例外是 `ww_engine/__init__.py` 这个组合根：`OK.app` 与惰性导出 `EngineApp`）。
"""

import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ww_engine.gui.Communicate import communicate
from ww_engine.util.config import Config
from ww_engine.util.logger import Logger
from ww_app_shell.start_controller import StartController

logger = Logger.get_logger(__name__)


class EngineApp:

    def __init__(self, config, exit_event=None):
        self.config = config
        self.exit_event = exit_event
        self.debug = config.get('debug', False)
        self.title = config.get('gui_title', 'OK-Echo')
        self.version = config.get('version', 'dev')
        self.about = config.get('about')
        self.global_config = None
        self.main_window = None
        self.overlay_window = None
        self.locale = None
        self.my_app = None

        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)
        self.app.setApplicationName(self.title)
        self.app.setApplicationDisplayName(self.title)
        self.app.setApplicationVersion(str(self.version))

        icon_path = config.get('gui_icon')
        self.icon = QIcon(icon_path) if icon_path else QIcon()

        self.ok_config = Config('_ok', {
            'window_x': -1, 'window_y': -1, 'window_width': -1, 'window_height': -1,
            'window_maximized': False, 'navigation_expanded': True,
            'use_overlay': False, 'show_overlay_logs': True,
        })
        self.start_controller = StartController(config, exit_event)
        communicate.quit.connect(self.quit)
        logger.info(f'EngineApp init: {self.title} {self.version}')

    def tr(self, key):
        if not key:
            return key
        return QCoreApplication.translate('app', key) or key

    def quit(self):
        logger.info('EngineApp quit')
        if self.exit_event:
            self.exit_event.set()
        if self.app:
            self.app.quit()

    def get_overlay_view(self):
        if self.overlay_window is None:
            from ww_app_shell.overlay_window import OverlayWindow
            from ww_engine.locator import og
            if og.device_manager is None or og.device_manager.hwnd_window is None:
                return None
            self.overlay_window = OverlayWindow(og.device_manager.hwnd_window)
            communicate.window.connect(self.overlay_window.update_overlay)
            self.overlay_window.set_boxes_enabled(self.ok_config.get('use_overlay', False))
        return self.overlay_window

    def update_overlay(self, visible, x, y, window_width, window_height, width, height, scaling):
        overlay_view = self.get_overlay_view()
        if overlay_view:
            overlay_view.update_overlay(visible, x, y, window_width, window_height, width, height, scaling)

    def exec(self):
        return self.app.exec()

    # 兼容旧调用（自建 UI 不会调用）
    def show_main_window(self):
        logger.warning('show_main_window is not available in ww_engine; use ui.main_window.MainWindow')
