# 交接（stage 29 之后：声骸组合穷举 + 伤害排名已落地）

> 给下一个会话：先读 `CLAUDE.md`（项目手册，含「组合穷举」一节）与本文；功能规格原文在 `panel_plan.md`
> （末尾有「实施状态」，列了与原文的差异与定案口径）。

## 一、已完成的阶段（全部已提交并 `push origin main`）

| 阶段 | 提交 | 内容 |
|---|---|---|
| 二十四 | `37829ac` | 审阅驱动的统一与清理（删多入口、单一来源、debug 开关） |
| 二十五 | `54c124f` | 官方静态数据层 L0~L2（`src/wuwa_data.py` + `tools/gen_echo_data.py`） + **37 张官方套装图标** + COST/主属性进报告 |
| 二十六 | `5d32374` / `abf5468` | **界面重构**：`FluentWindow` + 左导航、卡片式页面、运行页日志卡、快捷键、尺寸/页面记忆；修深色滚动页发白 |
| 二十七 | `d51f6e3` | **主属性数值校验**（生成物 `main_props` + `src/echo_main_prop.py` + 报告 `⚠ 数值可疑`）；定案「防御百分比」 |
| 二十八 | `7246757` | 生成物补 `pieces`（套装效果的"几件套"：2 件套 31 / 5 件套 31 / 3 件套 5 / 1 件套 1） |
| — | `7d20e1d` | 交接文档 `handoff.md` + CLAUDE.md 指针 |
| **二十九** | 本次 | **声骸组合穷举 + 伤害排名**：`src/echo_panel.py` / `src/echo_combos.py` / `src/echo_inventory.py` / `tools/echo_plan.py` / `ui/plan_tab.py` + 41 项单测 |

**基线（改东西后必须复跑）**
- `python -m unittest discover -s tests` → **120 passed / 1 skipped**
- `python tools/offline_eval_report.py`（109 只真实数据）→ 判定分布 `hold 38 / fail 24 / pass 39 / keep 1 / pending 7`、
  **主属性数值可疑 0 条**、套装来源 `{icon:108, name:1}`
- `python tools/eval_icon_match.py` → 217/219（99.1%）
- `python tools/ui_shot.py [--dark]` → 离屏渲染 **8 页**（改 UI 后必跑；深色兜底见下）
- `python tools/echo_plan.py --list` → 库存概览（109 只 / 47 个名字 / COST `{1:55, 3:35, 4:19}`）

## 二、阶段二十九做了什么（组合穷举）

**分层**：`echo_panel.py`（面板聚合 + 伤害）→ `echo_combos.py`（穷举 + Top-K）→ `echo_inventory.py`（库存导入）
→ `tools/echo_plan.py`（CLI）/ `ui/plan_tab.py`（界面）。**界面不碰伤害公式**（同"判定唯一收口"的纪律）。

**契约（用户已定，实现必须遵守）**：模式 `5` / `3+2`（两套时**必须指定 4C 归属**）；5 只**互异**（按名字）、
`ΣCOST ≤ 12`、只用 5★、**套装计数按去重只数**；补正**一律视为生效**（不做件数条件判定）；
套装效果**不自动解析**；伤害 `E = 缩放属性总值 × (1+暴击率×暴击伤害) × (1+加成区)`，
加成区 = 属伤 + 专伤合计（各类型直接相加）+ 通用增伤，**共效不计**。

**四个"必须记住"的口径（都有实测依据）**
1. **面板 = `基础值 × (1 + 百分比/100) + 固定值`**（calculator 源码 formula 原文；**固定值在括号外**）。
   裸面板的 `攻击/生命/防御` 填**基础值（角色+武器，不含声骸）**，不是游戏内面板总值。
2. **声骸面板有 2 行主属性，两行都算**：第 1 行 = 主属性；第 2 行 = **COST 固有属性**
   （COST1 生命 2280 / COST3 攻击 100 / COST4 攻击 150，满级；`0064`/`0001` 两张面板已逐张看图核对）。
3. **`攻击/生命/防御` 有固定与百分比两个变体**：报告路径按 `%` 判，JSON 路径按官方取值网格判
   （`echo_main_prop.candidates()`）；**别只看名字就当固定值**。
4. **5★ 无法从评估产物判定**（没有稀有度字段）→ 导入即视为 5★，由用户口径保证。

**实测规模**：109 只数据集、`息界同调之律(10) + 听唤语义之愿(12)` 的 3+2 → 候选 22 只 / 11 个名字 /
**评估 3330 组 / 0.075 s**；排列合理（前 5 名差距 0.9%~1.9%）。

**样例输入（注意：裸面板是占位值，不是用户真实数据）**
```
python tools/echo_plan.py --mode 3+2 --set-a 息界同调之律 --set-b 听唤语义之愿 --cost4 A \
    --scaling 攻击 --bare 攻击=1200 --bare 暴击=5 --bare 暴击伤害=150 \
    --corr 重击伤害加成=30:套装3件套 --corr 声骸技能伤害加成=16:套装2件套 --corr 气动伤害加成=10:天赋
```

## 三、数据面（关键认知，别再走弯路）

- **所有游戏表数据都在 `search/wwdata37`**（`Arikatsu/WutheringWaves_Data` @3.7 的稀疏检出，表被转成 **JSON**）：
  `BinData/{phantom, phantommanageplan, property, item, drop, monster_Info, monsterDisplay, ui_resource, role, weapon, skillTree}` + `Textmaps/zh-Hans`。
- 扩容：`cd search/wwdata37; git -c http.proxy= -c https.proxy= sparse-checkout add BinData/<表名>`
  （本机 git 全局配了 `http.proxy=127.0.0.1:7890`，代理没开时**必须**用这个 -c 覆盖走直连）。
- **外接盘 E: 只对 UI 贴图有用**（`tools/icon_export/`）；表数据不需要它。
- **库存导入的数据源**：`logs/eval_debug/<时间戳>/`（`image_report.md` 提供 名字/等级/COST/主属性 2 行/词条 5 条，
  `<tag>_full.png` 供图标识别定套装）或评估 JSON（`results`）。**图标识别是套装归属的关键**：
  `use_icons=False` 时多义名字会退到"通用"（0.05 s vs 5.2 s，但套装分布会错）。

## 四、下一棒（按价值排序）

1. **与 wuwa-calculator 对账**（`panel_plan.md` 步骤 4，最强的正确性验收）：同一组输入喂两边，伤害应一致。
   参考页 `.scratch/refs/wuwacalc.html`（`calculateDamage()` 在 ~49856 行；分区 formula 在 ~48307 行）。
   对账时要盯：① 固定值在括号外 ② 声骸 COST 固有属性算不算面板贡献 ③ 抗性默认（calculator 默认 20%，
   我们默认 10%）。
2. **真机界面走查**：导入库存 → 选套装/模式/4C 归属 → 填裸面板与补正 → 开始穷举 → 双击看明细 → 导出 CSV；
   顺带核对阶段二十六~二十八 的界面项（运行页日志卡、InfoBar、深色）。
3. **用户真实裸面板**：拿到后重跑一次，出真实排名（样例里的 1200 / 5% / 150% 是占位）。
4. **5★ 判定**（若要严格）：用主属性数值网格反推（不符网格 = 疑似 4★ 或 OCR 误读），见 `src/echo_main_prop.py`。
5. 图标识别兜底到强化模式 / 黑边校准（触发条件见 `CLAUDE.md`）。

## 五、跨会话的坑与经验（省时间）

- `HeaderCardWidget.viewLayout` 是**横向**的 → 正文自套纵向容器 + `card.vBoxLayout.setStretchFactor(card.view, 1)`；
  `TableWidget` 构造只收 `parent`；需要 `ConfigItem` 的 SettingCard 家族不要用。
- **`ComboBox` 没有 `setEditable`** → 用 `EditableComboBox`（补正来源下拉踩过）。
- 深色：`QScrollArea` viewport 用 palette 画底 → 必须过 `ui/widgets.make_scroll_transparent`；
  **不要**在 `apply_theme` 里手动 unpolish/polish 整树。
- **受限沙箱里 `QSettings` 写不进注册表**（写后读回 None）→ `tools/ui_shot.py --dark` 原本会静默出浅色图；
  已加兜底（`show()` 后再 `apply_theme("DARK", remember=False)`）。另外**直接 grab 一个裸 QWidget 会得到白底**
  （没有窗口背景）→ 要照"已填数据"的页面时，把它挂进 `FluentWindow` 再 grab（见 `.scratch/plan_page_shot.py`）。
- **别再用 `python -c "..."`**（PowerShell 引号/编码反复踩坑）→ 一律写成 `.py` 文件执行；
  要看中文输出就 `Out-File -Encoding utf8` 再用编辑器读（控制台是 GBK，直接看会乱码）。
- `BinData.pairs()` 返回 **(件数, fetter_id)**（件数在前）。
- 真机实跑**仍未验证**（阶段十六~二十九 的判定链 + 新页面）。
