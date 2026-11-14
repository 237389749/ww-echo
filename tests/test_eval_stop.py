"""「停止」按钮的接线守卫（静态检查，不需要游戏/UI）。

背景（2026-11-14）：评估跑在 `ui/run_tab` 自己的线程里，`_stop()` 只调 `task.disable()/unpause()`
是打不断它的（executor 的 `check_enabled` 只管 executor 线程），用户点停止后后台仍在点击。
修复后靠 `threading.Event` + 每屏/每格检查，这里用静态检查把这条接线钉住，防回退。
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def _method_body(src, name, max_lines=40):
    """取类方法体（到下一个同级 def 或文件尾），用于检查某个方法内部有没有调用。"""
    m = re.search(rf'^([ \t]+)def {name}\(', src, re.M)
    if not m:
        return ''
    indent = len(m.group(1))
    start = m.start()
    lines = src[start:].splitlines()
    body = [lines[0]]
    for line in lines[1:]:
        if re.match(r'^\s{0,%d}def ' % indent, line) and line.strip():
            break
        body.append(line)
        if len(body) > max_lines:
            break
    return '\n'.join(body)


class TestEvalStopWiring(unittest.TestCase):

    def test_task_has_stop_api_and_checks(self):
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        for name in ('request_stop', 'stop_requested', 'reset_stop'):
            self.assertIn(f'def {name}(', src, msg=f'EnhanceEchoTask 缺少 {name}()')
        # evaluate_only 里至少两处检查（每屏 / 每格）
        self.assertGreaterEqual(src.count('self.stop_requested()'), 2,
                                msg='evaluate_only 每屏/每格都该检查停止事件')
        # 停止后不应再生成报告 / 回调
        self.assertIn('if stopped:', src)
        self.assertIn('不生成报告', src)

    def test_ui_stop_requests_task_stop(self):
        src = _read(os.path.join('ui', 'run_tab.py'))
        stop_body = _method_body(src, '_stop')
        self.assertIn('request_stop', stop_body,
                      msg='_stop() 必须先 request_stop()，否则评估线程不会退出')
        start_body = _method_body(src, '_start')
        self.assertIn('reset_stop', start_body,
                      msg='_start() 应先 reset_stop()，避免"刚开始就停止"被清掉')


if __name__ == '__main__':
    unittest.main(verbosity=2)
