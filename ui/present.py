"""纯展示逻辑（**无 Qt、无引擎依赖**）：判定档位的文案/配色、计数、状态卡文案。

**为什么单独一个模块**（2026-11-22, U-03/U-04/U-11）:
1. `ui/run_tab.py` 顶部 `from ww_engine import og` —— 只要 import 它就会拉起整个引擎；
   而"离屏建 QApplication + show() 一个 Fluent 窗口 + 进程里 import 过 ww_engine" 会在
   **解释器退出时段错误**（0xC0000005，本机实测；`tools/ui_shot.py` 正是为此才给引擎打桩）。
   把这些纯函数放在没有依赖的模块里, `tools/ui_probe.py` 与单测就能**跑真代码**做验收,
   不必为了查一个文案把 Qt 和引擎都拖进来。
2. 它们本来就该共用: 评估报告的 HTML、运行页的「上次评估结果」卡、状态卡三格计数,
   以前各自算一套 → 「不合格 / 不建议强化」的合并口径漂移过（U-04）。

约定: 本模块**只允许** import 标准库（以后加东西也别 import Qt/ww_engine）。
"""
from __future__ import annotations

# 判定档位的英文码 → 中文文案。**权威文案来自判定层** —— JSON 记录里的 `verdict_cn`
# (judge_echo 产出); 这张表只在旧报告缺 `verdict_cn` 字段时兜底。
# 曾用它在渲染时**覆盖**记录里的文案, 导致阶段二十三的「建议强化 / 不建议强化」在报告里
# 根本显示不出来（审阅 A 类问题）。
VERDICT_CN = {"pass": "达标", "hold": "保留", "keep": "建议重铸",
              "pending": "建议强化", "fail": "不建议强化", "zero": "0级/无词条"}

# 判定配色（U-11）：键是**中文档位**（`verdict_cn` 的六档），因为 `fail` 一个码里装了两档
# （满级「不合格」/ 未满级「不建议强化」），按码配色根本分不开。
# 旧值对白底只有 2.16~3.68:1（#4caf50 2.78 / #ff9800 2.16 / #f44336 3.68）—— 14px 正文读不出来；
# 现值全部 ≥4.5（实测 5.93~10.47）。行内文字用 VERDICT_COLOR，摘要 chips 配 VERDICT_CHIP_BG。
VERDICT_COLOR = {"达标": "#1F6B4A", "保留": "#42576B", "建议重铸": "#3B4E9B",
                 "建议强化": "#8A5A00", "不建议强化": "#8C3B2E", "不合格": "#7A1C16",
                 "0级/无词条": "#5A5A5A"}
VERDICT_CHIP_BG = {"达标": "#E8F5E9", "保留": "#ECEFF1", "建议重铸": "#E8EAF6",
                   "建议强化": "#FFF4E0", "不建议强化": "#FDECEA", "不合格": "#FBE3E1",
                   "0级/无词条": "#F2F2F2"}

# 六档的展示顺序（汇总卡与报告摘要共用；数量为 0 的不显示）
VERDICT_ORDER = ("达标", "保留", "建议重铸", "建议强化", "不建议强化", "不合格")
_VERDICT_BY_CODE = {"pass": "达标", "hold": "保留", "keep": "建议重铸", "pending": "建议强化"}

# 色弱冗余（U-11）：只靠颜色区分六档，对红绿色弱不友好 → 每档再给一个固定符号。
# 报告行内是「符号 + 文字」，颜色只是辅助。符号都取自常用 BMP 区段（浏览器默认字体都有）。
VERDICT_MARK = {"达标": "●", "保留": "◐", "建议重铸": "◇",
                "建议强化": "↑", "不建议强化": "✕", "不合格": "✖", "0级/无词条": "○"}


def verdict_color(vcn: str = "", code: str = "") -> str:
    """判定文字色：优先按中文档位（`verdict_cn`），旧报告退回 verdict 码。

    「保留(词条缺失)」并到「保留」；认不出给中性深灰（仍是可读的 6.9:1）。
    """
    cn = vcn or VERDICT_CN.get(code, "")
    if cn.startswith("保留"):
        cn = "保留"
    return VERDICT_COLOR.get(cn, "#5A5A5A")


def count_verdicts(results) -> dict[str, int]:
    """按**六档中文判定**计数（汇总卡与报告共用同一份口径）。

    **为什么必须按 `verdict_cn`**: `fail` 一个码里装了两档 —— 满级是「不合格」、未满级是
    「不建议强化」。以前汇总卡按 `verdict` 码映射(`fail → 不合格`)把两档并成一个数，
    于是卡片显示「不合格 36」而报告写「不合格 21 + 不建议强化 15」（U-04）。
    这里只做归类：`verdict_cn` 以「保留」开头(含「保留(词条缺失)」)记进保留；
    旧报告没有该字段才退回 verdict 码（`fail` 只能归到未满级那档）。

    `zero`（0 级/无词条）本来就不写进报告，这里直接忽略。
    """
    out = {k: 0 for k in VERDICT_ORDER}
    for r in results or ():
        cn = r.get("verdict_cn") or ""
        if cn.startswith("保留"):          # 含「保留(词条缺失)」
            out["保留"] += 1
        elif cn in out:
            out[cn] += 1
        elif r.get("verdict") in _VERDICT_BY_CODE:
            out[_VERDICT_BY_CODE[r["verdict"]]] += 1
        elif r.get("verdict") == "fail":
            out["不建议强化"] += 1          # 旧报告没有 verdict_cn → 只能归到未满级那档
    return out


def summary_text(results) -> str:
    """「上次评估结果」卡的第一行：`N 只 · 达标 a · 保留 b · …`（纯函数，便于单测）。

    六档顺序固定（`VERDICT_ORDER`），数量为 0 的不显示。
    """
    counts = count_verdicts(results)
    parts = [f"{k} {counts[k]}" for k in VERDICT_ORDER if counts[k]]
    return f"{len(results)} 只 · " + " · ".join(parts)


def status_texts(task, is_eval: bool) -> tuple[str, str, str]:
    """状态卡三块计数文案（纯函数，便于单测）。

    **为什么分开**: 评估与强化读的计数键**完全不同**。评估链只写 `评估数量`（每记录一只写一次）、
    `评估失败` 与 `评估结束原因`，而状态卡以前一律读强化的
    `成功声骸数量/失败声骸数量/声骸得分` —— 于是评估跑 12 分钟，顶部一直
    「成功: 0 / 失败: 0 / 得分: -」（U-03）。评估也不产出"得分"（得分是强化的逐件结果），
    第三格改显示结束原因（0级尾部/到达背包底部/用户停止…）。

    返回 (第一格, 第二格, 第三格)；第三格可能是空串（评估还没结束 → 没有原因）。
    """
    if is_eval:
        reason = task.info_get('评估结束原因') or ''
        return (f"已记录: {task.info_get('评估数量') or 0}",
                f"失败: {task.info_get('评估失败') or 0}",
                f"结束: {reason}" if reason else "")
    score = task.info_get('声骸得分')
    return (f"成功: {task.info_get('成功声骸数量') or 0}",
            f"失败: {task.info_get('失败声骸数量') or 0}",
            f"得分: {score}" if score is not None else "得分: -")
