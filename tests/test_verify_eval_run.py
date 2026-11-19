"""`tools/analysis/verify_eval_run.py` 的解析与验收闸门守卫。

用合成日志/报告锁住四件事（真机复跑时靠它出结论，解析错了会误导判断）：
  ① 只取**最后一次**评估会话（日志是追加写的，不截断会把上一轮算进来）
  ② 每屏一行：格数/新增/重复/0词条 + 紧跟其后的那次滚动；无重叠守卫落在哪一屏
  ③ `--check` 的闸门：完全重复 / `set_src=text` 占比 / 日志与报告条数一致
  ④ 2026-11-19 的三个"必须为 0"：面板回顶失败 / 缺 COST / `持有数量` 假主属性
     （回顶失败数 JSON 优先、日志兜底；旧报告没有 cost 字段时降级为 SKIP 不误判）

跑法（项目根目录）：
    python -m unittest tests.test_verify_eval_run -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools' / 'analysis'))

import verify_eval_run as ver  # noqa: E402


def _line(ts, msg, level='INFO'):
    return f'2026-11-19 {ts} {level} Thread-2 (_run_eval) EnhanceEchoTask:{msg}'


OLD_SESSION = [
    _line('09:00:00,000', '评估遍历: 不识别声骸数量, 直到「连续两行 0 词条 / 网格为空」结束'),
    _line('09:00:01,000', '本屏完成: 30 格, 新增 30 条, 重复/点空 0 格, 0词条 0 格'),
    _line('09:00:02,000', '评估完成, 共30个声骸'),
]

NEW_SESSION = [
    _line('10:00:00,000', '评估遍历: 不识别声骸数量, 直到「连续两行 0 词条 / 网格为空」结束'),
    _line('10:00:00,500', '本屏网格: 6 列 × 5 行 (行距 138px)'),
    _line('10:00:01,000', '本屏完成: 30 格, 新增 30 条, 重复/点空 0 格, 0词条 0 格'),
    _line('10:00:02,000', '滚动(真实滚轮): 42 格 → +0.2 行 (≈8.0px/格, 残差 36, 停稳 0.75s, 画面变化 50%)'),
    _line('10:00:45,000', '本屏完成: 30 格, 新增 18 条, 重复/点空 12 格, 0词条 0 格'),
    _line('10:00:45,100', '本屏无重叠(滚过头, 中间整行被跳过) → 回滚 1 行重扫 (第 1 次)', 'WARNING'),
    _line('10:00:46,000', '[套装] 合鸣效果区读到套装名: 隐世回光(1.00, 滚 12 格)'),
    _line('10:00:47,000', '[评估#1] 先锋幼岩 | 5/5词条 | 得分=25.30 | 保留 | 套装=隐世回光(text)'),
    _line('10:00:47,500', '本屏完成: 30 格, 新增 29 条, 重复/点空 1 格, 0词条 0 格'),
    _line('10:00:48,000', '[评估#2] 无归的谬误 | 5/5词条 | 得分=18.00 | 保留 | 套装=隐世回光(name)'),
    _line('10:00:49,000', '评估完成, 共2个声骸'),
    # 会话结束后的无关日志不能被算进耗时
    _line('10:30:00,000', '[模板校验] 37 个套装通过校验'),
]


def _report(rows):
    return {'set': '通用', 'total': len(rows), 'evaluated_at': '2026-11-19 10:00:49',
            'results': rows}


def _row(i, name, setname, src, **extra):
    row = {'index': i, 'name': name, 'set': setname, 'set_src': src,
           'stats': [{'name': '暴击', 'value': 6.3 + i}],
           'main_props': [{'name': '攻击', 'value': 100.0}],
           'verdict': 'hold', 'score': 20.0}
    row.update(extra)
    return row


class ParseLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / 'ok-echo.log'
        self.log.write_text('\n'.join(OLD_SESSION + NEW_SESSION) + '\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_last_session(self):
        screens, stats, non_text, done = ver.parse_log(self.log)
        self.assertEqual(len(screens), 3)          # 旧会话的 1 屏不算
        self.assertEqual(done, 2)
        self.assertEqual(non_text, [(2, '无归的谬误', '隐世回光', 'name')])

    def test_screen_fields(self):
        screens, stats, _, _ = ver.parse_log(self.log)
        first, second, third = screens
        self.assertEqual((first.cells, first.new, first.dup, first.zero), (30, 30, 0, 0))
        self.assertEqual((first.cols, first.rows, first.row_pitch), (6, 5, 138))
        self.assertEqual(first.moved, 0.2)          # 滚动行挂在它**前面**那一屏
        self.assertEqual(first.resid, 36)
        self.assertEqual(first.still, 0.75)
        self.assertEqual(second.dup, 12)
        self.assertTrue(second.guarded)              # 守卫落在第 2 屏
        self.assertFalse(first.guarded)
        self.assertIsNone(third.moved)               # 最后一屏后面没有滚动

    def test_counters(self):
        _, stats, _, _ = ver.parse_log(self.log)
        self.assertEqual(stats['guard'], 1)
        self.assertEqual(stats['set_text'], 1)
        self.assertEqual(stats['duration'], 49.0)    # 10:00:00 → 10:00:49，不吃会话后的日志

    def test_screen_seconds(self):
        screens, _, _, _ = ver.parse_log(self.log)
        self.assertEqual(screens[0].secs, 44.0)      # 10:00:01 → 10:00:45


class MainGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = self.dir / 'ok-echo.log'
        self.log.write_text('\n'.join(NEW_SESSION) + '\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, report, extra=()):
        path = self.dir / 'eval_report.json'
        path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        argv = ['verify_eval_run.py', str(path), '--log', str(self.log)] + list(extra)
        buf = io.StringIO()
        with patch.object(sys, 'argv', argv), redirect_stdout(buf):
            code = ver.main()
        return code, buf.getvalue()

    def test_text_majority_passes(self):
        code, out = self._run(_report([_row(1, '先锋幼岩', '隐世回光', 'text'),
                                       _row(2, '无归的谬误', '隐世回光', 'text')]), ['--check'])
        self.assertEqual(code, 0, out)
        self.assertIn('[ok]', out)

    def test_no_panel_signal_fails(self):
        code, out = self._run(_report([_row(1, '先锋幼岩', '隐世回光', 'name'),
                                       _row(2, '无归的谬误', '隐世回光', 'default')]), ['--check'])
        self.assertEqual(code, 1, out)
        self.assertIn('面板套装信息一条都没读到', out)

    def test_effect_only_is_warn_not_fail(self):
        """面板读到了但只是按效果原文反查（text 0%）→ 提醒，不判失败。"""
        code, out = self._run(_report([_row(1, '先锋幼岩', '隐世回光', 'effect'),
                                       _row(2, '无归的谬误', '隐世回光', 'effect')]), ['--check'])
        self.assertEqual(code, 0, out)
        self.assertIn('set_src=text 只占 0%', out)

    def test_count_mismatch_fails(self):
        code, out = self._run(_report([_row(1, '先锋幼岩', '隐世回光', 'text')]), ['--check'])
        self.assertEqual(code, 1, out)
        self.assertIn('不一致', out)

    def test_duplicate_fails(self):
        row = _row(1, '先锋幼岩', '隐世回光', 'text')
        code, out = self._run(_report([row, dict(row)]), ['--check'])
        self.assertEqual(code, 1, out)
        self.assertIn('完全重复 1 组', out)


class RollingHealthGateTest(unittest.TestCase):
    """SESSION_2026-11-19 §9 的三个"必须为 0"：回顶失败 / 缺 COST / 假主属性。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = self.dir / 'ok-echo.log'
        self.log.write_text('\n'.join(NEW_SESSION) + '\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, report, log=None, extra=()):
        path = self.dir / 'eval_report.json'
        path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        argv = ['verify_eval_run.py', str(path), '--log', str(log or self.log)] + list(extra)
        buf = io.StringIO()
        with patch.object(sys, 'argv', argv), redirect_stdout(buf):
            code = ver.main()
        return code, buf.getvalue()

    def test_restore_fail_is_problem(self):
        rows = [_row(1, '先锋幼岩', '隐世回光', 'text', cost=4),
                _row(2, '无归的谬误', '隐世回光', 'text', cost=3)]
        report = dict(_report(rows), panel_restore_fail=5)
        code, out = self._run(report, extra=['--check'])
        self.assertEqual(code, 1, out)
        self.assertIn('[面板回顶] 失败 5 次', out)

    def test_restore_zero_passes(self):
        rows = [_row(1, '先锋幼岩', '隐世回光', 'text', cost=4),
                _row(2, '无归的谬误', '隐世回光', 'text', cost=3)]
        report = dict(_report(rows), panel_restore_fail=0)
        code, out = self._run(report, extra=['--check'])
        self.assertEqual(code, 0, out)
        self.assertIn('失败 0 次', out)

    def test_restore_falls_back_to_log(self):
        """离线重放/旧报告的 JSON 没有 panel_restore_fail → 用日志「评估完成」行里的次数。"""
        log = self.dir / 'restore.log'
        lines = NEW_SESSION[:-2] + [_line(
            '10:00:49,000',
            '评估完成, 共2个声骸 (套装来源: text=2; 点击失败 0 格; 面板回顶失败 3 次)')]
        log.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        rows = [_row(1, '先锋幼岩', '隐世回光', 'text', cost=4),
                _row(2, '无归的谬误', '隐世回光', 'text', cost=3)]
        code, out = self._run(_report(rows), log=log, extra=['--check'])
        self.assertEqual(code, 1, out)
        self.assertIn('失败 3 次（来自日志）', out)

    def test_restore_log_fallback_requires_same_run(self):
        """日志是上一轮的（条数对不上）→ 不许借它的回顶次数，宁可 SKIP。"""
        log = self.dir / 'old_run.log'
        lines = NEW_SESSION[:-2] + [_line(
            '10:00:49,000',
            '评估完成, 共3个声骸 (套装来源: text=3; 点击失败 0 格; 面板回顶失败 4 次)')]
        log.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        rows = [_row(1, '先锋幼岩', '隐世回光', 'text', cost=4),
                _row(2, '无归的谬误', '隐世回光', 'text', cost=3)]
        code, out = self._run(_report(rows), log=log, extra=['--check'])
        self.assertIn('[面板回顶] —', out)
        self.assertNotIn('来自日志', out)

    def test_missing_cost_is_problem(self):
        rows = [_row(1, '先锋幼岩', '隐世回光', 'text', cost=4),
                _row(2, '无归的谬误', '隐世回光', 'text', cost=None)]
        code, out = self._run(_report(rows), extra=['--check'])
        self.assertEqual(code, 1, out)
        self.assertIn('缺 1 / 2 条', out)

    def test_legacy_report_without_cost_skips(self):
        """2026-11-19 之前的报告没有 cost 字段 → 只 SKIP，不能当成"全缺 COST"误杀。"""
        rows = [_row(1, '先锋幼岩', '隐世回光', 'text'),
                _row(2, '无归的谬误', '隐世回光', 'text')]
        code, out = self._run(_report(rows), extra=['--check'])
        self.assertEqual(code, 0, out)
        self.assertIn('报告没有 cost 字段', out)

    def test_fake_main_prop_is_problem(self):
        rows = [_row(1, '共鸣回响·天演溯心', '凝夜白霜', 'text', cost=1,
                     main_props=[{'name': '持有数量：1', 'value': 1.0}])]
        code, out = self._run(_report(rows), extra=['--check'])
        self.assertEqual(code, 1, out)
        self.assertIn('假主属性 1 条', out)


if __name__ == '__main__':
    unittest.main()
