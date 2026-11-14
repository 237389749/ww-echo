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
                cv2.rectangle(img, (x, y - 125), (x + 110, y + 16), (90, 90, 90), -1)
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
        # 行优先
        self.assertEqual(cells[0], (st['cols'][0], st['rows'][0] + st['row_pitch'] * 0.08))

    def test_blank_frame_returns_none(self):
        import numpy as np
        img = np.full((889, 1254, 3), 20, np.uint8)
        self.assertIsNone(echo_grid.detect_grid_structure(img, (100, 89, 820, 800)))

    def test_cells_from_structure_click_offset(self):
        st = {'rows': [184.0, 322.0], 'cols': [163.0, 278.0], 'row_pitch': 138.0}
        cells = echo_grid.cells_from_structure(st)
        self.assertEqual(cells[0], (163.0, 184.0 + 138.0 * 0.08))
        self.assertEqual(len(cells), 4)


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


class TestRowsDiffer(unittest.TestCase):
    """判断"滚轮是否真的滚动"：行线变化比较。"""

    def test_same_rows(self):
        self.assertFalse(echo_grid.rows_differ([184, 322, 460], [184, 322, 460]))
        self.assertFalse(echo_grid.rows_differ([], []))

    def test_shifted_rows(self):
        self.assertTrue(echo_grid.rows_differ([184, 322, 460], [64, 202, 340]))
        self.assertTrue(echo_grid.rows_differ([184, 322], [184, 322, 460]))

    def test_one_side_empty(self):
        self.assertTrue(echo_grid.rows_differ([], [184, 322]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
