"""`src/echo_grid.py` 的单测：角标合并 + 等间距推断。

背景（2026-11-14 真机实测）：小窗口下 `+25` OCR 单次只检出 5~14/30 个，还会拆成 `+` 与 `25`；
`scan_grid` 因此漏行漏列、点到隔壁格。这里覆盖修复用的纯几何逻辑，不依赖游戏。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import echo_grid  # noqa: E402


class TestMergeBadgeMarks(unittest.TestCase):

    def test_merges_split_plus_and_digits(self):
        # OCR 把 +25 拆成 '+' 与 '25' 两个框（实测小窗口常见）
        texts = [('+', 100, 200, 10, 10), ('25', 111, 201, 14, 10)]
        marks = echo_grid.merge_badge_marks(texts)
        self.assertEqual(len(marks), 1)
        cx, cy = marks[0]
        self.assertTrue(108 <= cx <= 116, msg=f'合并后中心应在 + 与 25 之间: {cx}')
        self.assertTrue(203 <= cy <= 208, msg=f'合并后 y 应与两框一致: {cy}')

    def test_full_badge_and_dedup_across_two_ocr_passes(self):
        # 两路 OCR 对同一个角标各报一次（坐标差 2px）→ 只留一个
        texts = [('+25', 400, 300, 24, 12), ('+25', 402, 301, 24, 12)]
        self.assertEqual(len(echo_grid.merge_badge_marks(texts)), 1)

    def test_roi_filters_detail_panel_badge(self):
        # 右侧详情面板自己的 +25（x=871/1254≈0.695）不能当成网格格子
        texts = [('+25', 179, 740, 26, 14), ('+25', 871, 130, 39, 18)]
        marks = echo_grid.merge_badge_marks(texts, roi=(94, 89, 821, 800))
        self.assertEqual(marks, [(192, 747)])

    def test_ignores_non_badge_text(self):
        texts = [('声骸202/3000', 20, 30, 120, 20), ('COST', 850, 240, 40, 16),
                 ('+25', 300, 500, 24, 12)]
        self.assertEqual(len(echo_grid.merge_badge_marks(texts)), 1)


class TestCellsFromMarks(unittest.TestCase):
    """用 1254x889 实测的角标坐标（裁剪 OCR 的残缺结果）还原完整网格。"""

    def test_restores_six_columns_and_five_rows(self):
        # 裁剪 OCR 实测只给出 3 列 × 3 行（共 9 个角标），见文档 §6.6 / CHANGELOG 补记 31
        marks = []
        for y in (332, 471, 609):
            for x in (421, 535, 650):
                marks.append((x, y))
        cells = echo_grid.cells_from_marks(
            marks, (94, 89, 821, 800), row_tol=26.7, col_gap=57.7)
        xs = sorted({x for x, _ in cells})
        ys = sorted({y for _, y in cells})
        self.assertEqual(len(xs), 6, msg=f'应补全为 6 列: {xs}')
        self.assertEqual(len(ys), 5, msg=f'应补全为 5 行: {ys}')
        self.assertEqual(len(cells), 30)
        # 行优先排序：第一格在最上一行的最左列
        self.assertEqual(cells[0], (min(xs), min(ys)))
        self.assertEqual(cells[-1], (max(xs), max(ys)))
        # 外推不能越过表头/底部按钮
        self.assertGreaterEqual(min(ys), 89)
        self.assertLessEqual(max(ys), 800)

    def test_single_row_uses_pitch_hint(self):
        # 本屏只剩 1 行角标：沿用上一屏的行距推断出 5 行，而不是只点 1 行
        marks = [(193, 600), (307, 600), (421, 600), (535, 600), (650, 600), (764, 600)]
        cells = echo_grid.cells_from_marks(
            marks, (94, 89, 821, 800), row_tol=26.7, col_gap=57.7,
            row_pitch_hint=138.0)
        ys = sorted({y for _, y in cells})
        self.assertEqual(len(ys), 5, msg=f'应补全 5 行: {ys}')
        self.assertEqual(len(cells), 30)

    def test_no_marks(self):
        self.assertEqual(echo_grid.cells_from_marks([], (0, 0, 100, 100), 20, 50), [])

    def test_axis_pitch(self):
        self.assertAlmostEqual(echo_grid.axis_pitch([190, 305, 420, 535]) or 0, 115.0)
        self.assertIsNone(echo_grid.axis_pitch([190]))
        self.assertIsNone(echo_grid.axis_pitch([]))


class TestGridStructure(unittest.TestCase):
    """结构标定：等级条顶边 → 行，金色亮段 → 列（不识别任何文字）。"""

    @staticmethod
    def _synthetic():
        import cv2
        import numpy as np
        img = np.full((889, 1254, 3), 20, np.uint8)
        for k in range(5):
            y = 184 + 138 * k
            for c in range(6):
                x = 117 + 115 * c
                # 卡片高度 ~1 行距的 0.8, 下方留深色间隙（真机就是这么排的, 点击偏移靠它判卡片侧）
                cv2.rectangle(img, (x, y - 107), (x + 110, y + 2), (90, 90, 90), -1)
                cv2.line(img, (x + 4, y), (x + 106, y), (0, 190, 255), 3)   # 金色条顶线
                cv2.putText(img, '+25', (x + 55, y + 13), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (240, 240, 240), 1)
        return img

    def test_detects_six_columns_five_rows(self):
        st = echo_grid.detect_grid_structure(self._synthetic(), (100, 89, 820, 800))
        self.assertIsNotNone(st, msg='合成网格应能被结构标定')
        self.assertEqual(len(st['rows']), 5, msg=f'rows={st["rows"]}')
        self.assertEqual(len(st['cols']), 6, msg=f'cols={st["cols"]}')
        self.assertAlmostEqual(st['row_pitch'], 138, delta=4)
        cells = echo_grid.cells_from_structure(st)
        self.assertEqual(len(cells), 30)
        # 行优先; 点击偏移 = 标定给出的"卡片侧"(这帧卡片在行线上方 → 负偏移)
        self.assertEqual(cells[0], (st['cols'][0], st['rows'][0] + st['row_pitch'] * st['click_dy']))
        self.assertLess(st['click_dy'], 0)

    def test_blank_frame_returns_none(self):
        import numpy as np
        img = np.full((889, 1254, 3), 20, np.uint8)
        self.assertIsNone(echo_grid.detect_grid_structure(img, (100, 89, 820, 800)))

    def test_cells_from_structure_click_offset(self):
        st = {'rows': [184.0, 322.0], 'cols': [163.0, 278.0], 'row_pitch': 138.0}
        cells = echo_grid.cells_from_structure(st)
        self.assertEqual(cells[0], (163.0, 184.0 + 138.0 * 0.08))
        self.assertEqual(len(cells), 4)

    def test_truncated_edge_column_is_recovered(self):
        """ROI 切到第一格金条中间：那个半截段不能当列中心(偏 34px), 但必须把整列补回来。

        真机 7 列视图实测: 第一格金条只剩 (94,115)、中心 104.5, 真值 70.5;
        旧实现把它当列中心 → 整行列点偏三分之一列距(点选未切换), 且第一列永远点不到。
        """
        import cv2
        import numpy as np
        img = np.full((889, 1254, 3), 20, np.uint8)
        centers = [70.5 + 112.5 * c for c in range(7)]
        for k in range(5):
            y = 200 + 135 * k
            for cx in centers:
                x = int(cx - 46)
                cv2.rectangle(img, (x, y - 105), (x + 92, y + 6), (90, 90, 90), -1)
                cv2.line(img, (x + 2, y), (x + 90, y), (0, 190, 255), 3)
        st = echo_grid.detect_grid_structure(img, (94, 89, 821, 800))
        self.assertIsNotNone(st)
        self.assertEqual(len(st['cols']), 7, msg=f'cols={st["cols"]}')
        self.assertAlmostEqual(st['cols'][0], 70.5, delta=3.0)
        self.assertAlmostEqual(st['cols'][-1], 745.5, delta=3.0)


class TestLatticeFit(unittest.TestCase):
    """等间距拟合：个别列偏了不能把整行列距/锚点带偏（端点法的老坑）。"""

    def test_drops_outlier_and_keeps_spacing(self):
        # 真机 7 列帧实测: 第一个金段贴在 ROI 边界, 中心偏 34px
        anchor, pitch, grid = echo_grid.fit_lattice(
            [104.5, 183.5, 296.5, 409.0, 521.4, 634.5, 747.0])
        self.assertIsNotNone(anchor)
        self.assertAlmostEqual(pitch, 112.7, delta=1.0)
        self.assertEqual(len(grid), 6)                 # 离群列被剔掉
        self.assertAlmostEqual(grid[0], 183.5, delta=1.0)
        self.assertAlmostEqual(grid[-1], 747.0, delta=1.0)

    def test_fills_interior_gap(self):
        # 中间漏检一列(金线被图标挡掉) → 用格点补回, 不能整列消失
        _, pitch, grid = echo_grid.fit_lattice([163.0, 278.0, 508.5, 623.5, 739.0])
        self.assertEqual(len(grid), 6)
        self.assertAlmostEqual(grid[2], 393.5, delta=2.0)

    def test_too_few_columns(self):
        anchor, pitch, grid = echo_grid.fit_lattice([100.0, 200.0])
        self.assertIsNone(anchor)
        self.assertEqual(len(grid), 2)


class TestGridModel(unittest.TestCase):
    """布局模型：比例（列距/行距/首列）与位置（每屏行线）分离。"""

    STRUCT = {
        'rows': [184.0, 322.0, 460.0, 598.0, 736.0],
        'cols': [163.0, 278.0, 393.5, 508.5, 623.5, 739.0],
        'row_pitch': 138.0,
    }

    def test_model_from_structure_reproduces_cells(self):
        m = echo_grid.GridModel.from_structure(self.STRUCT, 1254.0)
        self.assertIsNotNone(m)
        self.assertEqual(m.cols, 6)
        for got, want in zip(m.col_centers(1254.0), self.STRUCT['cols']):
            self.assertAlmostEqual(got, want, delta=0.8)
        cells = m.cells(1254.0, self.STRUCT['rows'])
        self.assertEqual(len(cells), 30)
        self.assertAlmostEqual(cells[0][1], 184.0 + 138.0 * 0.08, delta=0.3)

    def test_matches_pitch(self):
        m = echo_grid.GridModel.from_structure(self.STRUCT, 1254.0)
        self.assertTrue(m.matches(138.0, 1254.0))
        self.assertTrue(m.matches(145.0, 1254.0))      # +5% 仍在容差内
        self.assertFalse(m.matches(100.0, 1254.0))     # 间距突变 → 模型失效

    def test_model_survives_scroll_shift(self):
        # 滚动 120px 后行线整体下移/上移，列布局与行距不变 → 模型给出的格点跟着行走
        m = echo_grid.GridModel.from_structure(self.STRUCT, 1254.0)
        shifted = [y - 120.0 for y in self.STRUCT['rows']]
        cells = m.cells(1254.0, shifted)
        self.assertEqual(len(cells), 30)
        self.assertAlmostEqual(cells[0][1], shifted[0] + 138.0 * 0.08, delta=0.3)

    def test_detect_row_lines_synthetic(self):
        img = TestGridStructure._synthetic()
        rows, pitch = echo_grid.detect_row_lines(img, (100, 89, 820, 800))
        self.assertEqual(len(rows), 5, msg=f'rows={rows}')
        self.assertAlmostEqual(pitch or 0, 138, delta=4)


class TestRowShift(unittest.TestCase):
    """滚轮位移测量：按已知行距估"滚了几行"（用于自适应滚动距离）。"""

    PITCH = 138.0

    @staticmethod
    def _frame():
        import cv2
        import numpy as np
        img = np.full((889, 1254, 3), 20, np.uint8)
        for k in range(5):
            y = 184 + 138 * k
            for c in range(6):
                x = 117 + 115 * c
                # 每行不同灰度 + 随机斑点，保证跨行可区分
                gray = 60 + 25 * k
                cv2.rectangle(img, (x, y - 120), (x + 110, y + 16), (gray, gray, gray), -1)
                cv2.circle(img, (x + 40 + 8 * k, y - 60), 12, (200, 200, 200), -1)
        return img

    @staticmethod
    def _shift(img, dy):
        import cv2
        import numpy as np
        m = np.float32([[1, 0, 0], [0, 1, dy]])
        return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)

    def test_exact_rows(self):
        f = self._frame()
        for k in (0, 1, 2, 3, 4):
            rows, diff = echo_grid.estimate_row_shift(f, self._shift(f, -self.PITCH * k),
                                                      (100, 89, 820, 800), self.PITCH)
            self.assertAlmostEqual(rows, k, delta=0.25, msg=f'k={k} got rows={rows} diff={diff}')

    def test_sub_row(self):
        f = self._frame()
        rows, _ = echo_grid.estimate_row_shift(f, self._shift(f, -self.PITCH * 0.5),
                                               (100, 89, 820, 800), self.PITCH)
        self.assertAlmostEqual(rows, 0.5, delta=0.25)

    def test_no_shift(self):
        f = self._frame()
        rows, diff = echo_grid.estimate_row_shift(f, f.copy(), (100, 89, 820, 800), self.PITCH)
        self.assertAlmostEqual(rows, 0.0, delta=0.05)
        self.assertLess(diff, 1.0)

    def test_five_rows_measurable(self):
        """5 行位移必须能量出来（旧实现把搜索范围限在"高-80"，711px 视口只到 4 行 →
        真机兜底滚屏走 5~6 行时估出 0，被当成"滚动受阻"又叠一次输入）。

        注：视口 711px、行距 138 → 6 行只剩 3px 重叠，**物理上无法用对齐测量**
        （真实滚动也不该一次走 6 行：拖拽兜底已限到 2.5 行）。超过 5 行由调用方用
        `frame_change_ratio` 判"动了但量不出"，不再叠加输入。
        """
        import numpy as np
        rng = np.random.RandomState(7)
        canvas = rng.randint(0, 255, (889 + 6 * 138, 1254, 3), dtype=np.uint8)
        before = canvas[:889]
        for k in (3, 4, 5):
            after = canvas[k * 138:k * 138 + 889]
            rows, diff = echo_grid.estimate_row_shift(before, after, (100, 89, 820, 800), self.PITCH)
            self.assertAlmostEqual(rows, float(k), delta=0.35, msg=f'k={k} rows={rows} diff={diff}')


class TestFrameChange(unittest.TestCase):
    """画面变化占比：不依赖对齐，用来判"到底动没动"。"""

    RECT = (100, 89, 820, 800)

    def test_identical(self):
        f = TestRowShift._frame()
        self.assertLess(echo_grid.frame_change_ratio(f, f.copy(), self.RECT), 0.01)

    def test_scroll_changes_most_pixels(self):
        f = TestRowShift._frame()
        after = TestRowShift._shift(f, -138.0)
        # 合成帧的整行灰阶只差 25（正好压在默认阈值上），这里用 10 只验证"位移会让大半区域变"
        self.assertGreater(echo_grid.frame_change_ratio(f, after, self.RECT, thresh=10), 0.35)

    def test_small_hover_change(self):
        import cv2
        f = TestRowShift._frame()
        after = f.copy()
        cv2.rectangle(after, (130, 100), (210, 170), (250, 250, 250), -1)   # 一格高光
        self.assertLess(echo_grid.frame_change_ratio(f, after, self.RECT), 0.12)


class TestScrollModel(unittest.TestCase):
    """滚轮距离模型：距离来自布局(行距)与实测 px/格，而不是猜 notches。"""

    def test_notches_from_layout(self):
        # 8px/格 是 1920 宽帧的实测值; 552px/8 = 69 格, 不该再被 40 截断(截断=只滚 2.3 行)
        m = echo_grid.ScrollModel(frame_width=1920.0)
        self.assertAlmostEqual(m.px_per_notch, 8.0, delta=0.01)
        self.assertEqual(m.notches_for(4, 138.0), 69)
        m2 = echo_grid.ScrollModel(px_per_notch=35.0)
        self.assertEqual(m2.notches_for(4, 138.0), 16)   # 552/35 ≈ 15.8 → 向上取整 16
        m3 = echo_grid.ScrollModel(px_per_notch=35.0, min_notches=1, max_notches=100)
        self.assertLessEqual(m3.notches_for(1, 138.0), 4)

    def test_px_per_notch_does_not_scale(self):
        """px/格 不随窗口缩放（真机 1254 帧实测 8.2~10.4，与 1920 帧的 8.0 一致）。

        曾按 `8.0 × 帧宽/1920` 缩放成 5.2 → 3 行的距离算成 80 格、实际滚 5~6 行 → 整行被跳过。
        """
        m = echo_grid.ScrollModel(frame_width=1254.0)
        self.assertAlmostEqual(m.px_per_notch, 8.0, delta=0.01)
        self.assertEqual(m.notches_for(3, 138.0), 52)      # 414px / 8 = 51.75 → 52

    def test_observe_updates_px_per_notch(self):
        m = echo_grid.ScrollModel(px_per_notch=8.0)
        m.observe(15, 15 * 30.0, weight=1.0)   # 实测 30px/格
        self.assertAlmostEqual(m.px_per_notch, 30.0, delta=0.1)
        # 距离随之收敛到 4 行所需格数（向上取整: 552/30 = 18.4 → 19）
        self.assertEqual(m.notches_for(4, 138.0), 19)

    def test_observe_ignores_no_move(self):
        m = echo_grid.ScrollModel(px_per_notch=12.0)
        m.observe(15, 0.5)
        self.assertAlmostEqual(m.px_per_notch, 12.0)


class TestRowShiftByLines(unittest.TestCase):
    """开局滚动标定用的**行线位移**(2026-11-19): 图像相关在这台机器上残差 27~34 永远不可信,
    px/格 学不到 → 每次请求 2 行实际滚 3~4 行, 整行被跳过(43/146)。行线是结构信号, 小位移(<1 行距)
    没有周期歧义, 用来量 6 格小步最稳。"""

    PITCH = 138
    RECT = (100, 89, 820, 800)

    def _frame(self):
        import cv2
        import numpy as np
        img = np.full((889, 1254, 3), 20, np.uint8)
        for k in range(5):
            y = 184 + 138 * k
            for c in range(6):
                x = 117 + 115 * c
                cv2.rectangle(img, (x, y - 107), (x + 110, y + 2), (90, 90, 90), -1)
                cv2.line(img, (x + 4, y), (x + 106, y), (0, 190, 255), 3)
        return img

    def _shift(self, img, dy):
        import cv2
        import numpy as np
        m = np.float32([[1, 0, 0], [0, 1, dy]])
        return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)

    def test_small_shifts_resolve(self):
        f = self._frame()
        # 只测 <1 个行距: 位移正好 1 行距时行线自相似(周期歧义), 本来就量不出来 ——
        # 标定只用 6 格小步(实测 0.3~0.6 行), 不会踩到这个区间。
        for frac in (0.2, 0.4, 0.6, 0.8):
            with self.subTest(frac=frac):
                rows, cost = echo_grid.row_shift_by_lines(
                    f, self._shift(f, -int(self.PITCH * frac)), self.RECT, self.PITCH, max_rows=1.2)
                self.assertAlmostEqual(rows, frac, delta=0.06)
                self.assertLess(cost, 6.0, msg='行线应能干净对齐')

    def test_no_move(self):
        f = self._frame()
        rows, cost = echo_grid.row_shift_by_lines(f, f, self.RECT, self.PITCH)
        self.assertAlmostEqual(rows, 0.0, delta=0.05)

    def test_blank_frames_are_untrusted(self):
        import numpy as np
        blank = np.zeros((889, 1254, 3), np.uint8)
        rows, cost = echo_grid.row_shift_by_lines(blank, blank, self.RECT, self.PITCH)
        self.assertGreaterEqual(cost, 6.0, msg='没有行线时必须判"不可信", 不能给 0 行')


class TestScrollModelGuard(unittest.TestCase):
    def test_garbage_measurement_is_clamped(self):
        """42 格只量到 32px(≈0.76 px/格)显然是错测 —— 不能让它把 px/格 拉到 1,
        否则 notches_for 会顶到上限(160), 一屏滚到底。"""
        m = echo_grid.ScrollModel(px_per_notch=8.0)
        m.observe(42, 32)
        self.assertGreaterEqual(m.px_per_notch, 4.0)

    def test_calibrated_distance(self):
        m = echo_grid.ScrollModel(px_per_notch=15.0)
        # 2 行 × 159px ÷ 15 ≈ 21 格(默认 8px/格 会算成 40 格, 实际滚出 4 行)
        self.assertAlmostEqual(m.notches_for(2.0, 159.0), 21, delta=2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
