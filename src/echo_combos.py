"""
声骸组合**穷举 + 伤害排名** —— 规格见仓库根 `panel_plan.md`, 契约见 `handoff.md`。

契约(用户已定):
- 模式两种: `5`(同一套 5 只) / `3+2`(套装 A 3 只 + 套装 B 2 只); 两套时**必须指定 4C 归属**,
  不能两套都取 5 件。
- 组合过滤: 5 只**互异**(同名声骸不可重复装, 按**名字**去重)、`ΣCOST ≤ 12`、只用 5★、
  **套装计数按去重只数**(所以"3 只同名"永远只算 1 只)。
- 补正**一律视为生效**(不做件数条件判定); 套装效果**不自动解析**(用户手填补正)。
- 伤害只用于排序: `E = 缩放属性总值 × (1 + 暴击率×暴击伤害) × (1 + 加成区)`(常数省略) —— 见 `echo_panel`。

实现要点:
- 先按**名字**分组(同名多只 = 同一名字的多个词条版本), 枚举"5 个互异名字"的组合, 再对该名字组合
  取各名字的实例笛卡尔积 → 每个实例组合做一次面板聚合。名字组合天然满足"互异"与"套装只数按只数"。
- 打分只依赖 5 只贡献的**加性**分量(E 对每个分量单调不减), 因此同名字组合内保持全实例枚举(不做近似剪枝),
  只对最终结果取 Top-K。
"""
from __future__ import annotations

import heapq
import itertools
import time
from dataclasses import dataclass, field

from src.echo_panel import Panel, aggregate, damage

# 有效的 COST 档(游戏里声骸只有 1/3/4)
VALID_COSTS: tuple[int, ...] = (1, 3, 4)
# ΣCOST 上限(契约): 5 只 4+3+3+1+1 = 12
MAX_TOTAL_COST = 12


@dataclass(frozen=True)
class EchoItem:
    """库存里的一只声骸: 名字 / COST / 套装 / 面板贡献(主属性 + 副词条)。"""
    name: str
    cost: int
    set_name: str
    stats: tuple[tuple[str, float], ...] = ()
    main: tuple[tuple[str, float], ...] = ()      # 主属性(展示用; 通常 = stats 前 2 条)
    level: int | None = None
    source: str = ""                              # 数据来源(便于追溯)

    def __str__(self) -> str:
        return f"{self.name}({self.cost}C·{self.set_name})"


@dataclass
class PlanRequest:
    """穷举请求(全部来自 UI/CLI 的输入装配, 引擎不猜默认值)。"""
    scaling: str = "攻击"            # 缩放属性: 攻击 / 防御 / 生命
    mode: str = "5"                  # "5" | "3+2"
    set_a: str = ""
    set_b: str = ""                  # 3+2 必填
    cost4_owner: str = "A"           # 3+2 必填: 4C 那只属于哪套("A" / "B")
    top_k: int = 50
    crit_mode: str = "expect"        # 期望 / 单次暴击 / 单次不暴击
    max_total_cost: int = MAX_TOTAL_COST
    max_level_only: bool = True      # 只用满级件(5 词条) —— 默认; 关掉才把未满级件也放进候选池


@dataclass
class Combo:
    """一个合法组合 + 它的面板与排序分。"""
    items: tuple[EchoItem, ...]
    panel: Panel
    score: float

    @property
    def total_cost(self) -> int:
        return sum(i.cost for i in self.items)

    @property
    def set_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for i in self.items:
            counts[i.set_name] = counts.get(i.set_name, 0) + 1
        return counts

    def scaling_total(self, scaling: str) -> float:
        return self.panel.scaling_total(scaling)


@dataclass
class PlanResult:
    combos: list[Combo] = field(default_factory=list)
    candidates: int = 0              # 过滤后的候选只数
    names: int = 0                   # 候选名字数(互异组合按名字计)
    evaluated: int = 0               # 实际评估的实例组合数
    elapsed: float = 0.0
    cancelled: bool = False          # 被 `should_stop` 提前中止(结果是部分排名)


def is_max_level(item: EchoItem) -> bool:
    """满级(5★ +25) ⇔ **5 条词条**: 第 n 条词条在 +5n 开, 而 5★ 上限就是 +25,
    所以"5 词条"与"满级"等价(反过来 `+22` 也可能已有 5 条 —— 那种也算满级口径)。
    评估产物里没有等级字段, 只能这么判(见 `src/echo_inventory` 的说明)。"""
    return len(item.stats) - len(item.main) >= 5


def candidate_pool(items, req: PlanRequest) -> list[EchoItem]:
    """过滤候选: 5★(由导入方保证) + COST 合法 + 属于目标套装 + (默认)**满级**。

    默认只收满级件: 未满级件的词条还会涨, 拿现状词条参与排名会低估它、也会把"其实要再练"的件
    混进推荐; 需要"看现有全部件"时把 `req.max_level_only` 置 False。
    """
    if not req.set_a:
        raise ValueError("必须指定目标套装")
    wanted = {req.set_a}
    if req.mode == "3+2":
        if not req.set_b:
            raise ValueError("3+2 模式必须指定套装 2")
        if req.set_b == req.set_a:
            raise ValueError("3+2 模式的两套不能是同一套装")
        wanted.add(req.set_b)
    elif req.mode != "5":
        raise ValueError(f"未知模式: {req.mode!r}(只有 '5' / '3+2')")
    return [it for it in items if it.cost in VALID_COSTS and it.set_name in wanted
            and (not req.max_level_only or is_max_level(it))]


def _by_name(pool: list[EchoItem]) -> dict[str, list[EchoItem]]:
    out: dict[str, list[EchoItem]] = {}
    for it in pool:
        out.setdefault(it.name, []).append(it)
    return out


def plan(items, req: PlanRequest, bare: dict | None = None, corrections=(),
         should_stop=None) -> PlanResult:
    """穷举 + 排名。返回按 `score` 降序的 Top-K(`req.top_k`)。

    `should_stop` = 可选的 `() -> bool`: 每评估 4096 组查一次, 返回 True 就提前停下
    (UI 的"取消"按钮用; 结果是**部分排名**, `PlanResult.cancelled` 会置 True)。
    """
    t0 = time.perf_counter()
    pool = candidate_pool(items, req)
    groups = _by_name(pool)
    # 同名多只: 名字 → {套装, COST} 必须一致(同一只声骸的多个词条版本); 不一致说明导入有脏数据
    name_set: dict[str, str] = {}
    name_cost: dict[str, int] = {}
    for name, its in groups.items():
        sets = {i.set_name for i in its}
        costs = {i.cost for i in its}
        if len(sets) > 1 or len(costs) > 1:
            raise ValueError(f"同名声骸的套装/COST 不一致, 数据有误: {name} {sorted(sets)} {sorted(costs)}")
        name_set[name] = its[0].set_name
        name_cost[name] = its[0].cost

    names_a = sorted(n for n, s in name_set.items() if s == req.set_a)
    names_b = sorted(n for n, s in name_set.items() if s == req.set_b) if req.mode == "3+2" else []

    if req.mode == "5":
        name_combos = itertools.combinations(names_a, 5)
    else:
        name_combos = ((*a, *b) for a in itertools.combinations(names_a, 3)
                       for b in itertools.combinations(names_b, 2))

    heap: list[tuple[float, int, tuple[EchoItem, ...], Panel]] = []
    evaluated = 0
    seq = 0
    cancelled = False
    owner_set = req.set_a if req.cost4_owner == "A" else req.set_b
    for names in name_combos:
        if should_stop is not None and cancelled:
            break
        cost = sum(name_cost[n] for n in names)
        if cost > req.max_total_cost:
            continue
        if req.mode == "3+2" and any(name_cost[n] == 4 and name_set[n] != owner_set for n in names):
            continue                                     # 4C 归属不满足
        for combo in itertools.product(*(groups[n] for n in names)):
            evaluated += 1
            panel = aggregate(bare, corrections, (s for it in combo for s in it.stats))
            score = damage(panel, req.scaling, crit_mode=req.crit_mode)
            seq += 1
            item = (score, seq, combo, panel)
            if len(heap) < max(1, req.top_k):
                heapq.heappush(heap, item)
            elif score > heap[0][0]:
                heapq.heapreplace(heap, item)
            if should_stop is not None and (seq == 1 or seq % 512 == 0) and should_stop():
                cancelled = True
                break

    combos = [Combo(items=c, panel=p, score=s) for s, _, c, p in sorted(heap, key=lambda x: (-x[0], x[1]))]
    return PlanResult(combos=combos, candidates=len(pool), names=len(groups),
                      evaluated=evaluated, elapsed=time.perf_counter() - t0, cancelled=cancelled)


def instance_tag(item: EchoItem) -> str:
    """同名多只时用来区分"是哪一只"的短标签(取自 `source`): `json#38` → `#38`; 素材路径 → `0001`。

    排名表里同名不同实例的组合看起来一模一样(名字+COST 相同), 只有词条/面板不同 —— 标出实例编号
    才能照着装。
    """
    src = item.source or ""
    if src.startswith("json#"):
        return "#" + src[5:].split("|")[0]
    head = src.split("|")[0]
    return head[:4] if head[:4].isdigit() else ""


def combo_summary(combo: Combo, req: PlanRequest) -> str:
    """一行文字摘要(CLI 表格与日志共用)。"""
    parts = ", ".join(f"{i.name}{instance_tag(i)} {i.cost}C" for i in combo.items)
    counts = " + ".join(f"{k}×{v}" for k, v in sorted(combo.set_counts.items()))
    return (f"{combo.score:.1f} | ΣCOST {combo.total_cost} | {counts} | "
            f"{req.scaling} {combo.panel.scaling_total(req.scaling):.1f} | "
            f"暴击 {combo.panel.crit_rate:.1f}%/{combo.panel.crit_dmg:.1f}% | "
            f"加成 {combo.panel.bonus_zone():.1f}% | {parts}")
