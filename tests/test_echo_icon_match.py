"""`src/echo_icon_match` 的单元测试 —— 纯函数 + 合成帧闭环, **不依赖游戏截图数据**。

跑法(项目根目录):
    python -m unittest discover -s tests -v
    python tests/test_echo_icon_match.py

合成帧闭环: 把模板自身贴到 `ICON_BOX` 位置造一张假整帧 → `match_icon` 必须认回该套装,
含 ±2px 偏移容差; 这样即使没有 1GB 的 `logs/eval_debug` 数据集, 也能锁住
"裁剪坐标 ↔ 模板库 ↔ 匹配逻辑" 的闭环。
"""

import glob
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.echo_icon_match as M  # noqa: E402


def template_paths():
    return sorted(glob.glob(os.path.join(M.icons_dir(), '*.png')))


def synth_frame(tpl_path, dx=0, dy=0, size=(1200, 1920)):
    """把模板贴到合成整帧的图标区(模拟详情面板), 用于不依赖截图的闭环测试。"""
    h, w = size
    frame = np.zeros((h, w, 3), np.uint8)
    x1, y1 = int(M.ICON_BOX[0] * w) + dx, int(M.ICON_BOX[1] * h) + dy
    x2, y2 = int(M.ICON_BOX[2] * w) + dx, int(M.ICON_BOX[3] * h) + dy
    patch = cv2.resize(M._template_gray(tpl_path), (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA)
    frame[y1:y2, x1:x2] = cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)
    return frame


class TestMaskAndCanvas(unittest.TestCase):

    def test_mask_sel_shape_center_and_symmetry(self):
        sel = M._mask_sel()
        self.assertEqual(sel.shape, (M.ICON_SIZE * M.ICON_SIZE,))
        n = int(sel.sum())
        self.assertGreater(n, 300)                 # r≤12 圆内约 452 px
        self.assertLess(n, M.ICON_SIZE ** 2)       # 必须排除四角面板背景
        m = sel.reshape(M.ICON_SIZE, M.ICON_SIZE)
        self.assertTrue(m[14, 14])                 # 圆心在内
        self.assertFalse(m[0, 0])                  # 四角在外
        self.assertTrue(np.array_equal(m, m[::-1, :]))   # 上下对称
        self.assertTrue(np.array_equal(m, m[:, ::-1]))   # 左右对称

    def test_to_canvas_pad_crop_and_direct(self):
        img = np.arange(76 * 76, dtype=np.uint8).reshape(76, 76)
        small = M._to_canvas(img, 27)
        self.assertEqual(small.shape, (28, 28))
        # 补白同样按整数偏移: o=(28-27)//2=0 → 白边落在右/下侧
        self.assertTrue(np.all(small[-1] == 255))
        self.assertTrue(np.all(small[:, -1] == 255))
        self.assertEqual(M._to_canvas(img, 28).shape, (28, 28))   # 直通
        big = M._to_canvas(img, 29)
        self.assertEqual(big.shape, (28, 28))
        # 29->28 偏移 o=(29-28)//2=0: 取左上 28x28(亚像素偏 0.5px, 回归基线基于此)
        resized = cv2.resize(img, (29, 29), interpolation=cv2.INTER_AREA).astype(np.float32)
        self.assertTrue(np.array_equal(big, resized[:28, :28]))

    def test_template_gray_reads_unicode_path(self):
        paths = template_paths()
        if not paths:
            self.skipTest('assets/echo_icons 缺失')
        self.assertIn('雪落无声之愿', ' '.join(os.path.basename(p) for p in paths))  # 中文文件名样本
        gray = M._template_gray(paths[0])
        self.assertIsNotNone(gray)          # cv2.imread 遇到中文路径会返回 None
        self.assertEqual(gray.ndim, 2)
        self.assertEqual(gray.dtype, np.uint8)

    def test_template_gray_composites_alpha_on_white(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, '测试套装.png')     # 中文名 + RGBA + 全透明
            cv2.imencode('.png', np.zeros((8, 8, 4), np.uint8))[1].tofile(path)
            gray = M._template_gray(path)
            self.assertIsNotNone(gray)
            self.assertEqual(gray.ndim, 2)
            self.assertTrue(np.all(gray == 255))         # 透明区合成到白底

    def test_template_gray_missing_file(self):
        self.assertIsNone(M._template_gray(os.path.join('assets', 'echo_icons', '不存在的套装.png')))


class TestCropIcon(unittest.TestCase):

    def test_invalid_frames(self):
        self.assertIsNone(M.crop_icon(None))
        self.assertIsNone(M.crop_icon(np.zeros((0, 0, 3), np.uint8)))
        self.assertIsNone(M.crop_icon(np.zeros((20, 20, 3), np.uint8)))   # 图标区 < 8px

    def test_valid_frame_shape_and_dtype(self):
        gray = M.crop_icon(np.zeros((1200, 1920, 3), np.uint8))
        self.assertEqual(gray.shape, (M.ICON_SIZE, M.ICON_SIZE))
        self.assertEqual(gray.dtype, np.float32)

    def test_accepts_grayscale_frame(self):
        self.assertEqual(M.crop_icon(np.zeros((1200, 1920), np.uint8)).shape, (28, 28))

    def test_resolution_independent(self):
        for h, w in ((1200, 1920), (900, 1600), (1080, 1920), (1600, 2560)):
            with self.subTest(frame=f'{w}x{h}'):
                self.assertEqual(M.crop_icon(np.zeros((h, w, 3), np.uint8)).shape, (28, 28))


class TestMatchIconClosedLoop(unittest.TestCase):
    """用合成帧锁死闭环: 不需要 logs/eval_debug 数据集。"""

    def test_synthetic_frame_hits_own_template(self):
        paths = template_paths()
        if not paths:
            self.skipTest('assets/echo_icons 缺失')
        for path in paths[:5]:
            name = os.path.splitext(os.path.basename(path))[0]
            with self.subTest(set_name=name):
                got, score, margin = M.match_icon(synth_frame(path))
                self.assertEqual(got, name)
                self.assertGreaterEqual(score, M.MIN_SCORE)
                self.assertGreaterEqual(margin, M.MIN_MARGIN)

    def test_shift_tolerance_within_2px(self):
        paths = template_paths()
        if not paths:
            self.skipTest('assets/echo_icons 缺失')
        path = paths[0]
        name = os.path.splitext(os.path.basename(path))[0]
        for dx, dy in ((0, 0), (2, 0), (-2, 1), (1, -2), (0, -2)):
            with self.subTest(offset=(dx, dy)):
                got, _, _ = M.match_icon(synth_frame(path, dx, dy))
                self.assertEqual(got, name)

    def test_blank_frame_is_low_confidence(self):
        got, score, margin = M.match_icon(np.zeros((1200, 1920, 3), np.uint8))
        self.assertIsNone(got)
        self.assertLess(score, M.MIN_SCORE)

    def test_none_and_tiny_frame_safe(self):
        self.assertEqual(M.match_icon(None), (None, 0.0, 0.0))
        self.assertEqual(M.match_icon(np.zeros((20, 20, 3), np.uint8)), (None, 0.0, 0.0))

    def test_empty_template_bank_returns_none(self):
        saved = M._bank_cache
        sel = M._mask_sel()
        M._bank_cache = ([], np.zeros((0, int(sel.sum())), np.float32), np.zeros(0, np.float32), sel)
        try:
            self.assertEqual(M.match_icon(np.zeros((1200, 1920, 3), np.uint8)), (None, 0.0, 0.0))
        finally:
            M._bank_cache = saved


if __name__ == '__main__':
    unittest.main(verbosity=2)
