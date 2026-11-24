"""
队伍声骸组合分析 —— 7 角色 / 4 队 / 仇远 3+2 与 5 对比。

输入: 评估产物 JSON（默认 eval_report6.json，160 条 / 131 满级；rep7 听唤满级件更少且有 OCR 变体）。
输出: team_plan.json / team_plan.md / *.csv（本脚本）；xlsx 由 team_plan_xlsx.py 生成。
开关: `--gates` 打开共效/暴击门槛系数（默认关闭，见下方口径 2）。

口径（与 src/echo_panel.py 一致，另外补了三条本任务必需的限制）:
1. 面板 = 基础值 × (1 + 百分比/100) + 固定值；裸面板的 攻击 用加号前的数值作百分比基底，
   加号后的部分是技能树默认攻击%已折算成固定值（零新百分比时仍等于用户给的 965/1300/...）。
2. E = 缩放总值 × (1 + min(暴击,100)/100 × 暴伤/100) × (1 + 加成区/100)；
   不计加深/抗性/防御。项目的共效/暴击门槛系数默认**关闭**（纯伤害口径，用户未给循环要求）；
   `--gates` 打开后 E 再乘 `循环系数 × 稳定性系数`（共效 120/0.30/0.85、暴击 100/0.40/0.80），
   见 src/echo_combos.gap_factor 与 docs/TEAM_PANEL_SUMMARY_2026-11-24.md §6.4。
3. 3C 主属性必须与角色元素一致（异元素主属性对角色无效）；4C 主属性不限。
4. 默认输出固定 43311（1×4C + 2×3C + 2×1C）；仇远 3+2 另给无 4C 的 33311。
5. 套装评分和用报告里的套装权重（item.score）；通用评分另算，仅作对照。
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
while not (ROOT / "src").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

from src.echo_combos import (PlanRequest, candidate_pool, _by_name, is_max_level,
                             energy_factor, crit_factor, instance_tag)
from src.echo_inventory import item_from_record, drop_exact_duplicates
from src.echo_panel import (aggregate, damage, Correction, DerivedBonus, ELEMENT_KEYS,
                            is_bonus_key, bonus_group)
from src.echo_scoring import compute_weighted_score
from src.echo_set_templates import verify_echo_name
from src.echo_stats import generic_weights_for_main

# ---------------------------------------------------------------- 输入配置

# 门槛系数开关（共效/暴击缺口线性打折，默认参数见 src/echo_combos.PlanRequest）：
#   系数 = max(最低, 1 − 斜率 × (目标 − 值) / 目标)，值 ≥ 目标 → 1.0（只减不增）
#   共效：目标 120 / 斜率 0.30 / 最低 0.85；暴击：目标 100 / 斜率 0.40 / 最低 0.80
# 默认口径（2026-11-24 两次调整后）：
#   共效循环系数 **打开**（低共效影响循环，是真实约束）；
#   暴击稳定性系数 **关闭** —— 挑战可无限重开，波折不构成成本，期望值本身就是最优目标；
#   再叠一层按暴击率的惩罚等于把暴击率计两次，还会让跨角色 E 不可比。`--crit-gate` 可开回来。
#   `--no-gates` 两个都关 = 纯伤害口径。
USE_GATES = True
USE_CRIT_GATE = False

# 4C 主词条假设：把每只 4C 的**主词条**换成暴伤 44（副词条/等级不动），副本与原件同名 ——
# 用来回答「4C 主属性该选暴击 22 还是暴伤 44」。`--swap4c` 打开（默认关，因为它是假设件）。
USE_SWAP4C = False
SWAP4C_MAIN = ("暴击伤害", 44.0)

# 3C 主词条假设：把 3C 的**元素增伤主词条**换成攻击% 30（副词条不动），副本与原件同名。
# `--swap3c 方案key[,key]` 只对指定方案注入（默认全局会让所有角色都看到这批假件，容易误读）。
SWAP3C_KEYS: set[str] = set()
SWAP3C_MAIN = ("攻击百分比", 30.0)


def C(key, value, source):
    return Correction(key, value, source)


def _bare(atk, energy, crit, cdmg, bonus_key=None, bonus=0.0):
    d = {"攻击": atk, "共鸣效率": energy, "暴击": crit, "暴击伤害": cdmg}
    if bonus_key:
        d[bonus_key] = bonus
    return d


@dataclass(frozen=True)
class PlanSpec:
    key: str
    character: str
    role: str
    team: str
    element: str
    mode: str
    set_a: str
    set_b: str
    cost4_owner: str
    bare: dict
    corrections: tuple
    allowed_bonus: tuple | None
    derived: tuple = ()
    note: str = ""


PLANS: tuple[PlanSpec, ...] = (
    PlanSpec(
        key="sanhua", character="散华", role="副C", team="散华+陆赫斯 / 散华+绯雪",
        element="冷凝", mode="5", set_a="轻云出月", set_b="", cost4_owner="",
        bare=_bare(862, 116, 29.3, 150, "冷凝伤害加成", 12),
        corrections=(
            C("攻击", 103, "裸面板默认攻击%（12%）已折算：965=862+103"),
            C("攻击百分比", 15, "武器 15% 攻击"),
            C("冷凝伤害加成", 20, "角色 20 增伤"),
            C("攻击百分比", 20, "共鸣链 20% 攻击（全队，含自身）"),
            C("攻击百分比", 45, "奶妈 25%+20% 全队攻击"),
            C("共鸣效率", 10, "轻云出月 2 件套"),
        ),
        allowed_bonus=("共鸣解放伤害加成", "共鸣技能伤害加成"),
        note="轻云 5 的 22.5% 攻击 +12 增伤给主C，不计入散华自身；20% 攻击共鸣链全队含自身。",
    ),
    PlanSpec(
        key="luhesis", character="陆赫斯", role="主C", team="散华+陆赫斯",
        element="衍射", mode="5", set_a="流金溯真之式", set_b="", cost4_owner="",
        bare=_bare(1049, 100, 37.3, 150),
        corrections=(
            C("攻击", 251, "裸面板默认攻击%（24%）已折算：1300=1049+251"),
            C("攻击百分比", 25, "角色 25% 攻击"),
            C("通用增伤", 20, "武器 20% 增伤"),
            C("衍射伤害加成", 40, "流金 2+5 件套：衍射 10+30"),
            C("普攻伤害加成", 40, "流金 5 件套：满层普攻 40"),
            C("攻击百分比", 20, "散华共鸣链 20% 全队攻击"),
            C("攻击百分比", 22.5, "散华轻云 5 件套（主C）"),
            C("通用增伤", 12, "散华轻云 5 件套：主C 12 增伤"),
            C("攻击百分比", 45, "奶妈 25%+20% 全队攻击"),
        ),
        allowed_bonus=("普攻伤害加成",),
        note="散华给全队 20% 攻击、轻云 22.5% 攻击 +12 增伤；她的 20 增伤是单人的，不计。",
    ),
    PlanSpec(
        key="dania", character="达妮娅", role="副C", team="达妮娅+爱弥斯",
        element="热熔", mode="5", set_a="轻云出月", set_b="", cost4_owner="",
        bare=_bare(925, 100, 41, 166),
        corrections=(
            C("攻击", 221, "裸面板默认攻击%（24%）已折算：1146=925+221"),
            C("攻击百分比", 30, "角色 30% 攻击"),
            C("通用增伤", 36, "角色 36 增伤"),
            C("通用增伤", 30, "全队 30 增伤（含自身）"),
            C("共鸣效率", 10, "轻云出月 2 件套"),
            C("攻击百分比", 45, "奶妈 25%+20% 全队攻击"),
        ),
        allowed_bonus=("共鸣解放伤害加成",),
        note="武器 24% 是爱弥斯的武器，计给爱弥斯；轻云 5 的 22.5% 攻击 +12 增伤也给爱弥斯，不计入达妮娅自身。",
    ),
    PlanSpec(
        key="aemis", character="爱弥斯", role="主C", team="达妮娅+爱弥斯",
        element="热熔", mode="5", set_a="长路启航之星", set_b="", cost4_owner="",
        bare=_bare(1012, 100, 37.3, 150, "热熔伤害加成", 12),
        corrections=(
            C("攻击", 121, "裸面板默认攻击%（12%）已折算：1133=1012+121"),
            C("攻击百分比", 24, "爱弥斯武器 24% 攻击"),
            C("暴击", 20, "长路 5 件套"),
            C("热熔伤害加成", 30, "长路 2+5 件套：热熔 10+20"),
            C("暴击伤害", 60, "角色 60 暴伤"),
            C("攻击百分比", 22.5, "达妮娅轻云 5 件套（主C）"),
            C("通用增伤", 12, "达妮娅轻云 5 件套：主C 12 增伤"),
            C("攻击百分比", 45, "奶妈 25%+20% 全队攻击"),
            C("通用增伤", 30, "达妮娅全队 30 增伤"),
        ),
        allowed_bonus=("共鸣解放伤害加成",),
        note="武器 24% 攻击已计入；轻云 5 给 22.5% 攻击 +12 增伤；裸面板 12 增伤视为武器/技能树已在面板里；达妮娅 36 增伤是单人的。",
    ),
    PlanSpec(
        key="qiuyuan32", character="仇远", role="副C", team="仇远+西格莉卡（3+2）",
        element="气动", mode="3+2", set_a="息界同调之律", set_b="轻云出月", cost4_owner="B",
        bare=_bare(962, 100, 57.3, 150),
        corrections=(
            C("攻击", 230, "裸面板默认攻击%（24%）已折算：1192=962+230"),
            C("攻击百分比", 10, "角色 10 攻击（按 10% 计）"),
            C("通用增伤", 50, "角色 50 增伤"),
            C("通用增伤", 30, "全队 30 增伤（含自身）"),
            C("暴击伤害", 30, "全队 30 暴伤（含自身）"),
            C("重击伤害加成", 60, "武器 60% 重击"),
            C("重击伤害加成", 30, "息界同调之律 3 件套：重击 30"),
            C("声骸技能伤害加成", 16, "息界同调之律 3 件套：队伍声骸技能 16（计入仇远自身）"),
            C("声骸技能伤害加成", 20, "武器：队伍声骸技能 20（计入仇远自身）"),
            C("共鸣效率", 10, "轻云出月 2 件套"),
            C("攻击百分比", 45, "奶妈 25%+20% 全队攻击"),
        ),
        allowed_bonus=("重击伤害加成",),
        note="按你的口径，息界 16% + 武器 20% 的「队伍声骸技能」计入仇远自身增伤；息界 2 件套气动10 未计入你的 206。",
    ),
    PlanSpec(
        key="qiuyuan5", character="仇远", role="副C", team="仇远+西格莉卡（轻云 5）",
        element="气动", mode="5", set_a="轻云出月", set_b="", cost4_owner="",
        bare=_bare(962, 100, 57.3, 150),
        corrections=(
            C("攻击", 230, "裸面板默认攻击%（24%）已折算：1192=962+230"),
            C("攻击百分比", 10, "角色 10 攻击（按 10% 计）"),
            C("通用增伤", 50, "角色 50 增伤"),
            C("通用增伤", 30, "全队 30 增伤（含自身）"),
            C("暴击伤害", 30, "全队 30 暴伤（含自身）"),
            C("重击伤害加成", 60, "武器 60% 重击"),
            C("声骸技能伤害加成", 20, "武器：队伍声骸技能 20（计入仇远自身）"),
            C("共鸣效率", 10, "轻云出月 2 件套"),
            C("攻击百分比", 45, "奶妈 25%+20% 全队攻击"),
        ),
        allowed_bonus=("重击伤害加成",),
        note="轻云 5 的 22.5% 攻击 +12 增伤给西格莉卡；仇远自身失去息界的 重击30+声骸16，但武器声骸20仍计入。",
    ),
    PlanSpec(
        key="sigrika32", character="西格莉卡", role="主C", team="仇远+西格莉卡（仇远 3+2）",
        element="气动", mode="5", set_a="听唤语义之愿", set_b="", cost4_owner="",
        bare=_bare(1024, 100, 13, 198.6),
        corrections=(
            C("攻击", 245, "裸面板默认攻击%（24%）已折算：1269=1024+245"),
            C("暴击", 20, "听唤 5 件套"),
            C("气动伤害加成", 25, "听唤 2+5 件套：气动 10+15"),
            C("气动伤害加成", 96, "角色 96 增伤"),
            C("通用增伤", 30, "仇远全队 30 增伤"),
            C("暴击伤害", 30, "仇远全队 30 暴伤"),
            C("声骸技能伤害加成", 36, "仇远息界 3 件套 16 + 武器 20（队伍声骸技能）"),
            C("攻击百分比", 45, "奶妈 25%+20% 全队攻击"),
        ),
        allowed_bonus=(),
        derived=(DerivedBonus("共鸣效率", 125, 2, 50, "通用增伤", "天赋：共效>125 每点 +2 增伤，上限 50"),),
        note="不吃专伤；共效天赋按最终面板逐组合计算。仇远 3+2 不给轻云 22.5% 攻击。",
    ),
    PlanSpec(
        key="sigrika5", character="西格莉卡", role="主C", team="仇远+西格莉卡（仇远轻云 5）",
        element="气动", mode="5", set_a="听唤语义之愿", set_b="", cost4_owner="",
        bare=_bare(1024, 100, 13, 198.6),
        corrections=(
            C("攻击", 245, "裸面板默认攻击%（24%）已折算：1269=1024+245"),
            C("暴击", 20, "听唤 5 件套"),
            C("气动伤害加成", 25, "听唤 2+5 件套：气动 10+15"),
            C("气动伤害加成", 96, "角色 96 增伤"),
            C("通用增伤", 30, "仇远全队 30 增伤"),
            C("暴击伤害", 30, "仇远全队 30 暴伤"),
            C("声骸技能伤害加成", 20, "仇远武器 20（队伍声骸技能）"),
            C("攻击百分比", 45, "奶妈 25%+20% 全队攻击"),
            C("攻击百分比", 22.5, "仇远轻云 5 件套（主C）"),
            C("通用增伤", 12, "仇远轻云 5 件套：主C 12 增伤"),
        ),
        allowed_bonus=(),
        derived=(DerivedBonus("共鸣效率", 125, 2, 50, "通用增伤", "天赋：共效>125 每点 +2 增伤，上限 50"),),
        note="仇远轻云 5 给 22.5% 攻击 +12 增伤，队伍声骸技能只有武器的 20%（没有息界 16%）。",
    ),
    PlanSpec(
        key="feixue", character="绯雪", role="主C", team="散华+绯雪",
        element="冷凝", mode="5", set_a="雪落无声之愿", set_b="", cost4_owner="",
        bare=_bare(1049, 100, 37.3, 150),
        corrections=(
            C("攻击", 251, "裸面板默认攻击%（24%）已折算：1300=1049+251"),
            C("暴击", 25, "雪落 5 件套"),
            C("冷凝伤害加成", 20, "雪落 2+5 件套：冷凝 10+10"),
            C("暴击伤害", 40, "角色 40 暴伤"),
            C("攻击百分比", 20, "散华共鸣链 20% 全队攻击"),
            C("攻击百分比", 22.5, "散华轻云 5 件套（主C）"),
            C("通用增伤", 12, "散华轻云 5 件套：主C 12 增伤"),
            C("攻击百分比", 45, "奶妈 25%+20% 全队攻击"),
        ),
        allowed_bonus=("共鸣解放伤害加成",),
        note="散华轻云5给 22.5% 攻击 +12 增伤；雪落 5 的「下一个角色冷凝 +25%」不是绯雪自己。",
    ),
)

# ---------------------------------------------------------------- 计算

@dataclass
class Row:
    combo: tuple
    panel: object
    score: float
    score_raw: float
    score_sum: float
    generic_sum: float
    score_missing: int


def clean_inventory(path: str):
    """评估 JSON → EchoItem；用套装清单反查纠正高置信 OCR 名，再折掉完全重复。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for rec in data.get("results") or []:
        it = item_from_record(rec)
        if it is None:
            continue
        fixed = verify_echo_name(it.name, it.set_name, it.cost, rec.get("set_src", ""))
        if fixed["src"] == "set-fix":
            it = dataclass_replace(it, name=fixed["name"])
        out.append(it)
    return drop_exact_duplicates(out)


def dataclass_replace(it, **kw):
    from dataclasses import replace
    return replace(it, **kw)


def swap4c_variants(items):
    """给每只 4C 追加一个「主词条 = 暴伤 44」的副本（副词条/等级/套装不动）。

    `--swap4c` 打开：副本与原件**同名同套装**，所以同一只 4C 在组合里只会出现一个版本
    （`_by_name` 按名字分组），不会出现"暴击版和暴伤版一起上"。
    用途：库存里的 4C 如果清一色暴击主词条（如轻云出月 4 只全是暴击 22），
    直接结论会是"无 4C 的 33311 更好"；这个假设用来回答"换成暴伤 4C 会不会更好"。
    """
    out = list(items)
    for it in items:
        if it.cost != 4 or not it.main or it.main[0][0] == SWAP4C_MAIN[0]:
            continue
        stats = list(it.stats)
        if stats and stats[0] == it.main[0]:
            stats[0] = SWAP4C_MAIN
        out.append(dataclass_replace(
            it,
            main=(SWAP4C_MAIN,) + tuple(it.main[1:]),
            stats=tuple(stats),
            source=(it.source or "") + "|swap4c",
        ))
    return out


def swap3c_variants(items):
    """给每只「主词条 = 元素增伤」的 3C 追加一个「主词条 = 攻击% 30」的副本。

    只对 `SWAP3C_KEYS` 里的方案注入（`--swap3c`），否则所有角色都会看到这批假件。
    用途：元素增伤堆到 200+ 之后边际很低，而攻击% 乘的是角色白值 —— 用来验证
    「3C 主属性选属伤还是攻击%」。
    """
    out = list(items)
    for it in items:
        if it.cost != 3 or not it.main:
            continue
        key, _val = it.main[0]
        if key not in ELEMENT_KEYS:
            continue
        stats = list(it.stats)
        if stats and stats[0] == it.main[0]:
            stats[0] = SWAP3C_MAIN
        out.append(dataclass_replace(
            it,
            main=(SWAP3C_MAIN,) + tuple(it.main[1:]),
            stats=tuple(stats),
            source=(it.source or "") + "|swap3c",
        ))
    return out


def element_ok(item, element: str) -> bool:
    """3C/4C 元素主属性必须与角色同元素；非元素主属性（攻击/共效等）不限。"""
    if not item.main:
        return True
    key = item.main[0][0]
    if key in ELEMENT_KEYS:
        return key == f"{element}伤害加成"
    return True


def layout_counts(combo) -> tuple[int, int, int]:
    """(4C 只数, 3C 只数, 1C 只数)。"""
    n = {1: 0, 3: 0, 4: 0}
    for it in combo:
        n[it.cost] = n.get(it.cost, 0) + 1
    return n.get(4, 0), n.get(3, 0), n.get(1, 0)


def layout_name(counts: tuple[int, int, int]) -> str:
    """(1,2,2) -> 43311；(0,3,2) -> 33311；(1,1,3) -> 43111。"""
    n4, n3, n1 = counts
    return "4" * n4 + "3" * n3 + "1" * n1


def generic_score(item) -> float:
    subs = item.stats[len(item.main):]
    main_name = item.main[0][0] if item.main else None
    gw = generic_weights_for_main(main_name)
    return round(compute_weighted_score([(n, str(v)) for n, v in subs], weights=gw)[0], 2)


def enumerate_rows(items, spec: PlanSpec, require_4c: bool):
    gate_kwargs = {}
    if not USE_GATES:
        gate_kwargs["energy_min"] = 0
    if not (USE_GATES and USE_CRIT_GATE):
        gate_kwargs["crit_target"] = 0
    req = PlanRequest(scaling="攻击", mode=spec.mode, set_a=spec.set_a, set_b=spec.set_b,
                      cost4_owner=spec.cost4_owner, top_k=10,
                      allowed_bonus=spec.allowed_bonus, derived=spec.derived,
                      **gate_kwargs)
    pool_items = swap4c_variants(items) if USE_SWAP4C else items
    if spec.key in SWAP3C_KEYS:
        pool_items = swap3c_variants(pool_items)
    pool = [it for it in candidate_pool(pool_items, req) if element_ok(it, spec.element)]
    gscore = {it: generic_score(it) for it in pool}
    groups = _by_name(pool)
    name_set, name_cost = {}, {}
    for name, its in groups.items():
        sets = {i.set_name for i in its}
        costs = {i.cost for i in its}
        if len(sets) > 1 or len(costs) > 1:
            raise ValueError(f"同名声骸的套装/COST 不一致: {name} {sets} {costs}")
        name_set[name] = its[0].set_name
        name_cost[name] = its[0].cost

    names_a = sorted(n for n, s in name_set.items() if s == spec.set_a)
    names_b = sorted(n for n, s in name_set.items() if s == spec.set_b) if spec.mode == "3+2" else []
    if spec.mode == "5":
        name_combos = itertools.combinations(names_a, 5)
    else:
        name_combos = ((*a, *b) for a in itertools.combinations(names_a, 3)
                       for b in itertools.combinations(names_b, 2))
    owner_set = spec.set_a if spec.cost4_owner == "A" else spec.set_b
    allowed = spec.allowed_bonus if spec.allowed_bonus is not None else ()
    rows = []
    evaluated = 0
    for names in name_combos:
        if sum(name_cost[n] for n in names) > 12:
            continue
        if require_4c and not any(name_cost[n] == 4 for n in names):
            continue
        if spec.mode == "3+2" and any(name_cost[n] == 4 and name_set[n] != owner_set for n in names):
            continue
        for combo in itertools.product(*(groups[n] for n in names)):
            evaluated += 1
            panel = aggregate(spec.bare, spec.corrections, (s for it in combo for s in it.stats),
                              allowed_bonus=allowed, derived=spec.derived)
            raw = damage(panel, "攻击", crit_mode="expect")
            fe = energy_factor(panel.energy, req.energy_min, req.energy_slope, req.energy_floor)
            fc = crit_factor(panel.crit_rate, req.crit_target, req.crit_slope, req.crit_floor)
            vals = [i.score for i in combo if i.score is not None]
            rows.append(Row(combo, panel, raw * fe * fc, raw, round(sum(vals), 2),
                            round(sum(gscore[i] for i in combo), 2), len(combo) - len(vals)))
    rows.sort(key=lambda r: -r.score)
    return rows, pool, evaluated


def row_dict(row: Row, rank: int, top_score: float):
    p = row.panel
    split = p.bonus_split()
    return {
        "rank": rank,
        "items": [{
            "name": i.name, "tag": instance_tag(i), "cost": i.cost, "set": i.set_name,
            "main": [{"name": k, "value": v} for k, v in i.main],
            "stats": [{"name": k, "value": v} for k, v in i.stats[len(i.main):]],
            "score": i.score, "source": i.source,
            "hypo4c": "|swap4c" in (i.source or ""),
            "hypo3c": "|swap3c" in (i.source or ""),
        } for i in row.combo],
        "total_cost": sum(i.cost for i in row.combo),
        "has_4c": any(i.cost == 4 for i in row.combo),
        "base": {k: round(v, 1) for k, v in p.base.items()},
        "flat": {k: round(v, 1) for k, v in p.flat.items()},
        "pct": {k: round(v, 1) for k, v in p.pct.items()},
        "attack": round(p.scaling_total("攻击"), 1),
        "crit": round(p.crit_rate, 1),
        "crit_dmg": round(p.crit_dmg, 1),
        "energy": round(p.energy, 1),
        "bonus": round(p.bonus_zone(), 1),
        "bonus_split": {k: round(v, 1) for k, v in split.items()},
        "bonus_detail": {k: round(v, 1) for k, v in p.bonus.items()},
        "derived": {k: round(v, 1) for k, v in p.derived.items()},
        "ignored_bonus": {k: round(v, 1) for k, v in p.ignored_bonus.items()},
        "score": round(row.score, 1),
        "score_raw": round(row.score_raw, 1),
        "score_sum": row.score_sum,
        "generic_sum": row.generic_sum,
        "gap_pct": round((top_score - row.score) / top_score * 100, 2),
    }


def best_row(rows, key):
    return max(rows, key=lambda r: (key(r), r.score))


def build_for_spec(items, spec: PlanSpec):
    rows_all, pool, eval_all = enumerate_rows(items, spec, require_4c=False)
    if not rows_all:
        raise RuntimeError(f"{spec.character}: 没有合法组合（检查套装/COST/元素）")

    def by_layout(counts):
        return [r for r in rows_all if layout_counts(r.combo) == counts]

    rows_43311 = by_layout((1, 2, 2))
    rows_33311 = by_layout((0, 3, 2))
    rows_43111 = by_layout((1, 1, 3))
    if not rows_43311:
        raise RuntimeError(f"{spec.character}: 没有 43311 组合")

    e_all = rows_all[0]
    e433 = rows_43311[0]
    e333 = rows_33311[0] if rows_33311 else None
    s_all = best_row(rows_all, lambda r: r.score_sum)
    s433 = best_row(rows_43311, lambda r: r.score_sum)
    s333 = best_row(rows_33311, lambda r: r.score_sum) if rows_33311 else None
    g433 = best_row(rows_43311, lambda r: r.generic_sum)

    # 裸面板 + 补正（**不含声骸**）—— 用来核对"带武器裸面板 + 各种面板补正"的合计数
    bp = aggregate(spec.bare, spec.corrections, [],
                   allowed_bonus=spec.allowed_bonus if spec.allowed_bonus is not None else (),
                   derived=())
    bp_split = bp.bonus_split()
    base_panel = {
        "base": {k: round(v, 1) for k, v in bp.base.items()},
        "flat": {k: round(v, 1) for k, v in bp.flat.items()},
        "pct": {k: round(v, 1) for k, v in bp.pct.items()},
        "attack": round(bp.scaling_total("攻击"), 1),
        "crit": round(bp.crit_rate, 1),
        "crit_dmg": round(bp.crit_dmg, 1),
        "energy": round(bp.energy, 1),
        "bonus": round(bp.bonus_zone(), 1),
        "bonus_split": {k: round(v, 1) for k, v in bp_split.items()},
        "bonus_detail": {k: round(v, 1) for k, v in bp.bonus.items()},
    }

    def gap_pct(a, b):
        return round((a - b) / a * 100, 2) if a else None

    result = {
        "key": spec.key, "character": spec.character, "role": spec.role, "team": spec.team,
        "element": spec.element, "mode": spec.mode, "set_a": spec.set_a, "set_b": spec.set_b,
        "cost4_owner": spec.cost4_owner, "note": spec.note,
        "bare": spec.bare,
        "base_panel": base_panel,
        "corrections": [{"key": c.key, "value": c.value, "source": c.source} for c in spec.corrections],
        "allowed_bonus": list(spec.allowed_bonus) if spec.allowed_bonus is not None else None,
        "derived": [{"source": d.source, "threshold": d.threshold, "per_point": d.per_point,
                     "cap": d.cap, "key": d.key, "label": d.label} for d in spec.derived],
        "candidates": len(pool), "evaluated": eval_all,
        "evaluated_43311": len(rows_43311), "evaluated_33311": len(rows_33311),
        "top": [row_dict(r, k, e433.score) for k, r in enumerate(rows_43311[:10], 1)],
        "best": row_dict(e433, 1, e433.score),
        "best_all": row_dict(e_all, 1, e_all.score),
        "best_33311": row_dict(e333, 1, e333.score) if e333 else None,
        "score_best": row_dict(s433, 1, s433.score),
        "score_best_all": row_dict(s_all, 1, s_all.score),
        "score_best_33311": row_dict(s333, 1, s333.score) if s333 else None,
        "generic_best": row_dict(g433, 1, g433.score),
        "all_layout": layout_name(layout_counts(e_all.combo)),
        "score_best_all_layout": layout_name(layout_counts(s_all.combo)),
        "has_33311": bool(rows_33311),
        "has_43111": bool(rows_43111),
        "all_vs_43311_pct": round((e_all.score - e433.score) / e433.score * 100, 2),
        "score_gap_all_pct": gap_pct(e_all.score, s_all.score),
        "score_gap_pct": gap_pct(e433.score, s433.score),
        "generic_gap_pct": gap_pct(e433.score, g433.score),
        "score_rank": rows_43311.index(s433) + 1,
        "generic_rank": rows_43311.index(g433) + 1,
        "33311_vs_43311_pct": round((e333.score - e433.score) / e433.score * 100, 2) if e333 else None,
        "33311_score_gap_pct": gap_pct(e333.score, s333.score) if s333 else None,
        "33311_advantage_pct": round((e333.score - e433.score) / e433.score * 100, 2) if e333 else None,
    }
    return result


def build(inventory_path: str):
    items = clean_inventory(inventory_path)
    plans = [build_for_spec(items, spec) for spec in PLANS]
    by_key = {p["key"]: p for p in plans}

    def e(key):
        """43311 最优 E。"""
        return by_key[key]["best"]["score"]

    def e333(key):
        """33311（无 4C）最优 E；没有该布局时返回 None。"""
        b = by_key[key]["best_33311"]
        return b["score"] if b else None

    teams = {}
    teams["散华+陆赫斯"] = {"sub": "散华", "main": "陆赫斯", "sub_E": e("sanhua"),
                              "main_E": e("luhesis"), "sum": round(e("sanhua") + e("luhesis"), 1)}
    teams["达妮娅+爱弥斯"] = {"sub": "达妮娅", "main": "爱弥斯", "sub_E": e("dania"),
                                "main_E": e("aemis"), "sum": round(e("dania") + e("aemis"), 1)}
    teams["散华+绯雪"] = {"sub": "散华", "main": "绯雪", "sub_E": e("sanhua"),
                            "main_E": e("feixue"), "sum": round(e("sanhua") + e("feixue"), 1)}
    teams["仇远+西格莉卡（3+2 标准43311）"] = {
        "sub": "仇远", "main": "西格莉卡", "sub_E": e("qiuyuan32"), "main_E": e("sigrika32"),
        "sum": round(e("qiuyuan32") + e("sigrika32"), 1)}
    teams["仇远+西格莉卡（3+2 无4C 33311）"] = {
        "sub": "仇远", "main": "西格莉卡",
        "sub_E": e333("qiuyuan32"),
        "main_E": e("sigrika32"),
        "sum": round((e333("qiuyuan32") or 0) + e("sigrika32"), 1)}
    teams["仇远+西格莉卡（轻云5 43311）"] = {
        "sub": "仇远", "main": "西格莉卡", "sub_E": e("qiuyuan5"), "main_E": e("sigrika5"),
        "sum": round(e("qiuyuan5") + e("sigrika5"), 1)}

    t32_43311 = e("qiuyuan32") + e("sigrika32")
    t32_33311 = (e333("qiuyuan32") or 0) + e("sigrika32")
    t5 = e("qiuyuan5") + e("sigrika5")
    d_sub_43311 = e("qiuyuan32") - e("qiuyuan5")
    d_sub_33311 = (e333("qiuyuan32") or 0) - e("qiuyuan5")
    d_main = e("sigrika32") - e("sigrika5")
    ratio_43311 = d_sub_43311 / (-d_main) if d_main else None
    ratio_33311 = d_sub_33311 / (-d_main) if d_main else None
    qiuyuan_compare = {
        "team32_43311": round(t32_43311, 1), "team32_33311": round(t32_33311, 1),
        "team5": round(t5, 1),
        "delta_43311": round(t32_43311 - t5, 1),
        "delta_43311_pct": round((t32_43311 - t5) / t5 * 100, 2),
        "delta_33311": round(t32_33311 - t5, 1),
        "delta_33311_pct": round((t32_33311 - t5) / t5 * 100, 2),
        "sub_delta_43311": round(d_sub_43311, 1),
        "sub_delta_33311": round(d_sub_33311, 1),
        "main_delta": round(d_main, 1),
        "main_share_breakeven_43311_pct": round(ratio_43311 / (1 + ratio_43311) * 100, 1) if ratio_43311 else None,
        "main_share_breakeven_33311_pct": round(ratio_33311 / (1 + ratio_33311) * 100, 1) if ratio_33311 else None,
    }

    return {
        "inventory": inventory_path,
        "inventory_count": len(items),
        "max_level_count": sum(is_max_level(i) for i in items),
        "plans": plans,
        "teams": teams,
        "qiuyuan_compare": qiuyuan_compare,
    }


# ---------------------------------------------------------------- 输出

def fmt_items(row):
    return " + ".join(f"{i['name']}{i['tag']}·{i['cost']}C" for i in row["items"])


def write_markdown(data, path):
    plans = data["plans"]
    L = []
    A = L.append
    A("# 鸣潮 7 角色声骸组合与队伍面板分析\n")
    A(f"- 库存：`{os.path.basename(data['inventory'])}`（{data['inventory_count']} 只，满级 {data['max_level_count']} 只）")
    A("- 伤害口径：`E = 攻击 × (1+暴击×暴伤) × (1+增伤)`；不计加深/抗性/防御。"
      + ("口径：" + ("共效循环系数 **开**（120/0.30/0.85）、"
                    if USE_GATES else "两个系数都关（`--no-gates`）、")
         + ("暴击稳定性系数 **开**（100/0.40/0.80）" if USE_CRIT_GATE else
            "暴击稳定性系数 **关**（可无限重开，波折不构成成本；`--crit-gate` 可开）")
         + "。表里的 E = 纯伤害 × 生效的系数。"))
    if USE_SWAP4C:
        A("- **4C 主词条假设**（`--swap4c`）：每只 4C 额外提供一个「主词条 = 暴伤 44」的副本"
          "（副词条/等级/套装不动，与原件同名），用来比较 4C 主属性选暴击还是暴伤。"
          "标了「假设」的件在库存里并不存在。")
    A("- 3C 主属性只保留与角色同元素；标准结果固定 43311（1×4C + 2×3C + 2×1C）。")
    A("- 单位是相对指数，不是实战 DPS；队伍合计按 1:1 权重，另给仇远队的临界主C占比。\n")

    A("## 一、总览（默认 43311）\n")
    A("| 角色 | 定位 | 队伍 | 套装 | 43311最优E | 33311最优E | 全排列最优布局 | 攻击 | 暴击/暴伤 | 共效 | 增伤 | 43311 的5只 |")
    A("|---|---|---|---|---:|---:|---|---:|---|---:|---:|---|")
    for p in plans:
        b = p["best"]
        b333 = p["best_33311"]
        b333_txt = f"{b333['score']:.1f}" if b333 else "—"
        A(f"| {p['character']} | {p['role']} | {p['team']} | {p['set_a']}"
          + (f"+{p['set_b']}" if p['mode'] == '3+2' else "")
          + f" | {b['score']:.1f} | {b333_txt} | {p['all_layout']} | {b['attack']:.0f} | "
            f"{b['crit']:.1f}/{b['crit_dmg']:.1f} | {b['energy']:.1f} | {b['bonus']:.1f} | {fmt_items(b)} |")
    A("")
    A("> 43311 = 1×4C + 2×3C + 2×1C；33311 = 0×4C + 3×3C + 2×1C（需要 3 个不同 3C 名字；"
      "流金只有 2 个，故陆赫斯为 —）。「全排列最优布局」= 不限布局时的最优；除仇远 3+2 外都是 43311。")
    A("")

    A("## 一.5、面板补正（裸面板 + 补正，不含声骸）\n")
    A("| 角色 | 裸攻击 | 攻击%补正 | 固定攻击 | 攻击总值 | 暴击 | 暴伤 | 共效 | 增伤 | 备注 |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for p in plans:
        bp = p["base_panel"]
        note = "条件补正需声骸共效，未计" if p["derived"] else ""
        A(f"| {p['character']}（{p['mode']}） | {bp['base']['攻击']:.0f} | {bp['pct']['攻击']:.1f}% | "
          f"{bp['flat']['攻击']:.0f} | {bp['attack']:.1f} | {bp['crit']:.1f} | {bp['crit_dmg']:.1f} | "
          f"{bp['energy']:.1f} | {bp['bonus']:.1f} | {note} |")
    A("")
    A("> 增伤 = 属伤 + 专伤 + 通用，直接相加；"
      "西格莉卡的条件补正（共效转增伤）需要声骸共效，表中未计，见组合面板。")

    A("## 二、队伍对比\n")
    A("| 队伍 | 副C E | 主C E | 合计 | 说明 |")
    A("|---|---:|---:|---:|---|")
    team_notes = {
        "散华+陆赫斯": "散华轻云5给陆赫斯22.5%攻击+12增伤",
        "达妮娅+爱弥斯": "达妮娅全队30增伤 + 轻云5给爱弥斯22.5%攻击+12增伤",
        "散华+绯雪": "散华轻云5给绯雪22.5%攻击+12增伤",
        "仇远+西格莉卡（3+2 标准43311）": "标准43311；4C属轻云",
        "仇远+西格莉卡（3+2 无4C 33311）": "无4C，3×3C+2×1C；比43311高1.06%",
        "仇远+西格莉卡（轻云5 43311）": "轻云5；西格莉卡得22.5%攻击+12增伤",
    }
    for name, t in data["teams"].items():
        A(f"| {name} | {t['sub_E']:.1f} | {t['main_E']:.1f} | {t['sum']:.1f} | {team_notes.get(name, '')} |")
    q = data["qiuyuan_compare"]
    A("")
    A(f"**仇远 3+2 vs 5**：3+2 标准43311 合计 {q['team32_43311']:.1f}；无4C 33311 合计 {q['team32_33311']:.1f}；"
      f"5 队合计 {q['team5']:.1f}。3+2 领先 **{q['delta_43311_pct']:.2f}%**（43311）/"
      f"**{q['delta_33311_pct']:.2f}%**（33311）。")
    A(f"仇远个人 3+2 比 5 高 {q['sub_delta_43311']:.1f} E（43311）/{q['sub_delta_33311']:.1f} E（33311）；"
      f"西格莉卡 3+2 比 5 低 {abs(q['main_delta']):.1f} E。")
    A(f"临界：若西格莉卡在队伍实际伤害中占比超过 **{q['main_share_breakeven_43311_pct']:.1f}%**（43311）/"
      f"**{q['main_share_breakeven_33311_pct']:.1f}%**（33311），5 件套才会反超。")
    A("")

    A("## 三、默认 43311 vs 全排列 / 评分法\n")
    A("「43311最高分E」= 在 43311 布局内按报告评分和最高的组合（不是评分前五）；"
      "「评分法差距」= 它比 43311 伤害最优低多少。\n")
    A("| 角色 | 43311最优E | 全排列最优E | 全排列布局 | 43311最高分E | 评分法差距 | 33311最优E | 33311 vs 43311 | 结论 |")
    A("|---|---:|---:|---|---:|---:|---:|---:|---|")
    for p in plans:
        b433 = p["best"]
        ball = p["best_all"]
        s433 = p["score_best"]
        b333 = p["best_33311"]
        gap_score = p["score_gap_pct"]
        all_layout = p["all_layout"]
        all_vs = p["all_vs_43311_pct"]
        if all_layout != "43311":
            head = f"默认43311不是最优（{all_layout} 高 {all_vs:.2f}%）"
        else:
            head = "默认43311=全排列最优"
        if gap_score <= 1:
            head += "；43311内评分法=最优"
        elif gap_score <= 6:
            head += f"；43311内评分法差 {gap_score:.2f}%"
        else:
            head += f"；43311内评分法差 {gap_score:.2f}%，建议穷举"
        if b333:
            e333_txt = f"{b333['score']:.1f}"
            g333 = p["33311_vs_43311_pct"]
            g333_txt = f"+{g333:.2f}%" if g333 > 0 else f"{g333:.2f}%"
        else:
            e333_txt, g333_txt = "—", "—"
        label = p["mode"]
        if p["key"] == "sigrika32":
            label = "仇远3+2"
        elif p["key"] == "sigrika5":
            label = "仇远轻云5"
        A(f"| {p['character']}（{label}） | {b433['score']:.1f} | {ball['score']:.1f} | {all_layout} | "
          f"{s433['score']:.1f} | {gap_score:.2f}% | {e333_txt} | {g333_txt} | {head} |")
    A("")
    A("> 43311 = 1×4C + 2×3C + 2×1C；33311 = 0×4C + 3×3C + 2×1C（陆赫斯 —：流金只有 2 个不同 3C 名字）。"
      "「全排列最优E」允许任意布局；除仇远 3+2 外，它与 43311 相同。"
      "3+2 的评分和跨两套权重，只作粗略对照。")
    A("")

    A("## 四、各角色 43311 Top 10\n")
    for p in plans:
        A(f"### {p['character']} · {p['mode']} · {p['set_a']}" + (f"+{p['set_b']}" if p['mode'] == '3+2' else ""))
        A(f"- 候选 {p['candidates']} 只 / 全排列 {p['evaluated']} 组 / 其中 43311 {p['evaluated_43311']} 组；裸面板 "
          + ", ".join(f"{k}={v:g}" for k, v in p["bare"].items()))
        if p["note"]:
            A(f"- 口径：{p['note']}")
        A("| # | 组合 | ΣCOST | 攻击 | 暴击/暴伤 | 共效 | 增伤% | E | 评分和 | 差距 |")
        A("|---|---|---:|---:|---|---:|---:|---:|---:|---:|")
        for r in p["top"]:
            crit = f"{r['crit']:.1f}" + ("→100" if r["crit"] > 100 else "")
            A(f"| {r['rank']} | {fmt_items(r)} | {r['total_cost']} | {r['attack']:.0f} | "
              f"{crit}/{r['crit_dmg']:.1f} | {r['energy']:.1f} | "
              f"{r['bonus']:.1f} | {r['score']:.1f} | "
              f"{r['score_sum']:.2f} | {r['gap_pct']:.2f}% |")
        if p["best_33311"] and p["33311_advantage_pct"] is not None and p["33311_advantage_pct"] > 0.1:
            b = p["best_33311"]
            A(f"- **无 4C 的 33311 更优**：E={b['score']:.1f}（比 43311 高 {p['33311_advantage_pct']:.2f}%），"
              f"组合 {fmt_items(b)}；如果必须 43311，用上表的第 1 名。")
        A("")

    A("## 五、结论摘要\n")
    q = data["qiuyuan_compare"]
    p32 = next(p for p in plans if p["key"] == "qiuyuan32")
    A("1. **默认 43311**：除仇远 3+2 外，全排列最优布局都是 43311；"
      f"仇远 3+2 的 33311（无4C）E {p32['best_33311']['score']:.1f}，比 43311 的 {p32['best']['score']:.1f} "
      f"高 {p32['33311_advantage_pct']:.2f}%。")
    g = {p["key"]: p["score_gap_pct"] for p in plans}
    A(f"2. **43311 内「简单最优」vs 伤害最优**：评分和最高的组合，西格莉卡=最优（0%）；"
      f"陆赫斯差 {g['luhesis']:.2f}%；爱弥斯 {g['aemis']:.2f}%；绯雪 {g['feixue']:.2f}%；"
      f"散华 {g['sanhua']:.2f}%；仇远 3+2 {g['qiuyuan32']:.2f}%；仇远 5 {g['qiuyuan5']:.2f}%；"
      f"达妮娅 {g['dania']:.2f}%。所以「评分和最高就是最优」只对西格莉卡成立、陆赫斯接近；其余要穷举。")
    A("3. **不限定 43311 时**，直接取评分和最高的合法 5 件会选到 33111/33311/11111"
      "（陆赫斯/爱弥斯/西格莉卡/仇远3+2），E 反而低 9.8%~22.8% —— 先限定 43311 再比评分才公平。")
    A(f"4. **仇远队**：3+2 标准43311 合计 {q['team32_43311']:.1f}；无4C 33311 合计 {q['team32_33311']:.1f}；"
      f"5 件套 {q['team5']:.1f}。3+2 领先 {q['delta_43311_pct']:.2f}% / {q['delta_33311_pct']:.2f}%；"
      f"临界主C占比 {q['main_share_breakeven_43311_pct']:.1f}% / {q['main_share_breakeven_33311_pct']:.1f}%。")
    A("5. **队伍合计只作相对参考**：E 不含技能倍率/站场时间；跨队比较没有意义。")
    A("")

    A("## 六、关键假设\n")
    A("- 裸面板的 攻击 用加号前的数值作百分比基底（862/1049/925/1012/962/1024/1049）；"
      "加号后的 103/251/221/121/230/245/251 是技能树默认攻击%（12%/24%）已折算成固定值，"
      "所以零新百分比时仍等于 965/1300/1146/1133/1192/1269/1300。")
    A("- 「全队」buff 含施放者自身；「角色」「武器」未标全队的是单人。")
    A("- 仇远「10攻击」按 10% 攻击计（用户说明这里的数值都是百分比）；若按固定 +10，差异 <0.5%。")
    A("- 爱弥斯裸面板的 12 增伤视为武器/技能树已在面板里，不另加武器增伤。")
    A("- 达妮娅的「武器：爱弥斯 24% 攻击」按爱弥斯的武器处理：24% 攻击计给爱弥斯，达妮娅不吃这 24%。")
    A("- 仇远的「队伍声骸技能 +16%/+20%」按你的口径计入仇远自身增伤，同时也给西格莉卡"
      "（3+2 共 36 / 5 共 20）；息界 2 件套气动 10 未计入你给的 206。")
    A("- 轻云 5 的 22.5% 攻击 +12 增伤只给下一个登场的主C，不给副C自己。")
    A("- 奶妈固定 25%+20%=45% 全队攻击，各队一致；奶妈自身的声骸不参与分配。")
    A("- 库存用 rep6：160 条 / 131 满级；rep7 只有 139 条 / 听唤满级 16 只且有更多 OCR 变体，故未用。"
      "用 rep7 复核：仇远/西格莉卡四项结果一致；散华 +3.5%、陆赫斯 -1.2%，结论不变。")
    A("- 西格莉卡的旧「300 增伤」预设仍在 `assets/char_profiles.json`（声骸技能160 / 气动80 / 通用25 / "
      "暴伤30 / 攻击37.5 / 共效天赋50），本次**没有使用**；本次按新给的 96+25+36/30 计算，避免重复。")
    A("")
    Path(path).write_text("\n".join(L), encoding="utf-8")


def write_csvs(data, outdir):
    os.makedirs(outdir, exist_ok=True)
    for p in data["plans"]:
        path = os.path.join(outdir, f"{p['key']}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["名次", "组合", "ΣCOST", "攻击", "暴击", "暴伤", "共效", "增伤",
                        "E", "评分和", "差距%"])
            for r in p["top"]:
                w.writerow([r["rank"], fmt_items(r), r["total_cost"], r["attack"], r["crit"],
                            r["crit_dmg"], r["energy"], r["bonus"], r["score"], r["score_sum"],
                            r["gap_pct"]])


def main():
    global USE_GATES, USE_SWAP4C
    ap = argparse.ArgumentParser(description="7 角色声骸组合 + 队伍分析")
    ap.add_argument("--inventory", default=str(ROOT / "eval_report6.json"))
    ap.add_argument("--out", default=str(ROOT / "logs" / "analysis" / "team_plan_20261124"))
    ap.add_argument("--no-gates", action="store_true",
                    help="两个门槛系数都关（回到纯伤害口径；默认只开共效循环系数）")
    ap.add_argument("--crit-gate", action="store_true",
                    help="打开暴击稳定性系数（默认关：可无限重开，波折不构成成本）")
    ap.add_argument("--swap4c", action="store_true",
                    help="假设 4C 主词条可换成暴伤 44（副词条不动），用来比较 4C 主属性")
    ap.add_argument("--swap3c", default="",
                    help="假设这些方案的 3C 属伤主词条可换成攻击%% 30（逗号分隔的 plan key）")
    a = ap.parse_args()
    USE_GATES = not a.no_gates
    USE_CRIT_GATE = a.crit_gate
    USE_SWAP4C = a.swap4c
    SWAP3C_KEYS.clear()
    SWAP3C_KEYS.update(k.strip() for k in a.swap3c.split(",") if k.strip())
    os.makedirs(a.out, exist_ok=True)
    data = build(a.inventory)
    data["gates"] = USE_GATES
    data["crit_gate"] = USE_CRIT_GATE
    data["swap4c"] = USE_SWAP4C
    data["swap3c"] = sorted(SWAP3C_KEYS)
    with open(os.path.join(a.out, "team_plan.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    write_markdown(data, os.path.join(a.out, "report.md"))
    write_csvs(data, a.out)
    print(f"wrote {a.out}/team_plan.json, report.md, *.csv")
    for p in data["plans"]:
        b = p["top"][0]
        print(f"{p['character']:4s} {p['mode']:3s} E433={b['score']:9.1f}  "
              f"s_score_gap={p['score_gap_pct']:5.2f}%  layout={p['all_layout']}")


if __name__ == "__main__":
    main()
