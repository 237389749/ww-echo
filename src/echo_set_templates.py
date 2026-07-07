"""
声骸套装模板 — 从 JSON 文件加载套装预期词条及其权重。

JSON 格式 (assets/echo_set_templates.json):
{
  "version": 1,
  "sets": {
    "套装名": { "词条名": 权重, ... },
    ...
  }
}

每个套装的权重字典同时定义:
1. 预期有效词条列表 (字典的键)
2. 各词条的独立权重 (字典的值, 渐进式评分时使用)
"""

import json
import os
from pathlib import Path

from ok import Logger

logger = Logger.get_logger(__name__)

# 游戏中实际存在的 13 个副词条名称（白名单）
VALID_STAT_NAMES: frozenset[str] = frozenset({
    "暴击", "暴击伤害",
    "攻击百分比", "攻击",
    "生命百分比", "生命",
    "防御百分比", "防御",
    "共鸣效率",
    "普攻伤害加成", "重击伤害加成",
    "共鸣解放伤害加成", "共鸣技能伤害加成",
})

# JSON 模板文件路径
_TEMPLATE_PATH = os.path.join("assets", "echo_set_templates.json")

# 缓存
_template_cache: dict | None = None
_cache_mtime: float = 0


def _get_template_path() -> str:
    """获取模板文件绝对路径（支持打包后的 exe 和源码运行）。"""
    # 尝试相对于当前工作目录
    if os.path.exists(_TEMPLATE_PATH):
        return _TEMPLATE_PATH
    # 尝试相对于源码目录
    src_dir = Path(__file__).parent.parent
    alt_path = src_dir / "assets" / "echo_set_templates.json"
    if alt_path.exists():
        return str(alt_path)
    return _TEMPLATE_PATH


def _validate_and_filter(sets: dict) -> dict[str, dict[str, float]]:
    """校验并过滤套装模板: 去除非白名单词条, 去重, 报告无效条目。"""
    cleaned: dict[str, dict[str, float]] = {}
    total_dropped = 0

    for set_name, stats in sets.items():
        if not isinstance(stats, dict):
            logger.warning(f"[模板校验] 套装 '{set_name}' 格式错误(非字典), 跳过")
            continue

        valid_stats: dict[str, float] = {}
        for stat_name, weight in stats.items():
            if stat_name not in VALID_STAT_NAMES:
                logger.warning(
                    f"[模板校验] 套装 '{set_name}' 中的 '{stat_name}' 不是合法词条, 已过滤"
                )
                total_dropped += 1
                continue
            if stat_name in valid_stats:
                logger.warning(
                    f"[模板校验] 套装 '{set_name}' 中的 '{stat_name}' 重复, 保留后者"
                )
            valid_stats[stat_name] = float(weight)

        cleaned[set_name] = valid_stats

    if total_dropped:
        logger.warning(
            f"[模板校验] 共过滤 {total_dropped} 个无效词条"
            f" (合法词条共 {len(VALID_STAT_NAMES)} 个: {sorted(VALID_STAT_NAMES)})"
        )
    logger.info(f"[模板校验] {len(cleaned)} 个套装通过校验")
    return cleaned


def load_templates(force: bool = False) -> dict[str, dict[str, float]]:
    """加载套装模板, 返回 {套装名: {词条名: 权重, ...}}。自动过滤无效词条。"""
    global _template_cache, _cache_mtime

    path = _get_template_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0

    if not force and _template_cache is not None and mtime == _cache_mtime:
        return _template_cache

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw_sets = data.get("sets", {})
        _template_cache = _validate_and_filter(raw_sets)
        _cache_mtime = mtime
        logger.info(f"加载套装模板: {len(_template_cache)} 个套装 from {path}")
        return _template_cache
    except FileNotFoundError:
        logger.warning(f"套装模板文件不存在: {path}, 使用空配置")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"套装模板 JSON 解析失败: {e}, 使用空配置")
        return {}


def get_all_set_names() -> list[str]:
    """获取所有套装名列表。"""
    templates = load_templates()
    return list(templates.keys())


def get_set_weights(set_name: str | None) -> dict[str, float] | None:
    """
    获取指定套装的 {词条名: 权重} 字典。
    返回 None 表示使用通用配置。
    """
    if not set_name or set_name == "通用":
        return None
    templates = load_templates()
    return templates.get(set_name)


def get_expected_stats(set_name: str | None) -> list[str]:
    """
    获取指定套装的预期词条列表（即权重字典的键）。
    用于渐进式 T1 校验。
    """
    weights = get_set_weights(set_name)
    if weights:
        return list(weights.keys())
    # 通用默认
    return ["暴击", "暴击伤害", "攻击百分比", "攻击", "共鸣效率"]


def get_stat_weight(set_name: str | None, stat_name: str) -> float:
    """
    获取某套装下某词条的权重。
    先查套装模板, 没有则返回 1.0。
    """
    weights = get_set_weights(set_name)
    if weights:
        return weights.get(stat_name, 0.0)  # 不在模板中 = 无效词条(权重0)
    return 1.0  # 通用模式由 UI 滑块控制
