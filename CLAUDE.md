# CLAUDE.md — ww-echo 开发手册

鸣潮(云游戏/本地)声骸强化 + 评估工具。基于 ok-script(截图/OCR/模板匹配/键鼠后端) + 自建 PySide6 UI。
**本手册面向后续开发(含 AI 协作者)。演进历史与改动原因见 CHANGELOG.md, 使用说明见 README.md,
判定规则的全景说明/分类审查/待讨论边界见 `eval_rules.md`。**

## 工作准则(项目级)

- 动手前陈述假设与取舍; 有歧义先问, 不静默选
- 最小改动解决当前问题; 只改与请求相关的行; 不超前抽象
- 改出孤儿引用(import/变量/函数)须清理, 但不动预存在的死代码
- 本机 ok-script 在 site-packages 有 `[ww-echo patch]` 补丁, **改动/升级前先 grep 定位**, 详见下
- 坐标、OCR 区、滚动量等常量集中在 `EnhanceEchoTask.evaluate_only` 顶部注释, 调参先看那里
- 目标驱动: 把请求转成可验证目标(如"修 bug"→"写复现测试再让它过"), 多步任务列出"步骤→验证"清单, 完成前以最相关测试/命令验证

## 项目结构

```
mainui.py                 唯一入口(PySide6); 启动先按 QSettings run_mode 调 apply_run_mode 再 OK(config)
                          (阶段二十四删除了 main.py/main_debug.py/run.py — 见下"阶段二十四要点")
config.py                 全套 ok-script 配置 + MODE_LOCAL/MODE_CLOUD + apply_run_mode()
ui/                       Fluent 左导航 8 页(运行/组合穷举/设备设置/热键设置/套装配置/调试工具/开发者 + 底部关于);
                          main_window=FluentWindow 外壳(尺寸记忆/主题/快捷键); 设备设置含运行模式开关(重启生效)
ui/plan_tab.py            「组合穷举」页: 输入装配(缩放属性/模式/套装/4C 归属/裸面板+补正) + 后台线程穷举 + 排名表/CSV
src/echo_panel.py         组合穷举**计算层**: 面板聚合(calculator 口径 基础值×(1+百分比)+固定值) + 加成区拆分 + 伤害
src/echo_combos.py        组合穷举: 5 只互异(按名) + ΣCOST≤12 + 套装只数 + 4C 归属 + Top-K(协作取消)
src/echo_inventory.py     库存导入: logs/eval_debug 素材(image_report.md + `<tag>_full.png` 图标定套装) 或评估 JSON → EchoItem
src/echo_stats.py         词条档位表 _TIERS + 官方档位概率 + snap_to_tier/get_mean(概率期望)/tier_percentile(分位)/is_stat_match
src/echo_set_templates.py 37 套装 JSON 模板(词条/权重/声骸清单) + 声骸名容错匹配(生成物优先: 官方 229 个显示名)
src/wuwa_data.py          官方配置表读取层: BinData(目录/zip, 两种序列化) + Textmaps + 管理方案 FlatBuffers 解码
src/echo_icon_match.py    详情面板套装图标识别(灰度 ZNCC 模板匹配) — 名字消歧硬信号
src/echo_score_sim.py     整只声骸分位: 按官方概率模拟"随机满级声骸"分数分布 → "击败 X%"
src/task/EnhanceEchoTask.py  强化(run) + 评估(evaluate_only v2 遍历, 核心)
src/task/BaseEchoTask.py  轻量基类(click 覆写/语言检测)
assets/echo_icons/        37 个套装图标(76x76, 文件名=套装名) — **全部来自客户端官方贴图**(见「官方静态数据层」)
assets/echo_set_templates.json 套装配置存档
assets/echo_probability.json   官方声骸副词条概率表(词条类型等概率 + 各档位概率, 见阶段十六)
eval_rules.md             判定规则全景说明 + 分类审查矩阵 + 已评估不改的项(改判定前先读; 已对齐阶段十八口径)
tests/                    单测(不依赖游戏): 图标匹配合成帧闭环 / 声骸名容错匹配 / 生成物与判据
tools/eval_icon_match.py  图标识别离线回归(用 logs/eval_debug 数据集, 无需开游戏)
tools/echo_plan.py        声骸组合穷举 + 伤害排名的命令行入口(离线; `--list` 看库存)
tools/ui_shot.py          离屏渲染 8 个页面出 PNG(桩件替代引擎, 改 UI 后的自检工具)
tools/offline_eval_report.py 离线重放评估(同素材) → eval_report.html 核对评分/判定/渲染
```

> **交接文档**：阶段二十四~二十九 的完成情况、数据面认知、下一棒(真机走查 / 与 calculator 对账)见仓库根 `handoff.md`。

## 界面(Fluent, 阶段二十六)

- **外壳**: `ui/main_window.FluentWindow` + 左侧 `NavigationInterface`(运行/设备设置/热键设置/套装配置/调试工具/开发者 +
  底部关于); 默认 1120x760、最小 940x620、**记住上次窗口几何与所在页面**(QSettings("OK-Echo","MainWindow"))。
- **分组卡片**: 每页用 `SettingCardGroup` + `SettingCard`(图标+标题+一句话说明+控件右对齐)。控件放卡右侧的写法是
  Gallery 惯例: `card.hBoxLayout.addWidget(w, 0, Qt.AlignRight)` + `addSpacing(16)`。
  **不要用 `ComboBoxSettingCard`/`RangeSettingCard`/`OptionsSettingCard`** —— 它们要求 qfluentwidgets 自己的
  `ConfigItem`, 而本项目配置在 ok-script/QSettings 里; 用 `SettingCard` + 原生 `ComboBox`/`SpinBox` 更省事。
- **`HeaderCardWidget` 的坑(已踩)**: `viewLayout` 是**横向**的(库源码 `QHBoxLayout(self.view)`), 正文必须自己套一层
  纵向容器; 并且要 `card.vBoxLayout.setStretchFactor(card.view, 1)` 才能让正文吃掉卡片多余高度(否则日志框不长高)。
  见 `ui/run_tab._card_body` / `ui/debug_tab._card_body` / `ui/about_tab._body`。
- **反馈**: 保存/切换/导入导出用 `InfoBar.success/error`(右上), 危险操作(导入覆盖、重启、清空)用 `MessageBox` 确认;
  长任务用状态卡的 `IndeterminateProgressBar` + 耗时。
- **快捷键**: `Ctrl+Enter` 开始/停止、`Ctrl+L` 清日志、`F1` 打开关于(见 `MainWindow._init_shortcuts`)。
- **日志**: 运行页与调试页**各持一份视图**(一个 `QWidget` 不能同时属于两个布局), 都接 `log_bridge` 同一条流;
  运行页日志带级别过滤/自动滚动/复制/清空/导出, ERROR/WARNING 着色(`RunTab._append_log` 缓冲 + 重渲染)。
- **主题**: `MainWindow.apply_theme(name)` 统一 `setTheme`(浅色默认, 深色/AUTO 可切; 深色下关云母)。
  业务/报告 HTML 里的固定色**不算**违规: 那是导出后浏览器打开的独立报告(`_build_eval_html`)。
- **深色下的坑(已修, 勿回退)**: qfluentwidgets 切主题只换样式表、**不改 `QPalette`**, 而 `QScrollArea` 的 viewport
  用调色板画底 → 滚动页在深色下会"浅底 + 浅字"(看着发白)。所有滚动容器统一走 `ui/widgets.make_scroll_transparent`
  (viewport 透明 + `enableTransparentBackground`)。另外**不要在 `apply_theme` 里手动 unpolish/polish 整棵树**:
  库自身会全局重绘, 手动那套在构造期/离屏下会崩。
- **自检工具**: `python tools/ui_shot.py [--dark] [--out 目录]` 离屏渲染 8 页 PNG(桩件替代引擎, 不需要游戏/显示器)。
  改 UI 后先跑它看图 + `python -m unittest discover -s tests`, 再上真机。
  **`--dark` 的一个环境坑(已兜)**: 它原本靠"启动前把主题写进 QSettings, 让 `_init_theme` 读回"进深色; 受限沙箱/无注册表
  写权限时 `QSettings` 写不进去(读回 None) → **静默出浅色图**。现在 `show()` 后再显式 `apply_theme("DARK", remember=False)`
  兜一次(不落盘), 因此抓图前必须逐页 `update()`。
- **`ComboBox` 没有 `setEditable`**: 需要可输入的组合框用 `EditableComboBox`(「组合穷举」页的补正来源用它)。
- **已知待办**: 传统模式选项那一块仍是紧凑控件(仅在「传统」策略下出现); 套装配置的表单校验只有 JSON 解析级。

## 组合穷举(阶段二十九: 面板聚合 + 伤害排名)

**分层**(与阶段二十四"判定唯一收口"同一条纪律): `src/echo_panel.py`(计算) → `src/echo_combos.py`(穷举) →
`src/echo_inventory.py`(库存导入) → `tools/echo_plan.py`(CLI) / `ui/plan_tab.py`(界面)。**界面不碰伤害公式**。

- **契约**(用户已定, 见 `handoff.md`): 模式 `5` / `3+2`(两套时**必须指定 4C 归属**); 5 只**互异**(按名字)、
  `ΣCOST ≤ 12`、只用 5★、**套装计数按去重只数**; 补正**一律视为生效**(不做件数判定); 套装效果**不自动解析**。
- **面板口径 = wuwa-calculator**: `总值 = 基础值 × (1 + 百分比/100) + 固定值`(其源码 formula 原文;
  **固定值在括号外**, 写进括号里会让固定词条多吃百分比)。裸面板的三系填**基础值(角色+武器, 不含声骸)**。
- **伤害只用于排序**: `E = 缩放属性总值 × (1+暴击率×暴击伤害) × (1+加成区)`; 加成区 = 属伤 + 专伤合计(直接相加)
  + 通用增伤, **共效不计**; 倍率/加深/防御/抗性默认 1(方案内常数, 不影响排序), 只有对账 calculator 时传。
  **暴击率按 100% 封顶**(`min(crit_rate,100)`): 实测组合会跑到 112%~119% 暴击, 不封顶会把溢出当收益;
  面板仍显示原始值, 溢出量见 `Panel.crit_wasted()`(CLI/UI 标 `→100`)。
- **候选默认只收满级件**(`PlanRequest.max_level_only=True`, 判据 = 5 条词条 ⇔ +25 满级; UI 复选框
  「只用满级件」默认勾选 / CLI `--all-levels` 反向): 未满级件词条还会涨, 用现状词条排名会低估它。
- **导入侧会折掉完全重复的实例**(`drop_exact_duplicates`: 名字/套装/COST/词条全同): 评估的 `dedup_key`
  键在原名上, OCR 把间隔号读成 `・` 时同一只会被记两次(实测 #38/#44), 组合穷举就会出现成对同分组合。
- **指定专伤(A 方案, 2026-10-10)**: 通用套(轻云出月)为普适给 普攻/重击/共技/共解 都配了 **0.1 占位权重**, 而角色
  通常只吃一种 → 不指定的话别的专伤副词条会被当成有效收益(实测仇远 3+2 差 **8.7%**)。指定方式:
  CLI `--specialty 重击`(可重复; 简写见 `echo_panel.SPECIALTY_ALIASES`) / UI 补正卡片「计进加成区的专伤」5 个勾选框;
  优先级 = `--all-bonus`(全算) > 指定 > 套装模板并集。**当前只作用于穷举伤害, 不碰评估评分**(评分侧见 (C) 待办)。
- **加成区归类**: `*伤害加成` 与 `通用增伤` 进加成区, 六元素 + `属性伤害加成` 记作"属伤", 其余为"专伤";
  基础/百分比/双暴/共效/治疗不进; 不认识的键记进 `Panel.unknown`(**不静默吞** —— CLI 会提示)。
- **专伤按套装有效词条过滤**(2026-10-09 用户口径): 专伤**分技能类型**(普攻/重击/共技/共解/声骸技能),
  只打共鸣解放的角色刷到"普攻伤害加成"副词条等于白给 → `aggregate(allowed_bonus=...)` 只计
  **套装模板权重键里的专伤**(`set_bonus_keys`, 3+2 取并集); **属伤/通用永远计入**, **补正一律计入**;
  被挡的量在 `Panel.ignored_bonus`(表里显示 `(忽略N)`); 开关 = UI「专伤不过滤」/ CLI `--all-bonus`。
  **权重 0 = 该套装不认**(与评分同一口径): `set_bonus_keys` 只收**权重 > 0** 的键 —— 曾经只按键名收集,
  于是把某套装的"重击"置 0 后重击副词条仍被计入(用户 2026-10-09 要求置 0 时发现); 那 20 多个"未定制"套装
  (占位键全 0)也因此不再计入任何专伤。
  **坑**: `bonus_group()` 对非加成键也返回"专伤", 过滤必须带 `is_bonus_key`(否则攻击/暴击/共效被一起挡掉)。
- **每个组合带"评分和"**(`EchoItem.score` → `Combo.score_sum()`, 与报告同一份 `compute_weighted_score`):
  **只按副词条算** —— 主属性不进评分, 别把 `main` 也传进去(3C 固有"攻击 100"会被当成攻击词条, 实测踩过);
  **两条导入途径都现算**(不直接用 JSON 记录里的 `score`: 那份是评估当时的, 改套装权重后就过期了)。
  CLI/UI/CSV 都有 评分和/均分 两列(UI 悬停给 5 只明细)。
- **「有效分」= 评分和 − 共效条分**(`EchoItem.score_dmg` / `Combo.score_sum_dmg()`): 共效在评分里有 0.6 权重、
  却不进伤害公式 → 减掉它以后与伤害排序的秩相关从 0.66/0.32 升到 0.81/0.59(见下条实测), 但**仍不能当排序**。
  排名表把它与评分和并成一列(`评分和/有效分`, UI 悬停给 5 只明细), CLI/CSV 各占一列。
  **共效驱动型天赋(如西格莉卡"共效>125 转增伤")时该列失效**: 共效正是伤害来源, 扣掉它是反向的 →
  `echo_combos.energy_is_damage(req)` 判定, CLI/UI 显示 **—** 并说明原因。
- **门槛系数(共效 / 暴击)共用同一个公式** `gap_factor = max(最低, 1 − 斜率×(目标−值)/目标)`, 值 ≥ 目标 → 1.0
  (**只减不增**): 共效 目标 120% / 斜率 0.30 / 最低 0.85(110→0.975、100→0.95); 暴击 目标 100% / 斜率 0.40 / 最低 0.80
  (96→0.984、93→0.972、80→0.92)。**为什么不用"接近目标给奖励"**(曾实现过一版, 已推翻): 两者都有天然上限,
  奖励形在现实区间(90~100%)只有 0.5% 动态范围, 还把 E 整体抬高、失去与未乘值的可比性; 惩罚形把 100%/120%
  定为 1.0 基准, 同样参数能把 90% 与 100% 拉开约 4%(实测绯雪第 1 与第 4 的差距 1.2% → 3.7%)。
  `energy_min<=0`/`energy_slope==0`(暴击是 target/slope 为 0)即关闭。
- 最终 `Combo.score = score_raw × energy_f × crit_f`(都保留未乘值与两个系数);
  UI 两张卡片(共效: 下限/斜率/最低; 暴击: 目标/斜率/最低)+ 悬停显示系数与未乘值,
  CSV 有 循环系数/稳定性系数 两列, CLI 有
  `--energy-min/--energy-slope/--energy-floor/--crit-target/--crit-slope/--crit-floor`。
- **评分和/有效分 不能当排序用(实测, 2026-10-09)**: 它们是"件本身练得怎么样", 与伤害排序只弱相关 ——
  真实库存 5 件套实测: ρ(评分和, E) = 0.663(爱弥斯 2799 组)/0.321(绯雪 672 组),
  ρ(有效分, E) = 0.811/0.585; 爱弥斯**评分和第 1 名的伤害只排第 540 名**(差 13.7%)。
  根因: **评分只算副词条, 主属性完全不进评分** —— 而 4C(暴击 22% vs 暴伤 44%)、3C(属伤 30% vs 攻击% 30%)
  的方向恰恰是伤害最大的变量; 少一件 4C(ΣCOST 11)评分也毫无感知。**排序只能看 E**, 评分和/有效分当辅助列;
  结果表悬停里给出主属性方向, 就是为了让这种偏差一眼可查。
- **排名表的列宽按 1120 默认窗口实测的"文本需要宽度"定**(视口 1001: 评分和/有效分 158、共效 84、排序分 88…);
  加列前先量一下(`.scratch/measure_table2.py`), 否则会挤成 `1...` 这种截断。
  **改结果表后必须跑一次"填充页渲染"**(`.scratch/plan_page_shot.py` / `.scratch/sigelika_page.py`) ——
  `tools/ui_shot.py` 只渲染空页面, `_render` 里的错误它抓不到(实测漏过一个 `NameError`)。
- **推导补正(天赋)**: `DerivedBonus(source, threshold, per_point, cap, key, label)` —— "共效 > 125 后每多 1%
  得 2% 增伤(上限 50)"这类**逐组合不同**的补正(静态 `Correction` 表达不了, 因为每套组合的共效被副词条改变)。
  在面板聚合**完成后**按**最终**值算 `min(cap, max(0, per_point×(值−阈值)))`, 加进 `key` 并记入 `Panel.derived`
  (悬停/CSV 可见)。触发属性支持 共效/暴击/暴伤/三系总值; 共效不进加成区 → 不会自我循环。
  接线: `PlanRequest.derived` → CLI `--derive 属性:阈值:每点:上限[:目标键][@标签]` / UI 补正卡片第二行「条件补正(天赋)」。
- **待办候选: 「本只贡献」列** —— 若要"评分"本身就能当排序, 需要把**主属性按当前面板的边际贡献**折进评分
  (等价于把 E 拆到 5 只头上)。实测根因见上条; 这是唯一能让"评分和"与伤害排序一致的路径。
- **声骸主属性有 2 行, 两行都算面板贡献**(实测 219 张面板 + 逐张看图核对): 第 1 行 = 声骸主属性;
  第 2 行 = **COST 固有属性**(COST1 生命 2280 / COST3 攻击 100 / COST4 攻击 150, 满级; 与生成物固定值变体逐档吻合)。
- **`攻击/生命/防御` 有固定与百分比两个变体**: 报告路径按数值里的 `%` 判, JSON 路径按**官方取值网格**判
  (`echo_main_prop.candidates()`, 区间不重叠 → 判定唯一)。**别只看名字就当成固定值**。
- **5★ 无法从评估产物判定**(没有稀有度字段): 导入即视为 5★, 由用户口径保证; 要真判定得用主属性数值网格反推。
- **库存从哪来**: 「运行」页评估结束保存报告时, `ui/run_tab._on_eval_done_ui` **顺手把评估数据写一份
  `<报告名>.json` 到报告同目录**(临时目录随后会被删)。「组合穷举」页「选择…」或
  `tools/echo_plan.py --inventory <该 json>` 直接导入它; `logs/eval_debug/<ts>/` 那条路只在需要
  **图标识别补套装**时才用(需 `SAVE_DEBUG_DATASET=True` + 一份 `image_report.md` 转录)。
- **性能**: 109 只数据集 3+2 约 3 千余组 / 0.08 秒(名字分组 → 名字组合 → 实例笛卡尔积); 组合规模大时靠 `top_k` 堆,
  取消走 `plan(..., should_stop=...)`(每 512 组查一次)。

## 运行模式(local / cloud)

- 切换写 QSettings("OK-Echo","OK-Echo") 的 `run_mode`, **重启生效**(mainui 在 OK() 初始化前 apply)
- **local**: `exe=Client-Win64-Shipping.exe`+`hwnd_class=UnrealWindow` 自动匹配本地客户端; PostMessage 可后台运行
- **cloud**(云游戏 = 浏览器/云客户端窗口, 如 Firefox):
  - `windows.title=re.compile('鸣潮')` → ok-script `find_hwnd` 按正则自动锁定标题含"鸣潮"的窗口, **无需手动选窗**
  - interaction=Pynput(前台真实键鼠), capture 锁定 `BitBlt_RenderFull`, `supported_resolution.ratio=None` 跳过 16:9 校验
  - 云游戏本地无 UnrealWindow 可后台投递 → **必须前台**, 任务运行中不要最小化游戏

## ok-script 补丁 — 升级 ok-script 会丢失, 需重打

ok-script(site-packages) 4 处(4 个文件), 本项目内另 1 处。全部标注 `[ww-echo ... patch]`:

| 文件 | 改动 | 为什么 |
|------|------|--------|
| `ok/gui/StartController.py` | `_auto_bring_to_front`(init=False; do_start 且 task 非 None 时置 True); `_wait_until_device_ready` 每轮按标志 `bring_to_front()`(含最小化恢复) | 点"开始"后自动把游戏窗口切前台启动任务; 纯启动不抢前台 |
| `ok/device/capture_methods/hwnd_window.py` | `visible = not win32gui.IsIconic(hwnd)` 替代 `is_foreground()` | 后台/被遮挡窗口(BitBlt_RenderFull 可抓)不再判不可用; visible=False 只在真最小化出现 |
| `ok/device/interaction_methods/pynput.py` | `should_capture()→True`; `clickable()` 保持纯 is_foreground; 新增 `_ensure_clickable()` | 任务主循环不再被前台门控(切走不再卡死); 真正 click/send_key/scroll 动作前自动拉前窗口 |
| `ok/util/window.py` | `find_hwnd` 开头过滤空 exe 项: `exe_names = [e for e in (exe_names or []) if e]` | 云模式 `selected_exe=''` 时, 空 exe 会让**所有**窗口在 exe 匹配处被判不匹配 → 找不到"鸣潮"窗口 |
| `ui/run_tab.py`(本项目, 非 site-packages) | 评估分支起线程前也 `bring_to_front()` | 评估模式与强化一致地切前台 |

## 屏幕坐标基线(1920x1200 帧; 归一化 = px/1920, px/1200)

| 元素 | 归一化区 | 备注 |
|------|---------|------|
| 声骸网格 | (0.10,0.15)-(0.72,0.92) | 每行 6 格; 列距≈176px, 行距≈212px(1920x1200 参考); `+xx` 角标在格右下 |
| 右侧详情面板 | (0.66,0.10)-(0.995,0.635) | 归一化 y 参考: 名字≈0.10/COST≈0.21/主属性≈0.37,0.42/词条≈0.45..0.61(第5条); "声骸技能"行(≈0.62)由 read_detail 按行过滤; **"前 2 行=主属性"是相对行序判断, 不依赖帧高**; 截图同区 (0.665,0.07)-(0.995,0.65) |
| **详情面板套装图标** | **(0.7302,0.1658)-(0.7448,0.1892)** | 1920x1200 = (1402,199)-(1430,227); 圆形外径≈28px(含 2px 外发光), 在等级 `+25` 文字右侧; **图标识别裁剪区**(见 `echo_icon_match.ICON_BOX`), 与网格滚动无关(实测 bbox 波动 ≤±3px) |
| 左上声骸计数 | (0.02,0.02)-(0.25,0.09) | `声骸145/3000` → 上限做步数限制 |
| 滚动热区 | (0.52,0.5) 常用 | 鸣潮列表滚动有热区(光标需网格中右部); 1920x1200 参考 ≈8px/notch |

## 词条过滤规则(关键, 勿回退成区间判断)

详情 OCR 出的属性行 = 主属性区 + 真词条, 按 y 序排列, **前 2 行固定为主属性**, 直接排除(即使固定值恰好命中档位, 如 主属性 生命=510 / 防御=50)。
判定词条: 排除前 2 行后, `echo_stats.is_stat_match(name, value)` = 归一化名在 `_TIERS` 且数值 **≈ 档位集合中某档**(容差 0.8)。
区间判断会误收主属性; 必须离散匹配。词条最多 5 条。

## 技能行 / 主属性语义噪声(已实测兜底, 无需处理; 勿再重复调查)

`read_detail` 按"detail_box 内、含 ≥2 连续汉字的 box"筛属性行(它不知道 UI 语义) → 面板底部的技能标题/描述行**也会进候选**:
- `声骸技能` 已在排除名单 `('声骸技能','COST','Z','C')` ✓ —— 实测必需: 它的 y=[570,615,660,705]
  与真词条 y=[543,589,635,681,725] **同区交错**(面板短时技能标题上移进词条区); 旧笔记"y≈793 在红框之下"只适用满级面板
- 变体 `使用声骸技能，召唤…`(无归的谬误面板) 仍会进 properties 并被 `_normalize_stat` 误归一化成
  `共鸣技能伤害加成`(逐字白名单剥掉 使用/声/骸 只剩 `技能`) —— **实测无害**: 它在 y 序尾部抢不到数值,
  `_pair_props` 配兜底 `"0"` → `is_stat_match(…, 0.0)` 拒(0 不在档位集合); 0218(+5)/0219(+0) 两张真实面板零误收
- 主属性用词 `热熔/气动/衍射/冷凝 伤害加成` 不在 `_STAT_CHARS` → 清洗后 '伤害加成' 经 LCS 归到
  `共鸣技能伤害加成`(语义错) —— **同样无害**: 它们只出现在主属性区, 被"前 2 行"规则排除
- **线上三重防线(实测 4071 个真实 detail box)**: `property_pattern` 的 `{2,}` 挡单字/符号误读(5 个)、
  排除名单挡 `声骸技能`、`_normalize_stat` 逐字白名单救回 **181/1718 = 10.5%** 图标误读前缀
  (`茶暴击伤害`→`暴击伤害` 53 次 / `发暴击伤害` 39 / `父攻击` 26 …)、`is_stat_match` 离散档位挡拿不到数值的杂行。
  另: 线上 box **从不含 `|`**(4071 个里 0 个) → `器 | 暴击伤害` 这种形式只存在于 `image_report.md` 转录(同行片段合并的产物)
- **警戒条件**: 若"前 2 行 = 主属性"这个行序假设失效(面板布局变动), 上面后两条要重新评估

## 声骸名容错匹配(勿回退成精确查表)

`get_sets_by_echo(名)` 走 `_match_echo_key`(照词条过滤的三级思路): ①**精确命中显示名**(含 `异相·X` 皮肤名) ②逐字白名单清洗(`_echo_chars` = 全部声骸名汉字集, 剥 OCR 错字/杂字) ③子串(唯一候选) ④最长公共子串 LCS(≥3 字且唯一); 全不中返回 `[]`。**返回候选列表**(不是取首个)。

★ **`异相·X` 是独立声骸, 有自己的套装**(官方配置表: **13 例与本体不同**, 如 `异相·巡游骑士`→彻空冥雷/熔山裂谷 而 `巡游骑士`→凌冽决断之心/幽夜隐匿之帷) → 匹配时**皮肤名与本体名分池, 绝不跨池回退**; 只有生成物缺失时才退回"剥前缀复用本体套装"的旧口径(旧安装兜底)。有生成物时索引来自官方配置表(**229 个显示名**; 旧口径 181 个)。
名字天生多义(**181 个声骸名中 120 个属 ≥2 套装**) + OCR 错字, 名字层无法完全消歧。已实证失效: `梦魔·青羽鹭`(清洗后含子串「青羽鹭」且该名独立存在于索引 → 子串分支抢跑 → 误配 `[啸谷长风, 浮星祛暗]`, 应 `[息界同调之律]`)、`侏侏驼`(驼→鸵, 清洗后仅「侏侏」2 字)、`咔嘧`/`阿磁磁`(真名 咔嚓嚓/阿嗞嗞, 清洗后仅 1 字)。详见 CHANGELOG 阶段十一。**这类由套装图标识别兜底(已实现, 见下)。**

## 套装图标识别(名字消歧硬信号, 阶段十二; 勿回退成"只用名字")

`src/echo_icon_match.py`: 详情面板图标区 → 灰度 28x28 → 与 `assets/echo_icons/{套装名}.png`(**37 张, 全部来自客户端官方贴图**)做 **ZNCC**:
①模板 76px 缩到 29px(尺度 1.05)中心裁 28, 两端同分辨率 1:1 比 ②**±2px 平移搜索**(消 bbox 抖动; 不搜索时 s1 从 0.9 掉到 0.23) ③圆形 mask(r≤12)排除外发光与面板背景 ④置信线 `MIN_SCORE=0.60` + 与次优间隔 `MIN_MARGIN=0.05`, 不达线返回 None 交调用方回退名字候选。
**颜色/环色特征不可用**: 37 个模板同构(彩色圆环 + 白底 + 深色图案), 缩到 28px 后轮廓主导 → 环色 top1 命中仅 28/183; 灰度 ZNCC 才是有效判据。
`EnhanceEchoTask.resolve_set_name(名)`: 图标优先(**与名字候选不一致也以图标为准** — 名字层错字无解) → 低置信回退 `get_set_by_echo(名, prefer=config套装)` → 再回退 config(评估=通用); 来源 `icon`/`name`/`default` 记入报告 JSON 的 `set`/`set_src`。
离线回归: `python tools/eval_icon_match.py [debug目录]`(用 `logs/eval_debug/<时间戳>/` 全屏图, 无需开游戏)。**当前基线: 219 张中 217 张高置信(99.1%, s1 中位 0.894); 名字候选非空 211 张中 196 一致(92.9%), 15 张不一致全部是名字层错字案例且图标给出正确套装(`梦魔·青羽鹭/啾啾河豚/咕咕河豚` → `息界同调之律`, s1=0.93); 2 张详情面板无图标(`无归的谬误`)s1≈0.22 → 回退名字候选。改判定逻辑后跑一次该工具对比基线。**

## 官方静态数据层(L0~L2, 2026-10-02; 生成物只读, 勿手改)

**动机**: 声骸↔套装/图标名/主属性方案/属性名原本是手抄(wuther.in 页面 + `1.txt`), 3.7 改版后已落后 3 套且皮肤条目归属错。
**做法**: 由官方配置表生成 —— 数据源是**离线导出**的游戏表(不是运行时读游戏/内存, 定位不变)。

| 文件 | 作用 |
|---|---|
| `src/wuwa_data.py` | `BinData`(目录/zip 自适应, 兼容 `[{Key,Value}]` 与 `{k:v}` 两种序列化) + `load_textmaps` + `parse_plan_bin`(管理方案 FlatBuffers 解码) + `read_version` |
| `tools/gen_echo_data.py` | 生成器 → `assets/gamedata/echo_data.json`(37 套 / 229 声骸 / `plan` / `props` / `main_prop_names`); `--sync-templates` 把 `_echoes`/`_icon` 同步进策略文件(**不动权重/`_core_first`**) |
| `assets/gamedata/echo_data.json` | 生成物: `sets{icon_asset,icon_file,fetter_ids,effects,echoes,plan}` + `echoes{cost,sets,base}` + `props` + `main_prop_names` |
| `tests/test_gamedata.py` / `test_main_prop_check.py` / `test_echo_stats_consistency.py` | 生成物结构自洽 + 3.7 回归锚点 + COST/方案判定 + 档位↔概率一致性断言 |

- **已拉取的表(2026-10, 稀疏检出模式)**: `BinData/{phantom, phantommanageplan, property, item, drop,``
  ``monster_Info, monsterDisplay, ui_resource, role, weapon, skillTree}` + `Textmaps/zh-Hans`。
  其中 `phantom`/`property` 供 L0~L2 与主属性数值; `item` 供道具名(`ItemInfo_<id>_Name`, 如特级密音筒);
  `role`/`weapon`/`skillTree` 供**面板模型(S1)**; `drop`/`monster_*`/`ui_resource` 待接。
  扩容命令: `git -c http.proxy= -c https.proxy= sparse-checkout add BinData/<表名>`（本机 git 配的全局代理
  常常没在监听, 直连 GitHub 反而通; 报告里的 `--bindata` 指 `search/wwdata37/BinData`）。
- **面板模型 / 主属性穷举(S1/S2)**: 实施规格见仓库根 `panel_plan.md` —— S1 用 `roleinfo.PropertyId` +
  `baseproperty` + `rolepropertygrowth(Level,BreachLevel)` + 武器 + 天赋算角色面板(**必须与游戏内面板对数字**);
  S2 穷举 `COST 型(43311/44111) × 每槽主属性 × 套装分配`(约 4 千组合), 副词条走期望/理想/库存三种口径
  (全穷举不可行: 单只 ≈4×10⁷ 组合)。
- **数据源与刷新**: `Arikatsu/WutheringWaves_Data` 分支 `3.7`(Global 3.7.0 / Resource 3.7.8; 本机 `search/wwdata37`, sparse checkout 只取 `Textmaps/zh-Hans` + `BinData/phantom*` + `property`; 刷新 = 该目录 `git pull`)。生成命令见 `tools/gen_echo_data.py` 文档串(需 `--bindata`/`--textmaps`)。
- **不变量**: 任何文本键解析不出 → **退出码 2 且不写文件**(宁失败不静默丢数据); 生成物**只读**, 策略(权重/`_core_first`)仍手写在 `echo_set_templates.json`。
- **官方管理方案**(`PhantomManagePlanV2`): 每 (套装, COST) 的主属性**保留组/丢弃组**(PropId)。客户端表是 FlatBuffers `BinData`, 解码器已用服务端显式字段表**逐行 100/100 验证**; 它同时覆盖 3.7 的 3 个新套装(服务端表只到 34 套)。
- **已知偏差(勿"修")**: `防御百分比` 的 8 个档位以**官方公示原文**为准(8.1/9.0/10.0/10.9/11.8/12.8/13.8/14.7; 18 张真实面板也只出现这 8 个值); zigrika 服务端的 `(std*mult+5000)//10000*10` 会多出 +0.1 的 5 个档 —— 那是服务端口径。
- **3.7 新增 3 套**: 衔梦照世之心(36, 导电) / 镜影流电之瞬(37, 导电) / 茜染怀想之花(38, 治疗); 已用通用权重播种。
- **套装图标已全部换成客户端官方贴图**(37 张, `assets/echo_icons/`): 与旧模板逐像素对比 **29 张完全一致**(corr=1.000)、**5 张不同**(失序彼岸之梦/奔狼燎原之焰/愿戴荣光之旅/此间永驻之光/流云逝尽之空 —— 旧版图标, 已换当前官方版)、**3 张新增**。
  复现路径(需客户端安装 + 工作区 `search/CUE4Parse-master` + .NET 10 SDK):
  ① `.scratch/scan_icons.py`(复用 ww-explore 的 pak 解析)列出 `IconElementAttri*` 条目; `.scratch/extract_icons.py` 用同一套 pak 解析导出 uasset/uexp 到松散文件树(`.scratch/loose/Aki/UI/...`);
  ② `.scratch/iconexport/`(CUE4Parse 控制台程序)`IconExport <松散树> <aesKey> <输出目录> IconElementAttri` 解出 PNG(76×76; `...128_*` 是 128×128);
  ③ `.scratch/swap_icons.py` 按 `gamedata` 的 `icon_file` 覆盖 `assets/echo_icons/`(先备份到 `.scratch/echo_icons_before/`)。
  要点: `TextureDecoder.UseAssetRipperTextureDecoder = true`(纯 C# BC7 解码, 免 CUE4Parse-Natives/Detex 原生库)、`-p:CUE4PARSE_SKIP_NATIVE=true` 跳过 CMake、中文路径传参易失败(用 `mklink /J` 建 ASCII 联接)。
- **主属性数值表(阶段二十七)**: 生成物多出 `main_props` 段 —— 5★ 主属性的 `StandardProperty` 基准值 +
  `PhantomGrowth` 成长曲线(26 档, 10000→50000) + 各属性名**多个变体**(`攻击` 同时有固定值 `30→150` 与
  百分比 `660→33.0%`)。运行时 `src/echo_main_prop.py::check_main_values` 用它判"面板读到的主属性**数值**是否
  落在官方网格上"(挡 OCR 误读); 两个实测教训已写进模块 docstring: ①等级只能取**下界**(词条数 n 只说明 ≥ +5n,
  真实数据集里就有 +22 却 5 词条的声骸) ②容差要按"能匹配上的变体"取, 不能拿第一个变体的百分比容差去比固定值。
  报告的「COST/主属性」格在数值可疑时显示 `⚠ 数值可疑`(行上带 `data-mpval="bad"`)。
- **真实数据验收**: `python tools/offline_eval_report.py` 会打印"主属性数值可疑: N 条"(109 只基线 = **0 条**);
  判定分布基线 `hold 38 / fail 24 / pass 39 / keep 1 / pending 7` **不变**(数值校验只加标记, 不动判定)。
- **灰度孪生(改图标/调阈值前必读)**: 图标是"彩色圆环+白底+深色图案", 灰度 ZNCC 下有几对天生相近 ——
  `星构寻辉之环↔逆光跃彩之约 0.878`、`幽夜隐匿之帷↔轻云出月 0.815`(**换官方图前就存在, 真实面板判定正常**)、
  `凝夜白霜↔茜染怀想之花 0.799`(3.7 新图标带来的新对)。合成帧测试下孪生会抢跑使 margin < 0.05 → `match_icon` 返回 None(正确行为, 测试已显式列白名单);
  真实口径以 `tools/eval_icon_match.py` 离线基线(217/219)为准; 若真机出现孪生误判, 再考虑用环色/色相做 tie-breaker(当前刻意不用颜色)。

## 评估遍历 v2 现状与约束

- 前置: 游戏已在**背包声骸列表界面**(无需预选)
- 流程: 网格 OCR `+xx` 角标 → 聚行 → 6 列基准(跨屏记忆 `col_centers`)补全缺列防漏 → 逐格点选 → 右侧详情 OCR → 档位过滤词条 → 评分/截图/记录
- **评估按套装图标优先映射套装**(阶段十二): `resolve_set_name` → 图标识别(高置信直接用, 可纠正名字候选) → 否则 `get_sets_by_echo` 候选(prefer=config 套装) → 否则回退"通用"; 声骸↔套装索引来自**生成物**(官方配置表 229 个显示名), 模板 `_echoes` 仅在生成物缺失时兜底
- **面板 COST 与主属性**(L2): `read_detail` 用 `parse_cost` 读 COST 角标(合框 `COST 4` 或"标签 + 同行右侧数字框"; 实测线上 219/219 可读), 前 2 行主属性与 COST 一起交给 `evaluate_one` → 报告「COST/主属性」列 + 官方管理方案判定。
  **真机 20261008 那批漏读 27/135**(小字数字框整个没检出, 复跑截图可复现: `eval_062` 只剩 `COST`) →
  现在 1× 读不到时走 `read_cost_badge()`: 只截 `_COST_ROI`(0.685,0.19–0.792,0.25)放大 3× 再 OCR
  (离线 27/27 读回); **离线侧**另有 `echo_inventory.infer_cost` 用面板第 2 行(= COST 固有属性:
  1C 生命 / 3C 攻击 100 / 4C 攻击 150)反推兜底 —— 角标与反推在真实数据上 108/108 一致
- 套装语境(权重/键/首核/声骸清单)供评估自动映射 + 强化模式使用; run_tab 评估仍隐藏套装下拉(靠图标+名字映射), 未映射时用通用
- **数据来源/工具备注**: 声骸↔套装 / 套装图标名 / 官方主属性方案 / 属性名 全部由 **`tools/gen_echo_data.py`** 从官方配置表生成(数据源是离线导出的客户端表 + zh-Hans 文本表, 见「官方静态数据层」一节; 生成物 `assets/gamedata/echo_data.json`, **只读**)。旧的 `tools/parse_wutherin_echoes.py` + `1.txt` + `echoes_check.md` 手工口径**已被取代**(脚本留着但不必再跑; `echoes_check.md` 是旧转录且已被手改过, 别当输入)
- 空格/未切换格**跳过继续**(不提前滚屏防漏真实格); 本屏无新内容才滚动 15 notches; 连续 3 次滚动无新格兜底
- **步数限定(read_count)**: 左上 `声骸N/3000` 取 **N**(总数或滚动位置, 非 3000 容量) 作上限, `handled >= N` 终止; **每屏动态重读并 max 跟随**(N 若为滚动位置会随滚动增大, 不误截断; 防 OCR 抖动回退)
- **0级声骸(0词条)跳过不记录、不终止**: 无评估价值, 不入报告; 置 processed_any 继续滚动推进; 0 级角标是 `+0` 也能被网格识别; 列表真到底 = 滚动后网格区**连续 2 次扫描为空**(empty_scan); 首屏即空且零记录才 raise 防呆
- 去重: `seen_sigs`(set[str]) 保存**声骸名 + 全部属性行档位值**(`dedup_key`, 档位值离散不受 OCR 抖动影响)的签名, 命中即跳过——防滚动重叠(15 notches≈120px < 行距 213px, 每屏与上屏重叠~1行)导致的重复记录; `last_sig`(全量文本)只判"点选未切换", **每次滚屏后重置**; 同名同属性两只会被合并, 属可接受近似
- **词条名容错(`_normalize_stat`)**: 三级处理①**逐字白名单**(`_STAT_CHARS`=标准词条名+主属性名单字并集, 图标/杂字直接剥离; 清洗后 <2 字返回原文不猜)②**精确子串链**(清洗后即子串匹配, 前缀污染 `艾攻击`→攻击%)③**最长公共子串回退**(删字后仍缺字如 `共鸣技伤害加成`→"伤害加成"4字归位; ≥3字直接归位平手按优先级, =2字仅唯一候选, 多候选不猜)
- 截图 = 右侧详情面板完整区(0.665,0.07)-(0.995,0.65), 非网格左上角
- **debug 数据集**(`evaluate_only` 内 `if True:` 开关): 每格存 全屏PNG + ROI框叠图(红=detail/绿=grid/蓝=count) + 三个区域裁剪图, 每次 OCR 的文本/坐标/置信度记入 `ocr_text.txt`; 输出 `logs/eval_debug/<时间戳>/`, 独立于报告临时目录不随报告删除(200声骸约数百MB~1GB); 供离线核对坐标常量与 OCR 输入(也是图标识别回归的数据源), 无需重开云游戏
- **评分公式**(`DEFAULT_WEIGHTS` + `compute_weighted_score`): 条分 = 档位值÷**期望值** ×10×权重(无效=0); **期望 = 官方公示的概率期望档位值**(`assets/echo_probability.json` → `echo_stats.get_mean`, **统一舍入 1 位小数** —— 报告明细行直接展示它; 官方档位概率不等, 双暴期望比算术平均低约 10%、其余约 2%~3% → **平均档 = 10.0 分, 满档 ≈ 13.1~14.0**); 通用权重(**阶段十八按满档词条的边际收益重排**, 旧值见 CHANGELOG): 暴击 **1.0** 爆伤 **0.7** 百分比三系(攻/生/防) **0.5** 共效 **0.6** 专伤(普攻/重击/共技/共解) **0.4** 固定三系(攻/生/防) **0.25**(恒为对应大值的 0.5 倍, 机制性结论); 套装模板权重已按同一因子折算(词条选择与组内比例保留套装差异)

## "通用口径" 不等于 "散搭收益"(实测结论, 勿据此改判定)

- **通用(DEFAULT_WEIGHTS)分几乎总高于套装分**: 实测 104 只里 **98 只(94%)** 通用分更高, 最大差 30.5
  (`火鬃狼/隐世回光`: 套装分 5.12 vs 通用分 35.64)。原因: 通用表覆盖 13 个词条(最低 0.5), 而套装模板
  一般只认 5~9 个键、未认词条记 0 → 这是**评分口径差异**, 不代表"散搭更强"
- **散搭收益本程序无法推断**: 真正决定"散搭 vs 套装"的是"套装效果 + 角色适配", 模板里没有这类数据
- **"某个套装值不值得练"是用户策略, 不做字段/系数**: 判定口径刻意保持"单套装视角"(只看该套装权重下的分数);
  用户若想排除不关心的套装, 用评估报告的「套装」下拉筛选(已实现)即可
- 实测依据: `tools/offline_eval_report.py` 跑 `logs/eval_debug/20260911_110817`(109 只)
- 评估/渐进判定(`judge_echo` 公共, **六档**): **Lv5/Lv10 = 结构判定**——存在"首条核心词条"(`_core_first`, 缺省=全部有效词条; 通用 weight>0)即过, 不限分(文案「建议强化/不建议强化」)。**完整判据/数学依据见 `eval_rules.md`(改判定前必读)**。Lv15+ 两条线: **达标线 A = 10 × 出现有效词条权重之和**; **基准线 B = 该套装有效键最低 (tier-1) 条之和×10**(配置未定制的套装其 B 即通用线 → Lv15/20/25 = **6.5 / 11.5 / 17.5**; 定制的套装用低权重"占位键"压 B 是刻意取向, 不被通用标准覆盖)。
  **达标 = score ≥ B 且 A ≥ B 且 score ≥ A**(三条同时); **A < B 说明出现有效词条太少、求和项不足以支撑达标 → 该只最高只能到"保留"**。数学: k(=出现有效词条数) ≥ tier-1 时 A ≥ B 恒成立; k < tier-1 时 A 可能 < B(实测 34% 样本 k < tier-1, 其中 25 只真的更低)。
  ★ **待决策(a 方案, 未实现)**: 现规则只拦 `A < B`, 而 A 由"**出现的那几条**"决定 —— 若出现的那 3 条恰好是该套装
  权重最高的几条(暴击 1.0 + 共效 0.6 + 共解 0.5 = 2.1 > B/10 = 1.85), 就能在**只有 3 条有效词条**时达标
  (实测 #1 虚造神型: k=3 / A=21.0 / B=18.5 / score 22.51, 加权平均档位比 1.072; 把共效换成期望档即掉到保留)。
  新报告全库满级 117 只: k 分布 `{1:3, 2:7, 3:51, 4:51, 5:5}` → **k < tier−1 有 61 只**, 其中**仍达标 16 只**。
  候选 (a) `k < tier−1` 封顶"保留"(只影响这 16 只) / (b) 无效词条扣分 / (c) B 用 tier 条最低权重和。详见 CHANGELOG 补记 13。
  满级: `A ≥ B 且 score ≥ A` → **达标**; `score ≥ B` → **保留**; 否则 `reforge_plan` 有方案(穷举"锁 L 条 + 刷 5−L 条", 要求**蒙特卡洛达标概率 ≥ `REFORGE_MIN_PROB`=0.60**、成本取最低) → **建议重铸**; 否则 **不合格**。
  未满级: `score ≥ B(满级)` → **建议强化**; 否则 `enchant_prospect` 前瞻(继续开到满级能过 B(满级) 的概率) ≥ `ENCHANT_MIN_PROB`=0.60 **且** `score ≥ A(现有)` → **建议强化**; 否则 **不建议强化**。
  **强化流程不豁免**(不达标/不建议强化仍丢弃), 保留/建议重铸/建议强化仅报告标注。**为什么用概率而非期望**: 期望只是均值(≈五成把握)且分布右偏, 而胚子可无限刷 → 不为低概率花资源(用户原则)。
- **套装模板校验**: `_core_first`(可选, 首条核心词条) + **键数<5 → 评估/强化启动硬拒**(强化后必有 5 词条)
- 报告(`_build_eval_html`): 名称独立列 + **套装列**(`set`, 来源 `set_src` 放单元格 `title`: 套装图标判定/声骸名兜底/默认(通用); 旧报告缺字段显示 `—`) + **「COST/主属性」列**(COST 角标 + 两条主属性 + 官方管理方案判定 `✔`/`✘`/`·`; 行上带 `data-cost`/`data-plan` 便于后续加筛选) + **评估规则折叠卡片**(`_build_rules_html`, `<details>`: 评分公式/达标线/判定四档/套装判定来源/官方主属性方案 + **本次报告涉及套装的权重表**, 让每行分数可追溯) + 得分区间/判定多选/名称包含/**套装下拉**(选项=本次出现的套装+全部, 带条目数)筛选(原生 JS 全靠 `data-*`, **不依赖列索引**, 加列不影响筛选) + **主指标「完成度」**(= 得分 ÷ 该套装 Top-5 权重词条全满档分; **同套装内跨件可比, 跨套装不可比**)与**按完成度排序**(默认/升/降; `data-comp` 驱动) + 未满级件附「继续到满级过保留线 ≈X%」(`prospect` 前瞻) + 词条按档位 ratio 单色相连续渐变着色(`hue=210`, 亮度 92%→46%, **越深越高档**; 白底细描边)
- **已知缺陷(原版 ok-ww 同款)**: 强化 `run()` 无"切下一只"推进, 依赖丢弃后游戏自动前移; 评估遍历在网格布局/字体变化时坐标常量需复核

## 阶段二十四要点(2026-09-16, 完整记录见 CHANGELOG)

- **判定文案的唯一来源 = 判定层**: 报告用记录里的 `verdict_cn`(judge_echo 产出), `ui/run_tab.VERDICT_CN`
  只兜底旧报告 —— 曾因 `verdict_cn_map` 在渲染时**覆盖**它, 导致新文案在报告里显示不出来。**勿再加渲染期改写文案的表**
- **`EnhanceEchoTask.evaluate_one()` 是评估的唯一收口**: 评分 + 判定 + 前瞻 + 重铸方案 + 词条明细;
  `evaluate_only` 与 `tools/offline_eval_report.py` 共用(改判定/明细只改这一处)。`dedup_key` 同理(静态方法)
- **单一来源**: 词条表与展示顺序 = `echo_set_templates.STAT_ORDER`(套装配置表格 / 强化下拉都由它派生);
  通用基准线代表集 `_GENERAL_WEIGHTS` = `DEFAULT_WEIGHTS` 的去重权重值(不再手抄两处); 套装名单 = `get_all_set_names()`
- **`judge_echo` 第三项 = reforge 方案**(不是旧 `keep`): 「建议重铸」时给方案, 其余 `None` —— 调用方**不要**再调一次
  `reforge_plan`(穷举锁定组合 + 蒙特卡洛, ≈190ms/次)
- **debug 数据集默认关**: `EnhanceEchoTask.SAVE_DEBUG_DATASET = False`; 需要 `logs/eval_debug/` 素材
  (两个 tools 的数据源)时改 `True`
- **唯一入口 `mainui.py`**: `main.py`/`main_debug.py`/`run.py` 已删; `ChangeEchoTask` 已删(自建 UI 无入口);
  `MouseResetTask` **保留**(TriggerTask, 默认 `_enabled=True` 且自建 UI 无开关)

## 接力状态 / 下一棒(2026-09-15)

**已完成**: 阶段十一~二十三 —— 套装图标识别 / 声骸名容错(十一/十二) → 官方概率期望(十六) → 分位体系(十七) →
权重按满档边际收益重排(十八) → 重铸判据改"锁 N 刷 M"(十九) → 报告主指标改**完成度**(二十) →
**重铸改蒙特卡洛达标概率 ≥0.60**(二十一) → **未满级前瞻**(二十二) → **未满级细分「建议强化/不建议强化」(二十三)**。
**判定链的权威说明是 `eval_rules.md`**(含分类矩阵、数学依据、已评估不改项 E1~E7、风险清单); 判定单测在 `tests/test_judge_rules.py`。

**工作区 / 推送(2026-10-08 更新)**: 阶段二十四~二十九 均已提交并 `push origin main`
(`37829ac` 阶段二十四 · `54c124f` 阶段二十五 官方静态数据层+官方图标 · `5d32374`/`abf5468` 阶段二十六 界面重构 ·
`d51f6e3` 阶段二十七 主属性数值校验 · `7246757` 阶段二十八 套装效果 `pieces` · 阶段二十九 组合穷举+伤害排名)。
改动后跑: `python -m unittest discover -s tests`(122 项) + `python tools/ui_shot.py`(界面自检, 8 页) +
`python tools/offline_eval_report.py`(离线重放, 需 `logs/eval_debug/` 素材) + `python tools/echo_plan.py --list`(库存)。

**唯一未验证: 真机实跑**。阶段十六~二十三 的判定链路变化极大(概率期望 / 新权重 / 概率门 / 前瞻 / 完成度),
跑一次评估核对三点: ① `[评估#N]` 的判定文案是否为新六档 ② 报告「完成度」与排序是否正常 ③ 整轮耗时
(蒙特卡洛只对"未过线"的件触发; 离线 109 只约 8 秒)。阶段二十九 的「组合穷举」页另需一次界面走查
(导入库存 → 选套装 → 穷举 → 双击明细 → 导出 CSV)。

**下一棒候选(按价值排序)**:
- **与 wuwa-calculator 对账**(`panel_plan.md` 步骤 4): 同一组输入喂两边, 伤害应一致 —— 这是组合穷举最强的正确性验收
  (尤其要盯"固定值在括号外"与"声骸 COST 固有属性算不算面板贡献"这两处口径)
- **真机实跑核对 + 界面走查**(见上)
- **用户真实裸面板**: 样例里的 `攻击 1200 / 暴击 5% / 暴击伤害 150%` 是**占位值**, 拿到真实面板后再跑一次排名
- **5★ 判定**: 评估产物无稀有度字段; 若要真判定, 可用主属性数值网格(`echo_main_prop`)反推(不符网格 = 疑似 4★ 或 OCR 误读)
- **图标识别兜底到强化模式**: 现在强化套装由用户在下拉里选定, 不用图标; 若要"自动套装"强化可复用 `match_icon`
- **新增套装素材: 已自动化**(阶段二十五) —— 新版本套装的图标从客户端 pak 抽取(命令见「官方静态数据层」), `assets/gamedata/echo_data.json` 的 `icon_asset` 就是客户端贴图名; 只有拿不到客户端安装时才需要手工补 PNG
- **黑边校准: 暂不做**(用户确认云平台大概率全屏自适应)。触发条件: 若 `s1 < 0.60` 的低置信集中在某一分辨率/窗口模式, 再按黑边导致的整体偏移排查

## 待办(与 README TODO 同步)

- **判定体系: 已实现(阶段十四~二十三)** —— 六档(达标/保留/建议重铸/建议强化/不建议强化/0级) + 两处概率门
  (`REFORGE_MIN_PROB` / `ENCHANT_MIN_PROB` = 0.60) + 完成度主指标; 规则细节见 `eval_rules.md`
- 首条核心 + 键数硬拒: **已实现** —— `_core_first`(缺省=全部有效词条) + 套装键数<5 评估/强化启动硬拒
- 声骸名容错匹配 / 套装图标识别: **已实现(阶段十一/十二)** —— 离线回归 99.1% 高置信、名字口径 92.9% 一致;
  失效案例由图标兜底
- **开放项**: `eval_rules.md` §6「已评估、决定不改的项」(E1~E7, 避免重复讨论) + §7「未验证 / 风险」

## 已知坑

- `pynput` 是必需依赖(点击层运行时才 import, 缺库表现为"点击无反应")— 勿从 requirements 移除
- **受限沙箱里 `QSettings` 写不进注册表**(写后读回 None): 主题/窗口几何/上次页面这些"记忆"在那种环境下不生效
  —— 这会让 `tools/ui_shot.py --dark` 静默出浅色图(已在工具里兜底: `show()` 后再 `apply_theme(..., remember=False)`);
  真机(正常权限)不受影响
- **`cv2.imread` 读不了中文路径**(`assets/echo_icons/雪落无声之愿.png` 会返回 None) → 用 `cv2.imdecode(np.fromfile(path, np.uint8), …)`(`echo_icon_match._template_gray`)
- WGC 抓云游戏/浏览器窗口常黑屏 → cloud 锁定 `BitBlt_RenderFull`
- 窗口尺寸: 初始 **1120x760** + 最小 940x620 + **记住上次几何/上次页面**(QSettings "OK-Echo"/"MainWindow");
  200% 高 DPI 下按工作区 clamp(旧版固定 700x520 会把内容裁掉)
- 云游戏 16:10 画面已跳过 16:9 校验; 若云平台带黑边渲染, UI 归一化位置会偏移(黑边校准未做)
