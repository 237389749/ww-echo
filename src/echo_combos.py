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

from src.echo_panel import DerivedBonus, Panel, aggregate, damage, is_bonus_key
from src.echo_set_templates import get_set_weights

# 有效的 COST 档(游戏里声骸只有 1/3/4)
VALID_COSTS: tuple[int, ...] = (1, 3, 4)
# ΣCOST 上限(契约): 5 只 4+3+3+1+1 = 12
MAX_TOTAL_COST = 12


@dataclass(frozen=True)
class EchoItem:
    """库存里的一只声骸: 名字 / COST / 套装 / 面板贡献(主属性 + 副词条) / 评估得分。"""
    name: str
    cost: int
    set_name: str
    stats: tuple[tuple[str, float], ...] = ()
    main: tuple[tuple[str, float], ...] = ()      # 主属性(展示用; 通常 = stats 前 2 条)
    level: int | None = None
    source: str = ""                              # 数据来源(便于追溯)
    score: float | None = None                    # 评估得分(该套装权重下的条分和, 与报告同口径)
    # **伤害相关得分**: 同一套权重, 但把**共效**权重置 0(共效不进伤害公式)。
    # 用户口径: 暴击不溢出时"评分和最高的通常就是最好的", 偏差主要来自共效占模 → 这个指标就是去掉它。
    score_dmg: float | None = None

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
    # 声骸副词条里允许计入的加成键; None = 由套装模板自动推断(见 `set_bonus_keys`)
    allowed_bonus: tuple[str, ...] | None = None
    # 由面板属性推导的补正(天赋类, 见 `echo_panel.DerivedBonus`): 逐组合按最终属性值算
    derived: tuple[DerivedBonus, ...] = ()
    # 循环门槛(共效): 共效 < 目标(下限)时按**线性缺口**扣系数(用户口径, 2026-10-09):
    #   系数 = max(floor, 1 − slope × (目标 − 值) / 目标)     (值 ≥ 目标 → 1.0; **系数只减不增**)
    # 例(目标 120 / 斜率 0.30 / 最低 0.85): 110% → 0.975; 100% → 0.950; 60% 及以下 → 0.85。
    # `energy_min <= 0` 或 `energy_slope == 0` 即关闭。
    energy_min: float = 120.0
    energy_slope: float = 0.30
    energy_floor: float = 0.85
    # 暴击门槛(稳定性): 与共效**同一个公式** —— 低于目标就扣(用户口径: 单段/少段伤害看重稳定暴击)。
    # 为什么不用"接近 100% 给奖励": 暴击与共效一样有天然上限, 增益形在现实区间(90~100%)只有
    # ±0.2% 的动态范围, 几乎不区分; 惩罚形把 100% 定为 1.0 基准(E 不再被整体抬高, 可与未乘值直接比),
    # 同样的参数能把 90% 与 100% 拉开数倍。
    # 例(目标 100 / 斜率 0.40 / 最低 0.80): 96% → 0.984; 93% → 0.972; 80% → 0.920; ≤50% → 0.80。
    # 与"暴击区(1+暴击率×暴伤)"不是一回事: 那是期望收益, 这是稳定性的口径加成。
    crit_target: float = 100.0
    crit_slope: float = 0.40
    crit_floor: float = 0.80


def gap_factor(value: float, target: float, slope: float, floor: float) -> float:
    """"离目标多远的线性惩罚": `max(floor, 1 − slope × (target − value)/target)`; 达标/关闭 → 1.0。

    共效(目标 120)与暴击(目标 100)共用这一个公式 —— 两者都是有上限的属性, 用"缺口惩罚"比
    "接近上限给奖励"更合理(奖励形在现实区间几乎恒定, 还会把所有 E 整体抬高、失去可比性)。
    """
    if target <= 0 or slope <= 0 or value >= target:
        return 1.0
    return max(floor, 1 - slope * (target - value) / target)


def energy_factor(energy: float, req_min: float, slope: float, floor: float) -> float:
    """共效循环系数(缺口线性惩罚)。"""
    return gap_factor(energy, req_min, slope, floor)


def crit_factor(crit_rate: float, target: float, slope: float, floor: float) -> float:
    """暴击稳定性系数(缺口线性惩罚; 暴击超过目标按目标算, 不再给额外奖励)。"""
    return gap_factor(min(crit_rate, 100.0), target, slope, floor)


@dataclass
class Combo:
    """一个合法组合 + 它的面板与排序分。"""
    items: tuple[EchoItem, ...]
    panel: Panel
    score: float                     # **最终排序分**(已含共效循环系数与暴击稳定性系数)
    score_raw: float = 0.0           # 未乘任何系数前的 E(展示/对比用)
    penalized: bool = False          # 共效 < 门槛 → 循环系数 < 1
    energy_f: float = 1.0            # 用到的共效循环系数
    crit_f: float = 1.0              # 用到的暴击稳定性系数

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

    def score_sum(self) -> tuple[float, int]:
        """五只的**评估得分之和** + 其中几只缺分数(报告路径没现成分数的会缺)。

        评分口径与评估报告一致(该套装权重下 档位值÷期望 ×10×权重), 所以同一套装内的组合可比;
        它是"这 5 只各自练得怎么样"的汇总, 与伤害排序分 E 是两个维度(高分件不一定面板最优)。
        """
        vals = [i.score for i in self.items if i.score is not None]
        return round(sum(vals), 2), len(self.items) - len(vals)

    def score_sum_dmg(self) -> tuple[float, int]:
        """五只的**伤害相关得分之和**(同一套权重但共效权重置 0)+ 缺分数的只数。

        比 `score_sum` 更贴近伤害排序: 共效在评分里有 0.6 权重, 却不进伤害公式 ——
        实测"评分和最高但伤害只排 34 名"的组合, 多出来的分几乎全来自共效。
        """
        vals = [i.score_dmg if i.score_dmg is not None else i.score
                for i in self.items if (i.score_dmg is not None or i.score is not None)]
        return round(sum(vals), 2), len(self.items) - len(vals)


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
    # 声骸副词条里只计**该套装有效词条**的加成键(专伤分类型; 3+2 取两套并集)。
    # `req.allowed_bonus` 显式给了就用它(None = 由模板推断; 传 () = 一个专伤都不计)。
    allowed_bonus = req.allowed_bonus if req.allowed_bonus is not None else set_bonus_keys(
        [req.set_a] + ([req.set_b] if req.mode == "3+2" else []))
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
            panel = aggregate(bare, corrections, (s for it in combo for s in it.stats),
                              allowed_bonus=allowed_bonus, derived=req.derived)
            raw = damage(panel, req.scaling, crit_mode=req.crit_mode)
            # 两个"用户口径"系数(同一公式, 只是目标不同): ① 共效不够 → 循环变慢 ② 暴击不够 → 不够稳
            f_energy = energy_factor(panel.energy, req.energy_min, req.energy_slope, req.energy_floor)
            f_crit = crit_factor(panel.crit_rate, req.crit_target, req.crit_slope, req.crit_floor)
            penalized = f_energy < 1.0
            score = raw * f_energy * f_crit
            seq += 1
            item = (score, seq, combo, panel, raw, penalized, f_energy, f_crit)
            if len(heap) < max(1, req.top_k):
                heapq.heappush(heap, item)
            elif score > heap[0][0]:
                heapq.heapreplace(heap, item)
            if should_stop is not None and (seq == 1 or seq % 512 == 0) and should_stop():
                cancelled = True
                break

    combos = [Combo(items=c, panel=p, score=s, score_raw=raw, penalized=pen,
                    energy_f=fe, crit_f=fc)
              for s, _, c, p, raw, pen, fe, fc in sorted(heap, key=lambda x: (-x[0], x[1]))]
    return PlanResult(combos=combos, candidates=len(pool), names=len(groups),
                      evaluated=evaluated, elapsed=time.perf_counter() - t0, cancelled=cancelled)


def energy_is_damage(req: "PlanRequest") -> bool:
    """本方案里**共效是否会转成伤害**(有以共效为触发源的天赋/推导补正)。

    此时「有效分 = 评分和 − 共效条分」是**反向**的(共效正是伤害来源, 不该被当无用项扣掉) →
    调用方应把有效分显示为"—"并说明原因, 而不是给一个误导的数(实测: 西格莉卡共效 1% = 2% 增伤)。
    """
    from src.echo_panel import ENERGY_KEY
    return any(d.source == ENERGY_KEY for d in req.derived)


def set_bonus_keys(set_names) -> tuple[str, ...] | None:
    """这些套装**有效词条**里的"专伤键", 用作 `allowed_bonus` 的默认值。

    **为什么要过滤**: 专伤分技能类型 —— 只打共鸣解放的角色刷到"普攻伤害加成"副词条等于白给。
    "哪几种专伤有效"的唯一来源 = 套装模板的权重键(`echo_set_templates`, 与评估/评分同一份口径:
    权重 0 = 不认)。3+2 取两套的**并集**。属伤/通用增伤不在这里管(它们与技能类型无关, 永远计入)。
    模板缺失 → 返回 `None`(`None` = 不过滤, 老行为可复现)。
    """
    from src.echo_panel import bonus_group
    keys: set[str] = set()
    found = False
    for name in set_names:
        if not name:
            continue
        weights = get_set_weights(name)
        if weights is None:
            continue
        found = True
        # **权重 0 = 该套装不认这个词条**(与评估评分同一口径: weight 0 → 0 分) → 不能算"有效专伤"。
        # 否则把某套装的"重击"权重置 0 后, 重击副词条仍会被计进伤害(实测踩过: 用户要求置 0)。
        keys |= {k for k, w in weights.items()
                 if w > 0 and is_bonus_key(k) and bonus_group(k) == "专伤"}
    return tuple(sorted(keys)) if found else None


def instance_tag(item: EchoItem) -> str:
    """同名多只时用来区分"是哪一只"的短标签(取自 `source`): `json#38` → `#38`; 素材 `0022_click…` → `#22`。

    排名表里同名不同实例的组合看起来一模一样(名字+COST 相同), 只有词条/面板不同 —— 标出实例编号
    才能照着装。去前导零是为了省表格宽度。
    """
    src = item.source or ""
    if src.startswith("json#"):
        num = src[5:].split("|")[0]
    else:
        head = src.split("|")[0]
        num = head[:4] if head[:4].isdigit() else ""
    return "#" + (num.lstrip("0") or "0") if num else ""


def combo_summary(combo: Combo, req: PlanRequest) -> str:
    """一行文字摘要(CLI 表格与日志共用)。"""
    parts = ", ".join(f"{i.name}{instance_tag(i)} {i.cost}C" for i in combo.items)
    counts = " + ".join(f"{k}×{v}" for k, v in sorted(combo.set_counts.items()))
    return (f"{combo.score:.1f} | ΣCOST {combo.total_cost} | {counts} | "
            f"{req.scaling} {combo.panel.scaling_total(req.scaling):.1f} | "
            f"暴击 {combo.panel.crit_rate:.1f}%/{combo.panel.crit_dmg:.1f}% | "
            f"加成 {combo.panel.bonus_zone():.1f}% | {parts}")
