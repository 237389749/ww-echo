"""
声骸评分(domain 层, 纯计算) —— 条分 = 档位值 ÷ 期望值 × 10 × 权重。

2026-11-13 耦合 P1 从 `src/task/EnhanceEchoTask.compute_weighted_score` 抽出的纯函数,
理由同 `src/echo_parse`(让 `src.echo_inventory` 不再 import task adapter)。
`EnhanceEchoTask.compute_weighted_score` 保留实例方法薄封装 —— 它多做一件事:
`set_name is None` 时读 `config['当前套装']` 作默认值(那是任务运行时状态, 不属于本模块)。

口径(勿改):
- 期望 = `echo_stats.get_mean` 的官方概率期望档位值(统一舍入 1 位小数; 平均档 = 10.0 分,
  满档 ≈ 13.1~14.0; 原按算术平均时分母偏大、上限才是 12.5);
- 权重 = 套装模板 `get_set_weights`; 通用模式(套装未映射 / `'通用'` / None)用 `DEFAULT_WEIGHTS`;
- `权重 <= 0` 或没有档位数据 → 该词条 0 分, 原因记进 `details`(不静默丢)。
"""

from src.echo_parse import parse_number
from src.echo_set_templates import get_set_weights
from src.echo_stats import DEFAULT_WEIGHTS, get_mean, snap_to_tier, tier_percentile


def compute_weighted_score(paired_stats, set_name=None) -> tuple[float, list[str]]:
    """`[(词条名, 数值串), ...]` → `(总分, 明细行列表)`。

    set_name: 套装名(`None` / `'通用'` = 通用权重表)。**只按传入的词条算** —— 主属性不要传进来
    (3C 固有"攻击 100"会被当成攻击词条, 实测踩过; 见 CLAUDE.md「组合穷举」)。
    """
    set_weights = get_set_weights(set_name if set_name != '通用' else None)

    total = 0.0
    details = []

    for stat_name, value_str in paired_stats:
        v = parse_number(value_str)
        # stat_name 已是 OCR 归一化名, 与 tier 键统一
        tier_name = stat_name

        if set_weights is not None:
            weight = set_weights.get(stat_name, 0.0)
            is_valid = weight > 0
        else:
            weight = DEFAULT_WEIGHTS.get(stat_name, 0.0)
            is_valid = weight > 0

        if not is_valid:
            details.append(f'{stat_name}={v} 无效(0)')
            continue

        tier_val = snap_to_tier(tier_name, v)
        mean_val = get_mean(tier_name)
        if tier_val is None or mean_val is None:
            details.append(f'{stat_name}={v} 无档位数据')
            continue

        contribution = (tier_val / mean_val) * 10 * weight
        total += contribution
        # 末尾附档位分位(跨词条可比的质量度量; 概率表不可用时不展示) —— 见 echo_stats.tier_percentile
        pct = tier_percentile(tier_name, v)
        pct_tag = f' [前{pct:g}%]' if pct is not None else ''
        details.append(f'{stat_name}={v}→{tier_val}/{mean_val}×10×{weight}={contribution:.2f}{pct_tag}')

    return total, details
