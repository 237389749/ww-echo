"""
声骸套装模板 — 从 JSON 文件加载套装预期词条及其权重。

JSON 格式 (assets/echo_set_templates.json):
{
  "version": 1,
  "sets": {
    "套装名": {
      "词条名": 权重, ...,
      "_core_first": ["词条名", ...]   // 可选: Lv5 首条必须命中的核心词条; 缺省=全部有效词条
    },
    ...
  }
}

每个套装的权重字典同时定义:
1. 预期有效词条列表 (字典的键)
2. 各词条的独立权重 (字典的值, 渐进式评分时使用)
3. _core_first(可选): 首条核心词条集合——Lv5/10 结构判定只认这些词条; 强化与评估配置通用
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

# 套装模板特殊键: Lv5 首条核心词条集合(可选, 缺省=全部有效词条)
_CORE_FIRST = '_core_first'
# 套装模板特殊键: 该套装包含的声骸清单 {"4c": [名...], "3c": [...], "1c": [...]}
_ECHOES = '_echoes'
_COST_KEYS = ('4c', '3c', '1c')
# 套装模板特殊键: 套装图标名(wuther.in IconElementAttri{名}; 供按图标识别/数据核对)
_ICON = '_icon'

# JSON 模板文件路径
_TEMPLATE_PATH = os.path.join("assets", "echo_set_templates.json")

# 缓存
_template_cache: dict | None = None
_cache_mtime: float = 0
# 声骸名 → [套装名,...] 反向索引(随模板缓存重建; 一个声骸可属多个套装)
_echo_index: dict[str, list[str]] | None = None


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


def _validate_and_filter(sets: dict) -> dict[str, dict]:
    """校验并过滤套装模板: 去除非白名单词条, 去重, 报告无效条目。
    返回 {套装名: {'weights': {词条:权重}, 'core_first': [词条,...]|None,
                    'echoes': {'4c': [...], '3c': [...], '1c': [...]}}}。"""
    cleaned: dict[str, dict] = {}
    total_dropped = 0

    for set_name, stats in sets.items():
        if not isinstance(stats, dict):
            logger.warning(f"[模板校验] 套装 '{set_name}' 格式错误(非字典), 跳过")
            continue

        valid_stats: dict[str, float] = {}
        core_first = None
        icon = ''
        echoes = {k: [] for k in _COST_KEYS}
        for stat_name, weight in stats.items():
            if stat_name == _CORE_FIRST:
                core_first = [s for s in weight if s in VALID_STAT_NAMES]
                continue
            if stat_name == _ECHOES:
                if isinstance(weight, dict):
                    for k in _COST_KEYS:
                        v = weight.get(k)
                        if isinstance(v, (list, tuple)):
                            echoes[k] = [str(n) for n in v if str(n).strip()]
                continue
            if stat_name == _ICON:
                icon = str(weight).strip()
                continue
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

        cleaned[set_name] = {'weights': valid_stats, 'core_first': core_first,
                             'echoes': echoes, 'icon': icon}

    if total_dropped:
        logger.warning(
            f"[模板校验] 共过滤 {total_dropped} 个无效词条"
            f" (合法词条共 {len(VALID_STAT_NAMES)} 个: {sorted(VALID_STAT_NAMES)})"
        )
    logger.info(f"[模板校验] {len(cleaned)} 个套装通过校验")
    return cleaned


def load_templates(force: bool = False) -> dict[str, dict]:
    """加载套装模板, 返回 {套装名: {'weights':…, 'core_first':…, 'echoes':…}}。自动过滤无效词条。"""
    global _template_cache, _cache_mtime, _echo_index

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
        _echo_index = None   # 模板变化 → 反向索引失效, 下次 get_set_by_echo 重建
        logger.info(f"加载套装模板: {len(_template_cache)} 个套装 from {path}")
        return _template_cache
    except FileNotFoundError:
        logger.warning(f"套装模板文件不存在: {path}, 使用空配置")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"套装模板 JSON 解析失败: {e}, 使用空配置")
        return {}


def get_set_echoes(set_name: str | None) -> dict[str, list[str]] | None:
    """获取指定套装包含的声骸清单 {'4c': [...], '3c': [...], '1c': [...]}; 通用/未知返回 None。"""
    if not set_name or set_name == "通用":
        return None
    info = load_templates().get(set_name)
    return info.get("echoes") if info else None


def get_sets_by_echo(echo_name: str) -> list[str]:
    """声骸名 → 所属套装名列表(一个声骸可属多个套装; 按模板声明顺序)。未录入返回 []。
    索引随模板缓存重建。"""
    global _echo_index
    templates = load_templates()
    if _echo_index is None:
        idx: dict[str, list[str]] = {}
        for set_name, info in templates.items():
            for names in (info.get("echoes") or {}).values():
                for n in names:
                    lst = idx.setdefault(n, [])
                    if set_name not in lst:
                        lst.append(set_name)
        _echo_index = idx
    return list(_echo_index.get(echo_name, []))


def get_set_by_echo(echo_name: str, prefer: str | None = None) -> str | None:
    """声骸名 → 套装名(评估时按声骸名选套装配置)。未录入返回 None(调用方回退通用)。
    多套装声骸: prefer 在候选内则取其(尊重调用方语境), 否则取声明顺序首个。"""
    sets = get_sets_by_echo(echo_name)
    if not sets:
        return None
    if prefer and prefer in sets:
        return prefer
    return sets[0]


def get_set_icon(set_name: str | None) -> str | None:
    """套装图标名(wuther.in IconElementAttri{名}, 如 Cloud/Ice); 未配置返回 None。"""
    if not set_name or set_name == "通用":
        return None
    info = load_templates().get(set_name)
    return (info.get("icon") or None) if info else None


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
    info = templates.get(set_name)
    return info["weights"] if info else None


def get_set_core_first(set_name: str | None) -> list[str] | None:
    """
    获取指定套装的 Lv5 首条核心词条集合(_core_first)。
    缺省(未配置) = 全部有效词条; 通用模式返回 None。
    """
    if not set_name or set_name == "通用":
        return None
    templates = load_templates()
    info = templates.get(set_name)
    if not info:
        return None
    core = info.get("core_first")
    if core:
        return list(core)
    return list(info["weights"].keys())


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

