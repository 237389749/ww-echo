"""统计离线评估报告（B2 产物）的六档判定分布与逐套装分解。

输入: `eval_report.html`（`tools/offline_eval_report.py` 的产物, 默认读仓库根那份）
输出: stdout —— 六档合计 + 逐套装六档表（可直接贴进 `eval_rules.md` §8）
支撑: `eval_rules.md` §8 的六档表/逐套装表 + `docs/BASELINE.md` B2 的期望分布

为什么不用 `data-verdict`: 它只有 pass/hold/keep/pending/fail 五个粗分桶, 而
「不建议强化」与「不合格」都记作 fail —— 六档必须读判定列的中文（`verdict_cn`）。

用法（仓库根）:
    python tools/offline_eval_report.py            # 先生成 eval_report.html
    python tools/analysis/b2_distribution.py [报告.html]
"""

import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TIERS = ["达标", "保留", "建议重铸", "建议强化", "不建议强化", "不合格"]
# 匹配顺序: 「不建议强化」含「建议强化」, 必须先试长的
MATCH_ORDER = ["建议重铸", "不建议强化", "建议强化", "达标", "保留", "不合格"]


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "eval_report.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    rows = re.findall(r"<tr (data-score=.*?)</tr>", html, re.S)

    total = Counter()
    by_set = defaultdict(Counter)
    for r in rows:
        set_name = re.search(r'data-set="([^"]*)"', r).group(1)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        cn = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        hit = next((t for t in MATCH_ORDER if any(t in c for c in cn)), None)
        total[hit] += 1
        by_set[set_name][hit] += 1

    print(f"报告: {path}")
    print("行数:", len(rows))
    print("六档:", {t: total[t] for t in TIERS}, "Σ", sum(total.values()))
    print()
    print("| 套装 | " + " | ".join(TIERS) + " | Σ |")
    for name in sorted(by_set, key=lambda x: -sum(by_set[x].values())):
        c = by_set[name]
        print(f"| {name} | " + " | ".join(str(c[t]) for t in TIERS) + f" | {sum(c.values())} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
