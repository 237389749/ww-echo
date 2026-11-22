"""评估报告的结构守卫（B3）：行折叠 / 判定 chip / 打印与分享 / 规则文案。

跑法(项目根目录):
    python -m unittest tests.test_report_layout -v

这些断言锁的是**用户能看见/能点的东西**：每件两条 `<tr>`（主行 + 详情行）、筛选排序只认主行、
排序时详情行跟着搬、打印样式展开所有行、筛选写进地址栏、页脚写明截图目录依赖。
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.present import VERDICT_CHIP_BG, VERDICT_COLOR, VERDICT_MARK  # noqa: E402
from ui.run_tab import _EVAL_CSS, _EVAL_JS, _build_eval_html         # noqa: E402


def _stat(name, value, ratio):
    return {"name": name, "value": value,
            "detail": f"{name}={value}→{ratio}×10×1.0=10.00 [前 22%]", "ratio": ratio}


def _record(index, verdict, cn, score=20.0, cost=4, stats=None, **kw):
    rec = {
        "index": index, "screenshot": f"x{index}.png", "name": f"测试{index}",
        "set": "凝夜白霜", "set_src": "icon", "score": score,
        "verdict": verdict, "verdict_cn": cn, "cost": cost,
        "stats": stats if stats is not None else [_stat("暴击", 6.3, 1.05)],
        "main_props": [{"name": "暴击伤害", "value": 44}], "plan_check": {"state": "ok"},
        "score_generic": 18.0,
    }
    rec.update(kw)
    return rec


DATA = {
    "total": 3, "evaluated_at": "2026-11-22 18:00:00", "set_mode": "icon_first",
    "results": [
        _record(1, "pass", "达标", 27.3),
        _record(2, "fail", "不合格", 12.1, cost=1),
        _record(3, "hold", "保留(词条缺失)", 18.4, stats_missing=1, level=20),
    ],
}


class TestRowFolding(unittest.TestCase):
    """U-10: 主行 56px（缩略图/名称/套装/COST/得分/判定），详情行收起截图与词条。"""

    def setUp(self):
        self.html = _build_eval_html(DATA)

    def test_each_record_has_main_and_detail_row(self):
        self.assertEqual(self.html.count('class="main"'), 3)
        self.assertEqual(self.html.count('class="detail" hidden'), 3,
                         "每件都要有配对的详情行, 且默认收起")

    def test_detail_row_follows_its_main_row(self):
        """详情行必须**紧跟**主行 —— 排序/展开都依赖 nextElementSibling。"""
        pairs = re.findall(r'<tr class="main".*?</tr>\s*<tr class="detail"', self.html, re.S)
        self.assertEqual(len(pairs), 3)

    def test_data_attributes_only_on_main_row(self):
        """筛选读的 data-* 必须在主行上（详情行没有 data-*, 被误当数据行就会重复计数）。"""
        for tr in re.findall(r'<tr class="detail"[^>]*>', self.html):
            self.assertNotIn("data-score", tr)

    def test_table_has_no_detail_column(self):
        """截图/词条进了详情行 → 主表只留 7 列。"""
        # 注意: 规则卡里的权重表也是 <thead><tr> —— 这里要的是**主表**(以 # 开头那张)
        head = re.search(r'<thead><tr><th>#</th>(.*?)</tr></thead>', self.html, re.S).group(0)
        self.assertEqual(head.count("<th>"), 7)
        self.assertNotIn("词条明细", head)

    def test_invalid_stats_folded_into_one_line(self):
        """无效词条（ratio 0）折叠成一行, 不占 5 行版面。"""
        rec = _record(9, "pass", "达标", stats=[
            _stat("暴击", 6.3, 1.05), _stat("暴击伤害", 12.6, 1.0), _stat("攻击百分比", 6.4, 0.9),
            _stat("生命百分比", 6.4, 0.0), _stat("防御百分比", 7.6, 0.0)])
        html = _build_eval_html({"total": 1, "results": [rec]})
        self.assertEqual(html.count('class="srow"'), 3, "3 条有效词条 → 3 行")
        self.assertEqual(html.count('class="srow invalid"'), 1, "2 条无效词条 → 合并 1 行")
        self.assertIn("无效/不计", html)

    def test_stat_formula_is_in_title(self):
        """公式与分位放 title, 不占视觉版面。"""
        self.assertIn("[前 22%]", self.html, "词条公式(含分位)应写进 title")


class TestReportScript(unittest.TestCase):
    """U-10: 筛选/排序只遍历主行; 排序时详情行跟着搬; 展开状态可同步。"""

    def test_filter_iterates_main_rows_only(self):
        self.assertIn("#tbody tr.main", _EVAL_JS)
        self.assertNotIn("querySelectorAll('#tbody tr')", _EVAL_JS,
                         "旧写法会把详情行也当数据行(计数翻倍/筛选错乱)")

    def test_sort_moves_detail_row_with_main(self):
        self.assertIn("detailOf(tr)", _EVAL_JS)
        self.assertRegex(_EVAL_JS, r"appendChild\(tr\);[\s\S]{0,80}appendChild\(d\)")

    def test_detail_visibility_synced_with_filter_and_open(self):
        self.assertIn("function syncDetail", _EVAL_JS)
        self.assertIn("classList.contains('open')", _EVAL_JS)

    def test_click_on_main_row_toggles(self):
        self.assertIn("closest", _EVAL_JS)
        self.assertIn("toggleRow", _EVAL_JS)


class TestShareAndPrint(unittest.TestCase):
    """U-20: 筛选写进地址栏、打印样式展开所有行并隐藏筛选条、页脚写明截图目录依赖。"""

    def setUp(self):
        self.html = _build_eval_html(DATA)

    def test_filter_persisted_to_hash(self):
        self.assertIn("location.hash", _EVAL_JS)
        self.assertIn("saveHash", _EVAL_JS)
        self.assertIn("loadHash", _EVAL_JS)

    def test_print_rules(self):
        self.assertIn("@media print", _EVAL_CSS)
        self.assertRegex(_EVAL_CSS, r"tr\.detail\[hidden\]\{display:table-row")
        self.assertRegex(_EVAL_CSS, r"\.filters[^{]*\{display:none")
        self.assertIn("box-shadow:none", _EVAL_CSS)

    def test_print_expands_rows_before_printing(self):
        self.assertIn("beforeprint", _EVAL_JS)

    def test_footer_documents_screenshot_dependency(self):
        self.assertIn("eval_screenshots/", self.html)
        self.assertIn("另存为 PDF", self.html)


class TestVerdictChips(unittest.TestCase):
    """U-11: 行内判定是「浅底 chip + 色点/符号 + 深色文字」, 摘要同一套色。"""

    def setUp(self):
        self.html = _build_eval_html(DATA)

    def test_row_chip_uses_shared_palette(self):
        self.assertIn('class="vchip"', self.html)
        for cn, fg in (("达标", VERDICT_COLOR["达标"]), ("不合格", VERDICT_COLOR["不合格"])):
            self.assertIn(f"color:{fg}", self.html)
            self.assertIn(f"background:{VERDICT_CHIP_BG[cn]}", self.html)

    def test_chips_carry_symbols_for_color_blind_users(self):
        for cn in ("达标", "保留", "建议重铸", "建议强化", "不建议强化", "不合格"):
            self.assertIn(f'<span class="mark">{VERDICT_MARK[cn]}</span>', self.html)

    def test_verdict_text_is_not_used_as_bare_row_color(self):
        """旧写法是整格 `color:#ff9800;font-weight:bold`（2.16:1）—— 不能回退。"""
        self.assertNotIn('style="color:{color};font-weight:bold"', self.html)


class TestRulesText(unittest.TestCase):
    """U-21: 规则文案要写清「图标优先 / 低置信才下滑读明文 / 精确模式」。"""

    def setUp(self):
        self.html = _build_eval_html(DATA)

    def test_mentions_icon_first_and_precise_mode(self):
        self.assertIn("图标优先", self.html)
        self.assertIn("精确模式", self.html)
        self.assertIn("合鸣效果", self.html)

    def test_mentions_fallback_chain(self):
        for word in ("徽章环色", "套装名明文", "声骸名"):
            self.assertIn(word, self.html)

    def test_effect_text_reverse_lookup_marked_disabled(self):
        self.assertIn("已停用", self.html)

    def test_no_markdown_asterisks_in_visible_report(self):
        """报告是给人看的 HTML —— 用户可见文本里不能出现 `**`(U-12 同类问题)。

        `<script>`/`<style>` 里的 `**` 是注释, 不算(JS/CSS 不渲染)。
        """
        body = re.sub(r"<script.*?</script>|<style.*?</style>", "", self.html, flags=re.S)
        self.assertNotIn("**", body, "报告正文里有 Markdown 星号 —— 会原样显示成星号")

    def test_reports_which_mode_was_used(self):
        self.assertIn("图标优先（低置信才读明文）", self.html)
        self.assertIn('id="setmode"', self.html)


class TestHtmlEscaping(unittest.TestCase):
    """B8(2026-11-22 后端审查)：报告里的 OCR 文本必须转义。

    名字/词条名/主属性名都来自 OCR —— 一个 `"` 就能截断属性、一个 `<` 就吃掉半行，
    而筛选下拉与 JS 的 `dataset` 读到的值也会跟着错位。
    """

    def test_ocr_name_stats_and_main_prop_are_escaped(self):
        nasty = '双极"<b>·渊陨重锋'
        rows = [_record(1, "pass", "达标", name=nasty, name_raw=nasty,
                        stats=[_stat('暴击"><img src=x>', 6.3, 1.05)],
                        main_props=[{"name": '攻击"<i>', "value": 100}])]
        html = _build_eval_html({"total": 1, "evaluated_at": "t", "results": rows})
        self.assertNotIn("<b>·渊陨重锋", html)            # 名字没被当成标签
        self.assertNotIn("<img src=x>", html)             # 词条名里的伪标签
        self.assertNotIn('攻击"<i>', html)                 # 主属性名
        self.assertIn("&lt;b&gt;", html)
        self.assertIn("&quot;", html)

    def test_set_name_and_filter_options_are_escaped(self):
        rows = [_record(1, "pass", "达标", set='凝夜"<i>白霜')]
        html = _build_eval_html({"total": 1, "evaluated_at": "t", "results": rows})
        self.assertNotIn('凝夜"<i>', html)
        self.assertIn("&lt;i&gt;", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
