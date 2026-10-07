# 交接（stage 24~28 之后：新功能"声骸组合穷举 + 伤害排名"开工前）

> 给下一个会话：先读 `CLAUDE.md`（项目手册）与本文；新功能的完整规格在 `panel_plan.md`。

## 一、已完成的阶段（全部已提交并 `push origin main`）

| 阶段 | 提交 | 内容 |
|---|---|---|
| 二十四 | `37829ac` | 审阅驱动的统一与清理（删多入口、单一来源、debug 开关） |
| 二十五 | `54c124f` | 官方静态数据层 L0~L2（`src/wuwa_data.py` + `tools/gen_echo_data.py` → `assets/gamedata/echo_data.json`）+ **37 张官方套装图标**（`tools/icon_export/` 流水线）+ COST/主属性进报告 |
| 二十六 | `5d32374` / `abf5468` | **界面重构**：`FluentWindow` + 左导航 7 页、卡片式设置/运行/工具页、运行页日志卡、快捷键、尺寸/页面记忆；随后修"深色下滚动页发白"（`ui/widgets.make_scroll_transparent`）与截图工具不落盘主题 |
| — | — | 入库：`helios/`（第三方私服启动器源码，内置）、`build_optimizer.md`（3.7 官方表施工图） |
| 二十七 | `d51f6e3` | **主属性数值校验**：生成物 `main_props`（5★ 基准值 + 成长曲线 + 固定/百分比多变异）、`src/echo_main_prop.py`、报告 `⚠ 数值可疑`；并**定案 `防御百分比`**（显示值口径正确，`_TIERS` 不改） |
| 二十八 | `7246757` | 生成物补 **`pieces`**：套装效果带"几件套"（实测 2 件套 31 / 5 件套 31 / **3 件套 5** / 1 件套 1）—— "3+2"里 3 件那套吃的是**它自己的 3 件套效果** |

**基线（改东西后必须复跑）**
- `python -m unittest discover -s tests` → **79 passed / 1 skipped**
- `python tools/offline_eval_report.py`（109 只真实数据）→ 判定分布 `hold 38 / fail 24 / pass 39 / keep 1 / pending 7`、
  **主属性数值可疑 0 条**
- `python tools/eval_icon_match.py` → 217/219（99.1%）、s1 中位 0.894
- `python tools/ui_shot.py [--dark]` → 离屏渲染 7 页（改 UI 后必跑）

## 二、数据面（关键认知，别再走弯路）

- **所有游戏表数据都在 `search/wwdata37`**（`Arikatsu/WutheringWaves_Data` @3.7 的稀疏检出，表被转成 **JSON**）：
  `BinData/{phantom, phantommanageplan, property, item, drop, monster_Info, monsterDisplay, ui_resource, role, weapon, skillTree}` + `Textmaps/zh-Hans`。
- 扩容：`cd search/wwdata37; git -c http.proxy= -c https.proxy= sparse-checkout add BinData/<表名>`
  （本机 git 全局配了 `http.proxy=127.0.0.1:7890`，代理没开时**必须**用这个 -c 覆盖走直连）。
- **外接盘 E: 只对 UI 贴图有用**（`tools/icon_export/`），表数据不需要它。

## 三、下一件大事：声骸组合穷举 + 伤害排名（规格见 `panel_plan.md`）

**要做的顺序**：② UI-1 页面骨架与输入 → ③ UI-2 库存导入 → ④ 引擎 → ⑤ UI-3 接排名。

**契约（用户已定，实现必须遵守）**
- 模式：`5`（同一套 5 只）或 `3+2`（套装A **3 只**吃其 2 件+3 件套效果；套装B **2 只**吃其 2 件套效果）；
  **两套时必须指定 4C 归属（A/B）**；不能两套都取 5 件。
- 组合过滤：5 只**互异**（同名声骸不可重复装）、`ΣCOST ≤ 12`、只用 **5★**、**套装计数按去重只数**。
- 补正：用户手填，**一律视为生效**，不满足件数的组合**直接剔除**（不做条件判定）；套装效果**不自动解析**。
- 伤害（只用于排序，方案内常数一律省略）：
  `E = 缩放属性总值 × (1 + 暴击率×暴击伤害) × (1 + 加成区)`；
  加成区 = 属伤 + **专伤合计（各类型直接相加）** + 通用增伤；**共效不计**；倍率/防御/抗性/加深省略。
- **缩放属性开关**：攻击 / 防御 / 生命。
- 样例（仇远 3+2 = 息界同调之律 3 件 + 听唤语义之愿 2 件）：补正填 重击+30%、声骸技能+16%(4%×4层)、气动+10%
  → 专伤合计 46%、属伤 10%。

**开工时需要的用户输入**：仇远（或其他角色）的**带武器裸面板数值** + 目标套装（1~2 个）+ 缩放属性。

## 四、跨会话的坑与经验（省时间）

- `HeaderCardWidget.viewLayout` 是**横向**的（库源码），正文要自套纵向容器 + `card.vBoxLayout.setStretchFactor(card.view, 1)`；
  `TableWidget` 构造只收 `parent`；`ComboBoxSettingCard/RangeSettingCard/OptionsSettingCard` 需要库自己的 `ConfigItem` → 别用。
- 深色主题：qfluentwidgets 只换样式表、不改 `QPalette`，`QScrollArea` 的 viewport 会用调色板画底 →
  所有滚动容器必须过 `ui/widgets.make_scroll_transparent`；**别**在 `apply_theme` 里手动 unpolish/polish 整棵树（会崩）。
- **别再用 `python -c "..."` 内联脚本**（PowerShell 引号/编码坑反复踩）→ 一律写成 `.py` 文件执行。
- `BinData.pairs()` 返回的是 **(件数, fetter_id)**（件数在前）。
- 真机实跑**仍未验证**（唯一未验证项）：跑一次 `python mainui.py` 评估 + 界面走查。
