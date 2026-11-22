#!/usr/bin/env python3
r"""界面缺陷探针（2026-11-22 评审的交接工具）：把几个"看不见但能量出来"的问题变成可执行检查。

输入:
  - 源码 `ui/*.py`（静态检查）
  - 离屏 Qt（运行检查：SpinBox 的 LineEdit 几何 + 抓图像素）
输出:
  - stdout 逐项 PASS/FAIL；`--strict` 时有 FAIL 退出码 1（交接验收用）
支撑:
  - `docs/UI_FIX_HANDOFF.md`（修复清单）与 `docs/UI_REVIEW_2026-11-22.md`（评审证据）
  - 评审时的现状：C1~C5 全 FAIL；第 1 批修完后应全 PASS

用法:
  python tools/ui_probe.py            # 诊断：只打印，不判退出码
  python tools/ui_probe.py --strict   # 验收：仍有 FAIL 则退出码 1
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def read(path: str) -> str:
    with open(os.path.join(ROOT, path), encoding='utf-8') as f:
        return f.read()


def luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def f(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def check_spin():
    """C1: 套装配置页的数值框必须真的画出数字。"""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    for f in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/msyhbd.ttc'):
        if os.path.exists(f):
            QFontDatabase.addApplicationFont(f)
    app.setFont(QFont('Microsoft YaHei UI', 9))

    from qfluentwidgets import DoubleSpinBox
    from ui.set_config_tab import SetConfigTab

    tab = SetConfigTab()
    tab.resize(1120, 760)
    tab.show()
    for _ in range(5):
        app.processEvents()
    spins = tab.findChildren(DoubleSpinBox)
    if not spins:
        return False, 'SetConfigTab 里找不到 DoubleSpinBox（控件被换掉了？）'
    narrow = [s for s in spins if s.lineEdit().width() < 20]
    # 再取一个抓图，防"宽度对了但没画"（对比度/颜色问题）
    img = spins[0].grab().toImage()
    darkest = min(img.pixelColor(x, y).lightness()
                  for x in range(img.width()) for y in range(img.height()))
    ok = not narrow and darkest < 120
    return ok, (f'{len(narrow)}/{len(spins)} 个 LineEdit 宽 < 20px'
                f'（首个 {spins[0].lineEdit().width()}px），首个抓图最暗像素 {darkest}')


def check_setconfig_scroll():
    """C2: 套装配置页在 892×570（940×620 窗口的内容区）必须能滚，而不是裁切。"""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    for f in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/msyhbd.ttc'):
        if os.path.exists(f):
            QFontDatabase.addApplicationFont(f)
    app.setFont(QFont('Microsoft YaHei UI', 9))

    from qfluentwidgets import SingleDirectionScrollArea
    from ui.set_config_tab import SetConfigTab

    tab = SetConfigTab()
    tab.resize(892, 570)
    tab.show()
    for _ in range(5):
        app.processEvents()
    # 注意: QTableWidget 自己也是 QAbstractScrollArea, 不能拿它当"页面能滚"的证据 ——
    # 只认页面级滚动容器(项目统一用 SingleDirectionScrollArea)。
    areas = tab.findChildren(SingleDirectionScrollArea)
    debug_src = read('ui/debug_tab.py')
    debug_ok = 'SingleDirectionScrollArea' in debug_src or 'QScrollArea' in debug_src
    if not areas:
        return False, 'SetConfigTab 没有页面级滚动容器（表格自身的滚动不算）'
    bar = areas[0].verticalScrollBar()
    ok = bar.maximum() > 0 and debug_ok
    detail = (f'SetConfigTab 页面滚动范围 {bar.maximum()}px，debug_tab '
              + ('有滚动容器' if debug_ok else '缺滚动容器'))
    return ok, detail


def check_eval_counters():
    """C3: 评估状态卡必须显示「评估数量」（当前只读强化的成功/失败/得分）。"""
    src = read('ui/run_tab.py')
    fn = _function_body(src, '_refresh_status')
    ok = bool(fn) and '评估数量' in fn
    return ok, 'run_tab._refresh_status 未引用 评估数量' if not ok else '已引用 评估数量'


def check_summary_split():
    """C4: 评估汇总必须按 verdict_cn 拆分「不合格 / 不建议强化」。"""
    src = read('ui/run_tab.py')
    fn = _function_body(src, '_update_eval_summary')
    ok = bool(fn) and 'verdict_cn' in fn
    return ok, 'run_tab._update_eval_summary 仍按 verdict 码合并' if not ok else '按 verdict_cn 拆分'


def check_report_contrast():
    """C5: 报告判定色对白底的对比度 ≥ 4.5（正文 14px）。"""
    src = read('ui/run_tab.py')
    m = re.search(r'VERDICT_COLOR\s*=\s*\{.*?\}', src, re.S)
    if not m:
        return False, '找不到 VERDICT_COLOR'
    colors = ast.literal_eval(m.group(0).split('=', 1)[1].strip())
    worst = min(colors.items(), key=lambda kv: contrast(kv[1], '#ffffff'))
    ratio = contrast(worst[1], '#ffffff')
    return ratio >= 4.5, f'最低 {worst[0]} {worst[1]} = {ratio:.2f}:1（需 ≥4.5）'


def _function_body(src: str, name: str) -> str:
    m = re.search(rf'^\s*def {re.escape(name)}\(', src, re.M)
    if not m:
        return ''
    start = m.start()
    nxt = re.search(r'^\s*def ', src[start + 1:], re.M)
    return src[start:start + 1 + nxt.start()] if nxt else src[start:]


CHECKS = (
    ('C1 SpinBox 数值可见', check_spin),
    ('C2 套装配置/调试页可滚', check_setconfig_scroll),
    ('C3 评估状态显示评估数量', check_eval_counters),
    ('C4 评估汇总按 verdict_cn 拆分', check_summary_split),
    ('C5 报告判定色对比度 ≥4.5', check_report_contrast),
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--strict', action='store_true', help='有 FAIL 时退出码 1（交接验收）')
    args = ap.parse_args()
    failed = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:                       # noqa: BLE001 - 诊断工具不该因单项炸掉
            ok, detail = False, f'{type(e).__name__}: {e}'
        print(f'[{"PASS" if ok else "FAIL"}] {name}: {detail}')
        failed += 0 if ok else 1
    print(f'\n{len(CHECKS) - failed}/{len(CHECKS)} 通过')
    return 1 if (args.strict and failed) else 0


if __name__ == '__main__':
    raise SystemExit(main())
