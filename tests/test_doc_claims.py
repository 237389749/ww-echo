"""文档数字自检 —— 把 README / CLAUDE / eval_rules 里**会随数据漂移的数字**变成断言。

动机（2026-10-29 文档审核）：判据层一直是对的，但文档里的"当前值"曾整表过期
（eval_rules §8 的判定分布停在阶段二十一、测试基线停在 122/135、"未定制套装的 B = 通用线"一直是错的）。
把这类数字钉成测试后，**文档写错 = 测试红**，比"写文档时记得回来改"可靠。

跑法（项目根目录）:
    python -m unittest discover -s tests -v
    python tests/test_doc_claims.py

依赖：`assets/echo_set_templates.json`、`assets/gamedata/echo_data.json`、`assets/echo_icons/`。
缺生成物时相关用例 skip（与其余测试一致）。
"""

import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.echo_set_templates import (get_set_weights, load_gamedata,  # noqa: E402
                                    get_all_set_names)
from src.echo_stats import DEFAULT_WEIGHTS, _TIERS, get_mean, snap_to_tier  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# eval_rules.md §3 的"未定制 5 键套装"（= 凝夜白霜 一类）
MATRIX_SET = {"暴击": 1.0, "暴击伤害": 0.7, "攻击百分比": 0.5, "共鸣效率": 0.6, "攻击": 0.25}
MATRIX_KS = [("暴击",), ("暴击", "暴击伤害"), ("暴击", "暴击伤害", "共鸣效率"),
             ("暴击", "暴击伤害", "共鸣效率", "攻击百分比"),
             ("暴击", "暴击伤害", "共鸣效率", "攻击百分比", "攻击")]
# eval_rules §3 的表格（A / 全最低档 / 全平均档 / 全满档）
MATRIX_EXPECT = [(10.0, 8.40, 10.00, 14.00), (17.0, 14.24, 16.95, 23.74),
                 (23.0, 18.58, 22.83, 31.65), (28.0, 22.22, 27.71, 38.24),
                 (30.5, 23.93, 30.00, 41.67)]


def _b_line(weights: dict, tier: int) -> float:
    """基准线 B = 有效键权重升序最低 (tier-1) 条之和 ×10（与 `_legacy_threshold` 同式）。"""
    if tier <= 2:
        return 0.0
    pos = sorted(10 * w for w in weights.values() if w > 0)
    return round(sum(pos[: tier - 1]), 1)


def _set_score(names, weights, mode) -> float:
    total = 0.0
    for n in names:
        m = get_mean(n)
        if mode == "min":
            v = min(_TIERS[n])
        elif mode == "max":
            v = max(_TIERS[n])
        else:
            v = snap_to_tier(n, m)
        total += v / m * 10 * weights[n]
    return total


class TestGamedataClaims(unittest.TestCase):
    """README/CLAUDE 的静态数据数字：37 套 / 229 声骸 / 13 例异相不同套 / 158 名多义 / 37 张图标。"""

    def setUp(self):
        self.gd = load_gamedata()
        if self.gd is None:
            self.skipTest("无 assets/gamedata/echo_data.json")

    def test_counts(self):
        self.assertEqual(len(self.gd["sets"]), 37)
        self.assertEqual(len(self.gd["echoes"]), 229)
        self.assertEqual(len(get_all_set_names()), 37)

    def test_skin_sets_differ_from_base(self):
        echoes = self.gd["echoes"]
        diffs = [n for n in echoes if n.startswith("异相·")
                 and (n.replace("异相·", "", 1) in echoes)
                 and set(echoes[n]["sets"]) != set(echoes[n.replace("异相·", "", 1)]["sets"])]
        self.assertEqual(len(diffs), 13)

    def test_multi_set_names(self):
        multi = [n for n, v in self.gd["echoes"].items() if len(v.get("sets") or []) >= 2]
        self.assertEqual(len(multi), 158)          # CLAUDE: “229 个显示名中 158 个属 ≥2 套装”

    def test_icon_files(self):
        icons = glob.glob(os.path.join(ROOT, "assets", "echo_icons", "*.png"))
        self.assertEqual(len(icons), 37)
        names = {os.path.splitext(os.path.basename(p))[0] for p in icons}
        self.assertEqual(names, set(get_all_set_names()))


class TestBaselineLines(unittest.TestCase):
    """README/CLAUDE/eval_rules 的 B 线口径：通用线 6.5/11.5/17.5, 套装模式按自身权重。"""

    def test_general_line(self):
        gen = {w for w in DEFAULT_WEIGHTS.values() if w > 0}
        for tier, expect in ((3, 6.5), (4, 11.5), (5, 17.5)):
            self.assertAlmostEqual(_b_line({f"k{i}": w for i, w in enumerate(sorted(gen))}, tier), expect)

    def test_set_lines(self):
        cases = {"凝夜白霜": (20.5, 7.5), "隐世回光": (19.0, 4.0), "轻云出月": (4.0, 2.0)}
        for name, (b5, b3) in cases.items():
            w = get_set_weights(name)
            if not w:
                self.skipTest(f"无模板: {name}")
            self.assertAlmostEqual(_b_line(w, 5), b5, msg=f"{name} B(5)")
            self.assertAlmostEqual(_b_line(w, 3), b3, msg=f"{name} B(3)")

    def test_uncustomized_set_is_not_general_line(self):
        """文档旧错："未定制套装 B = 通用线 17.5" —— 凝夜白霜是未定制 5 键套，B(5)=20.5。"""
        w = get_set_weights("凝夜白霜")
        self.assertNotAlmostEqual(_b_line(w, 5), 17.5)


class TestEvalRulesMatrix(unittest.TestCase):
    """eval_rules.md §3 的分类矩阵（A、三档位分数、末列判定）。"""

    def _row(self, names):
        A = round(10 * sum(MATRIX_SET[n] for n in names), 1)
        return (A, _set_score(names, MATRIX_SET, "min"),
                _set_score(names, MATRIX_SET, "mean"), _set_score(names, MATRIX_SET, "max"))

    def test_matrix(self):
        b = _b_line(MATRIX_SET, 5)
        self.assertAlmostEqual(b, 20.5)
        for names, (a, lo, mid, hi) in zip(MATRIX_KS, MATRIX_EXPECT):
            got = self._row(names)
            self.assertAlmostEqual(got[0], a, msg=f"A {names}")
            for g, e, tag in zip(got[1:], (lo, mid, hi), ("min", "mean", "max")):
                self.assertAlmostEqual(g, e, places=2, msg=f"{tag} {names}")

    def test_matrix_verdicts(self):
        """k=3：最低档 18.58 < B → 不合格；平均档 22.83 ∈ [B, A) → 保留；满档 31.65 ≥ A → 达标。
        k=2：最低 14.24 < A(17.0) → 不合格；满档 23.74 ≥ B → 保留。"""
        b = 20.5
        _, lo3, mid3, hi3 = self._row(MATRIX_KS[2])
        self.assertLess(lo3, b)
        self.assertGreaterEqual(mid3, b)
        self.assertLess(mid3, 23.0)
        self.assertGreaterEqual(hi3, 23.0)
        _, lo2, _, hi2 = self._row(MATRIX_KS[1])
        self.assertLess(lo2, 17.0)
        self.assertGreaterEqual(hi2, b)


class TestPercentileAndCompletion(unittest.TestCase):
    """eval_rules §1/§4：r 区间、完成度锚点 43.51。"""

    def test_r_ranges(self):
        lows, highs = [], []
        for name, tiers in _TIERS.items():
            m = get_mean(name)
            lows.append(min(tiers) / m)
            highs.append(max(tiers) / m)
        self.assertAlmostEqual(min(lows), 0.686, places=3)     # 固定攻击
        self.assertAlmostEqual(max(lows), 0.840, places=3)     # 暴击
        self.assertAlmostEqual(min(highs), 1.308, places=3)    # 固定防御
        self.assertAlmostEqual(max(highs), 1.400, places=3)    # 暴击

    def test_completion_anchor(self):
        w = get_set_weights("流金溯真之式")
        if not w:
            self.skipTest("无模板")
        top5 = sorted(w.values(), reverse=True)[:5]
        full = sum(10 * (max(_TIERS[n]) / get_mean(n)) * w[n] for n in w if w[n] in top5 and n in _TIERS)
        self.assertAlmostEqual(full, 43.51, places=2)


class TestDocsHygiene(unittest.TestCase):
    """活文档里不许再出现已更正的旧口径（历史记录 CHANGELOG 除外）。"""

    DOCS = ("README.md", "CLAUDE.md", "eval_rules.md", "handoff.md")
    FORBIDDEN = (
        "122 项",                      # 测试基线（现 156）
        "配置未定制的套装其 B 即通用线",   # B 线口径错误
        "未定制配置的套装 = 通用线",       # 同上（README 旧句）
        "两条线与五档判定",               # eval_rules 标题（六档）
        "`if True:` 开关",               # debug 数据集（现 SAVE_DEBUG_DATASET）
        "（34 套按同一因子折算过一次",      # 现 37 套
        "全部有效词条; 通用 weight>0",     # _core_first 缺省语义（现权重>0）
    )

    def test_no_stale_wording(self):
        for fn in self.DOCS:
            path = os.path.join(ROOT, fn)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for bad in self.FORBIDDEN:
                with self.subTest(doc=fn, stale=bad):
                    self.assertNotIn(bad, text, msg=f"{fn} 仍含旧口径: {bad!r}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
