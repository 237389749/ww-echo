#!/usr/bin/env python3
"""按「页面内容区」尺寸抓单页截图 —— 最小窗口布局的验收工具（U-02 / U-05）。

**为什么不直接用 `tools/ui_shot.py`**: 它是"整窗 + 全部 7 页"(走 MainWindow), 而离屏平台屏幕只有
800×800, 顶层窗口会被夹住 → `--size 940x620` 实际得到 640×480, 最小窗口根本没法看图。
本工具把页面当普通 QWidget 直接 `resize` + `show`(不套 MainWindow), 所以 **892×570**
(= 940×620 窗口的内容区)能如实渲染; 还能把页面级滚动容器滚到底再抓(看折叠在下面的卡片)。

引擎打桩复用 `tools/ui_shot.py` 里那套(不初始化 OK 引擎, 无设备环境会卡住)。

用法:
    python tools/ui_page_shot.py --list
    python tools/ui_page_shot.py setconfig 892x570 logs/setconfig_892.png
    python tools/ui_page_shot.py setconfig 892x570 logs/setconfig_892_bottom.png --bottom
    python tools/ui_page_shot.py plan 1120x760 logs/plan_1120.png
    python tools/ui_page_shot.py debug 892x570 logs/debug_892.png --dark
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")     # 无显示器也能渲染

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TOOLS))

from PySide6.QtCore import QObject, Signal                          # noqa: E402
from PySide6.QtWidgets import QApplication, QTextEdit               # noqa: E402

import ui_shot                                                      # noqa: E402  (复用桩件/字体)

PAGES = ("setconfig", "plan", "debug", "run", "settings", "dev", "about")


class _LogBridge(QObject):
    """运行页只要一个带 log_signal 的 QObject（不 import mainui, 免得拉起整个应用）。"""
    log_signal = Signal(str)


def _build(page: str):
    if page == "setconfig":
        from ui.set_config_tab import SetConfigTab
        return SetConfigTab()
    if page == "plan":
        from ui.plan_tab import PlanTab
        return PlanTab()
    if page == "debug":
        from ui.debug_tab import DebugTab
        return DebugTab(_fake_log())
    if page == "run":
        from ui.run_tab import RunTab
        return RunTab(ok_engine=None, log_bridge=_LogBridge(), log_area=_fake_log())
    if page == "settings":
        from ui.settings_tab import SettingsTab
        return SettingsTab()
    if page == "dev":
        from ui.dev_tab import DevTab
        return DevTab()
    from ui.about_tab import AboutTab
    return AboutTab()


def _fake_log() -> QTextEdit:
    """日志视图: 塞几行, 免得抓出来是空白(看不出高度是否够)。"""
    log = QTextEdit()
    log.setPlainText("\n".join(
        f"2026-11-22 17:{i:02d}:00 INFO  第 {i} 行示例日志 —— 用来量日志卡高度" for i in range(40)))
    return log


def _pump(app: QApplication, times: int = 6):
    for _ in range(times):
        app.processEvents()


def main() -> int:
    ap = argparse.ArgumentParser(description="按页面内容区尺寸抓单页截图")
    ap.add_argument("page", nargs="?", help="页面名: " + " / ".join(PAGES))
    ap.add_argument("size", nargs="?", default="892x570", help="内容区尺寸 WxH(默认 892x570)")
    ap.add_argument("out", nargs="?", help="输出 PNG 路径")
    ap.add_argument("--bottom", action="store_true", help="先把页面级滚动容器滚到底再抓")
    ap.add_argument("--dark", action="store_true", help="深色主题")
    ap.add_argument("--list", action="store_true", help="列出可抓的页面")
    a = ap.parse_args()
    if a.list or not a.page:
        print("可抓页面:", ", ".join(PAGES))
        return 0
    if a.page not in PAGES:
        print(f"未知页面 {a.page!r}; 可选: {', '.join(PAGES)}")
        return 2
    if not a.out:
        print("缺少输出路径")
        return 2

    app = QApplication(sys.argv[:1])
    ui_shot.register_fonts(app)

    # 引擎桩件: 界面只用到 og 的这几个属性(不初始化 OK 引擎)
    import ww_engine                                                        # noqa: F401
    from ww_engine import og
    for name, val in (("device_manager", ui_shot.StubDeviceManager()),
                      ("executor", SimpleNamespace(global_config=ui_shot.StubGlobalConfig())),
                      ("config", {"version": "ui-page-shot"})):
        try:
            setattr(og, name, val)
        except Exception as e:                                       # noqa: BLE001
            print(f"[warn] 无法设置 og.{name}: {e}")

    if a.dark:
        from qfluentwidgets import setTheme, Theme
        setTheme(Theme.DARK)

    page = _build(a.page)
    w, h = (int(x) for x in a.size.lower().split("x"))
    page.resize(w, h)
    page.show()
    _pump(app)

    if a.bottom:
        from qfluentwidgets import SingleDirectionScrollArea
        areas = page.findChildren(SingleDirectionScrollArea)
        if areas:
            bar = areas[0].verticalScrollBar()
            bar.setValue(bar.maximum())
            _pump(app)
            print(f"已滚到底: {bar.value()}/{bar.maximum()}px")
        else:
            print("[warn] 这个页面没有页面级滚动容器")

    page.update()
    app.processEvents()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    page.grab().save(a.out)
    print(f"saved {a.out}  ({page.width()}x{page.height()})")

    # 主动销毁顶层窗口: 进程里 import 过 ww_engine 时, 解释器退出与仍存活的窗口抢顺序会段错误
    # (0xC0000005, 实测; 详见 docs/UI_FIX_HANDOFF.md 的坑与 ui/widgets.py 附近的记录)
    page.hide()
    page.deleteLater()
    _pump(app, 2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
