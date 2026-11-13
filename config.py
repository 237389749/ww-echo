import os
import re

# WA: set empty PATH to resolve qfluentwidgets/PySide6 access os.environ['PATH'] issue
if 'PATH' not in os.environ:
    os.environ['PATH'] = ""

from src.run_modes import MODE_CLOUD, MODE_LOCAL

__all__ = ['config', 'apply_run_mode', 'MODE_LOCAL', 'MODE_CLOUD']

version = "echo-dev"

config = {
    'debug': False,
    'use_gui': True,
    'config_folder': 'configs',
    'gui_icon': 'icon.png',
    'ocr': {
        'lib': 'onnxocr',
        'params': {
            'use_openvino': True,
            'use_npu': True,
        }
    },
    'start_timeout': 120,
    'wait_until_settle_time': 0,
    'template_matching': {
        'coco_feature_json': os.path.join('assets', 'coco_annotations.json'),
        'default_horizontal_variance': 0.002,
        'default_vertical_variance': 0.002,
        'default_threshold': 0.8,
    },
    'windows': {
        'exe': 'Client-Win64-Shipping.exe',
        'hwnd_class': 'UnrealWindow',
        'interaction': 'PostMessage',
        'capture_method': ['WGC', 'BitBlt_RenderFull'],
        'start_exe': False,
        'check_hdr': False,
        'force_no_hdr': False,
        'check_night_light': True,
        'force_no_night_light': False,
    },
    'window_size': {
        'width': 1200,
        'height': 800,
        'min_width': 1200,
        'min_height': 800,
    },
    'supported_resolution': {
        'ratio': '16:9',
        'resize_to': [(2560, 1440), (1920, 1080), (1600, 900), (1280, 720)],
        'min_size': (1280, 720)
    },
    'screenshots_folder': "screenshots",
    'gui_title': 'OK-Echo',
    'log_file': 'logs/ok-echo.log',
    'error_log_file': 'logs/ok-echo_error.log',
    'version': version,
    'onetime_tasks': [
        ["src.task.EnhanceEchoTask", "EnhanceEchoTask"],
    ],
}

# ── 运行模式: 本地客户端(默认) / 云游戏(浏览器/云客户端前台窗口) ──
# 在 OK(config) 启动前调用 apply_run_mode(), 只改 windows 段相关键, 其余不动。
# 两种模式都**不自动拉起游戏**(start_exe=False): 本工具只做背包内的声骸强化/评估,
# 要求用户已把游戏开到背包声骸列表; 自动启动/自动战斗属 ok-ww 的农场能力, 已剥离。
# MODE_LOCAL / MODE_CLOUD 来自 src/run_modes.py(UI 也直接用它, 避免 UI→config 反向依赖)。

# 本地模式的静态默认值(与上方 windows 段一致), 切回 local 时用于还原。
_LOCAL_EXE = 'Client-Win64-Shipping.exe'
_LOCAL_HWND_CLASS = 'UnrealWindow'
_LOCAL_INTERACTION = 'PostMessage'
# 云游戏模式: 本地无 UnrealWindow 可后台投递, 用前台真实键鼠(需管理员运行 ww-echo)
_CLOUD_INTERACTION = 'Pynput'


def apply_run_mode(mode):
    """按运行模式调整 config['windows'] 的设备定位方式。

    'local' —— exe/hwnd_class 自动匹配本地游戏窗口, PostMessage 后台交互(默认)。
    'cloud' —— exe/hwnd_class 置空, 改按 title=re.compile('鸣潮') 正则自动锁定云游戏
               窗口(浏览器/云客户端, 画面需前台可见); interaction 切 Pynput 前台真实键鼠。
               同时关闭 16:9 分辨率比例校验: 本地模式 ok-script 会把游戏窗口自动
               resize 成 16:9, 云游戏的浏览器/云客户端窗口尺寸不受控(如 16:10 屏幕),
               ratio=None 时 TaskExecutor 跳过比例校验且不会触发坐标缩放换算。
    """
    win = config['windows']
    if mode == MODE_CLOUD:
        # 自动锁定标题含"鸣潮"的窗口(find_hwnd 对 title 正则做 re.search 匹配),
        # 云游戏窗口标题即带"鸣潮", 无需用户在窗口列表手动选窗
        win['title'] = re.compile('鸣潮')
        win['exe'] = None
        win['hwnd_class'] = None
        win['interaction'] = _CLOUD_INTERACTION
        # 云游戏窗口截图限定 BitBlt: 浏览器/云客户端窗口走 WGC 常黑屏或不支持
        win['capture_method'] = ['BitBlt_RenderFull']
        # 云游戏不自动启动游戏 exe
        win['start_exe'] = False
        config['supported_resolution']['ratio'] = None
    else:
        win['exe'] = _LOCAL_EXE
        win['hwnd_class'] = _LOCAL_HWND_CLASS
        win.pop('title', None)
        win['interaction'] = _LOCAL_INTERACTION
        win['capture_method'] = ['WGC', 'BitBlt_RenderFull']
        win['start_exe'] = False
        config['supported_resolution']['ratio'] = '16:9'
    return win
