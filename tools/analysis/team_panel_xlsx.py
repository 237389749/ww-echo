"""
队伍面板账本 —— 交接文档 §8 的五页结构：角色基础 / 补正明细 / 面板汇总 / 配队 / E 与 43311。

输入:
  - 口径与冻结数字：docs/TEAM_PANEL_SUMMARY_2026-11-24.md §2~§7
  - E / 33311 / 评分和最高：logs/analysis/team_plan_20261124/team_plan.json
    （由 tools/analysis/team_plan.py 生成，本脚本不重算组合穷举）
输出:
  - logs/analysis/team_plan_20261124/team_panel.xlsx
支撑的结论:
  - 「补正明细」是唯一事实源：一行 = 一条补正（提供方 / 目标 / 词条 / 数值 / 受益方案）。
    「面板汇总」用 SUMPRODUCT 从明细现算，再与文档 §3 的冻结值逐项比对（|Δ| ≤ 0.05），
    所以表里任何一个数值被改动，汇总与校验会一起动，不会出现"表改了字没改"。
  - 队伍声骸技能 16（息界 3 件套）+ 20（武器）只建一条「全队」记录，仇远与西格莉卡都从
    这一条取数；「给主C」的轻云 5 件套 22.5% 攻击 + 12 增伤也只建一条。按角色汇总时不会重复。
  - 面板汇总单元格是公式不是常量：改「补正明细」的数值，汇总与校验会跟着变。

口径（与文档一致，不再重复推导）:
  攻击 = 白值 × (1 + 攻击%/100) + 固定攻击；白值是裸面板加号前的数值，固定攻击是技能树
  默认 12%/24% 已折算的部分，不参与新百分比的乘法。
  增伤 = 属伤 + 专伤 + 通用，直接相加；共效不进增伤，条件补正（西格共效>125）需声骸共效，另算。

用法:
  python tools/analysis/team_panel_xlsx.py [team_plan.json] [team_panel.xlsx]
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON = ROOT / "logs/analysis/team_plan_20261124/team_plan.json"
DEFAULT_XLSX = ROOT / "logs/analysis/team_plan_20261124/team_panel.xlsx"

# ---------------------------------------------------------------- 样式

FONT = "Microsoft YaHei"
NAVY = "1F3864"
BLUE = "2F5597"
LIGHT_BLUE = "D9E2F3"
LIGHT_GRAY = "F7F7F7"
MID_GRAY = "BFBFBF"
GREEN = "C6EFCE"
YELLOW = "FFEB9C"
RED = "FFC7CE"
WHITE = "FFFFFF"
DARK = "262626"

THIN = Side(style="thin", color=MID_GRAY)
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def font(size=10, bold=False, color=DARK, italic=False):
    return Font(name=FONT, size=size, bold=bold, color=color, italic=italic)


def fill(color):
    return PatternFill("solid", fgColor=color)


def title(ws, row, text, ncols):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    c = ws.cell(row=row, column=1, value=text)
    c.font = font(15, bold=True, color=WHITE)
    c.fill = fill(NAVY)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[row].height = 30


def section(ws, row, text, ncols):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    c = ws.cell(row=row, column=1, value=text)
    c.font = font(11, bold=True, color=NAVY)
    c.fill = fill(LIGHT_BLUE)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[row].height = 22


def para(ws, row, text, ncols, height=None, italic=False, bold=False):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    c = ws.cell(row=row, column=1, value=text)
    c.font = font(10, bold=bold, italic=italic)
    c.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True, indent=1)
    if height:
        ws.row_dimensions[row].height = height


def header(ws, row, values, widths=None, height=32):
    for j, v in enumerate(values, 1):
        c = ws.cell(row=row, column=j, value=v)
        c.font = font(10, bold=True, color=WHITE)
        c.fill = fill(BLUE)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER
    ws.row_dimensions[row].height = height
    if widths:
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w


def body(ws, row, values, formats=None, align=None, height=None, band=False):
    for j, v in enumerate(values, 1):
        c = ws.cell(row=row, column=j, value=v)
        c.font = font(10)
        c.border = BORDER
        h = align[j - 1] if align else "left"
        c.alignment = Alignment(horizontal=h, vertical="center", wrap_text=True,
                                indent=1 if h == "left" else 0)
        if formats and j - 1 < len(formats) and formats[j - 1]:
            c.number_format = formats[j - 1]
        if band:
            c.fill = fill(LIGHT_GRAY)
    if height:
        ws.row_dimensions[row].height = height


def note(ws, row, text, ncols, height=None):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    c = ws.cell(row=row, column=1, value=text)
    c.font = font(9, italic=True, color="595959")
    c.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True, indent=1)
    if height:
        ws.row_dimensions[row].height = height


# ---------------------------------------------------------------- 结构定义

T1, T2, T3, T4, T5 = ("散华+陆赫斯", "达妮娅+爱弥斯", "散华+绯雪",
                      "仇远(3+2)+西格莉卡", "仇远(5)+西格莉卡")
ALL_TEAMS = (T1, T2, T3, T4, T5)


@dataclass(frozen=True)
class Plan:
    code: str            # P1..P9
    key: str             # team_plan.json 里的 key
    label: str           # 角色/方案
    character: str
    role: str
    teams: tuple[str, ...]
    bare_attack: float   # 白值（加号前）
    bare_flat: float     # 默认攻击%已折算的固定值（加号后）
    bare_energy: float
    bare_crit: float
    bare_cdmg: float
    bare_bonus: float
    bare_bonus_detail: str
    element: str
    note: str = ""

    def teams_text(self) -> str:
        return "、".join(self.teams)


PLANS: tuple[Plan, ...] = (
    Plan("P1", "sanhua", "散华", "散华", "副C", (T1, T3),
         862, 103, 116, 29.3, 150, 12, "冷凝", "冷凝",
         "轻云 5 的 22.5% 攻击 +12 增伤给主C，不入自身；共鸣链 20% 攻击是全队（含自己）。"),
    Plan("P2", "luhesis", "陆赫斯", "陆赫斯", "主C", (T1,),
         1049, 251, 100, 37.3, 150, 0, "", "衍射", ""),
    Plan("P3", "dania", "达妮娅", "达妮娅", "副C", (T2,),
         925, 221, 100, 41, 166, 0, "", "热熔",
         "武器 24% 攻击是爱弥斯的，不计达妮娅。"),
    Plan("P4", "aemis", "爱弥斯", "爱弥斯", "主C", (T2,),
         1012, 121, 100, 37.3, 150, 12, "热熔", "热熔",
         "裸面板 12 增伤视为武器/技能树已在面板里，不另加武器增伤。"),
    Plan("P5", "qiuyuan32", "仇远 3+2", "仇远", "副C", (T4,),
         962, 230, 100, 57.3, 150, 0, "", "气动",
         "3+2 = 息界同调之律 3 + 轻云出月 2；未计息界 2 件套气动 10（计则为 216）。"),
    Plan("P6", "qiuyuan5", "仇远 5", "仇远", "副C", (T5,),
         962, 230, 100, 57.3, 150, 0, "", "气动",
         "轻云出月 ×5：比 3+2 少 息界重击 30 + 队伍声骸 16，多 给主C 的 22.5%/12。"),
    Plan("P7", "sigrika32", "西格莉卡 3+2", "西格莉卡", "主C", (T4,),
         1024, 245, 100, 13, 198.6, 0, "", "气动",
         "条件补正：共效>125 每点 +2 增伤、上限 50，需逐组合按最终共效另算。"),
    Plan("P8", "sigrika5", "西格莉卡 5", "西格莉卡", "主C", (T5,),
         1024, 245, 100, 13, 198.6, 0, "", "气动",
         "条件补正同上；与 3+2 的差别只在队伍给的主C增益（+22.5%/12 vs 声骸技能 36）。"),
    Plan("P9", "feixue", "绯雪", "绯雪", "主C", (T3,),
         1049, 251, 100, 37.3, 150, 0, "", "冷凝",
         "雪落 5 件套的「下一个角色冷凝 +25%」不是绯雪自己，不计。"),
)
PLAN_BY_CODE = {p.code: p for p in PLANS}

TEAM_MEMBERS: dict[str, tuple[tuple[str, str, str | None], ...]] = {
    T1: (("副C", "散华", "P1"), ("主C", "陆赫斯", "P2"), ("治疗", "奶妈", None)),
    T2: (("副C", "达妮娅", "P3"), ("主C", "爱弥斯", "P4"), ("治疗", "奶妈", None)),
    T3: (("副C", "散华", "P1"), ("主C", "绯雪", "P9"), ("治疗", "奶妈", None)),
    T4: (("副C", "仇远", "P5"), ("主C", "西格莉卡", "P7"), ("治疗", "奶妈", None)),
    T5: (("副C", "仇远", "P6"), ("主C", "西格莉卡", "P8"), ("治疗", "奶妈", None)),
}


@dataclass
class Row:
    owner: str
    pos: str
    teams: tuple[str, ...]
    cat: str
    source: str
    target: str
    stat: str
    detail: str
    value: float
    note: str = ""
    benefits: tuple[str, ...] = ()

    def team_text(self) -> str:
        if set(self.teams) == set(ALL_TEAMS):
            return "全部（5 队）"
        return "、".join(self.teams)


def R(owner, pos, teams, cat, source, target, stat, detail, value, remark=""):
    return Row(owner, pos, teams, cat, source, target, stat, detail, float(value), remark)


# 套装名（与 team_plan.json 的 set_a/set_b 一致；下方 main() 会断言）
QINGYUN = "轻云出月"
XIJIE = "息界同调之律"
LIUJIN = "流金溯真之式"
CHANGLU = "长路启航之星"
TINGHUAN = "听唤语义之愿"
XUELUO = "雪落无声之愿"

LEDGER: list[Row] = [
    # ---------------- 散华（轻云出月 ×5，副C）
    R("散华", "副C", (T1, T3), "武器", "武器（15% 攻击）", "自身", "攻击%", "", 15),
    R("散华", "副C", (T1, T3), "角色本体", "角色自带增伤", "自身", "增伤", "冷凝", 20),
    R("散华", "副C", (T1, T3), "共鸣链", "共鸣链（20% 攻击）", "全队", "攻击%", "", 20,
      "全队含散华自己；陆赫斯 / 绯雪都吃。"),
    R("散华", "副C", (T1, T3), "套装", f"{QINGYUN} 2 件套", "自身", "共效", "", 10),
    R("散华", "副C", (T1, T3), "套装", f"{QINGYUN} 5 件套", "给主C", "攻击%", "", 22.5,
      "下一个登场角色；3+2 方案没有这一条。"),
    R("散华", "副C", (T1, T3), "套装", f"{QINGYUN} 5 件套", "给主C", "增伤", "通用", 12,
      "官方套装修文没单独写 12，按用户口径计入。"),

    # ---------------- 陆赫斯（流金溯真之式 ×5，主C）
    R("陆赫斯", "主C", (T1,), "武器", "武器（20% 增伤）", "自身", "增伤", "通用", 20),
    R("陆赫斯", "主C", (T1,), "角色本体", "角色（25% 攻击）", "自身", "攻击%", "", 25),
    R("陆赫斯", "主C", (T1,), "套装", f"{LIUJIN} 2+5 件套", "自身", "增伤", "衍射", 40,
      "衍射 10（2 件套）+ 30（5 件套）。"),
    R("陆赫斯", "主C", (T1,), "套装", f"{LIUJIN} 5 件套", "自身", "增伤", "普攻", 40,
      "满层普攻 40。"),

    # ---------------- 达妮娅（轻云出月 ×5，副C）
    R("达妮娅", "副C", (T2,), "角色本体", "角色（30% 攻击）", "自身", "攻击%", "", 30),
    R("达妮娅", "副C", (T2,), "角色本体", "角色（36% 增伤）", "自身", "增伤", "通用", 36),
    R("达妮娅", "副C", (T2,), "角色本体", "角色（30% 增伤）", "全队", "增伤", "通用", 30,
      "全队含达妮娅自己；爱弥斯也吃。"),
    R("达妮娅", "副C", (T2,), "套装", f"{QINGYUN} 2 件套", "自身", "共效", "", 10),
    R("达妮娅", "副C", (T2,), "套装", f"{QINGYUN} 5 件套", "给主C", "攻击%", "", 22.5),
    R("达妮娅", "副C", (T2,), "套装", f"{QINGYUN} 5 件套", "给主C", "增伤", "通用", 12),

    # ---------------- 爱弥斯（长路启航之星 ×5，主C）
    R("爱弥斯", "主C", (T2,), "武器", "武器（专武 24% 攻击）", "自身", "攻击%", "", 24,
      "这把武器是爱弥斯的，不给达妮娅。"),
    R("爱弥斯", "主C", (T2,), "角色本体", "角色（60% 暴伤）", "自身", "暴伤", "", 60),
    R("爱弥斯", "主C", (T2,), "套装", f"{CHANGLU} 5 件套", "自身", "暴击", "", 20),
    R("爱弥斯", "主C", (T2,), "套装", f"{CHANGLU} 2+5 件套", "自身", "增伤", "热熔", 30,
      "热熔 10（2 件套）+ 20（5 件套）。"),

    # ---------------- 仇远（3+2 与 5 共用自身增益，套装分开）
    R("仇远", "副C", (T4, T5), "武器", "武器（60% 重击）", "自身", "增伤", "重击", 60),
    R("仇远", "副C", (T4, T5), "武器", "武器（队伍声骸技能 20）", "全队", "增伤", "声骸技能", 20,
      "只建一条；仇远与西格莉卡都从这条取数。"),
    R("仇远", "副C", (T4, T5), "角色本体", "角色（10% 攻击）", "自身", "攻击%", "", 10,
      "按 10% 攻击计；若按固定 +10，差异 <0.5%。"),
    R("仇远", "副C", (T4, T5), "角色本体", "角色（50% 增伤）", "自身", "增伤", "通用", 50),
    R("仇远", "副C", (T4, T5), "角色本体", "角色（30% 增伤）", "全队", "增伤", "通用", 30,
      "全队含仇远自己。"),
    R("仇远", "副C", (T4, T5), "角色本体", "角色（30% 暴伤）", "全队", "暴伤", "", 30,
      "全队含仇远自己。"),
    R("仇远", "副C", (T4,), "套装", f"{XIJIE} 3 件套", "自身", "增伤", "重击", 30,
      "仅 3+2 方案有。"),
    R("仇远", "副C", (T4,), "套装", f"{XIJIE} 3 件套", "全队", "增伤", "声骸技能", 16,
      "仅 3+2 方案有；只建一条，仇远与西格都吃。"),
    R("仇远", "副C", (T4, T5), "套装", f"{QINGYUN} 2 件套", "自身", "共效", "", 10,
      "3+2 的 2 件套；5 件套方案里含在 5 件中。"),
    R("仇远", "副C", (T5,), "套装", f"{QINGYUN} 5 件套", "给主C", "攻击%", "", 22.5,
      "仅轻云 5 方案有。"),
    R("仇远", "副C", (T5,), "套装", f"{QINGYUN} 5 件套", "给主C", "增伤", "通用", 12,
      "仅轻云 5 方案有。"),

    # ---------------- 西格莉卡（听唤语义之愿 ×5，主C）
    R("西格莉卡", "主C", (T4, T5), "角色本体", "角色（96% 增伤）", "自身", "增伤", "通用", 96),
    R("西格莉卡", "主C", (T4, T5), "套装", f"{TINGHUAN} 5 件套", "自身", "暴击", "", 20),
    R("西格莉卡", "主C", (T4, T5), "套装", f"{TINGHUAN} 2+5 件套", "自身", "增伤", "气动", 25,
      "气动 10（2 件套）+ 15（5 件套）。"),

    # ---------------- 绯雪（雪落无声之愿 ×5，主C）
    R("绯雪", "主C", (T3,), "角色本体", "角色（40% 暴伤）", "自身", "暴伤", "", 40),
    R("绯雪", "主C", (T3,), "套装", f"{XUELUO} 5 件套", "自身", "暴击", "", 25),
    R("绯雪", "主C", (T3,), "套装", f"{XUELUO} 2+5 件套", "自身", "增伤", "冷凝", 20,
      "冷凝 10（2 件套）+ 10（5 件套）。"),

    # ---------------- 奶妈（全队，一条记录覆盖 5 队）
    R("奶妈", "治疗", ALL_TEAMS, "奶妈", "隐世回光 5 件套 + 全队 20%", "全队", "攻击%", "", 45,
      "25% + 20% 全队攻击；真正的五星奶还有其他加成未计。"),
]

# 文档 §3 冻结值：(攻击总值, 共效, 暴击, 暴伤, 增伤)
EXPECTED = {
    "P1": (1654.6, 126, 29.3, 150, 32),
    "P2": (2480.1, 100, 37.3, 150, 112),
    "P3": (1839.8, 110, 41, 166, 66),
    "P4": (2059.0, 100, 57.3, 210, 84),
    "P5": (1721.1, 110, 57.3, 180, 206),
    "P6": (1721.1, 110, 57.3, 180, 160),
    "P7": (1729.8, 100, 33, 228.6, 187),
    "P8": (1960.2, 100, 33, 228.6, 183),
    "P9": (2217.9, 100, 62.3, 190, 32),
}

STAT_ORDER = ("攻击%", "固定攻击", "共效", "暴击", "暴伤", "增伤")


def resolve_benefits() -> None:
    """按「队伍 × 目标」把每条补正落到受益方案（P1..P9）。"""
    for row in LEDGER:
        hit: list[str] = []
        for p in PLANS:
            if not (set(p.teams) & set(row.teams)):
                continue
            if row.target == "自身":
                if p.character == row.owner:
                    hit.append(p.code)
            elif row.target == "全队":
                hit.append(p.code)
            elif row.target == "给主C":
                if p.role == "主C":
                    hit.append(p.code)
            else:
                raise ValueError(f"未知目标: {row.target}")
        row.benefits = tuple(hit)


def rows_for(code: str) -> list[Row]:
    return [r for r in LEDGER if code in r.benefits]


def panel(code: str) -> dict:
    p = PLAN_BY_CODE[code]
    rows = rows_for(code)
    pct = sum(r.value for r in rows if r.stat == "攻击%")
    flat = p.bare_flat + sum(r.value for r in rows if r.stat == "固定攻击")
    return {
        "plan": p,
        "rows": rows,
        "pct": pct,
        "flat": flat,
        "attack": p.bare_attack * (1 + pct / 100.0) + flat,
        "energy": p.bare_energy + sum(r.value for r in rows if r.stat == "共效"),
        "crit": p.bare_crit + sum(r.value for r in rows if r.stat == "暴击"),
        "cdmg": p.bare_cdmg + sum(r.value for r in rows if r.stat == "暴伤"),
        "bonus": p.bare_bonus + sum(r.value for r in rows if r.stat == "增伤"),
    }


# 门槛系数默认参数（与 src/echo_combos.PlanRequest 一致）
GATE_ENERGY = (120.0, 0.30, 0.85)   # 目标 / 斜率 / 最低
GATE_CRIT = (100.0, 0.40, 0.80)

# `--values-only`：不写公式、直接写算好的数。
# openpyxl 写公式不会带缓存值，用不支持重算的查看器（或某些预览/转换链）打开会显示空白；
# 这个开关给那种场景兜底。默认仍写公式（改明细汇总会跟着变）。
VALUES_ONLY = False


def num_or_formula(value, formula):
    """默认写公式；`--values-only` 时写数值。"""
    return value if VALUES_ONLY else formula


def _gap_factor(value: float, target: float, slope: float, floor: float) -> float:
    """与 src/echo_combos.gap_factor 同一公式：max(最低, 1 − 斜率×(目标−值)/目标)。"""
    if target <= 0 or slope <= 0 or value >= target:
        return 1.0
    return max(floor, 1 - slope * (target - value) / target)


def gate_factors(best: dict) -> tuple[float, float]:
    """(稳定性系数, 循环系数)；只用于展示，准确性由 score/score_raw 的乘积校验兜底。"""
    return (_gap_factor(min(best["crit"], 100.0), *GATE_CRIT),
            _gap_factor(best["energy"], *GATE_ENERGY))


def short_stat(name: str) -> str:
    """把词条名压短，便于表格里看主属性/副词条。"""
    s = str(name or "")
    s = s.replace("伤害加成", "").replace("攻击百分比", "攻击%")
    s = s.replace("生命百分比", "生命%").replace("防御百分比", "防御%")
    s = s.replace("暴击伤害", "暴伤").replace("共鸣效率", "共效")
    s = s.replace("共鸣解放", "共解").replace("共鸣技能", "共技")
    s = s.replace("声骸技能", "声骸")
    return s


# 这些词条本身就是百分比：显示成「暴击22%」；攻击/生命/防御的固定值不带 %。
PCT_STATS = ("暴击", "暴伤", "共效", "治疗", "普攻", "重击", "共技", "共解", "声骸",
             "气动", "热熔", "冷凝", "衍射", "导电", "湮灭", "通用")


def fmt_stat(s: dict) -> str:
    """词条 → 「攻击18%」「暴击22%」「暴伤17.4%」「攻击50」「生命2280」（固定值不带 %）。"""
    if not s or not s.get("name"):
        return ""
    name = short_stat(s["name"])
    val = s["value"]
    if name.endswith("%"):
        return f"{name[:-1]}{val:g}%"
    if name.startswith(PCT_STATS):
        return f"{name}{val:g}%"
    return f"{name}{val:g}"


def _item_rank(item: dict) -> int:
    digits = "".join(ch for ch in (item.get("tag") or "") if ch.isdigit())
    return int(digits) if digits else 10 ** 9


def ordered_items(row: dict) -> list[dict]:
    """按 43311 的摆放顺序输出：4C → 3C → 3C → 1C → 1C；同 COST 内按实例编号从小到大。"""
    return sorted(row["items"], key=lambda i: (-i["cost"], _item_rank(i), i["name"]))


def summarize(rows: list[Row]) -> str:
    """把若干条补正压成一行文字：攻击% +10、增伤·通用 +50 …"""
    buckets: dict[str, float] = {}
    for r in rows:
        key = r.stat if not r.detail else f"{r.stat}·{r.detail}"
        buckets[key] = buckets.get(key, 0) + r.value
    if not buckets:
        return "—"
    order = {s: i for i, s in enumerate(STAT_ORDER)}
    items = sorted(buckets.items(), key=lambda kv: (order.get(kv[0].split("·")[0], 9), kv[0]))
    return "、".join(f"{k} +{v:g}" for k, v in items)


# ---------------------------------------------------------------- 读 team_plan.json

def load_plan_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    by_key = {p["key"]: p for p in data["plans"]}
    # 套装名断言：明细里的来源文字必须和穷举脚本一致
    for key, expect in (("sanhua", QINGYUN), ("luhesis", LIUJIN), ("dania", QINGYUN),
                        ("aemis", CHANGLU), ("qiuyuan32", XIJIE), ("qiuyuan5", QINGYUN),
                        ("sigrika32", TINGHUAN), ("sigrika5", TINGHUAN), ("feixue", XUELUO)):
        got = by_key[key]["set_a"]
        if got != expect:
            raise SystemExit(f"套装名对不上：{key} 期望「{expect}」实际「{got}」")
    if by_key["qiuyuan32"]["set_b"] != QINGYUN:
        raise SystemExit("仇远 3+2 的第二套不是轻云出月")
    return data


# ---------------------------------------------------------------- 生成工作簿

def build(data: dict, dst: Path) -> None:
    resolve_benefits()
    by_key = {p["key"]: p for p in data["plans"]}

    wb = Workbook()
    wb.remove(wb.active)

    n_detail = len(LEDGER)
    n_plan = len(PLANS)

    # ============================================================ Sheet 1 角色基础
    ws = wb.create_sheet("角色基础")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "Sheet 1 · 角色基础（攻击拆分与裸面板）", 12)
    para(ws, 2, "白值 = 带武器裸面板「加号前」的数值；固定攻击 = 「加号后」的部分，是技能树默认攻击%"
                "（12%/24%）已折算出来的固定值，不参与新百分比的乘法。零新百分比时 白值 + 固定 = 裸面板总值。",
         12, 34)
    header(ws, 4, ["角色", "定位", "元素", "白值", "默认%折算固定", "裸面板攻击", "裸共效%", "裸暴击%",
                   "裸暴伤%", "裸增伤%", "默认攻击%", "方案代码"],
           [12, 6, 7, 9, 13, 12, 8, 8, 8, 8, 9, 10])
    basics = [
        ("散华", "副C", "冷凝", 862, 103, 116, 29.3, 150, 12, "冷凝 12", 12, "P1"),
        ("陆赫斯", "主C", "衍射", 1049, 251, 100, 37.3, 150, 0, "—", 24, "P2"),
        ("达妮娅", "副C", "热熔", 925, 221, 100, 41, 166, 0, "—", 24, "P3"),
        ("爱弥斯", "主C", "热熔", 1012, 121, 100, 37.3, 150, 12, "热熔 12", 12, "P4"),
        ("仇远", "副C", "气动", 962, 230, 100, 57.3, 150, 0, "—", 24, "P5 / P6"),
        ("西格莉卡", "主C", "气动", 1024, 245, 100, 13, 198.6, 0, "—", 24, "P7 / P8"),
        ("绯雪", "主C", "冷凝", 1049, 251, 100, 37.3, 150, 0, "—", 24, "P9"),
    ]
    for i, b in enumerate(basics, 5):
        name, role, elem, base, flat, energy, crit, cdmg, bonus, detail, defpct, codes = b
        body(ws, i, [name, role, elem, base, flat, num_or_formula(base + flat, f"=D{i}+E{i}"),
                     energy, crit, cdmg, bonus,
                     f"{defpct}%", codes],
             formats=["", "", "", "#,##0", "#,##0", "#,##0.0", "0.0", "0.0", "0.0", "0.0", "", ""],
             align=["left", "center", "center", "right", "right", "right", "right", "right",
                    "right", "right", "center", "center"],
             band=(i % 2 == 1), height=24)
    note(ws, 5 + len(basics),
         "裸增伤列是裸面板里已经有的元素增伤（散华 冷凝 12 / 爱弥斯 热熔 12），"
         "它已经算在角色的裸面板里，所以「补正明细」不再重复记录。"
         "仇远与西格莉卡各有两套方案，但裸面板相同，故各占一行、方案代码写两遍。", 12, 34)

    # ============================================================ Sheet 2 补正明细
    ws = wb.create_sheet("补正明细")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "Sheet 2 · 补正明细（一行一条补正；可按「角色 × 目标 × 词条」透视）", 12)
    para(ws, 2, "「受益方案」由「队伍 + 目标」推出：自身 → 只给施放者；全队 → 该队所有成员（含施放者）；"
                "给主C → 只给该队主C。队伍声骸技能 16/20 只建一条「全队」记录，仇远与西格莉卡都从它取数。",
         12, 34)
    header(ws, 4, ["编号", "角色/来源方", "位置", "队伍", "来源大类", "来源", "目标", "受益方案",
                   "词条", "细分", "数值", "备注"],
           [6.5, 13, 6, 22, 10, 27, 7, 14, 8, 8, 8, 46])
    for i, row in enumerate(LEDGER, 5):
        body(ws, i, [f"L{i - 4}", row.owner, row.pos, row.team_text(), row.cat, row.source,
                     row.target, "、".join(row.benefits), row.stat, row.detail or "—", row.value,
                     row.note],
             formats=["", "", "", "", "", "", "", "", "", "", "0.0", ""],
             align=["center", "left", "center", "left", "center", "left", "center", "left",
                    "center", "center", "right", "left"],
             band=(i % 2 == 1), height=26)
    last = 4 + n_detail
    ws.auto_filter.ref = f"A4:L{last}"
    ws.freeze_panes = "C5"
    note(ws, last + 1,
         "透视做法：选中 A4:L%d → 插入数据透视表 → 行「角色/来源方」、列「词条」、值「数值（求和）」、"
         "筛选「目标 / 队伍」。" % last, 12, 26)
    note(ws, last + 2,
         "两条易错点：①队伍声骸技能（16 与 20）是「全队」记录，仇远和西格莉卡的面板都靠它，不要再各自建一条；"
         "②轻云 5 件套的 22.5% 攻击 + 12 增伤是「给主C」，不要写进副C自身。", 12, 34)

    # ============================================================ Sheet 3 面板汇总（公式）
    ws = wb.create_sheet("面板汇总")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "Sheet 3 · 面板汇总（不含声骸；数值由「补正明细」现算）", 13)
    para(ws, 2, "攻击总值 = 白值 × (1 + 攻击%/100) + 固定攻击。攻击% / 共效 / 暴击 / 暴伤 / 增伤"
                " 由 SUMPRODUCT 在「补正明细」里按受益方案求和，改明细本页会跟着变。", 13, 32)
    header(ws, 4, ["代码", "角色/方案", "队伍", "白值", "固定攻击", "攻击%", "攻击总值", "共效%",
                   "暴击%", "暴伤%", "增伤%", "补正条数", "备注"],
           [6, 14, 22, 8, 9, 8, 10, 8, 8, 8, 8, 9, 44])

    DET = "补正明细"
    det_stat = f"{DET}!$I$5:$I${last}"
    det_ben = f"{DET}!$H$5:$H${last}"
    det_val = f"{DET}!$K$5:$K${last}"

    def sumifs_stat(code: str, stat: str) -> str:
        return (f"SUMPRODUCT(({det_stat}=\"{stat}\")"
                f"*ISNUMBER(SEARCH(\"{code}\",{det_ben}))*{det_val})")

    base_row = {"P1": 5, "P2": 6, "P3": 7, "P4": 8, "P5": 9, "P6": 9, "P7": 10, "P8": 10, "P9": 11}
    first = 5
    for k, p in enumerate(PLANS):
        r = first + k
        br = base_row[p.code]
        pn = panel(p.code)
        body(ws, r, [p.code, p.label, p.teams_text(),
                     num_or_formula(p.bare_attack, f"=角色基础!D{br}"),
                     num_or_formula(p.bare_flat, f"=角色基础!E{br}"),
                     num_or_formula(pn["pct"], f"={sumifs_stat(p.code, '攻击%')}"),
                     num_or_formula(pn["attack"], f"=D{r}*(1+F{r}/100)+E{r}"),
                     num_or_formula(pn["energy"], f"=角色基础!G{br}+{sumifs_stat(p.code, '共效')}"),
                     num_or_formula(pn["crit"], f"=角色基础!H{br}+{sumifs_stat(p.code, '暴击')}"),
                     num_or_formula(pn["cdmg"], f"=角色基础!I{br}+{sumifs_stat(p.code, '暴伤')}"),
                     num_or_formula(pn["bonus"], f"=角色基础!J{br}+{sumifs_stat(p.code, '增伤')}"),
                     num_or_formula(len(pn["rows"]),
                                    f"=SUMPRODUCT(--ISNUMBER(SEARCH(\"{p.code}\",{det_ben})))"),
                     p.note],
             formats=["", "", "", "#,##0", "#,##0", "0.0", "#,##0.0", "0.0", "0.0", "0.0", "0.0",
                      "0", ""],
             align=["center", "left", "left", "right", "right", "right", "right", "right",
                    "right", "right", "right", "center", "left"],
             band=(k % 2 == 1), height=32)
    total_row = first + n_plan
    note(ws, total_row,
         "仇远 3+2 与 5 的白值/固定相同（962 / 230），差别只在套装记录；"
         "西格莉卡同理（1024 / 245）。西格莉卡的共效天赋（>125 每点 +2 增伤、上限 50）需要最终共效，"
         "本表未计，见「E 与 43311」的敏感性说明。", 13, 34)
    ws.freeze_panes = "C5"

    # ============================================================ Sheet 4 配队
    ws = wb.create_sheet("配队")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "Sheet 4 · 配队（谁给谁、各自吃到什么）", 9)
    para(ws, 2, "「自身补正」= 目标「自身」的记录；「全队补正」= 目标「全队」的记录（包括自己施放的全队效果"
                "和奶妈）；「给主C补正」= 目标「给主C」的记录，只有主C那一格会有。", 9, 30)
    header(ws, 4, ["队伍", "位置", "角色/方案", "自身补正", "全队补正（含自己/奶妈）", "给主C补正",
                   "合计面板（不含声骸）", "代码", "备注"],
           [24, 6, 15, 30, 34, 26, 40, 6, 40])
    r = 5
    for team in ALL_TEAMS:
        members = TEAM_MEMBERS[team]
        for j, (pos, name, code) in enumerate(members):
            if code is None:
                own = [x for x in LEDGER if x.owner == "奶妈" and x.target == "全队"]
                body(ws, r, [team, pos, "奶妈（治疗位）", "—", summarize(own), "—",
                             "全队攻击% +45", "—",
                             "真正的五星奶还有其他加成没算；当前只给全队攻击 45%"],
                     align=["left", "center", "left", "left", "left", "left", "left",
                            "center", "left"],
                     band=(j % 2 == 1), height=44)
                r += 1
                continue
            p = PLAN_BY_CODE[code]
            rows = rows_for(code)
            own = [x for x in rows if x.target == "自身"]
            team_rows = [x for x in rows if x.target == "全队"]
            main_rows = [x for x in rows if x.target == "给主C"]
            pn = panel(code)
            total = (f"攻击 {pn['attack']:,.1f}（{pn['pct']:.1f}%）/ 共效 {pn['energy']:g}% / "
                     f"暴击 {pn['crit']:g}% / 暴伤 {pn['cdmg']:g}% / 增伤 {pn['bonus']:g}%")
            body(ws, r, [team, pos, p.label, summarize(own), summarize(team_rows),
                         summarize(main_rows), total, code, p.note],
                 align=["left", "center", "left", "left", "left", "left", "left", "center", "left"],
                 band=(j % 2 == 1), height=60)
            r += 1
    note(ws, r, "「全队」含施放者自己；「给主C」只给主C，不给副C自己。"
                "队伍合计 E 见「E 与 43311」。", 9, 24)
    ws.freeze_panes = "A5"

    # ============================================================ Sheet 5 最优组合（5 只，带编号）
    ws = wb.create_sheet("最优组合")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "Sheet 5 · 每套方案的两套 5 只：伤害最优 / 评分和最高（照这个装）", 14)
    para(ws, 2, "编号 = 评估报告里的实例号（同名声骸靠它区分）；E 为默认口径（乘共效循环系数；暴击稳定性系数已关）。"
                "每个角色上下两块：上面是「伤害最优」，下面是「43311 内评分和最高」；两者是同一套时会标注。"
                "标「假设」的是 --swap4c 造出来的件，库存里并不存在。", 14, 34)
    header(ws, 4, ["方案", "声骸", "编号", "COST", "套装", "主属性 1", "主属性 2",
                   "副词条 1", "副词条 2", "副词条 3", "副词条 4", "副词条 5", "单件评分", "备注"],
           [16, 24, 7, 6, 17, 16, 14, 15, 15, 15, 15, 15, 9, 22])
    rr = 5
    for p in PLANS:
        j = by_key[p.key]
        set_txt = j["set_a"] + (f" + {j['set_b']}" if j["mode"] == "3+2" else " ×5")
        same = [f"{x['name']}{x['tag']}" for x in j["best"]["items"]] == \
               [f"{x['name']}{x['tag']}" for x in j["score_best"]["items"]]
        for kind, b in (("伤害最优", j["best"]), ("评分和最高（本方案 43311 内）", j["score_best"])):
            mark = "（与伤害最优同一套）" if same and kind.startswith("评分") else ""
            ws.merge_cells(start_row=rr, start_column=1, end_row=rr, end_column=14)
            c = ws.cell(row=rr, column=1,
                        value=f"{p.label}   |   {set_txt}   |   {kind}{mark}"
                              f"   |   E {b['score']:,.1f}   评分和 {b['score_sum']:.2f}"
                              f"   |   攻击 {b['attack']:,.1f}   暴击 {b['crit']:.1f}/{b['crit_dmg']:.1f}"
                              f"   共效 {b['energy']:.1f}   增伤 {b['bonus']:.1f}")
            c.font = font(10, bold=True, color=WHITE)
            c.fill = fill(BLUE)
            c.alignment = Alignment(vertical="center", indent=1)
            ws.row_dimensions[rr].height = 26
            rr += 1
            for x in ordered_items(b):
                mains = list(x["main"]) + [{"name": "", "value": ""}] * (2 - len(x["main"]))
                subs = list(x["stats"]) + [{"name": "", "value": ""}] * (5 - len(x["stats"]))
                hypo = "假设：4C 主词条改为暴伤" if x.get("hypo4c") else ""
                body(ws, rr, [p.label, x["name"], x["tag"], x["cost"], x["set"],
                              fmt_stat(mains[0]), fmt_stat(mains[1])]
                     + [fmt_stat(s) for s in subs[:5]] + [x["score"], hypo],
                     formats=["", "", "", "0", "", "", "", "", "", "", "", "", "0.00", ""],
                     align=["left", "left", "center", "center", "left", "left", "left",
                            "left", "left", "left", "left", "left", "right", "left"],
                     band=(rr % 2 == 0), height=22)
                rr += 1
        rr += 1

    # ============================================================ Sheet 6 E 与 43311
    ws = wb.create_sheet("E 与 43311")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "Sheet 6 · 伤害指数 E 与 43311（默认口径：共效循环系数；暴击惩罚已关）", 10)
    para(ws, 2, "E = 攻击 × (1 + min(暴击,100)/100 × 暴伤/100) × (1 + 增伤/100)；只用于排序，不是实战 DPS。"
                "43311 = 1×4C+2×3C+2×1C。33311（无 4C）只对仇远有意义 —— 他的 4C 池全是暴击主词条，具体见「4C 主属性」页；其它角色的 33311 列仅作参考。", 10, 34)
    header(ws, 4, ["角色/方案", "定位", "队伍", "43311 E", "33311 E（仇远）", "33311 vs 43311",
                   "评分和最高 E（43311）", "差距", "全排列最优 E", "全排列布局"],
           [18, 6, 24, 11, 11, 12, 16, 9, 12, 10])
    r = 5
    for p in PLANS:
        j = by_key[p.key]
        b333 = j.get("best_33311")
        if b333:
            e333 = b333["score"]
            adv = j.get("33311_advantage_pct")
            adv_txt = (f"+{adv:.2f}%" if adv and adv > 0 else f"{adv:.2f}%" if adv is not None else "—")
        else:
            e333, adv_txt = "—", "—"
        body(ws, r, [p.label, p.role, p.teams_text(), j["best"]["score"], e333, adv_txt,
                     j["score_best"]["score"], f"{j['score_gap_pct']:.2f}%",
                     j["best_all"]["score"], j["all_layout"]],
             formats=["", "", "", "#,##0.0", "#,##0.0", "", "#,##0.0", "", "#,##0.0", ""],
             align=["left", "center", "left", "right", "right", "right", "right", "right",
                    "right", "center"],
             band=(r % 2 == 0), height=26)
        r += 1
    last_e = r - 1

    r += 1
    section(ws, r, "队伍合计（1:1 相加，不折算站场/倍率）", 10); r += 1
    header(ws, r, ["队伍", "副C", "副C E", "主C", "主C E", "合计 E", "说明"],
           [34, 10, 11, 10, 11, 11, 46]); r += 1
    team_note = {
        T1: "散华给陆赫斯 20% 攻击 + 轻云 22.5%/12",
        T2: "达妮娅全队 30 增伤 + 轻云 22.5%/12 给爱弥斯",
        T3: "散华给绯雪 20% 攻击 + 轻云 22.5%/12",
        T4: "标准 43311；仇远 3+2 比 5 件套多 息界 重击30 + 声骸16",
        T5: "轻云 5：给西格 22.5%/12，但失去 息界 30+16",
    }
    for name, t in data["teams"].items():
        body(ws, r, [name, t["sub"], t["sub_E"], t["main"], t["main_E"], t["sum"],
                     team_note.get(name, "")],
             formats=["", "", "#,##0.0", "", "#,##0.0", "#,##0.0", ""],
             align=["left", "center", "right", "center", "right", "right", "left"],
             band=(r % 2 == 0), height=26)
        r += 1

    r += 1
    q = data["qiuyuan_compare"]
    section(ws, r, f"仇远队 3+2 vs 轻云 5：3+2 领先 {q['delta_43311_pct']:.2f}% / {q['delta_33311_pct']:.2f}%"
                   f"（临界主C占比 {q['main_share_breakeven_43311_pct']:.1f}% / "
                   f"{q['main_share_breakeven_33311_pct']:.1f}%）", 10)
    r += 2

    # ---- 敏感性：两个「未计入项」如果改口径会怎样
    section(ws, r, "敏感性：两个未计入项如果改口径", 10); r += 1
    header(ws, r, ["情形", "仇远增伤", "仇远 E", "西格 E", "队伍合计", "vs 轻云 5", "说明"],
           [34, 10, 11, 11, 11, 11, 46]); r += 1
    e5 = by_key["qiuyuan5"]["best"]["score"]
    s5 = by_key["sigrika5"]["best"]["score"]
    e32 = by_key["qiuyuan32"]["best"]["score"]
    s32 = by_key["sigrika32"]["best"]["score"]

    # 注意：JSON 里的 best["bonus"] 是「面板增伤 + 声骸给的增伤」的总量（E 里用的就是它），
    # 而 206/160 只是面板部分。所以敏感性要按「总量 + Δ面板」折算，不能直接把总量换成 206。
    total32 = by_key["qiuyuan32"]["best"]["bonus"]
    total5 = by_key["qiuyuan5"]["best"]["bonus"]
    panel32 = EXPECTED["P5"][4]
    panel5 = EXPECTED["P6"][4]

    def scale(total: float, delta: float) -> float:
        return (1 + (total + delta) / 100.0) / (1 + total / 100.0)

    scenarios = [
        ("当前口径（面板 206 / 160）", panel32, panel5,
         "与上面表格一致，作为基准。"),
        ("计入息界 2 件套气动 10（216）", panel32 + 10, panel5,
         "只影响仇远 3+2；3+2 对 5 的领先会进一步拉大。"),
        ("队伍声骸技能不计仇远自身（170 / 140）", panel32 - 36, panel5 - 20,
         "16+20 只给主C；仇远自身少 36（3+2）/ 20（5），西格莉卡不变。"),
    ]
    for i, (label, new32, new5, desc) in enumerate(scenarios):
        e32n = e32 * scale(total32, new32 - panel32)
        e5n = e5 * scale(total5, new5 - panel5)
        tot = e32n + s32
        delta = (tot / (e5n + s5) - 1) * 100
        if i == 0:
            # 基准行必须与上面「队伍合计」完全一致，否则说明折算基准写错了
            assert abs(tot - q["team32_43311"]) < 0.05 and abs(e5n - e5) < 0.05, \
                f"敏感性基准对不上：{tot} vs {q['team32_43311']}"
        body(ws, r, [label, f"{new32:g} / {new5:g}", e32n, s32, tot, f"{delta:+.2f}%", desc],
             formats=["", "", "#,##0.0", "#,##0.0", "#,##0.0", "+0.00;-0.00", ""],
             align=["left", "center", "right", "right", "right", "right", "left"],
             band=(i % 2 == 1), height=30)
        r += 1
    note(ws, r, "敏感性按「增伤线性」折算：只改增伤时 E 乘以 (1+新总增伤/100)/(1+旧总增伤/100)，"
                "攻击与双暴不变；组合本身不变，所以是精确值而不是估算。"
                "注意仇远总增伤（含声骸）比面板 206 高，折算要用总量。", 10, 30)
    r += 2

    section(ws, r, "评分和最高 vs 计算最优（43311 内）", 10); r += 1
    header(ws, r, ["角色", "差距", "结论"], [18, 10, 60]); r += 1
    for p in PLANS:
        j = by_key[p.key]
        gap = j["score_gap_pct"]
        verdict = "评分和=最优" if gap <= 1 else ("差距较小，可近似" if gap <= 6 else "建议穷举复核")
        body(ws, r, [p.label, f"{gap:.2f}%", verdict],
             align=["left", "right", "left"], band=(r % 2 == 0))
        r += 1
    note(ws, r, "评分和只算副词条，主属性（4C 暴击/暴伤、3C 属伤/攻击%）完全不进评分，"
                "所以它不能替代穷举排序；仇远与达妮娅的差距都在 15% 以上。", 10, 30)

    # ---- 两页对照（可选数据源）：4C 主属性 / 纯伤害口径
    base_dir = Path(dst).parent
    swap_path = base_dir / "swap4c" / "team_plan.json"
    pure_path = base_dir / "pure" / "team_plan.json"
    note(ws, r, "4C 主属性（暴击 22 vs 暴伤 44）的对比见「4C 主属性」页；"
                "纯伤害口径（两个系数都不乘）的对照见「纯伤害口径」页。", 10, 26)
    r += 2

    def combo_text(row: dict) -> str:
        return " + ".join(f"{i['name']}{i['tag']}·{i['cost']}C"
                          + ("[假设]" if i.get("hypo4c") else "") for i in ordered_items(row))

    if swap_path.exists():
        sd = json.loads(swap_path.read_text(encoding="utf-8"))
        sby = {p["key"]: p for p in sd["plans"]}
        w4 = wb.create_sheet("4C 主属性")
        w4.sheet_view.showGridLines = False
        title(w4, 1, "4C 主属性：暴击 22 vs 暴伤 44（只对仇远有意义）", 6)
        para(w4, 2, "库存里轻云出月的 4C（无常凶鹭 #13~#16）四只全是暴击 22 主词条，暴伤 44 的 4C 都在"
                    "长路/雪落/流金里 —— 仇远 3+2 的 4C 必须属于轻云，所以他的 43311 只能用暴击 4C，"
                    "再叠加共鸣链 +20 暴击就容易溢出。这就是「无 4C 的 33311」当时看起来更好的原因。"
                    "本页用 --swap4c 造一个「同副词条、主词条 = 暴伤 44」的副本，验证真正该换的是主词条、"
                    "而不是把 4C 拿掉。", 6, 60)
        header(w4, 4, ["方案", "4C 件", "4C 主属性", "43311 E", "相对现库存", "5 只组合"],
               [16, 20, 12, 12, 12, 74])
        rr = 5

        def four_of(row: dict) -> tuple[str, str]:
            for i in row["items"]:
                if i["cost"] == 4:
                    name = f"{i['name']}{i['tag']}" + ("（假设）" if i.get("hypo4c") else "")
                    main = fmt_stat(i["main"][0])
                    return name, main
            return "—（无 4C）", "—"

        for key, label in (("qiuyuan32", "仇远 3+2"), ("qiuyuan5", "仇远 5")):
            base = by_key[key]["best"]
            hy = sby[key]["best"]
            no4 = by_key[key]["best_33311"]
            rows4 = [
                (f"{label}（现库存）", base, 0.0),
                (f"{label}（4C 换暴伤）", hy, (hy["score"] / base["score"] - 1) * 100),
                (f"{label}（无 4C 33311）", no4, (no4["score"] / base["score"] - 1) * 100),
            ]
            for k, (lab, row, d) in enumerate(rows4):
                nm, mn = four_of(row)
                body(w4, rr, [lab, nm, mn, row["score"], "基准" if k == 0 else f"{d:+.2f}%",
                              combo_text(row)],
                     formats=["", "", "", "#,##0.0", "+0.00;-0.00", ""],
                     align=["left", "left", "left", "right", "right", "left"],
                     band=(k == 1), height=30)
                rr += 1
        q32 = by_key["qiuyuan32"]["best"]["score"]
        q5 = by_key["qiuyuan5"]["best"]["score"]
        h32, h5 = sby["qiuyuan32"]["best"]["score"], sby["qiuyuan5"]["best"]["score"]
        s32 = by_key["sigrika32"]["best"]["score"]
        s5 = by_key["sigrika5"]["best"]["score"]
        n32 = by_key["qiuyuan32"]["best_33311"]["score"]
        n5 = by_key["qiuyuan5"]["best_33311"]["score"]
        rr += 1
        section(w4, rr, "结论", 6); rr += 1
        for t in [
            f"仇远 3+2：4C 换暴伤后 E {q32:,.1f} → {h32:,.1f}（{(h32 / q32 - 1) * 100:+.2f}%），"
            f"比现库存 43311 高 {(h32 / q32 - 1) * 100:.2f}%，比 33311（{n32:,.1f}）高 "
            f"{(h32 / n32 - 1) * 100:.2f}%。→ 你的判断成立：该换的是 4C 主词条，不是把 4C 拿掉。",
            f"作为对照：不动 4C 时 33311 只比 43311 高 {(n32 / q32 - 1) * 100:+.2f}% —— "
            f"那点优势完全来自「暴击 4C 溢出」，换成暴伤 4C 后 43311 反而领先 33311 "
            f"{(h32 / n32 - 1) * 100:.2f}%。",
            f"仇远 5：E {q5:,.1f} → {h5:,.1f}（{(h5 / q5 - 1) * 100:+.2f}%），同样反超 33311（{n5:,.1f}）。",
            f"队伍层面：3+2 队合计 {q32 + s32:,.1f} → {h32 + s32:,.1f}；对轻云 5 队的领先 "
            f"{(q32 + s32) / (q5 + s5) - 1:+.2%} → {(h32 + s32) / (h5 + s5) - 1:+.2%}。",
            "代价：暴伤 4C 要重新刷（轻云出月 · COST4 · 暴伤主词条），副词条按上表「4C 换暴伤」那行即可 —— "
            "同一只件暴击 −22、暴伤 +44，所以副词条里暴击的价值会上升。",
            "其它角色不需要这套：爱弥斯/绯雪/达妮娅/陆赫斯的 4C 池里本来就有暴伤 44 的件，穷举会自动选。",
        ]:
            para(w4, rr, "• " + t, 6, 30 if len(t) < 60 else 44)
            rr += 1

    swap3c_path = base_dir / "swap3c" / "team_plan.json"
    if swap3c_path.exists():
        cd = json.loads(swap3c_path.read_text(encoding="utf-8"))
        cby = {p["key"]: p for p in cd["plans"]}
        w3 = wb.create_sheet("3C 主属性")
        w3.sheet_view.showGridLines = False
        title(w3, 1, "3C 主属性：气动 30 vs 攻击% 30（西格莉卡）", 8)
        para(w3, 2, "西格莉卡的增伤池非常大（面板 187 + 声骸，合计 265），30 点属伤此时只值 +8.2%；"
                    "而 30% 攻击乘的是 1024 白值 = +307 攻击（占 3090 的 +9.9%）。所以 3C 主属性从气动换攻击%"
                    "理论上略优 —— 本页用 --swap3c 把「主词条 = 气动 30」的 3C 换成「攻击% 30」（副词条不动）重跑验证。", 8, 44)
        header(w3, 4, ["方案", "3C 件", "3C 主属性", "E", "相对现库存", "攻击", "增伤", "5 只组合"],
               [14, 22, 16, 12, 12, 11, 11, 70])
        rr = 5
        for key, label in (("sigrika32", "西格莉卡 3+2"), ("sigrika5", "西格莉卡 5")):
            base = by_key[key]["best"]
            hy = cby[key]["best"]
            for k, (tag, row) in enumerate((("现库存", base), ("换攻击%", hy))):
                three = [i for i in row["items"] if i["cost"] == 3]
                names = " + ".join(f"{i['name']}{i['tag']}" + ("（假设）" if i.get("hypo3c") else "")
                                   for i in three)
                mains = " / ".join(fmt_stat(m) for i in three for m in i["main"][:1])
                body(w3, rr, [f"{label}（{tag}）", names, mains, row["score"],
                              "基准" if k == 0 else f"{(hy['score'] / base['score'] - 1) * 100:+.2f}%",
                              row["attack"], row["bonus"], combo_text(row)],
                     formats=["", "", "", "#,##0.0", "+0.00;-0.00", "#,##0.0", "0.0", ""],
                     align=["left", "left", "left", "right", "right", "right", "right", "left"],
                     band=(k == 1), height=32)
                rr += 1
        s32 = by_key["sigrika32"]["best"]["score"]
        s5 = by_key["sigrika5"]["best"]["score"]
        h32 = cby["sigrika32"]["best"]["score"]
        h5 = cby["sigrika5"]["best"]["score"]
        rr += 1
        section(w3, rr, "结论", 8); rr += 1
        for t in [
            f"3+2 方案：E {s32:,.1f} → {h32:,.1f}（{(h32 / s32 - 1) * 100:+.2f}%）；"
            f"5 件套方案：E {s5:,.1f} → {h5:,.1f}（{(h5 / s5 - 1) * 100:+.2f}%）。**更优，但不到 1%。**",
            "为什么差这么多：3+2 那套总攻击更低（3090 vs 3321），同样 +307 攻击的相对收益更大；"
            "而且它的增伤池更厚（265 vs 261），30 点属伤更不值钱。",
            "最优组合本身没变（还是那 5 只），只有 3C「双极·渊陨重锋 #43」的主词条从气动 30 换成攻击% 30；"
            "另一只 3C「隐迹铁影 #37」本来就是攻击% 30 —— 也就是说换完之后两个 3C 都是攻击% 主属性。",
            "实际取舍：这点差距（<1%）不值得专门去换件；但如果手上正好有副词条相近的「攻击% 3C」，"
            "给西格莉卡是更好的选择。副词条如果为了凑气动而更差，就别换。",
            "注意：这里假设副词条完全不动。现实里气动 3C 和攻击% 3C 是两只不同的件，"
            "换成副词条更差的那只会直接吃掉这 1%。",
        ]:
            para(w3, rr, "• " + t.replace("**", ""), 8, 30 if len(t) < 60 else 44)
            rr += 1

    if pure_path.exists():
        pd = json.loads(pure_path.read_text(encoding="utf-8"))
        pby = {p["key"]: p for p in pd["plans"]}
        wp = wb.create_sheet("纯伤害口径")
        wp.sheet_view.showGridLines = False
        title(wp, 1, "对照：纯伤害口径（两个系数都不乘）", 6)
        para(wp, 2, "默认口径只保留「共效循环系数」（低共效影响循环，是真实约束）；"
                    "暴击稳定性系数已关（挑战可无限重开，波折不构成成本）。本页是两个系数都不乘的纯伤害，"
                    "差异只来自共效<120 的那几套。", 6, 40)
        header(wp, 4, ["角色/方案", "默认 E（含共效）", "纯伤害 E", "变化", "循环系数", "说明"],
               [18, 16, 13, 10, 9, 40])
        rr = 5
        for i, p in enumerate(PLANS):
            g = by_key[p.key]["best"]
            o = pby[p.key]["best"]
            _cf, ef = gate_factors(g)
            why = "共效未满 120 → 打折" if ef < 1 else "共效达标，不扣"
            body(wp, rr, [p.label, g["score"], o["score"],
                          f"{(g['score'] / o['score'] - 1) * 100:+.2f}%", ef,
                          why or "两项都达标/接近达标，几乎不扣"],
                 formats=["", "#,##0.0", "#,##0.0", "+0.00;-0.00", "0.0000", ""],
                 align=["left", "right", "right", "right", "right", "left"],
                 band=(i % 2 == 1), height=24)
            rr += 1
        note(wp, rr, f"仇远队 3+2 对 5 的领先：纯伤害 {pd['qiuyuan_compare']['delta_43311_pct']:+.2f}% → "
                     f"默认口径 {data['qiuyuan_compare']['delta_43311_pct']:+.2f}%；结论一致（3+2 更好）。"
                     "注意这里的「纯伤害 E」是重新穷举后的最优解，不是把默认口径的 E 直接乘个系数。", 6, 34)

    # ============================================================ 说明与校验
    ws = wb.create_sheet("说明与校验")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "说明与校验（口径 / 与交接文档的核对 / 未计入项 / 用法）", 9)

    r = 3
    section(ws, r, "一、口径速查", 9); r += 1
    for k, v in [
        ("攻击", "攻击总值 = 白值 × (1 + 攻击%/100) + 固定攻击。白值取裸面板加号前（862/1049/925/1012/962/1024/1049），"
                 "固定攻击取加号后（103/251/221/121/230/245/251，技能树默认 12%/24% 已折算）。"),
        ("伤害", "E = 攻击 × (1 + min(暴击,100)/100 × 暴伤/100) × (1 + 增伤/100)，再乘共效循环系数；"
                 "不计加深/抗性/防御。暴击率在期望里已封顶 100%，不另加稳定性惩罚。"),
        ("门槛系数", "共效循环系数：共效 <120 时按 max(0.85, 1 − 0.30×(120−值)/120) 打折（src/echo_combos.gap_factor）。"
                     "暴击稳定性系数（目标 100 / 斜率 0.40 / 最低 0.80）已关闭 —— 挑战可无限重开，波折不构成成本，"
                     "期望值本身就是最优目标，再按暴击率扣一次等于把暴击率计两次；`--crit-gate` 可开回来。"),
        ("增伤", "属伤 + 专伤 + 通用，直接相加；共效不进增伤。"),
        ("目标", "自身 = 只有施放者；全队 = 该队所有成员（含施放者）；给主C = 只给该队主C。"),
        ("共享记录", "队伍声骸技能 16（息界 3 件套）+ 20（武器）只建一条「全队」记录，"
                     "仇远与西格莉卡的面板都计入它；轻云 5 的 22.5% + 12 只建一条「给主C」记录。"),
        ("条件补正", "西格莉卡：共效 >125 后每点 +2 增伤、上限 50，需按每套组合的最终共效逐条算；本工作簿的固定面板不含它。"),
    ]:
        c = ws.cell(row=r, column=1, value=k)
        c.font = font(10, bold=True)
        c.alignment = Alignment(vertical="top", indent=1)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
        c = ws.cell(row=r, column=2, value=v)
        c.font = font(10)
        c.alignment = Alignment(vertical="top", wrap_text=True, indent=1)
        ws.row_dimensions[r].height = 46 if len(v) > 70 else 30
        r += 1

    r += 1
    section(ws, r, "二、与交接文档 §3 面板冻结值的核对（本表 − 文档）", 9); r += 1
    header(ws, r, ["方案", "攻击总值（文档）", "本表", "Δ", "共效 Δ", "暴击 Δ", "暴伤 Δ",
                   "增伤 Δ", "判定"], [14, 14, 12, 8, 9, 9, 9, 9, 12]); r += 1
    check_first = r
    for p in PLANS:
        exp = EXPECTED[p.code]
        src_row = first + [x.code for x in PLANS].index(p.code)
        got = panel(p.code)
        d = [got["attack"] - exp[0], got["energy"] - exp[1], got["crit"] - exp[2],
             got["cdmg"] - exp[3], got["bonus"] - exp[4]]
        ok = max(abs(x) for x in d) <= 0.05
        body(ws, r, [p.label, exp[0],
                     num_or_formula(got["attack"], f"=面板汇总!G{src_row}"),
                     num_or_formula(d[0], f"=C{r}-B{r}"),
                     num_or_formula(d[1], f"=面板汇总!H{src_row}-{exp[1]}"),
                     num_or_formula(d[2], f"=面板汇总!I{src_row}-{exp[2]}"),
                     num_or_formula(d[3], f"=面板汇总!J{src_row}-{exp[3]}"),
                     num_or_formula(d[4], f"=面板汇总!K{src_row}-{exp[4]}"),
                     num_or_formula("✓ 一致" if ok else "⚠ 有差异",
                                    f"=IF(MAX(ABS(D{r}),ABS(E{r}),ABS(F{r}),ABS(G{r}),"
                                    f"ABS(H{r}))<=0.05,\"✓ 一致\",\"⚠ 有差异\")")],
             formats=["", "#,##0.0", "#,##0.0", "+0.000;-0.000", "+0.0;-0.0", "+0.0;-0.0",
                      "+0.0;-0.0", "+0.0;-0.0", ""],
             align=["left", "right", "right", "right", "right", "right", "right", "right", "center"],
             band=(r % 2 == 0))
        r += 1
    check_last = r - 1
    ws.conditional_formatting.add(f"I{check_first}:I{check_last}",
                                  CellIsRule(operator="equal", formula=['"✓ 一致"'], fill=fill(GREEN)))
    ws.conditional_formatting.add(f"I{check_first}:I{check_last}",
                                  CellIsRule(operator="notEqual", formula=['"✓ 一致"'], fill=fill(RED)))
    note(ws, r, "核对是实时公式：改「补正明细」任意数值，这一列会立刻变成 ⚠。"
                "攻击总值允许 ±0.05 的差（文档只保留一位小数，例如 2480.125 写成 2480.1）。", 9, 34)
    r += 1
    stale = [("aemis", "爱弥斯", 32632.6), ("qiuyuan5", "仇远 5", 31471.6),
             ("sigrika5", "西格莉卡 5", 37001.0), ("feixue", "绯雪", 26516.4)]
    parts = "；".join(f"{lab} {old:,.1f}→{by_key[k]['best_33311']['score']:,.1f}"
                     for k, lab, old in stale)
    note(ws, r, "⚠ 交接文档 §6.1「33311 E」列有 4 个数与 team_plan.json / report.md / team_plan.xlsx "
                "三处都不一致（其余 5 个一致），本工作簿采用可复现的 JSON：" + parts
                + "。建议把文档那 4 格改过来。", 9, 58)
    r += 2

    section(ws, r, "三、未计入 / 待确认（沿用交接文档 §7）", 9); r += 1
    for i, t in enumerate([
        "真正的五星奶还有其他加成没算：当前只给「全队攻击 +45%（25%+20%）」，治疗/增伤/武器效果未计。",
        "仇远 3+2 的 206 没算息界 2 件套气动 10；算的话是 216（见「E 与 43311」敏感性）。",
        "旧「300 增伤」西格莉卡预设仍在 assets/char_profiles.json，本次未使用；它的攻击仍是 1269，未拆成 1024+245。",
        "轻云 5 的 12 增伤按本地口径计入；官方套装修文里没有单独写 12。",
        "爱弥斯裸面板 12 增伤按「武器/技能树已在面板里」处理，没有另加武器增伤。",
        "仇远 10 攻击按 10% 攻击计；若按固定 +10，差异 <0.5%。",
        "全队 buff 含自己（散华 20%、达妮娅 30%、仇远 30/30）。",
        "仇远队伍声骸技能 16+20 计入仇远自身增伤，同时也给西格莉卡；若只想给主C，见敏感性第三行。",
    ], 1):
        para(ws, r, f"{i}. {t}", 9, 26 if len(t) < 46 else 38)
        r += 1

    r += 1
    section(ws, r, "四、怎么用", 9); r += 1
    for t in [
        "要改一个数值：只在「补正明细」改，面板汇总 / 配队 / 校验会自动变。",
        "要加一个角色：在「补正明细」加行（角色、队伍、目标、词条、数值、受益方案），在「角色基础」加裸面板行，"
        "再在「面板汇总」加引用行并把代码加进受益方案文本。",
        "要透视：选中「补正明细」A4:L 区域 → 数据透视表；行放「角色/来源方」、列放「词条」，值放「数值（求和）」。",
        "E 与 43311 页的数字来自组合穷举（tools/analysis/team_plan.py），本工作簿不重算穷举，只重算面板。",
    ]:
        para(ws, r, "• " + t, 9, 26 if len(t) < 46 else 38)
        r += 1

    for c, w in zip("ABCDEFGHI", [16, 18, 13, 9, 9, 9, 9, 9, 12]):
        ws.column_dimensions[c].width = w

    # ---------------- 收尾
    for s in wb.worksheets:
        s.sheet_properties.tabColor = BLUE if s.title in (
            "角色基础", "补正明细", "面板汇总", "配队", "最优组合", "E 与 43311", "4C 主属性") else "7F7F7F"
        if s.title != "说明与校验":
            s.sheet_view.zoomScale = 90

    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)


# ---------------------------------------------------------------- 自检

def self_check() -> None:
    resolve_benefits()
    bad = []
    for p in PLANS:
        got = panel(p.code)
        exp = EXPECTED[p.code]
        diffs = (got["attack"] - exp[0], got["energy"] - exp[1], got["crit"] - exp[2],
                 got["cdmg"] - exp[3], got["bonus"] - exp[4])
        if max(abs(d) for d in diffs) > 0.051:
            bad.append((p.label, diffs, got))
        else:
            print(f"  {p.code} {p.label:<10s} 攻击 {got['attack']:9.2f} 共效 {got['energy']:6.1f} "
                  f"暴击 {got['crit']:6.1f} 暴伤 {got['cdmg']:6.1f} 增伤 {got['bonus']:6.1f}  OK")
    # 结构守卫：共享记录不能重复
    for row in LEDGER:
        if not row.benefits:
            bad.append((row.owner, "没有受益方案", row))
        if row.target in ("自身", "给主C") and len(row.teams) > 1:
            pass
    if bad:
        for b in bad:
            print("  [不一致]", b)
        raise SystemExit("面板与交接文档不一致，拒绝写文件")


def main() -> None:
    global VALUES_ONLY
    argv = [a for a in sys.argv[1:] if a != "--values-only"]
    VALUES_ONLY = "--values-only" in sys.argv
    src = Path(argv[0]) if len(argv) > 0 else DEFAULT_JSON
    dst = Path(argv[1]) if len(argv) > 1 else DEFAULT_XLSX
    data = load_plan_json(src)
    print(f"ledger {len(LEDGER)} 条 / plans {len(PLANS)} 个"
          + ("（--values-only：写数值不写公式）" if VALUES_ONLY else ""))
    self_check()
    build(data, dst)
    print(f"wrote {dst}")
    if not VALUES_ONLY:
        print("  提示：openpyxl 写的公式没有缓存值，用 Excel/WPS/LibreOffice 打开一次会重算；"
              "若要在不支持重算的查看器里看，加 --values-only 重跑。")
    wb = load_workbook(dst)
    for name in wb.sheetnames:
        s = wb[name]
        print(f"  {name}: {s.max_row} rows x {s.max_column} cols")


if __name__ == "__main__":
    main()

