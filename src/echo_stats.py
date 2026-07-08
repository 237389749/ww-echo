"""
声骸词条档位数据与评分工具 — 键名统一使用 OCR 归一化名。

档位值来自社区解包数据，从高到低排列。
固定数值攻击/防御为 4 档，其余为 8 档（游戏实际设定）。
"""

# fmt: off
_TIERS: dict[str, list[float]] = {
    "暴击":             [10.5, 9.9, 9.3, 8.7, 8.1, 7.5, 6.9, 6.3],
    "暴击伤害":         [21.0, 19.8, 18.6, 17.4, 16.2, 15.0, 13.8, 12.6],
    "共鸣效率":         [12.4, 11.6, 10.8, 10.0, 9.2, 8.4, 7.6, 6.8],
    "攻击百分比":       [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "生命百分比":       [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "防御百分比":       [14.7, 13.8, 12.8, 11.8, 10.9, 10.0, 9.0, 8.1],
    "普攻伤害加成":     [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "重击伤害加成":     [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "共鸣技能伤害加成": [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "共鸣解放伤害加成": [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "生命":             [580, 540, 510, 470, 430, 390, 360, 320],
    "攻击":             [60, 50, 40, 30],
    "防御":             [70, 60, 50, 40],
}
# fmt: on

_MEANS: dict[str, float] = {}


def _compute_means() -> dict[str, float]:
    if not _MEANS:
        for name, tiers in _TIERS.items():
            _MEANS[name] = sum(tiers) / len(tiers)
    return _MEANS


def get_mean(stat_name: str) -> float | None:
    return _compute_means().get(stat_name)


def snap_to_tier(stat_name: str, raw_value: float) -> float | None:
    tiers = _TIERS.get(stat_name)
    if not tiers:
        return None
    return min(tiers, key=lambda t: abs(t - raw_value))
