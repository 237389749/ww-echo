"""评估遍历的**冒烟测试**：用一张合成帧把 `evaluate_only` 真跑一遍（不需要游戏）。

为什么需要（2026-11-14 教训）：`scan_grid`/`scroll_grid` 是 `evaluate_only` 里的**闭包**，
把 `self._log_grid_geometry(...)` 写成 self. 之后，点「开始」立刻 AttributeError 中止，
而所有单测（纯函数 + 静态字符串检查）全绿 —— 只有真跑一遍才能抓到这类运行时错误。
这里用合成帧 + 桩件（无 OCR / 点击不生效 / 滚不动）走完：
结构标定 → 逐格点击 → 读详情 → 每屏小结 → 滚动受阻 → 连续 2 次中止 → 生成报告。
"""

import os
import shutil
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - 无 cv2 的环境跳过
    cv2 = None
    np = None


def _frame_bgr():
    """1254x889：6 列 × 5 行卡片 + 底部金色等级条（卡片在行线上方，和真机一致）。"""
    img = np.full((889, 1254, 3), 20, np.uint8)
    for k in range(5):
        y = 200 + 135 * k
        for c in range(6):
            x = 40 + 113 * c
            cv2.rectangle(img, (x, y - 107), (x + 100, y + 2), (90, 90, 90), -1)
            cv2.line(img, (x + 4, y), (x + 96, y), (0, 190, 255), 3)
            cv2.putText(img, '+25', (x + 62, y + 13), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (240, 240, 240), 1)
    return img


class _FakeMethod:
    width = 1254
    height = 889


class _FakeExecutor:
    def __init__(self):
        self.method = _FakeMethod()
        self.device_manager = None      # → _real_wheel/_drag_scroll 直接返回 False


class _FakeHandler:
    def post(self, fn):
        fn()


@unittest.skipUnless(cv2 is not None, '需要 cv2')
class TestEvaluateOnlySmoke(unittest.TestCase):
    """跑一遍完整遍历（桩件下会"滚动受阻"中止），把运行期错误暴露出来。"""

    def _make_task(self):
        from src.task.EnhanceEchoTask import EnhanceEchoTask

        class _Task(EnhanceEchoTask):
            def __init__(self):
                self._frame = _frame_bgr()
                self._executor = _FakeExecutor()
                self._handler = _FakeHandler()
                self.config = {'当前套装': '通用'}
                self.logs = []
                self.clicks = []
                self.keys = []
                self._stop_event = threading.Event()   # stop_requested() 用它

            # `executor`/`frame`/`handler`/`width`/`height` 在 Task 上是只读 property,
            # 子类必须同样用 property 覆盖（直接赋值会 AttributeError）。
            @property
            def executor(self):
                return self._executor

            @property
            def handler(self):
                return self._handler

            @property
            def width(self):
                return 1254

            @property
            def height(self):
                return 889

            @property
            def frame(self):
                return self._frame

            def sleep(self, timeout):
                return True

            def ocr(self, *a, **k):
                return []

            def click(self, x, y, after_sleep=0, **k):
                self.clicks.append((float(x), float(y)))
                return True

            def scroll_relative(self, x, y, count):
                return None

            def send_key(self, key, **k):
                self.keys.append(str(key))
                return True

            def info_set(self, *a, **k):
                return None

            def _check_set_keys(self, set_name):
                return True, ''

            def log_info(self, msg, notify=False):
                self.logs.append(('INFO', str(msg)))

            def log_warning(self, msg, notify=False):
                self.logs.append(('WARNING', str(msg)))

            def log_error(self, msg, exception=None, notify=False):
                self.logs.append(('ERROR', str(msg)))

            def log_debug(self, msg, notify=False):
                self.logs.append(('DEBUG', str(msg)))

        return _Task()

    def test_full_traversal_does_not_crash(self):
        """桩件下 OCR 永远读不到东西 → 连续 6 格(一整行)计失败后中止并出部分报告。

        2026-11-19 用户口径："按布局点了但没识别到应计入失败，而不是一直继续" ——
        所以这条路不再走"每屏小结 → 滚动受阻 → 中止"，而是更快地失败并留下报告。
        **中途一次复位**: 一整行都点空时先按 B×2 回背包重扫(疑似被点进别的界面), 再失败才中止。
        """
        task = self._make_task()
        done = {}

        def _on_done(json_path, ss_dir):
            done['json'] = json_path
            done['ss'] = ss_dir

        # 测试不写 logs/panel_debug/(默认开是为了真机拿数据, 单测里没必要)
        import src.task.EnhanceEchoTask as mod
        from unittest.mock import patch
        try:
            with patch.object(mod, 'SAVE_PANEL_DATASET', False):
                task.evaluate_only(on_done=_on_done)
        finally:
            # evaluate_only 正常结束不删临时目录 → 交给测试收尾（在断言之后执行）
            if 'json' in done:
                self.addCleanup(shutil.rmtree, os.path.dirname(done['json']), True)

        texts = [m for _, m in task.logs]
        self.assertTrue(any('本屏网格' in m for m in texts), msg=f'缺每屏几何日志: {texts[:8]}')
        self.assertTrue(any('[失败]' in m for m in texts), msg='点了读不到属性必须记一条失败')
        self.assertTrue(any('点击后都读不到属性' in m for m in texts),
                        msg='连续失败应中止，不空转')
        # 开局复位: 按两次 B; 中途点空一整行还会再按两次(复位背包重扫)
        self.assertGreaterEqual(len(task.keys), 2)
        self.assertEqual(task.keys[:2], ['b', 'b'], msg=f'开局应按两次 B: {task.keys}')
        self.assertTrue(any('复位背包' in m for m in texts), msg='开场应记一条"复位背包"')
        # 第一屏 6×5=30 格；连续 6 格失败 → 复位重扫 → 再 6 格失败才中止(每格最多点 2 次)
        self.assertGreaterEqual(len(task.clicks), 6)
        self.assertLessEqual(len(task.clicks), 26)
        # 读不到任何详情 → 一条记录都没有，但仍应产出报告
        self.assertIn('json', done, msg='未产出报告 JSON')
        self.assertTrue(os.path.exists(done['ss']), msg='截图目录不存在')

    def test_empty_grid_retries_b_once_then_raises(self):
        """首屏就是空网格(不在背包/被挡住): 先补按一次 B 再扫, 仍空才报错 —— 不能一声不响就停。

        同时锁住"空网格要**连续两次**才算到底": 每次空只许 +1(曾经在改兜底时写出过两次自增,
        会让"一屏空"就误判到达底部/误报不在背包)。
        """
        task = self._make_task()
        task._frame = np.zeros((889, 1254, 3), np.uint8)   # 纯黑: 没有行线/金条 → scan_grid 空
        with self.assertRaises(Exception) as ctx:
            task.evaluate_only(on_done=lambda *a, **k: None)
        self.assertIn('未在背包界面检测到声骸网格', str(ctx.exception))
        # 开局 2 下 + 兜底 1 下
        self.assertEqual(task.keys.count('b'), 3, msg=f'B 次数不对: {task.keys}')
        texts = [m for _, m in task.logs]
        self.assertEqual(sum('到达背包底部' in m for m in texts), 0,
                         msg='首屏空不能当"到达底部"')


if __name__ == '__main__':
    unittest.main(verbosity=2)
