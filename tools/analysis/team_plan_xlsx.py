"""
把 `team_plan.py` 生成的 team_plan.json 渲染成 Excel 工作簿。

运行（需要 openpyxl；项目默认 Python 没有，用 DSH bundled Python）:
    python tools/analysis/team_plan_xlsx.py logs/analysis/team_plan_20261124/team_plan.json \
        logs/analysis/team_plan_20261124/team_plan.xlsx
"""
from __future__ import annotations

import json
import os
import sys

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT = "Microsoft YaHei"
NAVY = "1F3864"
BLUE = "2F5597"
LIGHT_BLUE = "D9E2F3"
LIGHT_GRAY = "F2F2F2"
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


def title(ws, row, text, ncols, size=16):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    c = ws.cell(row=row, column=1, value=text)
    c.font = font(size, bold=True, color=WHITE)
    c.fill = fill(NAVY)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[row].height = 28 if size >= 16 else 22


def section(ws, row, text, ncols):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    c = ws.cell(row=row, column=1, value=text)
    c.font = font(12, bold=True, color=NAVY)
    c.fill = fill(LIGHT_BLUE)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[row].height = 22


def para(ws, row, text, ncols, height=None, bold_prefix=None):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    c = ws.cell(row=row, column=1, value=text)
    c.font = font(10)
    c.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True, indent=1)
    if height:
        ws.row_dimensions[row].height = height


def header(ws, row, values, widths=None, height=30):
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


def body_row(ws, row, values, formats=None, align=None, height=None, band=False):
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


def fmt_num(v, nd=1):
    return f"{v:,.{nd}f}"


def short_stat(name: str) -> str:
    """把词条名压短，便于表格里看主属性。"""
    s = str(name or "")
    s = s.replace("伤害加成", "")
    s = s.replace("攻击百分比", "攻击%").replace("生命百分比", "生命%").replace("防御百分比", "防御%")
    s = s.replace("暴击伤害", "暴伤")
    s = s.replace("共鸣效率", "共效")
    s = s.replace("共鸣解放", "共解").replace("共鸣技能", "共技")
    s = s.replace("声骸技能", "声骸")
    return s


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "team_plan.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "team_plan.xlsx"
    data = json.load(open(src, encoding="utf-8"))
    plans = data["plans"]
    by_key = {p["key"]: p for p in plans}

    wb = Workbook()
    wb.remove(wb.active)

    # ------------------------------------------------------------ 目录
    ws = wb.create_sheet("目录")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "鸣潮 7 角色声骸组合与队伍面板分析", 4)
    para(ws, 2, "本工作簿由 tools/analysis/team_plan.py 生成；所有数值为相对伤害指数 E，不是实战 DPS。", 4, 20)
    header(ws, 4, ["工作表", "内容", "怎么用"], [24, 66, 40])
    rows = [
        ("说明", "数据来源、伤害口径、面板口径、队伍加成与假设", "先读这一页"),
        ("结论", "仇远 3+2 vs 5、评分法能否替代穷举、裸Top5 问题", "只看结论"),
        ("总览", "9 个方案（7 角色）的最优面板与 5 只组合", "横向对比"),
        ("面板补正", "裸面板 + 各种补正（不含声骸）的合计", "核对输入"),
        ("配队补正", "每队谁给谁、自身/队友补正、合计面板、未计入项", "核对有没有算漏"),
        ("队伍对比", "4 队的副C+主C合计、仇远队临界主C占比", "看仇远队"),
        ("43311对比", "43311 内计算最优 vs 评分和最高；全排列布局与 33311 无4C", "回答'排列组合有没有必要'"),
        ("散华", "轻云出月 ×5，Top 10", "副C"),
        ("陆赫斯", "流金溯真之式 ×5，Top 10", "主C"),
        ("达妮娅", "轻云出月 ×5，Top 10", "副C"),
        ("爱弥斯", "长路启航之星 ×5，Top 10", "主C"),
        ("仇远3+2", "息界 3 + 轻云 2，含4C Top 10；另给无4C上限", "副C"),
        ("仇远5", "轻云出月 ×5，Top 10", "副C"),
        ("西格莉卡3+2", "听唤语义之愿 ×5（仇远3+2 的队伍buff）", "主C"),
        ("西格莉卡5", "听唤语义之愿 ×5（仇远轻云5 的队伍buff）", "主C"),
        ("绯雪", "雪落无声之愿 ×5，Top 10", "主C"),
        ("最佳组合词条", "每个方案第 1 名的 5 只声骸：主属性/副词条/单件评分", "照着装"),
        ("输入明细", "每个方案的裸面板、补正、专伤、条件补正", "核对输入"),
    ]
    for i, (name, desc, how) in enumerate(rows, 5):
        body_row(ws, i, [name, desc, how], align=["left", "left", "left"], band=(i % 2 == 0))
        ws.cell(row=i, column=1).hyperlink = f"#'{name}'!A1"
        ws.cell(row=i, column=1).font = font(10, color="0563C1")
        ws.cell(row=i, column=1).border = BORDER

    # ------------------------------------------------------------ 说明
    ws = wb.create_sheet("说明")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "说明：数据、口径与假设", 4)
    row = 3
    section(ws, row, "一、数据与伤害口径", 4); row += 1
    items = [
        ("库存", f"{os.path.basename(data['inventory'])}：{data['inventory_count']} 只 / 满级 {data['max_level_count']} 只。"
                 "rep7（139 条、听唤满级 16 只、OCR 变体更多）未用；rep6 的听唤满级件更多、名字更干净。"),
        ("裸面板", "攻击用加号前的数值作百分比基底（862/1049/925/1012/962/1024/1049）；"
                    "加号后的 103/251/221/121/230/245/251 是技能树默认攻击%（12%/24%）已折算成固定值，"
                    "所以零新百分比时仍等于 965/1300/1146/1133/1192/1269/1300。"
                    "面板 = 基础值 × (1 + 百分比/100) + 固定值。"),
        ("伤害", "E = 攻击 × (1 + min(暴击,100)/100 × 暴伤/100) × (1 + 增伤/100)。"
                 "不计加深/抗性/防御；默认口径乘共效循环系数（<120 打折），暴击稳定性系数已关（可无限重开，波折不构成成本）。"),
        ("增伤", "属伤 + 专伤 + 通用增伤，直接相加；共效不进增伤。"),
        ("元素", "声骸 3C 主属性必须与角色同元素；异元素 3C 主属性对角色无效，已从候选中剔除。"),
        ("4C", "标准结果固定 43311（1×4C+2×3C+2×1C）；仇远 3+2 另给无4C 的 33311 作对照（默认口径下只高 0.2%；真正的解法是 4C 主词条换暴伤，见 team_panel.xlsx「4C 主属性」）。"),
        ("评分", "报告里的套装评分（只按副词条）；通用评分另算作对照，但本批数据上并不更接近伤害最优。"),
    ]
    for k, v in items:
        ws.cell(row=row, column=1, value=k).font = font(10, bold=True)
        ws.cell(row=row, column=1).alignment = Alignment(vertical="top")
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
        c = ws.cell(row=row, column=2, value=v)
        c.font = font(10)
        c.alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[row].height = 72 if len(v) > 100 else (46 if len(v) > 50 else 26)
        row += 1

    row += 1
    section(ws, row, "二、队伍加成（未标全队的都是单人）", 4); row += 1
    header(ws, row, ["来源", "对象", "加成", "说明"], [18, 20, 42, 60]); row += 1
    buffs = [
        ("奶妈", "全队", "攻击% +45", "隐世回光 5 件套 25% + 20% 全队攻击；各队一致。"),
        ("散华", "全队", "攻击% +20", "共鸣链 20% 攻击全队加成（含散华自己）。"),
        ("散华", "主C", "攻击% +22.5 / 增伤 +12", "轻云出月 5 件套：下一个登场的角色。"),
        ("达妮娅", "全队", "增伤 +30", "全队 30 增伤（含达妮娅自己）。"),
        ("达妮娅", "主C", "攻击% +22.5 / 增伤 +12", "轻云出月 5 件套。"),
        ("爱弥斯武器", "爱弥斯", "攻击% +24", "按纠正：这把武器给爱弥斯，不给达妮娅。"),
        ("仇远", "全队", "增伤 +30 / 暴伤 +30", "全队 30 增伤、30 暴伤（含仇远自己）。"),
        ("仇远 3+2", "主C", "声骸技能 +36", "息界 3 件套 16% + 武器 20%，只计给西格莉卡。"),
        ("仇远 5", "主C", "声骸技能 +20 / 攻击% +22.5 / 增伤 +12", "武器 20% 声骸技能 + 轻云 5 的 22.5% 攻击 +12 增伤。"),
        ("各角色自身", "自己", "见「输入明细」", "武器/角色/套装/共鸣链的单人加成。"),
    ]
    for i, b in enumerate(buffs):
        body_row(ws, row, list(b), align=["left", "left", "left", "left"], band=(i % 2 == 1))
        row += 1

    row += 1
    section(ws, row, "三、关键假设与注意", 4); row += 1
    notes = [
        "「全队」buff 含施放者自身；「角色」「武器」未标全队的是单人。",
        "仇远「10攻击」按 10% 攻击计（用户说明这里的数值都是百分比）；若按固定 +10，差异 <0.5%。",
        "爱弥斯裸面板的 12 增伤视为武器/技能树已在面板里，不另加武器增伤。",
        "达妮娅的「武器：爱弥斯 24% 攻击」按爱弥斯武器处理：24% 计给爱弥斯，达妮娅不吃这 24%。",
        "仇远的「队伍声骸技能 +16%/+20%」计入仇远自身增伤，同时也给西格莉卡（3+2共36/5共20）；息界2件套气动10未计入你给的206。",
        "轻云 5 的 22.5% 攻击 +12 增伤只给下一个登场的主C，不给副C自己。",
        "队伍合计 E 按 1:1 权重相加，不含技能倍率/站场时间；跨队比较没有意义，仇远队内部比较已给临界主C占比。",
        "散华与达妮娅都用轻云出月；若两队同时上场，1C 的游弋蝶/呼咻咻需要错开。达妮娅把游弋蝶换晶螯蝎只低约 0.13%。",
        "3+2 的评分和跨两套权重，严格来说不可直接比；评分法对比表仍按报告评分和展示，仅作粗略对照。",
        "rep7 复核（同脚本）：仇远/西格莉卡四项结果一致；散华 +3.5%、陆赫斯 -1.2%（库存差异），结论不变。",
        "西格莉卡的旧「300 增伤」预设仍在 assets/char_profiles.json（声骸技能160 / 气动80 / 通用25 / 暴伤30 / 攻击37.5 / 天赋50），本次未使用；本次按新给的 96+25+36/30 计算，避免重复。",
    ]
    for t in notes:
        para(ws, row, "• " + t, 4, 40 if len(t) > 80 else 24)
        row += 1
    for c, w in zip("ABCD", [18, 24, 48, 64]):
        ws.column_dimensions[c].width = w

    # ------------------------------------------------------------ 结论
    ws = wb.create_sheet("结论")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "结论速览", 7)
    q = data["qiuyuan_compare"]
    row = 3
    section(ws, row, "1. 仇远队：3+2 vs 轻云 5", 7); row += 1
    header(ws, row, ["方案", "仇远E", "西格莉卡E", "合计E", "相对5件套", "说明"],
           [30, 12, 12, 12, 12, 44]); row += 1
    e32 = by_key["qiuyuan32"]["best"]["score"]
    e32n = by_key["qiuyuan32"]["best_33311"]["score"]
    e5 = by_key["qiuyuan5"]["best"]["score"]
    s32 = by_key["sigrika32"]["best"]["score"]
    s5 = by_key["sigrika5"]["best"]["score"]
    rows = [
        ("仇远 3+2（标准43311）", e32, s32, round(e32 + s32, 1), f"+{q['delta_43311_pct']:.2f}%", "标准 3+2：息界3+轻云2，4C属轻云"),
        ("仇远 3+2（无4C 33311）", e32n, s32, round(e32n + s32, 1), f"+{q['delta_33311_pct']:.2f}%", "不带4C的对照（默认口径下只高 0.2%）"),
        ("仇远 轻云5（43311）", e5, s5, round(e5 + s5, 1), "基准", "轻云5：失去息界的 气动10+重击30，但给西格莉卡22.5%攻击"),
    ]
    for i, r in enumerate(rows):
        body_row(ws, row, list(r)[:6], formats=["", "#,##0.0", "#,##0.0", "#,##0.0", "", ""],
                 align=["left", "right", "right", "right", "right", "left"], band=(i % 2 == 1))
        row += 1
    para(ws, row, f"3+2 领先 5 件套 {q['delta_43311_pct']:.2f}%（43311）/ {q['delta_33311_pct']:.2f}%（33311）。"
                  f"临界：西格莉卡实际伤害占比超过 {q['main_share_breakeven_43311_pct']:.1f}%（43311）/ "
                  f"{q['main_share_breakeven_33311_pct']:.1f}%（33311）时，5 件套才反超。",
         7, 34); row += 2

    section(ws, row, "2. 默认 43311 内：计算最优 vs 评分和最高", 7); row += 1
    header(ws, row, ["角色", "方案", "43311最优E", "43311最高分E", "差距%", "结论"],
           [22, 14, 14, 14, 10, 34]); row += 1
    for p in plans:
        gap = p["score_gap_pct"]
        verdict = "评分和=最优" if gap <= 1 else ("差距较小" if gap <= 6 else "建议穷举")
        label = p["mode"]
        if p["key"] == "sigrika32":
            label = "5（仇远3+2）"
        elif p["key"] == "sigrika5":
            label = "5（仇远轻云5）"
        body_row(ws, row, [p["character"], label, p["best"]["score"], p["score_best"]["score"],
                           f"{gap:.2f}%", verdict],
                 formats=["", "", "#,##0.0", "#,##0.0", "", ""],
                 align=["left", "center", "right", "right", "right", "left"],
                 band=(row % 2 == 0))
        row += 1
    g = {p["key"]: p["score_gap_pct"] for p in plans}
    para(ws, row, f"结论：43311 内评分和最高，西格莉卡=最优；陆赫斯 {g['luhesis']:.2f}%、"
                  f"爱弥斯 {g['aemis']:.2f}%、绯雪 {g['feixue']:.2f}%、散华 {g['sanhua']:.2f}%，"
                  f"可作近似或需复核；仇远3+2 {g['qiuyuan32']:.2f}%、仇远5 {g['qiuyuan5']:.2f}%、"
                  f"达妮娅 {g['dania']:.2f}%，建议穷举。"
                  "若不限定 43311，评分和最高的合法5件会选到 33111/33311/11111，E 反而低 9.8%~22.8%。",
         6, 48); row += 2

    section(ws, row, "3. 建议", 7); row += 1
    for t in [
        "仇远队优先 3+2；如果西格莉卡是绝对主C（占比 >80%），再考虑轻云5。",
        "先在 43311 内用「评分和最高」做短名单，再用穷举复核；达妮娅/仇远不要只用评分。",
        "仇远 3+2 的 33311（无4C）在默认口径下只比 43311 高 0.2%（纯伤害口径 1.06%）；库里 4C 全是暴击件，换暴伤主词条收益更大。其他角色全排列最优就是 43311。",
        "异元素 3C 主属性一律不要；同名多只只能选一只，ΣCOST 不超过 12。",
        "各角色独立最优；散华/达妮娅同用轻云时，注意 1C 实例错开。",
    ]:
        para(ws, row, "• " + t, 7, 22)
        row += 1
    for c, w in zip("ABCDEFG", [22, 14, 14, 14, 10, 34, 2]):
        ws.column_dimensions[c].width = w

    # ------------------------------------------------------------ 总览
    ws = wb.create_sheet("总览")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "总览：9 个方案的 43311 最优配装", 16)
    headers = ["角色", "定位", "队伍", "模式", "套装A", "套装B", "43311最优E", "33311最优E",
               "全排列布局", "攻击", "暴击%", "暴伤%", "共效%", "增伤%", "评分和", "5只组合"]
    widths = [12, 6, 30, 6, 16, 14, 11, 11, 10, 9, 8, 8, 8, 9, 8, 72]
    header(ws, 3, headers, widths)
    for i, p in enumerate(plans, 4):
        b = p["best"]
        b333 = p["best_33311"]
        combo = " + ".join(f"{x['name']}{x['tag']}·{x['cost']}C" for x in b["items"])
        body_row(ws, i, [p["character"], p["role"], p["team"], p["mode"], p["set_a"], p["set_b"],
                         b["score"], b333["score"] if b333 else "—", p["all_layout"],
                         b["attack"], b["crit"], b["crit_dmg"],
                         b["energy"], b["bonus"], b["score_sum"], combo],
                 formats=["", "", "", "", "", "", "#,##0.0", "#,##0.0", "", "#,##0.0", "0.0", "0.0",
                          "0.0", "0.0", "0.00", ""],
                 align=["left", "center", "left", "center", "left", "left", "right", "right",
                        "center", "right", "right", "right", "right", "right", "right", "left"],
                 band=(i % 2 == 0), height=48)
    ws.freeze_panes = "A4"
    note(ws, 4 + len(plans), "说明：E 是相对指数，不能跨角色比较；43311 = 1×4C+2×3C+2×1C，"
                            "33311 = 0×4C+3×3C+2×1C（需要 3 个不同 3C 名字；流金只有 2 个，故陆赫斯为 —）。"
                            "仇远 3+2 的 33311 只比 43311 高 0.2%（默认口径），其余角色的全排列最优就是 43311。", 16, 40)

    # ------------------------------------------------------------ 面板补正
    ws = wb.create_sheet("面板补正")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "面板补正：裸面板 + 各种补正（不含声骸）", 10)
    header(ws, 3, ["角色/方案", "裸攻击", "攻击%补正", "固定攻击", "攻击总值", "暴击%", "暴伤%",
                   "共效%", "增伤%", "备注"],
           [20, 10, 11, 10, 11, 9, 9, 9, 10, 30])
    for i, p in enumerate(plans, 4):
        bp = p["base_panel"]
        remark = "条件补正需声骸共效，表中未计" if p["derived"] else ""
        body_row(ws, i, [f"{p['character']}（{p['mode']}）", bp["base"]["攻击"], bp["pct"]["攻击"],
                         bp["flat"]["攻击"], bp["attack"], bp["crit"], bp["crit_dmg"], bp["energy"],
                         bp["bonus"], remark],
                 formats=["", "#,##0.0", "0.0", "#,##0.0", "#,##0.0", "0.0", "0.0", "0.0", "0.0", ""],
                 align=["left", "right", "right", "right", "right", "right", "right", "right",
                        "right", "left"],
                 band=(i % 2 == 0), height=26)
    note(ws, 4 + len(plans), "攻击总值 = 裸攻击 × (1 + 攻击%补正/100) + 固定攻击；不含声骸主属性/副词条。"
                            "增伤 = 属伤+专伤+通用，直接相加；条件补正（共效转增伤）需声骸共效，表中未计。", 10, 30)

    # ------------------------------------------------------------ 队伍对比
    ws = wb.create_sheet("队伍对比")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "队伍对比（副C + 主C）", 8)
    header(ws, 3, ["队伍", "副C", "副C E", "主C", "主C E", "合计E", "说明", ""],
           [34, 12, 12, 12, 12, 12, 44, 2])
    team_notes = {
        "散华+陆赫斯": "散华轻云5给陆赫斯22.5%攻击+12增伤；散华20%攻击共鸣链全队",
        "达妮娅+爱弥斯": "达妮娅全队30增伤 + 轻云5给爱弥斯22.5%攻击+12增伤",
        "散华+绯雪": "散华轻云5给绯雪22.5%攻击+12增伤；散华20%攻击共鸣链全队",
        "仇远+西格莉卡（3+2 标准43311）": "标准43311：息界3+轻云2，4C属轻云",
        "仇远+西格莉卡（3+2 无4C 33311）": "无4C，3×3C+2×1C；默认口径下仅高 0.2%",
        "仇远+西格莉卡（轻云5 43311）": "轻云5：仇远失去息界 重击30+声骸16，西格莉卡得22.5%攻击+12增伤",
    }
    r = 4
    for name, t in data["teams"].items():
        body_row(ws, r, [name, t["sub"], t["sub_E"], t["main"], t["main_E"], t["sum"],
                         team_notes.get(name, ""), ""],
                 formats=["", "", "#,##0.0", "", "#,##0.0", "#,##0.0", "", ""],
                 align=["left", "center", "right", "center", "right", "right", "left", "left"],
                 band=(r % 2 == 0))
        r += 1
    note(ws, r, "合计 E 按 1:1 权重；不含技能倍率/站场时间，跨队比较没有意义。", 8)
    r += 2

    section(ws, r, "仇远队：3+2 vs 轻云 5（关键对比）", 8); r += 1
    header(ws, r, ["方案", "仇远E", "西格莉卡E", "合计E", "Δ vs 5", "Δ%", "备注", ""],
           [30, 12, 14, 12, 12, 10, 44, 2]); r += 1
    comp = [
        ("仇远 3+2（标准43311）", e32, s32, round(e32 + s32, 1), round(e32 + s32 - (e5 + s5), 1),
         q["delta_43311_pct"], "标准 3+2"),
        ("仇远 3+2（无4C 33311）", e32n, s32, round(e32n + s32, 1), round(e32n + s32 - (e5 + s5), 1),
         q["delta_33311_pct"], "不带4C的绝对上限"),
        ("仇远 轻云5（43311）", e5, s5, round(e5 + s5, 1), 0, 0, "基准"),
    ]
    for i, rowv in enumerate(comp):
        body_row(ws, r, list(rowv),
                 formats=["", "#,##0.0", "#,##0.0", "#,##0.0", "+#,##0.0;-#,##0.0", "+0.00;-0.00", ""],
                 align=["left", "right", "right", "right", "right", "right", "left", "left"],
                 band=(i % 2 == 1))
        r += 1
    para(ws, r, f"仇远个人 3+2 比 5 高 {q['sub_delta_43311']:.1f} E（43311）/ {q['sub_delta_33311']:.1f} E（33311）；"
                f"西格莉卡 3+2 比 5 低 {abs(q['main_delta']):.1f} E。"
                f"临界主C占比：43311 {q['main_share_breakeven_43311_pct']:.1f}% / "
                f"33311 {q['main_share_breakeven_33311_pct']:.1f}%。",
         8, 34); r += 1
    for c, w in zip("ABCDEFGH", [34, 12, 12, 12, 12, 12, 44, 2]):
        ws.column_dimensions[c].width = w

    # ------------------------------------------------------------ 43311 对比
    ws = wb.create_sheet("43311对比")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "默认 43311：计算最优 vs 评分和最高", 10)
    header(ws, 3, ["角色", "方案", "43311最优E", "43311最高分E", "差距%", "全排列最优E", "全排列布局",
                   "33311最优E", "33311 vs 43311", "结论"],
           [12, 12, 13, 14, 9, 13, 10, 12, 13, 32])
    for i, p in enumerate(plans, 4):
        gap = p["score_gap_pct"]
        verdict = "评分和=最优" if gap <= 1 else ("差距较小" if gap <= 6 else "建议穷举")
        if p["all_layout"] != "43311":
            verdict = f"43311非全排列最优；{verdict}"
        b333 = p["best_33311"]
        if b333:
            e333 = b333["score"]
            g333 = p["33311_vs_43311_pct"]
            g333_txt = f"+{g333:.2f}%" if g333 > 0 else f"{g333:.2f}%"
        else:
            e333, g333_txt = "—", "—"
        label = p["mode"]
        if p["key"] == "sigrika32":
            label = "5（仇远3+2）"
        elif p["key"] == "sigrika5":
            label = "5（仇远轻云5）"
        body_row(ws, i, [p["character"], label, p["best"]["score"], p["score_best"]["score"], gap,
                         p["best_all"]["score"], p["all_layout"], e333, g333_txt, verdict],
                 formats=["", "", "#,##0.0", "#,##0.0", "0.00", "#,##0.0", "", "#,##0.0", "", ""],
                 align=["left", "center", "right", "right", "right", "right", "center", "right", "right", "left"],
                 band=(i % 2 == 0), height=30)
    last = 3 + len(plans)
    ws.conditional_formatting.add(f"E4:E{last}",
                                  CellIsRule(operator="lessThanOrEqual", formula=["1"], fill=fill(GREEN)))
    ws.conditional_formatting.add(f"E4:E{last}",
                                  CellIsRule(operator="between", formula=["1", "6"], fill=fill(YELLOW)))
    ws.conditional_formatting.add(f"E4:E{last}",
                                  CellIsRule(operator="greaterThan", formula=["6"], fill=fill(RED)))
    note(ws, last + 2, "「43311最高分E」= 43311（1×4C+2×3C+2×1C）内按报告评分和最高的组合，不是评分前五；"
                       "「差距」= 它比 43311 伤害最优低多少。"
                       "「全排列最优E」允许任意布局；除仇远3+2外均为43311。"
                       "「33311 vs 43311」正数=无4C更好（仅仇远3+2），负数=更差。", 10, 40)
    ws.freeze_panes = "A4"

    # ------------------------------------------------------------ 每方案 Top 10
    sheet_names = {
        "sanhua": "散华", "luhesis": "陆赫斯", "dania": "达妮娅", "aemis": "爱弥斯",
        "qiuyuan32": "仇远3+2", "qiuyuan5": "仇远5",
        "sigrika32": "西格莉卡3+2", "sigrika5": "西格莉卡5", "feixue": "绯雪",
    }
    for p in plans:
        sname = sheet_names[p["key"]]
        ws = wb.create_sheet(sname)
        ws.sheet_view.showGridLines = False
        b = p["top"][0]
        set_txt = p["set_a"] + (f" + {p['set_b']}" if p["mode"] == "3+2" else " ×5")
        title(ws, 1, f"{p['character']} · {p['mode']} · {set_txt} · 43311 Top 10",
              15)
        para(ws, 2, f"43311最优 E {fmt_num(b['score'])} | 攻击 {fmt_num(b['attack'])} | 暴击 {b['crit']:.1f}% / 暴伤 {b['crit_dmg']:.1f}% | "
                    f"共效 {b['energy']:.1f}% | 增伤 {b['bonus']:.1f}% | 候选 {p['candidates']} 只 / "
                    f"全排列 {p['evaluated']} 组 / 43311 {p['evaluated_43311']} 组",
             15, 22)
        header(ws, 4, ["#", "组合（名#实例·COST）", "主属性（首行）", "ΣCOST", "攻击", "暴击%", "暴伤%", "共效%",
                       "增伤%", "E", "评分和", "差距"],
               [5, 68, 52, 9, 9, 9, 9, 9, 9, 10, 8, 8])
        for i, r in enumerate(p["top"], 5):
            combo = " + ".join(f"{x['name']}{x['tag']}·{x['cost']}C" for x in r["items"])
            mains = " | ".join(f"{x['name']}:{short_stat(x['main'][0]['name'])}{x['main'][0]['value']:g}"
                               for x in r["items"] if x["main"])
            body_row(ws, i, [r["rank"], combo, mains, r["total_cost"], r["attack"], r["crit"],
                             r["crit_dmg"], r["energy"], r["bonus"],
                             r["score"], r["score_sum"], r["gap_pct"] / 100],
                     formats=["0", "", "", "0", "#,##0.0", "0.0", "0.0", "0.0", "0.0",
                              "#,##0.0", "0.00", "0.00%"],
                     align=["center", "left", "left", "center", "right", "right", "right", "right",
                            "right", "right", "right", "right"],
                     band=(i % 2 == 1), height=46)
        ws.conditional_formatting.add(f"L5:L{4 + len(p['top'])}",
                                      ColorScaleRule(start_type="num", start_value=0, start_color=GREEN,
                                                     mid_type="num", mid_value=0.03, mid_color=YELLOW,
                                                     end_type="num", end_value=0.10, end_color=RED))
        ws.freeze_panes = "A5"
        if p["note"]:
            note(ws, 6 + len(p["top"]), "口径：" + p["note"], 12, 30)
        if p["best_33311"] and p["33311_advantage_pct"] is not None and p["33311_advantage_pct"] > 0.1:
            nb = p["best_33311"]
            ncombo = " + ".join(f"{x['name']}{x['tag']}·{x['cost']}C" for x in nb["items"])
            note(ws, 7 + len(p["top"]),
                 f"无 4C 的 33311：E {fmt_num(nb['score'])}（比 43311 高 {p['33311_advantage_pct']:.2f}%），组合 {ncombo}。",
                 12, 30)

    # ------------------------------------------------------------ 配队补正总表
    ws = wb.create_sheet("配队补正")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "配队补正总表：谁给谁、有没有算入", 7)
    header(ws, 3, ["队伍", "角色/方案", "自身补正", "队友/奶妈补正", "合计面板（不含声骸）", "未计入/注意", "备注"],
           [24, 16, 48, 34, 58, 40, 30])
    exclude_notes = {
        "sanhua": "轻云5 的22.5%攻击+12增伤给主C，不计入散华自身",
        "luhesis": "散华20增伤是单人的，不计；流金80已拆成衍射40+普攻40；轻云5 22.5%+12已计入",
        "dania": "武器24%是爱弥斯的，不计达妮娅；轻云5 的22.5%+12增伤给爱弥斯；角色30%/36%是单人的",
        "aemis": "武器24%攻击已计入；达妮娅36增伤是单人的；轻云5 22.5%+12已计入；裸面板12增伤已含武器/技能树",
        "qiuyuan32": "队伍声骸技能16+20已计入仇远自身；气动10未计入你的206；10攻击按10%计",
        "qiuyuan5": "队伍声骸技能20已计入仇远自身；轻云5 22.5%+12增伤给西格莉卡",
        "sigrika32": "仇远10%/50%是单人的；旧300预设未使用；3+2没有轻云5的12增伤；共效天赋另算",
        "sigrika5": "仇远10%/50%是单人的；轻云5 22.5%+12增伤已计入；共效天赋另算",
        "feixue": "散华20增伤是单人的；轻云5 22.5%+12已计入；雪落5的25%给下一个，不计自己",
    }
    r = 4
    for p in plans:
        self_c, team_c = [], []
        for c in p["corrections"]:
            src = c["source"]
            is_team = "奶妈" in src
            for n in ("散华", "达妮娅", "仇远"):
                if n != p["character"] and n in src:
                    is_team = True
            item = f"{c['key']} +{c['value']:g}（{src}）"
            (team_c if is_team else self_c).append(item)
        bp = p["base_panel"]
        total = (f"攻击 {bp['pct']['攻击']:.1f}% / 暴击 {bp['crit']:.1f} / 暴伤 {bp['crit_dmg']:.1f} / "
                 f"增伤 {bp['bonus']:.1f} / 共效 {bp['energy']:.1f}")
        max_lines = max(len(self_c), len(team_c), 3)
        body_row(ws, r, [p["team"], f"{p['character']}（{p['mode']}）",
                         "\n".join(self_c) or "—", "\n".join(team_c) or "—",
                         total, exclude_notes.get(p["key"], ""), p["note"]],
                 align=["left", "left", "left", "left", "left", "left", "left"],
                 band=(r % 2 == 0), height=max(96, 18 * max_lines + 12))
        r += 1
    note(ws, r, "「合计面板」= 裸面板 + 全部补正（不含声骸、不含西格莉卡的条件补正）；"
                "「未计入」列列出本角色不该重复吃到的队友/套装效果。", 7, 30)

    # ------------------------------------------------------------ 最佳组合词条
    ws = wb.create_sheet("最佳组合词条")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "每个方案第 1 名的 5 只声骸（主属性/副词条/评分）", 13)
    header(ws, 3, ["角色/方案", "声骸", "实例", "COST", "套装", "主属性1", "主属性2",
                   "副词条1", "副词条2", "副词条3", "副词条4", "副词条5", "单件评分"],
           [18, 24, 8, 6, 16, 18, 16, 15, 15, 15, 15, 15, 9])
    def write_block(ws, r, p, b, suffix=""):
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=13)
        c = ws.cell(row=r, column=1,
                    value=f"{p['character']} · {p['mode']} · {p['set_a']}"
                          + (f" + {p['set_b']}" if p['mode'] == '3+2' else " ×5")
                          + suffix
                          + f"   |   E {fmt_num(b['score'])}   攻击 {fmt_num(b['attack'])}   "
                            f"暴击 {b['crit']:.1f}/{b['crit_dmg']:.1f}   共效 {b['energy']:.1f}   加成 {b['bonus']:.1f}")
        c.font = font(10, bold=True, color=WHITE)
        c.fill = fill(BLUE)
        c.alignment = Alignment(vertical="center", wrap_text=True, indent=1)
        ws.row_dimensions[r].height = 32
        r += 1
        label = f"{p['character']}（{suffix.strip('（）')}）" if suffix else f"{p['character']}（{p['mode']}）"
        for x in b["items"]:
            mains = x["main"] + [{"name": "", "value": ""}] * (2 - len(x["main"]))
            subs = x["stats"] + [{"name": "", "value": ""}] * (5 - len(x["stats"]))
            body_row(ws, r, [label, x["name"], x["tag"], x["cost"],
                             x["set"], f"{short_stat(mains[0]['name'])}{mains[0]['value']:g}" if mains[0]["name"] else "",
                             f"{short_stat(mains[1]['name'])}{mains[1]['value']:g}" if mains[1]["name"] else "",
                             f"{short_stat(subs[0]['name'])}{subs[0]['value']:g}" if subs[0]["name"] else "",
                             f"{short_stat(subs[1]['name'])}{subs[1]['value']:g}" if subs[1]["name"] else "",
                             f"{short_stat(subs[2]['name'])}{subs[2]['value']:g}" if subs[2]["name"] else "",
                             f"{short_stat(subs[3]['name'])}{subs[3]['value']:g}" if subs[3]["name"] else "",
                             f"{short_stat(subs[4]['name'])}{subs[4]['value']:g}" if subs[4]["name"] else "",
                             x["score"]],
                     formats=["", "", "", "0", "", "", "", "", "", "", "", "", "0.00"],
                     align=["left", "left", "center", "center", "left", "left", "left", "left",
                            "left", "left", "left", "left", "right"],
                     band=(r % 2 == 0), height=22)
            r += 1
        pct = b["pct"].get("攻击", 0)
        flat = b["flat"].get("攻击", 0)
        base = b["base"].get("攻击", 0)
        panel_txt = (f"面板：攻击 {base:g} × (1 + {pct:.1f}%) + {flat:g} = {b['attack']:,.1f}；"
                     f"暴击 {b['crit']:.1f}% / 暴伤 {b['crit_dmg']:.1f}% / 共效 {b['energy']:.1f}%；"
                     f"增伤 {b['bonus']:.1f}%")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=13)
        c = ws.cell(row=r, column=1, value=panel_txt)
        c.font = font(9, italic=True, color="404040")
        c.fill = fill(LIGHT_GRAY)
        c.alignment = Alignment(vertical="top", wrap_text=True, indent=1)
        ws.row_dimensions[r].height = 26
        return r + 2

    r = 4
    for p in plans:
        r = write_block(ws, r, p, p["best"])
        if p["key"] == "qiuyuan32" and p["best_33311"]:
            r = write_block(ws, r, p, p["best_33311"], "（33311 无4C）")
    ws.freeze_panes = "A4"

    # ------------------------------------------------------------ 输入明细
    ws = wb.create_sheet("输入明细")
    ws.sheet_view.showGridLines = False
    title(ws, 1, "输入明细：裸面板、补正、专伤、条件补正", 7)
    header(ws, 3, ["角色/方案", "模式/套装", "裸面板", "补正", "计进加成区的专伤", "条件补正", "备注"],
           [18, 30, 40, 62, 26, 30, 50])
    for i, p in enumerate(plans, 4):
        bare_txt = "\n".join(f"{k} {v:g}" for k, v in p["bare"].items())
        corr_txt = "\n".join(f"{c['key']} +{c['value']:g}（{c['source']}）" for c in p["corrections"])
        spec_txt = "、".join(k.replace("伤害加成", "") for k in (p["allowed_bonus"] or [])) or "不计专伤（西格莉卡）"
        der_txt = "\n".join(f"{d['label']}：{d['source']}>{d['threshold']:g} 每点+{d['per_point']:g}，上限{d['cap']:g}"
                            for d in p["derived"]) or "—"
        set_txt = p["set_a"] + (f" + {p['set_b']}" if p["mode"] == "3+2" else " ×5")
        body_row(ws, i, [p["character"], f"{p['mode']} / {set_txt}", bare_txt, corr_txt, spec_txt,
                         der_txt, p["note"]],
                 align=["left", "left", "left", "left", "left", "left", "left"], height=150)
    ws.freeze_panes = "A4"

    # 统一默认字体/行高
    for ws in wb.worksheets:
        ws.sheet_properties.tabColor = BLUE if ws.title in ("目录", "结论", "总览", "面板补正", "配队补正", "队伍对比", "43311对比") else "7F7F7F"
        ws.sheet_view.zoomScale = 90

    wb.save(dst)
    print(f"wrote {dst}")
    # 轻量自检
    wb2 = load_workbook(dst)
    print("sheets:", wb2.sheetnames)
    for name in wb2.sheetnames:
        s = wb2[name]
        print(f"  {name}: {s.max_row} rows x {s.max_column} cols")


if __name__ == "__main__":
    main()
