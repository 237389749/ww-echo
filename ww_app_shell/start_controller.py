"""Start controller (vendored from ok-script, trimmed to Windows/Cloud window mode).

只做四件事：
  1. 刷新设备列表并等待窗口就绪（本地 UnrealWindow / 云游戏标题匹配）
  2. 用户点“开始”时把窗口拉到前台（含最小化恢复）
  3. 启用目标 onetime 任务
  4. 启动 TaskExecutor
不自动启动游戏、不检查 GPU 驱动、不处理 ADB/模拟器/浏览器。
"""

import time

from PySide6.QtCore import QObject

from ww_engine.locator import og
from ww_engine.util.handler import Handler
from ww_engine.util.logger import Logger
from ww_engine.device.capture import BaseWindowsCaptureMethod
from ww_engine.gui.Communicate import communicate
from ww_engine.util.window import resize_window

logger = Logger.get_logger(__name__)


class StartController(QObject):
    STARTED_WINDOW_MIN_SIZE = (100, 100)
    STARTED_WINDOW_STABLE_SECONDS = 10
    STARTED_WINDOW_POLL_INTERVAL = 0.2

    def __init__(self, app_config, exit_event):
        super().__init__()
        self.config = app_config
        self.exit_event = exit_event
        self.handler = Handler(exit_event, __name__)
        self.start_timeout = app_config.get('start_timeout', 60)
        windows_config = app_config.get('windows') or {}
        self.start_exe = windows_config.get('start_exe', False)
        # 只有用户点“开始”（task 非 None）时才抢前台；启动程序本身不抢
        self._auto_bring_to_front = False

    @staticmethod
    def _mark_task_enabled(task):
        if not task.enabled:
            task._enabled = True
        if task.paused:
            task.unpause()

    def start(self, task=None, exit_after=False, on_done=None):
        """异步启动（投递到 handler 线程）。

        `on_done(ok: bool)` 在**handler 线程**上被调用 —— UI 侧要转成 Qt 信号再碰控件。
        为什么要这个回调：`start()` 只是 `handler.post(...)` 就返回，把返回值当"跑完了"会让调用方
        在任务刚提交时就去复位状态（2026-11-22 后端审查 B2）。
        """

        def _run():
            try:
                ok = self.do_start(task, exit_after)
            except Exception as e:                     # noqa: BLE001 - 回调链不能因为启动异常断掉
                logger.error(f'do_start exception: {e}', e)
                ok = False
            if on_done is not None:
                try:
                    on_done(bool(ok))
                except Exception as e:                 # noqa: BLE001
                    logger.error(f'start on_done callback failed: {e}', e)

        self.handler.post(_run)

    def do_start(self, task=None, exit_after=False):
        self._auto_bring_to_front = task is not None
        communicate.starting_emulator.emit(False, None, self.start_timeout)
        try:
            if isinstance(task, int):
                task = og.executor.onetime_tasks[task]
            if task and task.enabled and task.paused:
                logger.info(f'resume paused task {task}')
                if exit_after:
                    task.exit_after_task = True
                    communicate.task.emit(task)
                task.unpause()
                communicate.starting_emulator.emit(True, None, 0)
                return True
            if task and og.executor.current_task and og.executor.current_task != task:
                logger.info(f'queue task while another task is running {task}')
                if exit_after:
                    task.exit_after_task = True
                self._mark_task_enabled(task)
                communicate.starting_emulator.emit(True, None, 0)
                return True
        except Exception as e:
            logger.error(f'do_start resume exception: {e}', e)
            communicate.starting_emulator.emit(True, self.tr(f'Start failed: {e}'), 0)
            return False

        try:
            logger.info(f'do_start: refresh device (start_exe={self.start_exe})')
            og.device_manager.do_refresh(True)
        except Exception as e:
            logger.error(f'do_start refresh exception: {e}', e)
            communicate.starting_emulator.emit(True, self.tr(str(e)), 0)
            return False

        try:
            # 本项目 start_exe 恒 False：不自动拉起游戏，但等待已连接的窗口就绪
            if not self._wait_until_device_ready():
                return False

            tasks_to_enable = []
            for start_task in og.executor.get_all_tasks():
                if getattr(start_task, 'enable_after_start', False):
                    tasks_to_enable.append(start_task)
            if task:
                if task not in tasks_to_enable:
                    tasks_to_enable.append(task)
                if exit_after:
                    task.exit_after_task = True
            for t in tasks_to_enable:
                self._mark_task_enabled(t)

            og.executor.start()
            communicate.starting_emulator.emit(True, None, 0)
            return True
        except Exception as e:
            logger.error(f'do_start exception: {e}', e)
            communicate.starting_emulator.emit(True, self.tr(f'Start failed: {e}'), 0)
            return False

    def _wait_until_device_ready(self):
        wait_until = time.time() + self.start_timeout
        while not self.exit_event.is_set():
            hwnd_window = getattr(og.device_manager, 'hwnd_window', None)
            if self._auto_bring_to_front and hwnd_window is not None and hwnd_window.hwnd:
                try:
                    hwnd_window.bring_to_front()
                except Exception as e:
                    logger.error(f'bring_to_front failed: {e}')
            og.device_manager.do_refresh(True)
            error = self.check_device_error()
            if error is None:
                return True
            logger.error(f'waiting for game error: {error}')
            remaining = wait_until - time.time()
            if remaining <= 0:
                communicate.starting_emulator.emit(True, self.tr('Start game timeout!'), 0)
                return False
            communicate.starting_emulator.emit(False, None, int(remaining))
            time.sleep(2)
        return False

    def check_device_error(self):
        try:
            device = og.device_manager.get_preferred_device()
            if not device:
                return self.tr('No game selected!')
            error_msg = self.tr('{} is not connected, please select the game window.').format(
                device.get('nick', ''))
            if og.device_manager.capture_method is None:
                return self.tr('Selected capture method is not supported by the game or your system!')
            if not og.device_manager.device_connected():
                return self.tr('Game window is not connected, please select it first!')
            capture = og.device_manager.capture_method
            if not capture.connected():
                return error_msg
            if isinstance(capture, BaseWindowsCaptureMethod):
                hwnd_window = capture.hwnd_window
                if not hwnd_window.pos_valid:
                    if hwnd_window.hwnd and hwnd_window.window_width > 0 and hwnd_window.window_height > 0:
                        logger.info(f'window pos invalid, center window {hwnd_window.window_width}x'
                                    f'{hwnd_window.window_height}')
                        resize_window(hwnd_window.hwnd, hwnd_window.window_width,
                                      hwnd_window.window_height)
                        hwnd_window.do_update_window_size()
                    if not hwnd_window.pos_valid:
                        return self.tr('Window is minimized or out of screen; do not use fullscreen exclusive mode!')
            frame = self.try_capture_a_frame()
            if frame is None:
                return self.tr('Capture failed, please check game window')
            if og.executor.feature_set is not None and not og.executor.feature_set.check_size(frame):
                return self.tr('Image resource load failed, please try reinstall.')
            resolution_error = self.check_resolution()
            if resolution_error:
                return resolution_error
            return None
        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f'check_device_error exception: {e}', e)
            return self.tr(str(e))

    def check_resolution(self):
        supported_resolution = self.config.get('supported_resolution', {})
        supported_ratio = supported_resolution.get('ratio')
        min_size = supported_resolution.get('min_size')
        resize_to = supported_resolution.get('resize_to')
        force_ratio = supported_resolution.get('force_ratio')
        supported, resolution = og.executor.check_frame_and_resolution(supported_ratio, min_size)
        if not supported:
            resize_success = False
            if resize_to and isinstance(og.device_manager.capture_method, BaseWindowsCaptureMethod):
                resize_success = og.device_manager.capture_method.hwnd_window.try_resize_to(resize_to)
            if not resize_success:
                error = self.tr('Resolution {resolution} check failed, some tasks might not work correctly!').format(
                    resolution=resolution)
                if supported_ratio:
                    error += self.tr(', the supported ratio is {supported_ratio}').format(
                        supported_ratio=supported_ratio)
                if min_size:
                    error += self.tr(', the supported min resolution is {min_size}').format(
                        min_size=f'{min_size[0]}x{min_size[1]}')
                if force_ratio:
                    return error
                logger.warning(error)
        return None

    @staticmethod
    def try_capture_a_frame():
        start = time.time()
        while True:
            if og.device_manager.capture_method is None:
                return None
            frame = og.device_manager.capture_method.get_frame()
            if frame is not None:
                return frame
            if time.time() - start > 5:
                logger.error('time out try_capture_a_frame')
                return None
            time.sleep(0.1)
