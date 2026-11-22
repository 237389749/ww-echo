"""界面回归守卫（U-01 / U-02 / U-03 / U-04 / U-11）—— 不需要游戏, 不需要真窗口。

跑法(项目根目录):
    python -m unittest tests.test_ui_guards -v

为什么要有这个文件: `tools/ui_probe.py` 是**交接验收**用的探针(C1~C5), 但它不跑在单测里;
这里的断言是同一批缺陷的**长期回归守卫** —— 谁把 SpinBox 换回库里的原版、把页面滚动容器删掉、
或者让评估状态卡改回读强化计数, 单测立刻红。

**离屏 + 退出坑**: 本机实测 —— 进程里 `import ww_engine` 且 `show()` 过 Fluent 顶层窗口时,
解释器退出会段错误(0xC0000005)。单测套件里 `test_engine_lazy` 会 import ww_engine, 所以这里的
窗口**必须**在 tearDown 里 `deleteLater()` + `processEvents()` 走 Qt 自己的销毁路径(实测有效)。
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")     # 无显示器也能跑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.present import (VERDICT_CHIP_BG, VERDICT_COLOR, count_verdicts,  # noqa: E402
                        status_texts, summary_text, verdict_color)

_app = None


def _qapp():
    """全进程共用一个 QApplication（重复创建会崩）。"""
    global _app
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    from PySide6.QtGui import QFont, QFontDatabase
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"):
        if os.path.exists(f):
            QFontDatabase.addApplicationFont(f)
    _app.setFont(QFont("Microsoft YaHei UI", 9))
    return _app


def _pump(app, times=5):
    for _ in range(times):
        app.processEvents()


def _drop(widget, app):
    """销毁顶层窗口（见模块 docstring 的退出坑）。"""
    if widget is None:
        return
    widget.hide()
    widget.deleteLater()
    _pump(app, 2)


def _contrast(fg: str, bg: str) -> float:
    def lum(hex_color: str) -> float:
        r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))

        def f(v):
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    a, b = lum(fg), lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


class TestSpinBoxVisible(unittest.TestCase):
    """U-01: 套装配置页所有数值框必须真的画出数字（不是只有上下箭头）。"""

    def setUp(self):
        self.app = _qapp()
        from ui.set_config_tab import SetConfigTab
        self.tab = SetConfigTab()
        self.tab.resize(1120, 760)
        self.tab.show()
        _pump(self.app)

    def tearDown(self):
        _drop(self.tab, self.app)

    def test_line_edit_has_room(self):
        """qfluentwidgets 1.11.3 + PySide6 6.12 的 lineEdit 会被压成 1px → 数字一个像素都画不出来。"""
        from qfluentwidgets import DoubleSpinBox
        spins = self.tab.findChildren(DoubleSpinBox)
        self.assertTrue(spins, "SetConfigTab 里找不到 DoubleSpinBox（控件被换掉了？）")
        narrow = [(i, s.lineEdit().width()) for i, s in enumerate(spins) if s.lineEdit().width() < 20]
        self.assertEqual(narrow, [], f"这些数值框的编辑区太窄, 看不见数字: {narrow}")

    def test_value_is_painted(self):
        """宽度对了还不够 —— 抓图里要有比箭头更深的像素（= 文字真的画出来了）。"""
        from qfluentwidgets import DoubleSpinBox
        spin = self.tab.findChildren(DoubleSpinBox)[0]
        self.assertTrue(spin.lineEdit().text(), "数值框没有文本")
        img = spin.grab().toImage()
        darkest = min(img.pixelColor(x, y).lightness()
                      for x in range(img.width()) for y in range(img.height()))
        self.assertLess(darkest, 120, f"抓图最暗像素 {darkest} —— 只有箭头、没有文字")

    def test_text_actually_fits(self):
        """比"宽度 ≥ 20px"更严的口径: 编辑区放得下当前文本（否则显示成 `0.1` 这种截断值）。

        两个 31px 的上下按钮要吃掉 71px, 所以控件宽度 < ~105px 就装不下 `0.10`。
        """
        from qfluentwidgets import DoubleSpinBox
        clipped = []
        for spin in self.tab.findChildren(DoubleSpinBox):
            edit = spin.lineEdit()
            need = edit.fontMetrics().horizontalAdvance(edit.text())
            if edit.width() < need + 4:      # +4: 恰好等于文本宽度时仍会裁掉最后一两个字
                clipped.append((spin.width(), edit.width(), edit.text(), need))
        self.assertEqual(clipped, [], f"这些数值框把文本裁掉了 (控件宽, 编辑区宽, 文本, 需要): {clipped}")


class TestPageScrolls(unittest.TestCase):
    """U-02: 940×620 最小窗口下, 套装配置页整页可滚（内容 892×570 时不能互相压叠）。"""

    def setUp(self):
        self.app = _qapp()
        from ui.set_config_tab import SetConfigTab
        self.tab = SetConfigTab()
        self.tab.resize(892, 570)          # = 940×620 窗口的内容区
        self.tab.show()
        _pump(self.app)

    def tearDown(self):
        _drop(self.tab, self.app)

    def test_has_page_level_scroll_area(self):
        """只认页面级滚动容器: QTableWidget 自己也是 QAbstractScrollArea, 不能算证据。"""
        from qfluentwidgets import SingleDirectionScrollArea
        areas = self.tab.findChildren(SingleDirectionScrollArea)
        self.assertTrue(areas, "SetConfigTab 没有页面级滚动容器（表格自身的滚动不算）")
        self.assertGreater(areas[0].verticalScrollBar().maximum(), 0,
                           "892×570 下页面滚不动 —— 内容还是被压叠/裁切")

    def test_table_has_min_height(self):
        """表格要有最小高度（内部滚动）, 不能跟固定高度的卡片抢空间。"""
        self.assertGreaterEqual(self.tab.table.minimumHeight(), 200)


class TestPlanTabSpinBoxes(unittest.TestCase):
    """U-01 的另一半: 「组合穷举」页 30 个数值框（门槛/补正/条件补正/裸面板）也要放得下文本。"""

    def setUp(self):
        self.app = _qapp()
        from ui.plan_tab import PlanTab
        self.tab = PlanTab()

    def tearDown(self):
        _drop(self.tab, self.app)

    def test_text_fits_at_both_sizes(self):
        from qfluentwidgets import DoubleSpinBox, SpinBox
        for size in ((1120, 760), (940, 620)):
            self.tab.resize(*size)
            self.tab.show()
            _pump(self.app)
            clipped = []
            for spin in self.tab.findChildren(DoubleSpinBox) + self.tab.findChildren(SpinBox):
                edit = spin.lineEdit()
                need = edit.fontMetrics().horizontalAdvance(edit.text())
                if edit.width() < need + 4:
                    clipped.append((size, spin.width(), edit.width(), edit.text(), need))
            self.assertEqual(clipped, [], f"数值框把文本裁掉了 (窗口, 控件宽, 编辑区宽, 文本, 需要): {clipped}")


class TestDebugTabLayout(unittest.TestCase):
    """U-02 的另一半: 「调试工具」页在 892×570 下日志卡必须真的看得见。

    以前整页没有滚动容器、且 `QStackedWidget` 按**最高**子页(截图页预览图)预留高度 ——
    620 高窗口下日志只剩 60px 并被裁掉。
    """

    def setUp(self):
        self.app = _qapp()
        from PySide6.QtWidgets import QTextEdit
        from ui.debug_tab import DebugTab
        self.log = QTextEdit()
        self.log.setPlainText("\n".join(f"第 {i} 行" for i in range(30)))
        self.tab = DebugTab(self.log)
        self.tab.resize(892, 570)
        self.tab.show()
        _pump(self.app)

    def tearDown(self):
        _drop(self.tab, self.app)

    def test_log_card_visible_without_scrolling(self):
        card = self.tab.log_card
        self.assertLessEqual(card.geometry().bottom(), self.tab.height(),
                             "892×570 下日志卡被顶到视口外面（要滚才能看见）")
        self.assertGreaterEqual(card.height(), 200, "日志卡太矮，看不到几行")

    def test_stack_follows_current_subpage(self):
        """子页高度跟着当前页走（不按最高子页预留，否则中间空一大片）。"""
        self.tab.segmented.setCurrentItem("ocr")
        _pump(self.app, 2)
        ocr_h = self.tab.stack.height()
        self.tab.segmented.setCurrentItem("shot")
        _pump(self.app, 2)
        self.assertGreater(self.tab.stack.height(), ocr_h, "切到「截图」页后子页没长高")


class TestStatusTexts(unittest.TestCase):
    """U-03: 评估状态卡显示评估链的计数, 强化口径不能被改坏。"""

    class _FakeTask(dict):
        def info_get(self, key, default=None):
            return self.get(key, default)

    def _task(self):
        # 强化的键故意填上 —— 评估模式绝不能偷读它们
        return self._FakeTask({'评估数量': 7, '评估失败': 2, '评估结束原因': '到达0级尾部',
                               '成功声骸数量': 99, '失败声骸数量': 88, '声骸得分': '1.00'})

    def test_eval_mode_reads_eval_keys(self):
        first, second, third = status_texts(self._task(), True)
        self.assertEqual(first, "已记录: 7")
        self.assertEqual(second, "失败: 2")
        self.assertIn("到达0级尾部", third)

    def test_eval_mode_without_reason_has_empty_third(self):
        task = self._FakeTask({'评估数量': 0, '评估失败': 0})
        self.assertEqual(status_texts(task, True), ("已记录: 0", "失败: 0", ""))

    def test_enhance_mode_unchanged(self):
        first, second, third = status_texts(self._task(), False)
        self.assertEqual((first, second, third), ("成功: 99", "失败: 88", "得分: 1.00"))

    def test_enhance_mode_without_score(self):
        task = self._FakeTask({'成功声骸数量': 1})
        self.assertEqual(status_texts(task, False)[2], "得分: -")


class TestVerdictCounting(unittest.TestCase):
    """U-04: 汇总与报告按 verdict_cn 拆六档（`fail` 一个码里装了两档）。"""

    @staticmethod
    def _rec(verdict, cn):
        return {"verdict": verdict, "verdict_cn": cn}

    def test_fail_splits_into_two_levels(self):
        recs = ([self._rec("pass", "达标")] * 2 + [self._rec("fail", "不合格")] * 3
                + [self._rec("fail", "不建议强化")] * 4
                + [self._rec("hold", "保留(词条缺失)")] * 1)
        counts = count_verdicts(recs)
        self.assertEqual(counts["达标"], 2)
        self.assertEqual(counts["不合格"], 3)
        self.assertEqual(counts["不建议强化"], 4)
        self.assertEqual(counts["保留"], 1, "「保留(词条缺失)」要并进保留")

    def test_summary_text_order_and_zero_hidden(self):
        recs = [self._rec("fail", "不建议强化"), self._rec("pass", "达标")]
        text = summary_text(recs)
        self.assertEqual(text, "2 只 · 达标 1 · 不建议强化 1")
        self.assertNotIn("不合格 0", text, "数量为 0 的档位不该显示")
        self.assertLess(text.index("达标"), text.index("不建议强化"), "顺序要固定为六档顺序")

    def test_old_report_falls_back_to_code(self):
        """旧报告没有 verdict_cn: 只能按码归类（fail 归到未满级那档）。"""
        recs = [{"verdict": "pass"}, {"verdict": "fail"}, {"verdict": "zero"}]
        counts = count_verdicts(recs)
        self.assertEqual((counts["达标"], counts["不建议强化"]), (1, 1))
        self.assertEqual(sum(counts.values()), 2, "zero 不该被计数")


class TestVerdictColors(unittest.TestCase):
    """U-11: 判定色对白底 ≥4.5:1（14px 正文）, 且摘要 chips 的前/背景也要够。"""

    def test_row_text_contrast(self):
        worst = min(VERDICT_COLOR.items(), key=lambda kv: _contrast(kv[1], "#ffffff"))
        self.assertGreaterEqual(_contrast(worst[1], "#ffffff"), 4.5,
                                f"判定色 {worst[0]} {worst[1]} 对比度不足")

    def test_chip_contrast(self):
        for name, fg in VERDICT_COLOR.items():
            bg = VERDICT_CHIP_BG.get(name)
            if bg is None:
                continue
            self.assertGreaterEqual(_contrast(fg, bg), 4.5,
                                    f"摘要 chip「{name}」{fg} on {bg} 对比度不足")

    def test_color_uses_chinese_level(self):
        """fail 的两档必须能分出颜色（按 verdict 码配色是分不开的）。"""
        self.assertNotEqual(verdict_color("不合格", "fail"), verdict_color("不建议强化", "fail"))
        self.assertEqual(verdict_color("保留(词条缺失)", "hold"), VERDICT_COLOR["保留"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
