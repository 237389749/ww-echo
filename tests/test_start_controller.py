"""`StartController.start()` 的"完成回调"契约（2026-11-22 后端审查 B2）。

`start()` 只是把 `do_start` 投递到 handler 线程就返回 —— 旧调用方（运行页）把它当同步：
提交完立刻打「══ 结束 ══」并把开始按钮放开，而任务其实在跑。修法是给 `start()` 一个
`on_done(ok)` 回调，让调用方拿到**真实**结果。这里钉住回调的三种取值。

跑法（项目根目录）：
    python -m unittest tests.test_start_controller -v
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ww_app_shell.start_controller import StartController                      # noqa: E402
from ww_engine.util.handler import ExitEvent                                   # noqa: E402


class _SyncHandler:
    """把 `post` 变成同步执行（真实 Handler 是另一个线程，断言会变成竞态）。"""

    def post(self, fn):
        fn()
        return True


class StartCallbackTest(unittest.TestCase):
    def setUp(self):
        # Handler 要的是 ExitEvent（它自己会 `exit_event.bind_stop(self)`），不是裸 threading.Event
        self.exit_event = ExitEvent()
        self.sc = StartController({"start_timeout": 1, "windows": {}}, self.exit_event)
        self.sc.handler = _SyncHandler()       # 真 Handler 线程留着也没用，直接换掉

    def tearDown(self):
        self.exit_event.set()                  # 让真实 Handler 的守护线程退出

    def test_on_done_true(self):
        got = []
        self.sc.do_start = lambda task=None, exit_after=False: True
        self.sc.start(None, on_done=got.append)
        self.assertEqual(got, [True])

    def test_on_done_false(self):
        got = []
        self.sc.do_start = lambda task=None, exit_after=False: False
        self.sc.start(None, on_done=got.append)
        self.assertEqual(got, [False])

    def test_on_done_false_when_do_start_raises(self):
        got = []

        def boom(task=None, exit_after=False):
            raise RuntimeError("设备刷新失败")

        self.sc.do_start = boom
        self.sc.start(None, on_done=got.append)      # 不抛给调用方
        self.assertEqual(got, [False])

    def test_on_done_is_optional(self):
        self.sc.do_start = lambda task=None, exit_after=False: True
        self.sc.start(None)                          # 不传回调也不能崩
        self.sc.start(None, exit_after=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
