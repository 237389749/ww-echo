"""评估报告 HTML 的筛选控件（不依赖游戏/浏览器）：判定拆分 + COST 筛选 + 无 0 级选项。

跑法(项目根目录):
    python -m unittest tests.test_report_filters -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.run_tab import _build_eval_html  # noqa: E402


def _record(index, verdict, verdict_cn, cost, score=20.0):
    return {
        "index": index, "screenshot": f"x{index}.png", "name": f"测试{index}",
        "set": "凝夜白霜", "set_src": "text", "score": score,
        "verdict": verdict, "verdict_cn": verdict_cn, "cost": cost,
        "stats": [{"name": "暴击", "value": 6.3, "detail": "暴击=6.3", "ratio": 0.8}],
        "main_props": [], "plan_check": {}, "score_generic": 18.0,
    }


DATA = {
    "total": 2, "evaluated_at": "2026-01-01 00:00:00", "click_fail": 0,
    "set": "通用", "set_src": {"text": 2},
    "results": [
        _record(1, "fail", "不合格", 4),
        _record(2, "fail", "不建议强化", 1),
    ],
}


class TestReportFilters(unittest.TestCase):

    def _html(self):
        return _build_eval_html(DATA)

    def test_fail_and_bad_are_separate_options(self):
        """满级「不合格」与未满级「不建议强化」用同一个 verdict 码, 筛选项必须分开。"""
        html = self._html()
        self.assertIn('value="不合格"', html)
        self.assertIn('value="不建议强化"', html)
        self.assertIn("不合格 1", html)       # 汇总按 verdict_cn 拆分
        self.assertIn("不建议强化 1", html)
        self.assertIn('data-vcn="不合格"', html)

    def test_cost_filter_on_toolbar(self):
        html = self._html()
        self.assertIn('id="fcost"', html)
        self.assertIn('<option value="4">4C</option>', html)
        self.assertIn('<option value="3">3C</option>', html)
        self.assertIn('<option value="1">1C</option>', html)
        self.assertIn('data-cost="4"', html)

    def test_zero_level_filter_removed(self):
        """0 级件不写报告, 筛选/汇总里的「0级/无词条」是死选项 → 已移除。"""
        self.assertNotIn("0级/无词条", self._html())


if __name__ == '__main__':
    unittest.main(verbosity=2)
