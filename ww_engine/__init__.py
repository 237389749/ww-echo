"""ww_engine — self-owned runtime for ww-echo.

从 ok-script 1.0.160 (MIT) 精简 vendored 的 Windows 自动化内核：
截图 / 窗口 / 键鼠注入 / OCR / 模板匹配 / 任务运行时。
只保留本项目用到的部分；ok-script 的原生 GUI、ADB/模拟器/浏览器、
更新/打包/分析/i18n 等已删除。
"""

import os
import sys

from ww_engine.util.config import Config, ConfigOption
from ww_engine.util.GlobalConfig import GlobalConfig, register_basic_options, basic_options
from ww_engine.util.handler import Handler, ExitEvent
from ww_engine.util.logger import Logger, config_logger
from ww_engine.util.process import check_mutex, parse_arguments_to_map
from ww_engine.util.file import get_path_relative_to_exe
from ww_engine.gui.Communicate import communicate

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

# 这些 import 必须在 og/Logger/Handler 之后：StartController/OverlayWindow
# 会从 `ww_engine` 根导入它们。
from ww_engine.app import EngineApp  # noqa: E402
from ww_engine.device.DeviceManager import DeviceManager  # noqa: E402
from ww_engine.task.TaskExecutor import TaskExecutor  # noqa: E402
from ww_engine.gui.tasks.TaskManger import TaskManager  # noqa: E402
from ww_engine.task.task import BaseTask, TriggerTask, FindFeature, OCR  # noqa: E402
from ww_engine.feature.Box import Box, get_bounding_box  # noqa: E402
from ww_engine.feature.Feature import Feature  # noqa: E402
from ww_engine.feature.FeatureSet import FeatureSet  # noqa: E402
from ww_engine.task.exceptions import (  # noqa: E402
    CannotFindException, TaskDisabledException, FinishedException,
    WaitFailedException, CaptureException, HotkeyConfigException,
)


class ScreenshotFolder:
    """轻量替代 ok-script 的 Screenshot 类：只提供截图目录。"""

    def __init__(self, folder='screenshots'):
        self.screenshot_folder = folder or 'screenshots'
        self.ui_dict = {}


class OK:
    """Minimal engine entrypoint (replaces ok-script.OK)."""

    exit_event = ExitEvent()
    init_error = None
    device_manager = None
    feature_set = None
    task_executor = None
    screenshot = None

    def __init__(self, config):
        if config.get('check_mutex', True):
            check_mutex()
        og.ok = self
        og.config = config
        og.exit_event = self.exit_event
        og.handler = Handler(self.exit_event, 'global')
        self.config = config
        config['config_folder'] = config.get('config_folder') or 'configs'
        Config.config_folder = config['config_folder']
        config_logger(config)
        logger.info(f'ww_engine init {config.get("version")}, {sys.argv}, pid={os.getpid()}')
        config['debug'] = config.get('debug', False)
        self.args = parse_arguments_to_map()
        self._app = None
        self.debug = config['debug']
        self.global_config = GlobalConfig(config.get('global_configs'))
        register_basic_options(self.global_config, enable_blur=False)
        og.global_config = self.global_config
        og.set_use_dml()
        try:
            import ctypes
            error_code = ctypes.windll.shcore.SetProcessDpiAwareness(2)
            logger.info(f'SetProcessDpiAwareness {error_code}')
        except Exception as e:
            logger.error(f'SetProcessDpiAwareness error: {e}')
        try:
            self.do_init()
        except Exception as e:
            logger.error(f'ww_engine init error: {e}', e)
            self.quit()
            raise

    @property
    def app(self):
        if self._app is None:
            self._app = EngineApp(self.config, self.exit_event)
            og.app = self._app
        return self._app

    def do_init(self):
        logger.info(f'do_init, config: {self.config}')
        self.init_device_manager()
        self.screenshot = ScreenshotFolder(self.config.get('screenshots_folder', 'screenshots'))

        template_matching = self.config.get('template_matching')
        if template_matching is not None:
            coco_feature_json = template_matching.get('coco_feature_json')
            self.feature_set = FeatureSet(
                self.debug, coco_feature_json,
                default_horizontal_variance=template_matching.get('default_horizontal_variance', 0.002),
                default_vertical_variance=template_matching.get('default_vertical_variance', 0.002),
                default_threshold=template_matching.get('default_threshold', 0.8),
                feature_processor=template_matching.get('feature_processor'),
                hcenter_features=template_matching.get('hcenter_features'),
                vcenter_features=template_matching.get('vcenter_features'))
        else:
            self.feature_set = None

        ocr_target_height = 0
        if ocr := self.config.get('ocr'):
            ocr_target_height = ocr.get('target_height', 0)

        self.task_executor = TaskExecutor(
            self.device_manager, exit_event=self.exit_event,
            wait_until_settle_time=self.config.get('wait_until_settle_time', 1),
            feature_set=self.feature_set,
            config_folder=self.config.get('config_folder'), debug=self.debug,
            global_config=self.global_config, ocr_target_height=ocr_target_height,
            config=self.config)
        og.task_manager = TaskManager(
            task_executor=self.task_executor, app=self.app,
            onetime_tasks=self.config.get('onetime_tasks', []),
            trigger_tasks=self.config.get('trigger_tasks', []),
            scene=self.config.get('scene'))
        og.executor = self.task_executor
        logger.info('do_init end')
        return True

    def init_device_manager(self):
        if self.device_manager is None:
            self.device_manager = DeviceManager(self.config, self.exit_event, self.global_config)
            og.device_manager = self.device_manager

    def quit(self):
        logger.info('ww_engine quit')
        self.exit_event.set()
        if self._app:
            self._app.quit()


__all__ = [
    'OK', 'og', 'OkGlobals', 'EngineApp', 'ScreenshotFolder',
    'Config', 'ConfigOption', 'GlobalConfig', 'basic_options',
    'Handler', 'ExitEvent', 'Logger',
    'BaseTask', 'TriggerTask', 'FindFeature', 'OCR',
    'Box', 'get_bounding_box', 'Feature', 'FeatureSet',
    'DeviceManager', 'TaskExecutor', 'TaskManager',
    'communicate',
    'CannotFindException', 'TaskDisabledException', 'FinishedException',
    'WaitFailedException', 'CaptureException', 'HotkeyConfigException',
]
