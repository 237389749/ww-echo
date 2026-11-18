"""详情面板「长截图」拼接的单元测试（`src/echo_panel_shot.py`）。

面板滚动条是所有声骸共用的，套装名又在面板下半截 —— 拼接正确与否直接决定"离线看一眼就能定位
问题"这件事靠不靠谱。这里用**已知位移**的合成长图，逐条钉住：
  ① 位移估计 = 真值；② 静止帧不被当位移；③ 三帧拼接能还原原图；④ 不相干的帧要跳过而不是硬拼。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None
    np = None

from src import echo_panel_shot as shot  # noqa: E402


def _panel(height=420, width=300, seed=7):
    """合成一张"有行结构"的面板长图：不同长度的横条 + 微弱噪声（模拟文字行/分隔线）。"""
    rng = np.random.default_rng(seed)
    img = np.full((height, width, 3), 24, np.uint8)
    y = 12
    i = 0
    while y < height - 20:
        line_h = 8 + (i * 7) % 13
        line_w = int(width * (0.35 + ((i * 37) % 60) / 100.0))
        color = (200 - (i * 11) % 120, 180 - (i * 17) % 110, 190 - (i * 23) % 130)
        cv2.rectangle(img, (16, y), (16 + line_w, y + line_h), color, -1)
        y += line_h + 9
        i += 1
    noise = rng.integers(-6, 7, img.shape, dtype=np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


@unittest.skipUnless(cv2 is not None, '需要 cv2')
class TestVerticalOffset(unittest.TestCase):

    def test_known_shift(self):
        long_img = _panel(900)
        prev = long_img[0:420]
        cur = long_img[80:500]
        self.assertEqual(shot.vertical_offset(prev, cur), 80)

    def test_second_shift(self):
        long_img = _panel(900)
        prev = long_img[200:620]
        cur = long_img[316:736]
        self.assertEqual(shot.vertical_offset(prev, cur), 116)

    def test_static_frame_is_not_a_shift(self):
        long_img = _panel(520)
        prev = long_img[0:420]
        self.assertIsNone(shot.vertical_offset(prev, prev))

    def test_unrelated_frames_are_rejected(self):
        a = _panel(420, seed=1)
        b = _panel(420, seed=99)
        self.assertIsNone(shot.vertical_offset(a, b))


@unittest.skipUnless(cv2 is not None, '需要 cv2')
class TestStitch(unittest.TestCase):

    def test_three_frames_reconstruct(self):
        long_img = _panel(900)
        frames = [long_img[0:420], long_img[80:500], long_img[160:580]]
        out, used, offsets = shot.stitch(frames)
        self.assertIsNotNone(out)
        self.assertEqual(len(used), 3)
        self.assertEqual(offsets, [80, 80])
        # 前 580 行应当与原始长图一致（像素级）
        self.assertEqual(out.shape[0], 580)
        diff = np.abs(out.astype(np.int16) - long_img[0:580].astype(np.int16)).mean()
        self.assertLess(diff, 1.0)

    def test_garbage_frame_is_skipped(self):
        long_img = _panel(900)
        frames = [long_img[0:420], _panel(420, seed=42), long_img[80:500]]
        out, used, _ = shot.stitch(frames)
        self.assertIsNotNone(out)
        self.assertNotIn(1, used)          # 不相干的那帧必须被跳过
        self.assertIn(2, used)

    def test_no_frames(self):
        self.assertEqual(shot.stitch([]), (None, [], []))
        self.assertEqual(shot.stitch([None]), (None, [], []))

    def test_height_cap(self):
        long_img = _panel(1200)
        frames = [long_img[i * 60:i * 60 + 420] for i in range(8)]
        out, _, _ = shot.stitch(frames, max_height=700)
        self.assertIsNotNone(out)
        self.assertLessEqual(out.shape[0], 700 + 420)


if __name__ == '__main__':
    unittest.main()
