#!/usr/bin/env python3
r"""界面缺陷探针（2026-11-22 评审的交接工具）：把几个"看不见但能量出来"的问题变成可执行检查。

输入:
  - 源码 `ui/present.py`（C5 静态读配色表）
  - 离屏 Qt（C1/C2 运行检查：SpinBox 的 LineEdit 几何 + 抓图像素）
  - 纯函数直调（C3/C4 喂假数据看输出, 不 grep 源码）
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


_APP = None


def _qapp():
    """全进程共用一个 QApplication（并注册中文字体）。

    **坑（2026-11-22）**: 每项检查各自 `QApplication.instance() or QApplication([])` 并把实例存在
    局部变量里 —— 函数返回后 Python 侧引用没了, 销毁时机就落到解释器退出期, 与仍存活的顶层窗口
    抢顺序 → **段错误 0xC0000005**（实测 6 次里 4 次）。所以: 实例挂模块级; 检查用完的窗口主动
    `deleteLater()` + `processEvents()`, 走 Qt 自己的销毁路径。
    """
    global _APP
    if _APP is None:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtGui import QFont, QFontDatabase
        from PySide6.QtWidgets import QApplication
        _APP = QApplication.instance() or QApplication([])
        for f in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/msyhbd.ttc'):
            if os.path.exists(f):
                QFontDatabase.addApplicationFont(f)
        _APP.setFont(QFont('Microsoft YaHei UI', 9))
    return _APP


def _pump(times=5):
    for _ in range(times):
        _qapp().processEvents()


def _drop(widget):
    """销毁顶层窗口（见 `_qapp` 的退出坑）。"""
    if widget is None:
        return
    widget.hide()
    widget.deleteLater()
    _pump(2)


def check_spin():
    """C1: 套装配置页的数值框必须真的画出数字。"""
    _qapp()
    from qfluentwidgets import DoubleSpinBox
    from ui.set_config_tab import SetConfigTab

    tab = SetConfigTab()
    tab.resize(1120, 760)
    tab.show()
    _pump()
    spins = tab.findChildren(DoubleSpinBox)
    if not spins:
        _drop(tab)
        return False, 'SetConfigTab 里找不到 DoubleSpinBox（控件被换掉了？）'
    narrow = [s for s in spins if s.lineEdit().width() < 20]
    # 更严的口径: 编辑区要放得下**当前文本**(两个 31px 按钮吃掉 71px, 控件 < ~105px 就会把 `0.10`
    # 显示成 `0.1` —— 宽度够 20px 也不代表读得出数值)
    clipped = [s for s in spins
               if s.lineEdit().width() < s.lineEdit().fontMetrics().horizontalAdvance(
                   s.lineEdit().text()) + 4]     # +4: 恰好等于文本宽度时仍会裁掉最后一两个字
    # 再取一个抓图，防"宽度对了但没画"（对比度/颜色问题）
    img = spins[0].grab().toImage()
    darkest = min(img.pixelColor(x, y).lightness()
                  for x in range(img.width()) for y in range(img.height()))
    first_width = spins[0].lineEdit().width()
    ok = not narrow and not clipped and darkest < 120
    _drop(tab)
    return ok, (f'{len(narrow)}/{len(spins)} 个 LineEdit 宽 < 20px'
                f'（首个 {first_width}px）, 文本被裁 {len(clipped)} 个, '
                f'首个抓图最暗像素 {darkest}')


def check_setconfig_scroll():
    """C2: 套装配置页在 892×570（940×620 窗口的内容区）必须能滚，而不是裁切。"""
    _qapp()
    from qfluentwidgets import SingleDirectionScrollArea
    from ui.set_config_tab import SetConfigTab

    tab = SetConfigTab()
    tab.resize(892, 570)
    tab.show()
    _pump()
    # 注意: QTableWidget 自己也是 QAbstractScrollArea, 不能拿它当"页面能滚"的证据 ——
    # 只认页面级滚动容器(项目统一用 SingleDirectionScrollArea)。
    areas = tab.findChildren(SingleDirectionScrollArea)
    debug_src = read('ui/debug_tab.py')
    debug_ok = 'SingleDirectionScrollArea' in debug_src or 'QScrollArea' in debug_src
    if not areas:
        _drop(tab)
        return False, 'SetConfigTab 没有页面级滚动容器（表格自身的滚动不算）'
    bar = areas[0].verticalScrollBar()
    ok = bar.maximum() > 0 and debug_ok
    detail = (f'SetConfigTab 页面滚动范围 {bar.maximum()}px，debug_tab '
              + ('有滚动容器' if debug_ok else '缺滚动容器'))
    _drop(tab)
    return ok, detail


def check_eval_counters():
    """C3: 评估状态卡必须显示「评估数量」（当前只读强化的成功/失败/得分）。

    这项**跑代码**而不是 grep 源码。两条理由:
    ① 旧的静态检查有个致命 bug（`_function_body` 从"行首+1"切片, 正则 `^\s*def` 在字符串开头
       就命中函数自己 → 返回 1 字符, 于是 C3/C4 **永远 FAIL**, 交接时"修完应 5/5"根本做不到）;
    ② grep 分不清"读了正确的键"和"读了别的键"。这里直接喂假 task 给 `status_texts` 看输出。
    """
    from ui.present import status_texts

    class _FakeTask(dict):
        def info_get(self, key, default=None):
            return self.get(key, default)

    # 故意把**强化**的键也填上, 用来证明评估模式没在偷读它们
    task = _FakeTask({'评估数量': 7, '评估失败': 2, '评估结束原因': '到达0级尾部',
                      '成功声骸数量': 99, '失败声骸数量': 88, '声骸得分': '1.00'})
    first, second, third = status_texts(task, True)
    if '7' not in first:
        return False, f'评估模式没显示「评估数量」(得到 {first!r})'
    if '99' in first or '99' in second:
        return False, f'评估模式仍在读强化的 成功声骸数量 (得到 {first!r} / {second!r})'
    if '2' not in second:
        return False, f'评估模式没显示「评估失败」(得到 {second!r})'
    if '到达0级尾部' not in third:
        return False, f'评估模式没显示结束原因(得到 {third!r})'
    # 强化口径必须保持原样(不能为了修评估把强化改坏)
    h_first, h_second, h_third = status_texts(task, False)
    if '成功: 99' not in h_first or '失败: 88' not in h_second or '得分: 1.00' not in h_third:
        return False, f'强化口径被改坏: {h_first!r} / {h_second!r} / {h_third!r}'
    return True, f'评估 → {first} / {second} / {third}；强化口径不变'


def check_summary_split():
    """C4: 评估汇总必须按 verdict_cn 拆分「不合格 / 不建议强化」。

    同样跑代码: 喂 2 达标 + 3 不合格 + 4 不建议强化 + 1 保留(词条缺失), 看汇总行是否六档分开
    （静态 grep 的老毛病见 C3 的说明）。
    """
    from ui.present import summary_text

    def rec(verdict, cn):
        return {'verdict': verdict, 'verdict_cn': cn}

    recs = ([rec('pass', '达标')] * 2 + [rec('fail', '不合格')] * 3
            + [rec('fail', '不建议强化')] * 4 + [rec('hold', '保留(词条缺失)')] * 1)
    text = summary_text(recs)
    for need in ('达标 2', '不合格 3', '不建议强化 4', '保留 1'):
        if need not in text:
            return False, f'汇总没按六档拆开(缺「{need}」): {text}'
    if '不合格 7' in text or '不建议强化 7' in text:
        return False, f'「不合格 / 不建议强化」又被合并了: {text}'
    return True, text


def check_report_contrast():
    """C5: 报告判定色对白底的对比度 ≥ 4.5（正文 14px）。"""
    src = read('ui/present.py')
    m = re.search(r'VERDICT_COLOR\s*=\s*\{.*?\}', src, re.S)
    if not m:
        return False, '找不到 VERDICT_COLOR'
    colors = ast.literal_eval(m.group(0).split('=', 1)[1].strip())
    worst = min(colors.items(), key=lambda kv: contrast(kv[1], '#ffffff'))
    ratio = contrast(worst[1], '#ffffff')
    return ratio >= 4.5, f'最低 {worst[0]} {worst[1]} = {ratio:.2f}:1（需 ≥4.5）'


_APP = None


def _qapp():
    """全进程共用一个 QApplication（并注册中文字体）。

    **坑（2026-11-22）**: 每项检查各自 `QApplication.instance() or QApplication([])` 并把实例存在
    局部变量里 —— 函数返回后 Python 侧引用没了, 销毁时机就落到解释器退出期, 与仍存活的顶层窗口
    抢顺序 → **段错误 0xC0000005**（实测 6 次里 4 次）。所以: 实例挂模块级; 检查用完的窗口主动
    `deleteLater()` + `processEvents()`, 走 Qt 自己的销毁路径。
    """
    global _APP
    if _APP is None:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtGui import QFont, QFontDatabase
        from PySide6.QtWidgets import QApplication
        _APP = QApplication.instance() or QApplication([])
        for f in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/msyhbd.ttc'):
            if os.path.exists(f):
                QFontDatabase.addApplicationFont(f)
        _APP.setFont(QFont('Microsoft YaHei UI', 9))
    return _APP


def _pump(times=5):
    for _ in range(times):
        _qapp().processEvents()


def _drop(widget):
    """销毁顶层窗口（见 `_qapp` 的退出坑）。"""
    if widget is None:
        return
    widget.hide()
    widget.deleteLater()
    _pump(2)


def check_spin():
    """C1: 套装配置页的数值框必须真的画出数字。"""
    _qapp()
    from qfluentwidgets import DoubleSpinBox
    from ui.set_config_tab import SetConfigTab

    tab = SetConfigTab()
    tab.resize(1120, 760)
    tab.show()
    _pump()
    spins = tab.findChildren(DoubleSpinBox)
    if not spins:
        _drop(tab)
        return False, 'SetConfigTab 里找不到 DoubleSpinBox（控件被换掉了？）'
    narrow = [s for s in spins if s.lineEdit().width() < 20]
    # 更严的口径: 编辑区要放得下**当前文本**(两个 31px 按钮吃掉 71px, 控件 < ~105px 就会把 `0.10`
    # 显示成 `0.1` —— 宽度够 20px 也不代表读得出数值)
    clipped = [s for s in spins
               if s.lineEdit().width() < s.lineEdit().fontMetrics().horizontalAdvance(
                   s.lineEdit().text()) + 4]     # +4: 恰好等于文本宽度时仍会裁掉最后一两个字
    # 再取一个抓图，防"宽度对了但没画"（对比度/颜色问题）
    img = spins[0].grab().toImage()
    darkest = min(img.pixelColor(x, y).lightness()
                  for x in range(img.width()) for y in range(img.height()))
    first_width = spins[0].lineEdit().width()
    ok = not narrow and not clipped and darkest < 120
    _drop(tab)
    return ok, (f'{len(narrow)}/{len(spins)} 个 LineEdit 宽 < 20px'
                f'（首个 {first_width}px）, 文本被裁 {len(clipped)} 个, '
                f'首个抓图最暗像素 {darkest}')


def check_setconfig_scroll():
    """C2: 套装配置页在 892×570（940×620 窗口的内容区）必须能滚，而不是裁切。"""
    _qapp()
    from qfluentwidgets import SingleDirectionScrollArea
    from ui.set_config_tab import SetConfigTab

    tab = SetConfigTab()
    tab.resize(892, 570)
    tab.show()
    _pump()
    # 注意: QTableWidget 自己也是 QAbstractScrollArea, 不能拿它当"页面能滚"的证据 ——
    # 只认页面级滚动容器(项目统一用 SingleDirectionScrollArea)。
    areas = tab.findChildren(SingleDirectionScrollArea)
    debug_src = read('ui/debug_tab.py')
    debug_ok = 'SingleDirectionScrollArea' in debug_src or 'QScrollArea' in debug_src
    if not areas:
        _drop(tab)
        return False, 'SetConfigTab 没有页面级滚动容器（表格自身的滚动不算）'
    bar = areas[0].verticalScrollBar()
    ok = bar.maximum() > 0 and debug_ok
    detail = (f'SetConfigTab 页面滚动范围 {bar.maximum()}px，debug_tab '
              + ('有滚动容器' if debug_ok else '缺滚动容器'))
    _drop(tab)
    return ok, detail


def check_eval_counters():
    """C3: 评估状态卡必须显示「评估数量」（当前只读强化的成功/失败/得分）。

    这项**跑代码**而不是 grep 源码。两条理由:
    ① 旧的静态检查有个致命 bug（`_function_body` 从"行首+1"切片, 正则 `^\s*def` 在字符串开头
       就命中函数自己 → 返回 1 字符, 于是 C3/C4 **永远 FAIL**, 交接时"修完应 5/5"根本做不到）;
    ② grep 分不清"读了正确的键"和"读了别的键"。这里直接喂假 task 给 `status_texts` 看输出。
    """
    from ui.present import status_texts

    class _FakeTask(dict):
        def info_get(self, key, default=None):
            return self.get(key, default)

    # 故意把**强化**的键也填上, 用来证明评估模式没在偷读它们
    task = _FakeTask({'评估数量': 7, '评估失败': 2, '评估结束原因': '到达0级尾部',
                      '成功声骸数量': 99, '失败声骸数量': 88, '声骸得分': '1.00'})
    first, second, third = status_texts(task, True)
    if '7' not in first:
        return False, f'评估模式没显示「评估数量」(得到 {first!r})'
    if '99' in first or '99' in second:
        return False, f'评估模式仍在读强化的 成功声骸数量 (得到 {first!r} / {second!r})'
    if '2' not in second:
        return False, f'评估模式没显示「评估失败」(得到 {second!r})'
    if '到达0级尾部' not in third:
        return False, f'评估模式没显示结束原因(得到 {third!r})'
    # 强化口径必须保持原样(不能为了修评估把强化改坏)
    h_first, h_second, h_third = status_texts(task, False)
    if '成功: 99' not in h_first or '失败: 88' not in h_second or '得分: 1.00' not in h_third:
        return False, f'强化口径被改坏: {h_first!r} / {h_second!r} / {h_third!r}'
    return True, f'评估 → {first} / {second} / {third}；强化口径不变'


def check_summary_split():
    """C4: 评估汇总必须按 verdict_cn 拆分「不合格 / 不建议强化」。

    同样跑代码: 喂 2 达标 + 3 不合格 + 4 不建议强化 + 1 保留(词条缺失), 看汇总行是否六档分开
    （静态 grep 的老毛病见 C3 的说明）。
    """
    from ui.present import summary_text

    def rec(verdict, cn):
        return {'verdict': verdict, 'verdict_cn': cn}

    recs = ([rec('pass', '达标')] * 2 + [rec('fail', '不合格')] * 3
            + [rec('fail', '不建议强化')] * 4 + [rec('hold', '保留(词条缺失)')] * 1)
    text = summary_text(recs)
    for need in ('达标 2', '不合格 3', '不建议强化 4', '保留 1'):
        if need not in text:
            return False, f'汇总没按六档拆开(缺「{need}」): {text}'
    if '不合格 7' in text or '不建议强化 7' in text:
        return False, f'「不合格 / 不建议强化」又被合并了: {text}'
    return True, text


def check_report_contrast():
    """C5: 报告判定色对白底的对比度 ≥ 4.5（正文 14px）。"""
    src = read('ui/present.py')
    m = re.search(r'VERDICT_COLOR\s*=\s*\{.*?\}', src, re.S)
    if not m:
        return False, '找不到 VERDICT_COLOR'
    colors = ast.literal_eval(m.group(0).split('=', 1)[1].strip())
    worst = min(colors.items(), key=lambda kv: contrast(kv[1], '#ffffff'))
    ratio = contrast(worst[1], '#ffffff')
    return ratio >= 4.5, f'最低 {worst[0]} {worst[1]} = {ratio:.2f}:1（需 ≥4.5）'


def _function_body(src: str, name: str) -> str:
    """取 `def <name>(...)` 到下一个 `def` 之前的源码（保留给以后需要看函数体的检查）。

    **坑（2026-11-22 修）**: 旧版写的是 `re.search(r'^\\s*def ', src[start + 1:], re.M)` ——
    切片从"行首 +1"开始, 于是新串的**第 0 个字符就是行首**, `^` 在字符串开头直接匹配,
    `\\s*` 吃掉剩下 3 个缩进、`def ` 命中 `def <name>` 自己 → 返回长度 1 的残片。
    结果 C3/C4 这两项**永远 FAIL**, 无论代码怎么改（交接时"修完应 5/5"做不到的根因）。
    现在: 从 `m.end()` 往后找, 并且缩进只认空格/制表符（`\\s` 会跨行匹配到下一个 def）。
    """
    m = re.search(rf'^[ \t]*def {re.escape(name)}\(', src, re.M)
    if not m:
        return ''
    nxt = re.search(r'^[ \t]*def ', src[m.end():], re.M)
    return src[m.start():m.end() + nxt.start()] if nxt else src[m.start():]


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
