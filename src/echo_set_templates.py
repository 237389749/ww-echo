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


def load_templates(force: bool = False) -> dict[str, dict[str, float]]:
    """加载套装模板, 返回 {套装名: {词条名: 权重, ...}}。"""
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
        _template_cache = data.get("sets", {})
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
