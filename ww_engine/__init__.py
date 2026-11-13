"""ww_engine — self-owned runtime for ww-echo.

从 ok-script 1.0.160 (MIT) 精简 vendored 的 Windows 自动化内核：
截图 / 窗口 / 键鼠注入 / OCR / 模板匹配 / 任务运行时。
只保留本项目用到的部分；ok-script 的原生 GUI、ADB/模拟器/浏览器、
更新/打包/分析/i18n 等已删除。

**应用外壳在 `ww_app_shell`**（2026-11-13 第三阶段拆出）：`EngineApp`/`StartController`/overlay/QMessageBox
都在那边；本包只剩自动化内核 + 一个 QtCore 依赖（`gui/Communicate.py` 的信号中枢）。
本模块是**组合根**：`OK.app` 与惰性导出 `EngineApp` 会 import `ww_app_shell`，其余 engine 模块不碰它。

**导入成本（工程约定）**：根包 eagerly 只导入「stdlib + QtCore(`communicate`) + psutil」这一档；
`EngineApp` / `DeviceManager` / `TaskExecutor` / `TaskManager` / `BaseTask` / `FeatureSet` 等
会拉起 QtWidgets / cv2 / PIL / rotypes / pynput 的名字走 PEP 562 的 `__getattr__` 按需导入
（见 `_LAZY_IMPORTS`）。`from ww_engine import EngineApp` 与 `ww_engine.EngineApp` 用法完全不变。
目标：`import ww_engine` < 0.5 s（实测与依据见 `docs/COUPLING.md` §0.3/§6）。
"""

import importlib
import importlib.util
import os
import sys

from ww_engine.util.config import Config, ConfigOption
from ww_engine.util.GlobalConfig import GlobalConfig, register_basic_options, basic_options
from ww_engine.util.handler import Handler, ExitEvent
from ww_engine.util.logger import Logger, config_logger
from ww_engine.util.process import check_mutex, parse_arguments_to_map
from ww_engine.util.file import clear_folder
from ww_engine.gui.Communicate import communicate
from ww_engine.locator import OkGlobals, og          # og 在子模块里，避免 根包↔应用外壳 的 import 环
from ww_engine.task.exceptions import (
    CannotFindException, TaskDisabledException, FinishedException,
    WaitFailedException, CaptureException, HotkeyConfigException,
)

logger = Logger.get_logger('ww_engine')

# 惰性导入表：名字 -> (模块, 属性)。这些模块会拉起 QtWidgets(QApplication)、cv2、PIL、rotypes、pynput ——
# 只有真要跑任务/开窗口时才该付这笔钱。
# 新增根导出时：轻的写上面(含 `og`/`Logger`/`Config` 的依赖闭包)，重的登记到这里。
# `EngineApp` 在 `ww_app_shell`（应用外壳）：只有组合根(本文件)知道它，engine 其余模块不 import shell。
_LAZY_IMPORTS = {
    'EngineApp': ('ww_app_shell.app', 'EngineApp'),
    'DeviceManager': ('ww_engine.device.DeviceManager', 'DeviceManager'),
    'TaskExecutor': ('ww_engine.task.TaskExecutor', 'TaskExecutor'),
    'TaskManager': ('ww_engine.task.TaskManager', 'TaskManager'),
    'BaseTask': ('ww_engine.task.task', 'BaseTask'),
    'TriggerTask': ('ww_engine.task.task', 'TriggerTask'),
    'FindFeature': ('ww_engine.task.task', 'FindFeature'),
    'OCR': ('ww_engine.task.task', 'OCR'),
    'Box': ('ww_engine.feature.Box', 'Box'),
    'get_bounding_box': ('ww_engine.feature.Box', 'get_bounding_box'),
    'Feature': ('ww_engine.feature.Feature', 'Feature'),
    'FeatureSet': ('ww_engine.feature.FeatureSet', 'FeatureSet'),
}


def __getattr__(name):
    """PEP 562：重的根导出按需导入（表见 `_LAZY_IMPORTS`），首次解析后缓存在模块字典里。

    兜底：`from ww_engine import rotypes` 这类「子包当属性用」的写法交给 import 机制
    （rotypes 内部就有 `from ww_engine import rotypes`），不在这里硬编码。
    """
    if name.startswith('__') and name.endswith('__'):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    target = _LAZY_IMPORTS.get(name)
    if target is not None:
        module = importlib.import_module(target[0])
        value = getattr(module, target[1])
        # 写回模块字典缓存（不用 globals()：子模块名曾把内置 globals 遮蔽过一次）
        sys.modules[__name__].__dict__[name] = value
        return value
    try:
        spec = importlib.util.find_spec(f'{__name__}.{name}')
    except (ImportError, AttributeError, ValueError):
        spec = None
    if spec is not None:                 # 是子模块/子包（如 rotypes、task、gui）
        return importlib.import_module(f'{__name__}.{name}')
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(_LAZY_IMPORTS))


class ScreenshotFolder:
    """轻量替代 ok-script 的 Screenshot 类：只提供截图目录。"""

    def __init__(self, folder='screenshots'):
        self.screenshot_folder = folder or 'screenshots'
        self.ui_dict = {}


class OK:
    """Minimal engine entrypoint (replaces ok-script.OK).

    重模块（EngineApp/DeviceManager/TaskExecutor/TaskManager）**只在 `OK()` 里按需导入**：
    这样 `import ww_engine` 与 `from ww_engine import og` 不必先把 QtWidgets/cv2 拉起来。
    """

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
            from ww_app_shell.app import EngineApp      # 惰性：QtWidgets 只在要窗口时拉起
            self._app = EngineApp(self.config, self.exit_event)
            og.app = self._app
        return self._app

    def do_init(self):
        from ww_engine.feature.FeatureSet import FeatureSet
        from ww_engine.task.TaskManager import TaskManager
        from ww_engine.task.TaskExecutor import TaskExecutor

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
            from ww_engine.device.DeviceManager import DeviceManager
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
    'Box', 'get_bounding_box', 'clear_folder', 'Feature', 'FeatureSet',
    'DeviceManager', 'TaskExecutor', 'TaskManager',
    'communicate',
    'CannotFindException', 'TaskDisabledException', 'FinishedException',
    'WaitFailedException', 'CaptureException', 'HotkeyConfigException',
]
