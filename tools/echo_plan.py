"""声骸组合穷举 + 伤害排名的**命令行**入口(UI 与它共用 `src/echo_panel.py` / `src/echo_combos.py`)。

用法::

    # 先看库存里有什么(有哪些套装可用)
    python tools/echo_plan.py --list

    # 仇远 3+2 样例: 息界同调之律 3 件 + 听唤语义之愿 2 件, 4C 属 A
    python tools/echo_plan.py --mode 3+2 --set-a 息界同调之律 --set-b 听唤语义之愿 --cost4 A \
        --scaling 攻击 --bare 攻击=1200 --bare 暴击=5 --bare 暴击伤害=150 \
        --corr 重击伤害加成=30:套装3件套 --corr 声骸技能伤害加成=16:套装2件套 --corr 气动伤害加成=10:天赋

    # 同一套 5 件
    python tools/echo_plan.py --set-a 隐世回光 --bare 生命=20000 --scaling 生命

参数省略时: 素材取 `logs/eval_debug/` 最新目录(或 `--dir` 指定 / `--inventory <评估JSON>`)。
**契约**: 补正一律视为生效; 伤害只用于排序(`E = 缩放总值 × 双爆区 × 加成区`), 倍率/加深/防御/抗性
在方案内是常数 —— CLI 额外把它折进「伤害」列(与 calculator 对数字用), 排序与「排序分 E」一致。
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.echo_combos import PlanRequest, instance_tag, plan               # noqa: E402
from src.echo_inventory import load_inventory, summarize                  # noqa: E402
from src.echo_panel import Correction, defense_zone, resist_zone               # noqa: E402


def parse_pairs(values, what):
    """`键=值[:来源]` → [(键, 值, 来源)]。"""
    out = []
    for raw in values or []:
        body, _, source = str(raw).partition(":")
        key, _, val = body.partition("=")
        try:
            out.append((key.strip(), float(val), source.strip()))
        except ValueError:
            raise SystemExit(f"{what} 格式应为 `键=值[:来源]`: {raw!r}")
    return out


def build_request(a) -> PlanRequest:
    return PlanRequest(scaling=a.scaling, mode=a.mode, set_a=a.set_a, set_b=a.set_b,
                       cost4_owner=a.cost4.upper(), top_k=a.top, crit_mode=a.crit,
                       max_level_only=not getattr(a, "all_levels", False))


def print_inventory(items, limit=12):
    from src.echo_combos import is_max_level
    s = summarize(items)
    n_max = sum(1 for i in items if is_max_level(i))
    print(f"库存: {s['total']} 只 / {s['names']} 个名字 | COST 分布 {s['by_cost']} | "
          f"满级 {n_max} / 未满级 {s['total'] - n_max}")
    print("套装(只数, 括号内=其中满级):")
    for name, n in list(s["by_set"].items())[:limit]:
        k = sum(1 for i in items if i.set_name == name and is_max_level(i))
        print(f"  {name}: {n}({k})")
    if len(s["by_set"]) > limit:
        print(f"  … 其余 {len(s['by_set']) - limit} 个套装(用 --list-all 看全)")


def print_result(res, req, bare, corrections, args):
    split_zone = {"expect": "期望", "crit": "暴击", "non_crit": "非暴击"}[req.crit_mode]
    zb, rb = defense_zone(args.char_level, args.monster_level, args.def_ignore), resist_zone(args.resist)
    print(f"\n输入: 缩放={req.scaling} | 模式={req.mode}"
          + (f"(A={req.set_a} ×3 + B={req.set_b} ×2, 4C 属 {req.cost4_owner})" if req.mode == "3+2"
             else f"(A={req.set_a} ×5)")
          + f" | 双爆区={split_zone} | 防御区={zb:.4f} 抗性区={rb:.3f}(角色{args.char_level:g}级/怪物"
            f"{args.monster_level:g}级/无视{args.def_ignore:g}%/抗性{args.resist:g}%)")
    print(f"裸面板: " + ", ".join(f"{k}={v:g}" for k, v in sorted(bare.items())))
    print("补正(一律视为生效): " + (", ".join(f"{c.key} +{c.value:g}({c.source or '未标来源'})"
                                              for c in corrections) or "无"))
    print(f"候选 {res.candidates} 只 / {res.names} 个名字 | 评估 {res.evaluated} 组 | "
          f"取前 {len(res.combos)} / 耗时 {res.elapsed:.3f}s"
          + ("" if req.max_level_only else " | **含未满级件**"))
    if not res.combos:
        print("没有合法组合: 检查套装是否有 4C/3C/1C 声骸、ΣCOST≤12 与 4C 归属")
        return
    head = (f"{'名次':<4}{'伤害':>12}{'排序分E':>11}{'ΣCOST':>7}{'套装':>10}{'缩放总值':>11}"
            f"{'暴击/爆伤':>14}{'加成区':>9}  组合")
    print("\n" + head)
    top = res.combos[0].score
    for rank, c in enumerate(res.combos, 1):
        zone = c.panel.bonus_split()
        sets = "+".join(f"{k}{v}" for k, v in sorted(c.set_counts.items()))
        dmg = c.score * zb * rb
        print(f"{rank:<4}{dmg:>12.1f}{c.score:>11.1f}{c.total_cost:>7}{sets:>10}"
              f"{c.panel.scaling_total(req.scaling):>11.1f}"
              f"{c.panel.crit_rate:>6.1f}{'→100' if c.panel.crit_wasted() else '':>4}/{c.panel.crit_dmg:<6.1f}"
              f"{zone['属伤']:>4.0f}+{zone['专伤']:>3.0f}+{zone['通用']:>2.0f}"
              f"  " + " ".join(f"{i.name}{instance_tag(i)}·{i.cost}C" for i in c.items)
              + ("" if c.score == top else f"  (第1名 −{(1 - c.score / top) * 100:.1f}%)"))
    print("\n注: 「排序分 E」= 缩放属性总值 × (1+暴击率×暴击伤害) × (1+加成区), 方案内常数(倍率/加深)"
          "已省略;\n    「伤害」= E × 防御区 × 抗性区(便于与 wuwa-calculator 对数字);\n"
          "    暴击率按 100% 封顶(标 →100 表示溢出, 溢出部分算 0 收益);\n"
          "    名字后的 #N 是实例编号(json#N = 评估记录序号): 同名多只靠它区分是哪一只。")


def main() -> int:
    ap = argparse.ArgumentParser(description="声骸组合穷举 + 伤害排名(离线, 用评估数据)")
    ap.add_argument("--inventory", default="", help="评估 JSON 文件; 省略则用 --dir(默认最新素材目录)")
    ap.add_argument("--dir", default="", help="logs/eval_debug/<时间戳> 素材目录")
    ap.add_argument("--no-icons", action="store_true", help="跳过套装图标识别(快, 但多义名字会退到通用)")
    ap.add_argument("--list", action="store_true", help="只打印库存概览")
    ap.add_argument("--list-all", action="store_true", help="库存概览打印全部套装")
    ap.add_argument("--all-levels", action="store_true",
                    help="把**未满级**件也放进候选池(默认只用满级件 = 5 词条)")
    ap.add_argument("--mode", default="5", choices=("5", "3+2"), help="5 = 同套 5 件; 3+2 = A 3 件 + B 2 件")
    ap.add_argument("--set-a", default="", help="套装 A(3+2 时是 3 件那套, 也是 4C 默认归属)")
    ap.add_argument("--set-b", default="", help="套装 B(3+2 必填, 2 件)")
    ap.add_argument("--cost4", default="A", choices=("A", "B", "a", "b"), help="3+2 时 4C 声骸属于哪套")
    ap.add_argument("--scaling", default="攻击", choices=("攻击", "防御", "生命"), help="缩放属性开关")
    ap.add_argument("--crit", default="expect", choices=("expect", "crit", "non_crit"),
                    help="暴击区口径: 期望 / 单次暴击 / 单次不暴击")
    ap.add_argument("--bare", action="append", default=[], metavar="键=值",
                    help="裸面板(不含声骸); 攻击/生命/防御填**基础值**(角色+武器)。可重复")
    ap.add_argument("--corr", action="append", default=[], metavar="键=值[:来源]",
                    help="补正(套装效果/共鸣链/天赋…), 一律视为生效。可重复")
    ap.add_argument("--top", type=int, default=20, help="输出前 N 名(默认 20)")
    ap.add_argument("--char-level", type=float, default=90, help="角色等级(防御区用)")
    ap.add_argument("--monster-level", type=float, default=100, help="怪物等级(防御区用)")
    ap.add_argument("--def-ignore", type=float, default=0, help="无视防御%%(防御区用)")
    ap.add_argument("--resist", type=float, default=10, help="抗性%%(抗性区用; calculator 默认 20)")
    a = ap.parse_args()

    items = load_inventory(a.inventory or a.dir, use_icons=not a.no_icons)
    print_inventory(items, limit=99 if a.list_all else 12)
    if a.list:
        return 0

    bare = {k: v for k, v, _ in parse_pairs(a.bare, "--bare")}
    corrections = [Correction(k, v, s) for k, v, s in parse_pairs(a.corr, "--corr")]
    req = build_request(a)
    if not req.set_a:
        print("\n需要 --set-a(套装名); 候选套装见上面的库存概览")
        return 2

    res = plan(items, req, bare=bare, corrections=corrections)
    # 遗漏的键(不在键空间里)会进 unknown —— 提示一次, 不静默吞掉
    unknown = sorted({k for c in res.combos for k in c.panel.unknown})
    print_result(res, req, bare, corrections, a)
    if unknown:
        print(f"\n⚠ 这些键不认识, 已忽略(检查拼写/是否属于加成区): {unknown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
