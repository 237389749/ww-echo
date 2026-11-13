"""Windows-only device manager (vendored from ok-script, trimmed).

只保留本项目需要的窗口模式：
  - 本地客户端：exe / hwnd_class / title 定位窗口
  - 云游戏：title 正则定位浏览器/云客户端窗口
  - 截图：WGC / BitBlt_RenderFull
  - 交互：PostMessage / Pynput
ADB、模拟器、BrowserCaptureMethod、Nemu、DesktopDuplication 等分支已删除。
"""

import os

from ww_engine.device.capture import HwndWindow, update_capture_method
from ww_engine.device.interaction import PostMessageInteraction, PynputInteraction
from ww_engine.gui.Communicate import communicate
from ww_engine.util.collection import parse_ratio
from ww_engine.util.config import Config
from ww_engine.util.handler import Handler
from ww_engine.util.logger import Logger
from ww_engine.util.window import find_hwnd, find_all_visible_windows, get_window_bounds

logger = Logger.get_logger(__name__)


class DeviceManager:

    def __init__(self, app_config, exit_event=None, global_config=None):
        logger.info('DeviceManager init start')
        self._device = None
        self.executor = None
        self.capture_method = None
        self.global_config = global_config
        supported_resolution = app_config.get('supported_resolution', {})
        self.supported_ratio = parse_ratio(supported_resolution.get('ratio'))
        self.windows_capture_config = app_config.get('windows')
        self.debug = app_config.get('debug')
        self.interaction = None
        self.device_dict = {}
        self.exit_event = exit_event
        self.resolution_dict = {}
        self.config = Config("devices",
                             {"preferred": "", "pc_full_path": "", 'capture': 'windows', 'selected_exe': '',
                              'selected_hwnd': 0, 'interaction': ''})
        self.handler = Handler(exit_event, 'RefreshWindows')
        self.hwnd_window = None
        self.win_interaction_class = PynputInteraction

        if self.windows_capture_config is not None:
            if isinstance(self.windows_capture_config.get('exe'), str):
                self.windows_capture_config['exe'] = [self.windows_capture_config.get('exe')]

            self.hwnd_window = HwndWindow(
                exit_event, self.windows_capture_config.get('title'),
                self.windows_capture_config.get('exe'),
                hwnd_class=self.windows_capture_config.get('hwnd_class'),
                global_config=self.global_config, device_manager=self,
                top_hwnd_class=self.windows_capture_config.get('top_hwnd_class'))

            interaction = self.windows_capture_config.get('interaction')
            if isinstance(interaction, list):
                selected_interaction = interaction[0] if interaction else 'Pynput'
            else:
                selected_interaction = interaction

            saved_interaction = self.config.get('interaction')
            if saved_interaction:
                if isinstance(interaction, list):
                    for item in interaction:
                        item_name = item.__name__ if isinstance(item, type) else item
                        if saved_interaction == item_name:
                            selected_interaction = item
                            break
                else:
                    item_name = interaction.__name__ if isinstance(interaction, type) else interaction
                    if saved_interaction == item_name:
                        selected_interaction = interaction

            if selected_interaction == 'PostMessage':
                self.win_interaction_class = PostMessageInteraction
            elif selected_interaction == 'Pynput':
                self.win_interaction_class = PynputInteraction
            elif selected_interaction:
                self.win_interaction_class = selected_interaction
            else:
                self.win_interaction_class = PynputInteraction

        logger.info('DeviceManager init end')

    # ── 窗口/设备列表 ──
    def stop_hwnd(self):
        if self.hwnd_window:
            logger.info('stop_hwnd: close capture only (game process is not killed)')
            try:
                self.hwnd_window.stop()
            except Exception as e:
                logger.warning(f'stop_hwnd failed: {e}')

    def select_hwnd(self, exe, hwnd):
        self.config['selected_exe'] = exe
        self.config['selected_hwnd'] = hwnd

    def refresh(self):
        logger.debug('calling refresh')
        self.handler.post(self.do_refresh, remove_existing=True, skip_if_running=True)

    def get_devices(self):
        return sorted(self.device_dict.values(),
                      key=lambda d: 0 if d.get('device') == 'windows' else 1)

    def update_pc_device(self):
        if self.windows_capture_config is None:
            return None
        cfg = self.windows_capture_config
        if not cfg.get('exe') and not cfg.get('hwnd_class') and not cfg.get('title'):
            # 没有定位条件时列出可见窗口（设置页手动选窗用）
            windows = find_all_visible_windows()
            for k in [k for k in self.device_dict if k.startswith('pc_')]:
                del self.device_dict[k]
            for hwnd, title, exe_name, full_path in windows:
                x, y, _, _, width, height, _ = get_window_bounds(hwnd)
                if width > 0 and height > 0:
                    imei = f"pc_{hwnd}"
                    self.device_dict[imei] = {
                        "address": "", "imei": imei, "device": "windows",
                        "model": "", "nick": title, "width": width, "height": height,
                        "hwnd": title, "capture": "windows", "connected": True,
                        "full_path": full_path, "real_hwnd": hwnd, "exe": exe_name,
                        "resolution": f"{width}x{height}",
                    }
            return None

        name, hwnd, full_path, x, y, width, height, hwnds = find_hwnd(
            cfg.get('title'),
            cfg.get('exe') or self.config.get('selected_exe'), 0, 0,
            player_id=-1, class_name=cfg.get('hwnd_class'),
            selected_hwnd=self.config.get('selected_hwnd'),
            top_hwnd_class=cfg.get('top_hwnd_class'))
        exe_list = cfg.get('exe') or self.config.get('selected_exe')
        if isinstance(exe_list, str):
            exe_list = [exe_list]
        nick = name or (exe_list[0] if exe_list else "PC")
        imei = f"pc_{hwnd}" if hwnd else "pc"
        pc_device = {"address": "", "imei": imei, "device": "windows",
                     "model": "", "nick": nick, "width": width, "height": height,
                     "hwnd": nick, "capture": "windows", "connected": hwnd > 0,
                     "full_path": full_path or self.config.get('pc_full_path'),
                     "real_hwnd": hwnd, "exe": exe_list}
        if width != 0:
            pc_device["resolution"] = f"{width}x{height}"
        logger.info(f'update_pc_device pc_device: {pc_device}')
        self.device_dict[imei] = pc_device
        if imei != 'pc':
            self.device_dict.pop('pc', None)
        if full_path and full_path != self.config.get('pc_full_path'):
            self.config['pc_full_path'] = full_path
        return imei

    def do_refresh(self, current=False):
        try:
            self.update_pc_device()
        except Exception as e:
            logger.error(f'refresh error: {e}')
        if self.exit_event.is_set():
            return
        self.do_start()
        logger.debug(f'refresh {self.device_dict}')

    def set_preferred_device(self, imei=None, index=-1):
        logger.debug(f"set_preferred_device {imei} {index}")
        if index != -1:
            imei = self.get_devices()[index]['imei']
        elif imei is None:
            imei = self.config.get("preferred")
        preferred = self.device_dict.get(imei)
        if preferred is None:
            if self.device_dict:
                connected_device = None
                for device in self.device_dict.values():
                    if device.get('connected') or connected_device is None:
                        connected_device = device
                logger.info(f'first start use first or connected device {connected_device}')
                preferred = connected_device
                imei = preferred['imei']
            else:
                logger.warning('no devices')
                return
        if self.config.get("preferred") != imei:
            logger.info(f'preferred device did change {imei}')
            self.config["preferred"] = imei
            if preferred.get('device') == 'windows' and preferred.get('real_hwnd'):
                self.select_hwnd(preferred.get('exe'), preferred.get('real_hwnd'))
            self.start()
        logger.debug(f'preferred device: {preferred}')

    def get_preferred_device(self):
        return self.device_dict.get(self.config.get("preferred"))

    def get_preferred_capture(self):
        return self.config.get("capture")

    def set_hwnd_name(self, hwnd_name):
        preferred = self.get_preferred_device()
        if preferred and preferred.get("hwnd") != hwnd_name:
            preferred['hwnd'] = hwnd_name
            if self.hwnd_window:
                self.hwnd_window.title = hwnd_name
            self.config.save_file()

    def set_capture(self, capture):
        if self.config.get("capture") != capture:
            self.config['capture'] = capture
            self.start()

    def set_interaction(self, interaction):
        interaction_name = interaction.__name__ if isinstance(interaction, type) else interaction
        config_interaction = self.windows_capture_config.get('interaction') if self.windows_capture_config else None
        if isinstance(interaction, str):
            if isinstance(config_interaction, list):
                for item in config_interaction:
                    if isinstance(item, type) and item.__name__ == interaction:
                        interaction = item
                        break
            elif isinstance(config_interaction, type) and config_interaction.__name__ == interaction:
                interaction = config_interaction

        if self.config.get("interaction") != interaction_name:
            self.config['interaction'] = interaction_name
            if interaction == 'PostMessage':
                self.win_interaction_class = PostMessageInteraction
            elif interaction == 'Pynput':
                self.win_interaction_class = PynputInteraction
            elif interaction:
                self.win_interaction_class = interaction
            self.start()

    def get_hwnd_name(self):
        preferred = self.get_preferred_device()
        return preferred.get('hwnd') if preferred else None

    def ensure_hwnd(self, title, exe, frame_width=0, frame_height=0, player_id=-1,
                    hwnd_class=None, top_hwnd_class=None):
        if self.hwnd_window is None:
            self.hwnd_window = HwndWindow(
                self.exit_event, title, exe, frame_width, frame_height, player_id,
                hwnd_class, global_config=self.global_config,
                device_manager=self, top_hwnd_class=top_hwnd_class)
        else:
            self.hwnd_window.update_window(title, exe, frame_width, frame_height,
                                           player_id, hwnd_class, top_hwnd_class)

    def use_windows_capture(self):
        selected_method = self.config.get('capture')
        valid_methods = self.windows_capture_config.get('capture_method', [])
        if not selected_method or selected_method not in valid_methods:
            if valid_methods:
                selected_method = valid_methods[0]
        self.capture_method = update_capture_method(
            self.windows_capture_config, self.capture_method, self.hwnd_window,
            exit_event=self.exit_event, selected_method=selected_method)
        if self.capture_method is None:
            logger.error('cant find a usable windows capture')
        else:
            logger.info(f'capture method {type(self.capture_method)}')
            if self.interaction:
                self.interaction.capture = self.capture_method

    def start(self):
        self.handler.post(self.do_start, remove_existing=True, skip_if_running=True)

    def do_start(self):
        logger.debug('do_start')
        preferred = self.get_preferred_device()
        if preferred is None:
            if self.device_dict:
                self.set_preferred_device()
            return
        if preferred.get('device') != 'windows':
            logger.warning(f'unsupported device type: {preferred.get("device")}')
            return

        title = self.windows_capture_config.get('title')
        exe = self.windows_capture_config.get('exe')
        if not exe and not title and preferred.get('real_hwnd'):
            exe = preferred.get('exe')
        self.ensure_hwnd(title, exe,
                         hwnd_class=self.windows_capture_config.get('hwnd_class'),
                         top_hwnd_class=self.windows_capture_config.get('top_hwnd_class'))
        self.use_windows_capture()
        if not isinstance(self.interaction, self.win_interaction_class):
            self.interaction = self.win_interaction_class(self.capture_method, self.hwnd_window)
        elif self.interaction:
            self.interaction.capture = self.capture_method
        preferred['connected'] = self.capture_method is not None and self.capture_method.connected()
        communicate.adb_devices.emit(True)

    def update_resolution_for_hwnd(self):
        # 云/本地窗口不需要 ADB 分辨率同步；保留接口给 TaskExecutor 调用。
        return None

    @property
    def width(self):
        return self.capture_method.width if self.capture_method is not None else 0

    @property
    def height(self):
        return self.capture_method.height if self.capture_method is not None else 0

    def clear_devices(self):
        logger.info('clear_devices')
        self.device_dict.clear()
        self.config['preferred'] = ''
        self.config['selected_hwnd'] = 0
        self.config['pc_full_path'] = ''
        self._device = None
        self.resolution_dict.clear()

    def device_connected(self):
        preferred = self.get_preferred_device()
        return bool(preferred and preferred.get('device') == 'windows')

    def get_exe_path(self, device):
        path = device.get('full_path') if device else None
        if not path or path == 'none':
            return None
        return path if os.path.exists(path) else None

    def update_capture(self, config: dict):
        """Windows-only 版：设置页切换窗口后重建 capture/interaction。"""
        import time
        logger.info(f'update_capture {config}')
        win_config = config.get('windows')
        if not win_config:
            raise Exception('only windows capture is supported')
        reset_selected_hwnd = any(
            key in win_config for key in ('title', 'exe', 'hwnd_class', 'top_hwnd_class', 'selected_hwnd'))
        selected_hwnd = self.config.get('selected_hwnd')
        self.clear_devices()
        if not reset_selected_hwnd:
            self.config['selected_hwnd'] = selected_hwnd
        for key in ('title', 'hwnd_class', 'top_hwnd_class'):
            if key in win_config:
                self.windows_capture_config[key] = win_config[key]
        if 'exe' in win_config:
            exe_val = win_config['exe']
            self.windows_capture_config['exe'] = [exe_val] if isinstance(exe_val, str) else exe_val
            self.config['selected_exe'] = exe_val if isinstance(exe_val, str) else exe_val[0]
        if 'selected_hwnd' in win_config:
            self.config['selected_hwnd'] = win_config['selected_hwnd']

        imei = self.update_pc_device()
        if not imei:
            raise Exception("Cannot find window")
        pc = self.device_dict.get(imei)
        if not pc or not pc.get('connected'):
            logger.error(f"Cannot find window. PC device data: {pc}, config: {self.windows_capture_config}")
            raise Exception("Cannot find window")
        self.set_preferred_device(imei)

        if 'interaction' in win_config:
            self.set_interaction(win_config['interaction'])
        if 'capture_method' in win_config:
            self.set_capture(win_config['capture_method'])
        elif 'capture' in win_config:
            self.set_capture(win_config['capture'])

        if 'resolution' in win_config and getattr(self, 'hwnd_window', None):
            resolution = win_config['resolution']
            for _ in range(50):
                if self.hwnd_window.hwnd:
                    break
                time.sleep(0.1)
            if self.hwnd_window.hwnd:
                logger.info(f'update_capture try_resize_to {resolution}')
                if not self.hwnd_window.try_resize_to([resolution]):
                    raise Exception(f"Failed to resize window to {resolution}")
        if getattr(self, 'hwnd_window', None):
            self.hwnd_window.do_update_window_size()
            logger.info(f'update_capture window size {self.hwnd_window.width}x{self.hwnd_window.height}')

    def ensure_capture(self, config: dict):
        """Windows-only 版：启动前确认窗口/capture 可用。"""
        logger.info(f'ensure_capture {config}')
        self.clear_devices()
        win_config = config.get('windows')
        if not win_config:
            raise Exception('only windows capture is supported')
        for key in ('title', 'hwnd_class', 'top_hwnd_class'):
            if key in win_config:
                self.windows_capture_config[key] = win_config[key]
            else:
                self.windows_capture_config.pop(key, None)
        if 'exe' in win_config:
            exe_val = win_config['exe']
            self.windows_capture_config['exe'] = [exe_val] if isinstance(exe_val, str) else exe_val
            self.config['selected_exe'] = exe_val if isinstance(exe_val, str) else exe_val[0]
        self.config['selected_hwnd'] = 0

        imei = self.update_pc_device()
        if not imei:
            raise Exception("Cannot find window")
        pc = self.device_dict.get(imei)
        if not pc or not pc.get('connected'):
            raise Exception("Cannot find window")
        self.set_preferred_device(imei)
        if 'interaction' in win_config:
            self.set_interaction(win_config['interaction'])
        if 'capture_method' in win_config:
            self.set_capture(win_config['capture_method'])
        else:
            self.set_capture('windows')
