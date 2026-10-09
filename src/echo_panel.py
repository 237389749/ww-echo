"""
声骸组合的「面板聚合 + 伤害」计算层 —— 供 `src/echo_combos.py`(穷举)与 UI/CLI 共用。

**规格**: 仓库根 `panel_plan.md`(公式与分区采用 wuwa-calculator); **契约**(用户已定, 见 `handoff.md`):
- 面板按 calculator 的「共鸣者基础属性」公式: `基础值 × (1 + 百分比提升) + 固定值`
  (calculator 源码 `计算分区` 里写着这句; 注意**固定值在括号外**, 所以"攻击 +30"这类固定词条不吃百分比加成)。
  `基础值` = 角色 + 武器(**不含声骸**), 由用户填; 百分比/固定 = 裸面板 + 补正 + 5 只声骸(主属性 + 副词条)。
- 伤害只用于**排序**, 方案内常数一律省略:
  `E = 缩放属性总值 × (1 + 暴击率/100 × 暴击伤害/100) × (1 + 加成区/100)`
  加成区 = 属伤 + **专伤合计(各类型直接相加)** + 通用增伤; **共效不计**。
  倍率/加深/防御/抗性在排序里是常数(默认 1), 只有为了与 calculator 对数字时才由调用方传入。
- **补正一律视为生效**(用户口径): 本模块不做任何"件数是否够"的条件判定。

键空间(全部为中文标准名, 与 `echo_set_templates.STAT_ORDER` + 生成物 `main_prop_names` 对齐):
- `攻击/生命/防御`            → 基础值(被百分比放大)
- `攻击百分比/生命百分比/防御百分比` → 百分比
- `暴击/暴击伤害/共鸣效率/治疗效果加成` → 数值面板
- `...伤害加成` / `通用增伤`  → 加成区
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 缩放三系(用户的「缩放属性」开关): 键 → 对应的百分比键
BASE_KEYS: tuple[str, ...] = ("攻击", "生命", "防御")
PCT_KEY: dict[str, str] = {"攻击": "攻击百分比", "生命": "生命百分比", "防御": "防御百分比"}

CRIT_RATE_KEY = "暴击"
CRIT_DMG_KEY = "暴击伤害"
ENERGY_KEY = "共鸣效率"
HEAL_KEY = "治疗效果加成"

# 六种属性伤害加成(与生成物 `main_prop_names` 一致; tests/test_echo_panel.py 有对齐断言)
ELEMENT_KEYS: tuple[str, ...] = ("冷凝伤害加成", "热熔伤害加成", "导电伤害加成",
                                 "气动伤害加成", "衍射伤害加成", "湮灭伤害加成")
# 泛用属伤(用户手填"气动 +10%"时也可直接填在这里) + 声骸技能专伤 + 通用增伤
ELEMENTAL_GENERIC_KEY = "属性伤害加成"
GENERIC_BONUS_KEY = "通用增伤"
EXTRA_BONUS_KEYS: tuple[str, ...] = (ELEMENTAL_GENERIC_KEY, "声骸技能伤害加成", GENERIC_BONUS_KEY)

# 不进加成区的键(基础/百分比/双暴/共效/治疗): 其余 `*伤害加成` 与 `通用增伤` 都进加成区
NON_BONUS_KEYS: frozenset[str] = frozenset(
    BASE_KEYS + tuple(PCT_KEY.values()) + (CRIT_RATE_KEY, CRIT_DMG_KEY, ENERGY_KEY, HEAL_KEY)
)


def is_bonus_key(key: str) -> bool:
    """该键是否进「加成区」: 除基础/百分比/双暴/共效/治疗之外的伤害加成类键。"""
    if key in NON_BONUS_KEYS:
        return False
    return key.endswith("伤害加成") or key == GENERIC_BONUS_KEY


def bonus_group(key: str) -> str:
    """加成条目归类: `属伤` / `通用` / `专伤`(其余) —— 对应契约里的三个来源。"""
    if key in ELEMENT_KEYS or key == ELEMENTAL_GENERIC_KEY:
        return "属伤"
    if key == GENERIC_BONUS_KEY:
        return "通用"
    return "专伤"


@dataclass(frozen=True)
class Correction:
    """一条手填补正(套装 2/3/5 件效果、共鸣链、队伍增伤、天赋…): **一律视为生效**。

    `key` 必须是本模块的键(见 `is_bonus_key`/`BASE_KEYS`); `source` 只用于展示与追溯。
    加在 `攻击/生命/防御` 上的补正是**固定值**(会计入括号外的固定合计)。
    """
    key: str
    value: float
    source: str = ""


@dataclass
class Panel:
    """聚合后的面板: 基础值 / 固定合计 / 百分比合计 / 双暴共效 / 各加成键合计。"""
    base: dict[str, float] = field(default_factory=dict)
    flat: dict[str, float] = field(default_factory=dict)
    pct: dict[str, float] = field(default_factory=dict)
    crit_rate: float = 0.0
    crit_dmg: float = 0.0
    energy: float = 0.0
    heal: float = 0.0
    bonus: dict[str, float] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)   # 不认识的键(调用方可据此提示, 不静默吞掉)

    def scaling_total(self, scaling: str) -> float:
        """缩放属性总值 = 基础值 × (1 + 百分比/100) + 固定值(calculator 口径)。"""
        if scaling not in BASE_KEYS:
            raise KeyError(f"缩放属性只能是 {BASE_KEYS}: {scaling!r}")
        return self.base.get(scaling, 0.0) * (1 + self.pct.get(scaling, 0.0) / 100.0) \
            + self.flat.get(scaling, 0.0)

    def crit_zone(self, mode: str = "expect") -> float:
        """暴击区: `expect`(默认, 期望) = 1 + 暴击率×暴击伤害; `crit`/`non_crit` = 单次口径。

        **暴击率按 100% 封顶**: 超出 100% 的部分不产生收益(实测用户组合里就会出现 112%~119%:
        4C 暴击主属性 + 5 条暴击词条 + 套装/共鸣链补正)。不封顶会把"溢出暴击"当成收益,
        让"暴击堆过头"的组合排在前面 —— 参考实现(wuwa-calculator)的边际分析也是 `Math.min(100, critRate + 10)`,
        说明 100% 就是口径上的上限。面板显示仍用原始值(游戏面板怎么显示就怎么显示),
        溢出量见 `crit_wasted()`。
        """
        rate = min(self.crit_rate, 100.0) / 100.0
        dmg = self.crit_dmg / 100.0
        if mode == "expect":
            return 1 + rate * dmg
        if mode == "crit":
            return 1 + dmg
        if mode == "non_crit":
            return 1.0
        raise ValueError(f"未知暴击模式: {mode!r}")

    def crit_wasted(self) -> float:
        """暴击率超出 100% 的溢出点数(展示用; 不影响 `crit_zone` 之外的任何东西)。"""
        return max(0.0, self.crit_rate - 100.0)

    def bonus_zone(self) -> float:
        """加成区(%) = 属伤 + 专伤合计 + 通用增伤(各类型直接相加)。"""
        return sum(self.bonus.values())

    def bonus_split(self) -> dict[str, float]:
        """加成区按来源拆开(展示用): {属伤, 专伤, 通用}。"""
        out = {"属伤": 0.0, "专伤": 0.0, "通用": 0.0}
        for k, v in self.bonus.items():
            out[bonus_group(k)] += v
        return out


def aggregate(bare: dict[str, float] | None = None, corrections=(), echo_stats=()) -> Panel:
    """裸面板 + 补正 + 5 只声骸(主属性/副词条) → `Panel`。

    `bare`: {键: 值}; `攻击/生命/防御` 在这里是**基础值**(角色+武器, 不含声骸)。
    `corrections`: 可迭代的 `Correction` 或 `(键, 值[, 来源])`。
    `echo_stats`: 可迭代的 `(键, 值)` —— 5 只声骸的全部主属性 + 副词条平铺。
    """
    panel = Panel()
    for key in BASE_KEYS:
        panel.base[key] = 0.0
        panel.flat[key] = 0.0
        panel.pct[key] = 0.0
    for k, v in (bare or {}).items():
        _add(panel, str(k), float(v), base=True)

    def _iter_corrections():
        for c in corrections:
            if isinstance(c, Correction):
                yield c.key, float(c.value)
            else:
                yield str(c[0]), float(c[1])

    for k, v in _iter_corrections():
        _add(panel, k, v, base=False)
    for k, v in echo_stats:
        _add(panel, str(k), float(v), base=False)
    return panel


def _add(panel: Panel, key: str, value: float, *, base: bool) -> None:
    """把一条数值并进面板: `base=True` 只对裸面板输入生效(定基础值), 否则进固定/百分比/加成。"""
    if key in BASE_KEYS:
        if base:
            panel.base[key] += value
        else:
            panel.flat[key] += value
    elif key in PCT_KEY.values():
        panel.pct[_scaling_of(key)] += value
    elif key == CRIT_RATE_KEY:
        panel.crit_rate += value
    elif key == CRIT_DMG_KEY:
        panel.crit_dmg += value
    elif key == ENERGY_KEY:
        panel.energy += value
    elif key == HEAL_KEY:
        panel.heal += value
    elif is_bonus_key(key):
        panel.bonus[key] = panel.bonus.get(key, 0.0) + value
    elif key not in panel.unknown:
        panel.unknown.append(key)


def _scaling_of(pct_key: str) -> str:
    for base_key, pk in PCT_KEY.items():
        if pk == pct_key:
            return base_key
    raise KeyError(pct_key)


def defense_zone(char_level: float, monster_level: float, def_ignore: float = 0.0) -> float:
    """防御区(calculator 口径): `(100+角色等级) / ((100+角色等级) + (99+怪物等级)×(1−无视防御))`。

    **排序里是常数**(同一方案内不变) —— 只有与 calculator 对数字时才需要它。
    """
    return (100 + char_level) / ((100 + char_level) + (99 + monster_level) * (1 - def_ignore / 100.0))


def resist_zone(resist: float = 10.0) -> float:
    """抗性区 = 1 − 抗性/100(排序里同样是常数)。"""
    return 1 - resist / 100.0


def damage(panel: Panel, scaling: str, *, crit_mode: str = "expect", skill_mult: float = 1.0,
           amplify: float = 1.0, def_factor: float = 1.0, res_factor: float = 1.0) -> float:
    """最终伤害 = 缩放属性总值 × 暴击区 × 加成区 × (倍率 × 加深 × 防御 × 抗性)。

    后四项默认 1(契约: 只排序, 方案内常数省略); 显式传入才参与(对账 calculator 用)。
    """
    return (panel.scaling_total(scaling) * panel.crit_zone(crit_mode)
            * (1 + panel.bonus_zone() / 100.0) * skill_mult * amplify * def_factor * res_factor)
