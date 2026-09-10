import os
import re
from pathlib import Path

# WA: set empty PATH to resolve qfluentwidgets/PySide6 access os.environ['PATH'] issue
if 'PATH' not in os.environ:
    os.environ['PATH'] = ""
from qfluentwidgets import FluentIcon

from ok import Box, ConfigOption
from src.task.process_feature import process_feature

version = "echo-dev"


def calculate_pc_exe_path(running_path):
    game_exe_folder = Path(running_path).parents[3]
    return str(game_exe_folder / "Wuthering Waves.exe")


def blur_area(width, height):
    blur_width = int(0.12 * width)
    blur_height = int(0.024 * height)
    return Box(width * 0.879, height * 0.976, blur_width * 0.973, blur_height * 0.994)


key_config_option = ConfigOption('Game Hotkey', {
    'Echo Key': 'q',
    'Liberation Key': 'r',
    'Resonance Key': 'e',
    'Tool Key': 't',
    'Jump Key': 'space',
    'Dodge Key': 'lshift',
    'Wheel Key': 'tab',
    'Guidebook Key': 'f2',
}, description='In Game Hotkey for Skills', show_at_tab=True, icon=FluentIcon.GAME)

monthly_card_config_option = ConfigOption('Monthly Card Config', {
    'Check Monthly Card': False,
    'Monthly Card Time': 4
}, description='Turn on to avoid interruption by monthly card when executing tasks', config_description={
    'Check Monthly Card': 'Check for monthly card to avoid interruption of tasks',
    'Monthly Card Time': 'Your computer\'s local time when the monthly card will popup, hour in (1-24)'
})

config = {
    'debug': False,
    'use_gui': True,
    'config_folder': 'configs',
    'blur_area': blur_area,
    'gui_icon': 'icon.png',
    'global_configs': [key_config_option, monthly_card_config_option],
    'ocr': {
        'lib': 'onnxocr',
        'auto_simplify': True,
        'params': {
            'use_openvino': True,
            'use_npu': True,
        }
    },
    'my_app': ['src.globals', 'Globals'],
    'start_timeout': 120,
    'wait_until_settle_time': 0,
    'template_matching': {
        'coco_feature_json': os.path.join('assets', 'coco_annotations.json'),
        'default_horizontal_variance': 0.002,
        'default_vertical_variance': 0.002,
        'default_threshold': 0.8,
        'feature_processor': process_feature,
        'vcenter_features': ['monthly_card'],
        'hcenter_features': ['monthly_card']
    },
    'windows': {
        'top_hwnd_class': [re.compile('CAgreementDlg'), re.compile('CLoginDlg_P_'),
                           'CefBrowserWindow', 'Chrome_RenderWidgetHostHWND', '#32770',
                           re.compile('CNativeLoginDlg'), 'Static', 'ComboBox', 'ComboLBox', 'Button'
                           ],
        'calculate_pc_exe_path': calculate_pc_exe_path,
        'exe': 'Client-Win64-Shipping.exe',
        'hwnd_class': 'UnrealWindow',
        'interaction': 'PostMessage',
        'capture_method': ['WGC', 'BitBlt_RenderFull'],
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
    'links': {
        'default': {
            'github': 'https://github.com/ok-oldking/ok-wuthering-waves',
            'discord': 'https://discord.gg/vVyCatEBgA',
        },
    },
    'about': """
    <p>声骸强化工具 - 基于 ok-ww 剥离</p>
    <p>仅供学习交流使用</p>
""",
    'screenshots_folder': "screenshots",
    'gui_title': 'OK-Echo',
    'log_file': 'logs/ok-echo.log',
    'error_log_file': 'logs/ok-echo_error.log',
    'launcher_log_file': 'logs/launcher.log',
    'launcher_error_log_file': 'logs/launcher_error.log',
    'version': version,
    'onetime_tasks': [
        ["src.task.EnhanceEchoTask", "EnhanceEchoTask"],
        ["src.task.ChangeEchoTask", "ChangeEchoTask"],
    ],
    'trigger_tasks': [
        ["src.task.MouseResetTask", "MouseResetTask"],
    ],
    'scene': ["src.scene.WWScene", "WWScene"],
}

# ── 运行模式: 本地客户端(默认) / 云游戏(浏览器/云客户端前台窗口) ──
# 在 OK(config) 启动前调用 apply_run_mode(), 只改 windows 段相关键, 其余不动。
MODE_LOCAL = 'local'
MODE_CLOUD = 'cloud'

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
        # 云游戏窗口标题即带"鸣潮", 无需用户在窗口列表手动选择
        win['title'] = re.compile('鸣潮')
        win['exe'] = None
        win['hwnd_class'] = None
        win['interaction'] = _CLOUD_INTERACTION
        # 云游戏窗口截图限定 BitBlt: 浏览器/云客户端窗口走 WGC 常黑屏或不支持
        win['capture_method'] = ['BitBlt_RenderFull']
        # 云游戏不自动启动游戏 exe(start_device 会用 calculate_pc_exe_path 推 exe 路径而崩)
        win['start_exe'] = False
        config['supported_resolution']['ratio'] = None
    else:
        win['exe'] = _LOCAL_EXE
        win['hwnd_class'] = _LOCAL_HWND_CLASS
        win.pop('title', None)
        win['interaction'] = _LOCAL_INTERACTION
        win['capture_method'] = ['WGC', 'BitBlt_RenderFull']
        win['start_exe'] = True
        config['supported_resolution']['ratio'] = '16:9'
    return win
