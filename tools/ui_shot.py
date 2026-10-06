#!/usr/bin/env python3
"""离屏渲染界面截图 —— 改 UI 后的自检工具(不需要游戏、不需要显示器)。

做法: 用**桩件**替代 ok-script 引擎(设备管理/全局配置), 只构建 `MainWindow` 并把每个页面渲染成 PNG。
注意 `OK(config)` 会自己创建 QApplication 且在无设备环境会卡住, 所以本工具**不**初始化引擎, 只替换
`ok.og` 上界面用到的几个属性; 因此它只能验证"界面能否构建 + 长什么样", 不能验证真实任务流程。

用法::

    python tools/ui_shot.py                     # 输出到 .scratch/ui_shots/
    python tools/ui_shot.py --out D:\\shots --dark --size 1280x860
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")     # 无显示器也能渲染

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QEventLoop, QTimer                        # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase                       # noqa: E402
from PySide6.QtWidgets import QApplication                           # noqa: E402


def register_fonts(app: QApplication):
    """离屏模式 Qt 自带字体目录是空的 → 注册系统中文字体, 否则截图里全是方块。"""
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
              "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/consola.ttf"):
        if os.path.exists(f):
            QFontDatabase.addApplicationFont(f)
    app.setFont(QFont("Microsoft YaHei UI", 9))


class StubCfg(dict):
    def save_file(self):
        pass


class StubGlobalConfig:
    """ok-script 的 global_config: 界面只用 get_config(name) → 字典。"""

    def __init__(self):
        self._cfgs = {}

    def get_config(self, key):
        k = str(getattr(key, "name", key))
        return self._cfgs.setdefault(
            k, StubCfg({"Check Monthly Card": True, "Monthly Card Time": 4,
                        "Mute Game while in Background": False}))


class StubDeviceManager:
    """假设备: 给界面一点内容(3 个窗口 / 3 种截图方式 / 2 种交互方式)。"""
    windows_capture_config = {
        "capture_method": ["BitBlt_RenderFull", "WGC", "BitBlt"],
        "interaction": ["PostMessage", "Pynput"],
    }
    config = {"preferred": "stub-2", "capture_method": "BitBlt_RenderFull",
              "interaction": "PostMessage"}

    def refresh(self):
        from ok.gui.Communicate import communicate
        communicate.adb_devices.emit(True)

    def get_devices(self):
        return [{"nick": "鸣潮（云·鸣潮）", "address": "cloud-1", "connected": True, "imei": "stub-1"},
                {"nick": "Client-Win64-Shipping (UnrealWindow)", "address": "", "connected": True,
                 "imei": "stub-2"},
                {"nick": "浏览器（鸣潮 标签页）", "address": "", "connected": False, "imei": "stub-3"}]

    def set_preferred_device(self, **kw):
        pass

    def set_capture(self, x):
        pass

    def set_interaction(self, x):
        pass


def wait(ms: int = 400):
    """等切页淡入动画走完, 否则 grab 到半透明的空页。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    ap = argparse.ArgumentParser(description="离屏渲染 ww-echo 界面(桩件模式)")
    ap.add_argument("--out", default=str(REPO / ".scratch" / "ui_shots"), help="输出目录")
    ap.add_argument("--size", default="1180x820", help="窗口尺寸 WxH")
    ap.add_argument("--dark", action="store_true", help="用深色主题渲染(自检深色适配)")
    a = ap.parse_args()

    app = QApplication(sys.argv)
    register_fonts(app)

    # 只替换界面用到的 og 属性 —— 不初始化 OK 引擎(无设备环境会卡住)
    import ok                                                        # noqa: F401
    from ok import og

    for name, val in (("device_manager", StubDeviceManager()),
                      ("executor", SimpleNamespace(global_config=StubGlobalConfig())),
                      ("config", {"version": "ui-shot"})):
        try:
            setattr(og, name, val)
        except Exception as e:                                       # noqa: BLE001
            print(f"[warn] 无法设置 og.{name}: {e}")

    from mainui import LogBridge
    from ui.main_window import MainWindow

    win = MainWindow(ok_engine=None, log_bridge=LogBridge())
    if a.dark:
        win.apply_theme("DARK")
    w, h = (int(x) for x in a.size.lower().split("x"))
    win.resize(w, h)
    win.show()
    app.processEvents()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stack = win.stackedWidget
    for i in range(stack.count()):
        stack.setCurrentIndex(i)
        wait()
        page = stack.widget(i)
        name = page.objectName().replace("page_", "") or f"page{i}"
        path = out / f"{'dark_' if a.dark else ''}{i}_{name}.png"
        win.grab().save(str(path))
        print("saved", path)
    print(f"共 {stack.count()} 页 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
