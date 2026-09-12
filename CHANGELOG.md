# 开发历程 | Development Log

## 阶段一：剥离 ok-ww (2026-07-07)

从 [ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) 提取声骸强化模块。

**操作：**
- 复制 `EnhanceEchoTask` / `ChangeEchoTask` 及依赖链
- 删除 `char/` (52个角色)、`combat/` (战斗)、YOLO模型(37MB)、15+战斗任务
- 保留 `BaseWWTask`(1197行) → 后替换为 `BaseEchoTask`(43行)
- 项目从 ~50MB 减至 3.6MB

---

## 阶段二：评分系统搭建 (2026-07-07)

**新增：**
- `src/echo_stats.py` — 13词条档位数据 + `snap_to_tier()` / `get_mean()`
- `src/echo_set_templates.py` — 31套装模板 (JSON格式)
- 均值归一化评分: `单词条 = 档位值/均值 × 权重`
- 权重体系: 暴击2.0 / 爆伤1.5 / 攻击%1.0 / 攻击0.5 / 共效1.0 / 专属加成2.0

**策略：**
- 传统模式: 满级后一次性判断
- 渐进式模式: Lv5/Lv10/Lv15/Lv20/Lv25 逐级评估，不达标立即丢弃
- 评估模式: 只读遍历，截图+评分，生成HTML报告

---

## 阶段三：自建 UI (2026-07-08)

放弃 ok-script 原生 GUI，自建 PySide6 界面。

**UI 面板 (7 tab)：**

| Tab | 来源 |
|-----|------|
| 设备设置 | ok-script StartTab |
| 热键设置 | ok-script Game Hotkey global config |
| 强化运行 | 自建 — 模式/策略/套装/启停/状态 |
| 套装配置 | 自建 — 表格编辑词条&权重, 导入导出 |
| 调试工具 | ok-script DebugTab + 共享日志 |
| 开发者 | ok-script RunCodeTab + TemplateTab |
| 关于 | ok-script AboutTab |

**关键设计决策：**
- `ok-script` 仅用作后端引擎 (截图/OCR/模板匹配/键鼠)，不创建其GUI
- `mainui.py` 直接调用 `og.app.start_controller.start()`
- 套装词条&权重→JSON双向同步，JSON即保存即导入导出

---

## 阶段四：代码审查与修复 (2026-07-08)

双 Agent 审查 (代码 + 产品)，修复 P0/P1 共 9 项：

**P0 (4项):**
1. 评估/强化阈值不一致 → `evaluate_only` 改用 `check_echo_progressive`
2. 评估进度不显示 → 状态栏增加评估计数
3. `dev_tab` exec() 安全漏洞 → 移除 `exec()`
4. `_stop` 竞态条件 → 加 `thread.join()`

**P1 (5项):**
5. 三重命名体系 → 统一 `echo_stats` 键名为 OCR名，删除 `_OCR_TO_TIER_NAME`
6. 归一化代码重复4次 → 提取 `_normalize_stat()` + `_pair_props()` 静态方法
7. 恢复默认按钮无效 → 改名"重新加载"
8. 评估取消不删临时文件 → 加 `shutil.rmtree` 清理
9. 死代码: `is_max_level`, `score_stat`, `DEFAULT_WEIGHTS`, `get_stat_weight`, `text_white_color`

---

## 阶段五：日志/注释审查 (2026-07-08)

Agent 审查日志质量：

**修复：**
- `evaluate_only` 中 `threshold` 变量未定义 (NameError → 崩溃)
- `lock_and_esc` 日志误导 ("成功弃置" → "成功上锁")
- OCR 输出级别过高 (info → debug)
- 死代码 `src/__init__.py` 删除

---

## 阶段六：云游戏适配 (2026-09-08)

目标: 鸣潮跑在云游戏(浏览器/云客户端, 如 Firefox 全屏)时也能自动强化/评估。

**运行模式双轨 (`config.apply_run_mode`)**
- `local`(默认): exe/hwnd_class 自动匹配本地 `UnrealWindow`, PostMessage 后台交互
- `cloud`: 置空 exe/hwnd_class, `title=re.compile('鸣潮')` 让 ok-script `find_hwnd` 正则自动锁定标题含"鸣潮"的窗口(免手动选窗); interaction=Pynput(前台真实键鼠); capture 锁定 `BitBlt_RenderFull`(WGC 对云客户端不可靠); `supported_resolution.ratio=None` 跳过 16:9 校验(16:10 屏); 模式存 QSettings("OK-Echo"), 重启生效

**ok-script(site-packages)补丁 — 升级 ok-script 会丢失, 需重打(均在代码内标注 `[ww-echo ... patch]`)**
| 文件 | 改动 |
|------|------|
| `ok/gui/StartController.py` | `_auto_bring_to_front`: 仅当用户点开始(task 非 None)时, device-ready 等待循环每轮自动 `bring_to_front()`(含最小化恢复); 纯启动不抢前台 |
| `ok/device/capture_methods/hwnd_window.py` | `visible = not IsIconic()` 替代 `is_foreground()`: 后台/被遮挡窗口仍视为可用(BitBlt_RenderFull 可抓), 不再因切走而翻转状态 |
| `ok/device/interaction_methods/pynput.py` | `should_capture()`→True(任务主循环不再被前台门控); `clickable()` 保持纯判断; 新增 `_ensure_clickable()` 供各动作(click/send_key/scroll…)非前台时自动拉前再操作 |
| `ok/util/window.py` | `find_hwnd` 开头过滤空 exe 项: `exe_names = [e for e in (exe_names or []) if e]`: 云模式 `selected_exe=''` 时, 空 exe 会让所有窗口在 exe 匹配处被判不匹配 → 找不到"鸣潮"窗口 |

**踩坑记录**
- 云游戏本地无 `UnrealWindow`/`Client-Win64-Shipping.exe` → 按窗口类找目标整套失效(为什么 navigator 这类"读屏工具"能用于云游戏, 本项目"读窗口工具"不能)
- `PynputInteraction` 前台注入必须目标窗口在前台, ok-script 原逻辑把"是否前台"当运行前提 → 切走即停/一运行抢前台; 拆成"点击动作层自动拉前, 识别层不要求前台"
- 缺 `pynput` 依赖(点击层运行时才 import, 缺库表现为点击无反应) → 已补 requirements
- 鸣潮背包滚动有"热区": 光标需在网格中右部(≈归一化 x0.42-0.63), 左侧列与底部不响应; ~8px/notch
- 高 DPI 200% 下固定 860x640 逻辑窗口物理化超屏 → 初始 700x520 + 工作区 clamp/居中(`ui/main_window.py`)

---

## 阶段七：评估遍历 v2 + 词条过滤 (2026-09-09)

原 evaluate_only/run 只处理"当前选中声骸", 无"切下一只/识别/到底"三件套(原版 ok-ww 同样没有), 表现为秒退"无可评估/无可强化"或死循环同一只。

**评估遍历 v2 (`evaluate_only`)**
- 识别: OCR 网格区 `+xx` 角标 → 聚行 → 6 列基准(跨屏记忆 `col_centers`) → **行内缺列补全防漏点**
- 点格 → 右侧详情 OCR → 评分/截图/记录 → 空格/未切换**跳过继续**(不提前滚漏真实格) → 本屏处理完滚动 15 notches(光标热区 0.52,0.5)
- 到底: 详情"0 词条"(全新/列表末)结束; 左上 `声骸N/3000` 数量上限收尾; 连续 3 次滚动无新格兜底
- 唯一性: 废弃角标 dhash(同种声骸角标相同会误跳) → 用**详情全量 OCR 文本签名**

**词条筛选关键修复 (`echo_stats.is_stat_match`)**
- 详情面板属性行混排主属性与词条; 主属性数值可能落在词条档位区间内(如低等级主属性 攻击54 ∈ [30,60]) → **区间判断会误收**
- 改**离散档位集合匹配**: 数值须≈档位表中某个档位值(容差 0.8); 主属性 150/1915/54/15.1% 全部被拒; 词条最多 5 条
- 评估判定统一用"得分 ≥ tier 阈值"(1.0/2.0/2.5/3.0), 不再调 `check_echo_progressive`(避免两套阈值打架)

---

## 阶段八：评分体系与判定重构 (2026-09-11)

用户主导的评分/权重/阈值全链路重设计。

**权重标度**
- 条分改为 `档位值÷均值 ×10×权重`（每条上限自然 12.5，无效 0 分）；旧标度作废
- `DEFAULT_WEIGHTS` 定稿：暴击1.0 / 爆伤0.9 / 百分比三系(攻/生/防)0.85 / 共效0.7 / 专伤(普攻/重击/共技/共解)0.6 / 固定三系 0.5（白值700-1000下小攻击≈1%攻，全乘区通用）
- 套装模板权重多次重映射对齐通用表

**达标线(锚线)**
- `_tier_threshold` = 有效词条"平均档加权分"(10×权重)中**最低 (tier-1) 条之和**；通用 6 种适配集：Lv15=11 / Lv20=18 / Lv25=26.5；键数不足取全部键
- Lv5/Lv10 = **结构判定**：存在"首条核心词条"(`_core_first`，缺省=全部有效词条；通用 weight>0)即过，不限分

**判定统一**
- 抽出 `judge_echo(set_name,tier,score,stats)` → `(verdict, verdict_cn, threshold, keep)`，评估与渐进强化共用一份（强化 = 评估判定 + 强化动作）
- `keep`(建议保留重铸)：满级不达标 且 有效条数≥2 且 有效分≥18（洗练成本线，锁2追3 语义）；**强化流程不豁免**（不达标仍丢弃），仅评估报告标注——按用户决定不做游戏内重铸动作

**套装模板校验**
- `_core_first` 首条核心词条（套装配置 UI 有"首核"勾选列，缺省全勾=全部有效）
- **键数<5 → 评估/强化启动硬拒**（强化后必有 5 词条，最少需 5 个有效）

**报告增强 (`_build_eval_html`)**
- 判定四档：达标 / 待强化 / 建议保留重铸 / 不合格（兼容 0级）
- 名称独立列；筛选：得分区间(≥/≤) + 判定多选 + 名称包含匹配；词条按档位 ratio 着色(roll-4~0)
- 评估模式隐藏套装下拉（改为按声骸名映射，见阶段九）

**套装配置 UI**
- 勾选词条自动带出通用默认权重（专伤=0.6 等，替代固定 1.0）；权重 SpinBox 两位小数（0.85 不失真）

## 阶段九：套装声骸数据与自动映射 (2026-09-11)

**数据结构**（`echo_set_templates.json` 每套装）
- `_echoes: {"4c":[...], "3c":[...], "1c":[...]}` 该套装的声骸清单
- `_icon`: 套装图标名（wuther.in `IconElementAttri{名}`，如 Cloud/Ice）

**数据来源**（合规说明）
- kurobbs 需登录令牌、wuther.in robots.txt 明确 `Disallow` AI 爬虫 → **不做脚本爬取**；改由用户浏览器保存页面后本地解析
- 解析要点：声骸卡片左上角图标 ↔ 筛选按钮"图标+套装名"对照；一个声骸可属多套装（多图标）
- 解析工具 `tools/parse_wutherin_echoes.py <页面.html>`：只覆盖解析到数据的套装（**保留手补值**）、自动补 `_icon`/新增套、生成 `echoes_check.md` 核对表
- 结果：34 套（31 原 + 3 新：羽落空尘之歌/清邪荡煞之心/冥途夜行之灯）；后以用户手工整理的 `1.txt` 为准整体校准 `_echoes`——移除错误前缀「异相」(正确为「梦魇」)、剔除误录入的角色/多余声骸、补全 `剪心辑梦之影` 等缺失清单

**评估自动映射**
- `get_sets_by_echo(名)` → 候选套装列表；`get_set_by_echo(名, prefer=config套装)` → prefer 在候选内则尊重，否则模板顺序首个；未录入回退通用
- 评估逐格按声骸名取套装 → 用该套装的权重/有效键/首核/锚线判分（不再需要通用下拉）

---

## 阶段十：代码审查修复 + 报告着色改造 (2026-09-12)

**审查修复(11 项, P1+P2/P3)**
- 文案对齐新标度: `EnhanceEchoTask.config_description` 旧阈值描述 → 新标度
- 评估注释/日志: "固定通用权重" → "按声骸名自动映射套装权重"
- 边界/死代码清理: `src/globals.py`、`src/scene/WWScene.py`、`src/task/ChangeEchoTask.py`、`ui/dev_tab.py`、`ui/settings_tab.py`(`addItem(None)`)、`src/task/process_feature.py`(docstring)
- `mainui.py`: `config['debug']` 默认 `True` → `False`(不再默认开调试); `config.py`: `calculate_pc_exe_path` 补注释

**报告词条着色: 多色相离散 → 单色相连续渐变**
- 旧: `roll-0~4` 五档离散色(绿/黄/橙/红), 与判定列语义色冲突且色相跳变
- 新: `_ratio_color(ratio)`: `t=clamp((ratio-0.65)/0.7,0,1)`, `L=92-46*t`, 返回 `hsl(210,60%,L%)` → **越深越高档**; 词条改用 inline `style="background:…"`
- CSS 删 `roll-0~4`; `.stat` 加 `border:1px solid rgba(0,0,0,0.06)`(白底描边保证可见)

---

## 阶段十一：声骸名容错匹配 (2026-09-12, **工作区未提交**)

**背景**: 反向索引里 181 个声骸名中 **120 个属 ≥2 套装**(共 351 条归属), 加上 OCR 错字, 使"按声骸名映射套装"频繁错配/丢失。

**实现(`src/echo_set_templates.py`, 照词条过滤 `_normalize_stat` 的三级思路)**
- `_echo_chars`: 全部声骸名的汉字白名单(**341 字**), 建反向索引时顺带收集
- `_strip_echo_prefix`: 剥「异相」皮肤前缀(`异相·双极·星升辉铳` → `双极·星升辉铳`); **「梦魇·」是真实前缀(独立声骸), 保留**
- `_match_echo_name`: ①剥前缀 → ②精确 → ③逐字白名单清洗(剥错字/杂字) → ④子串(唯一候选) → ⑤LCS 最长公共子串(≥3 字且唯一); 全不中返回 `[]`
- `get_sets_by_echo` 改调 `_match_echo_name`; 返回**候选列表**(非取首个)
- **未提交**: 用户要求与"套装图标识别"一起做完再提交

**实测**
- 正确: 海维夏 / 戏猿 / 车刃镰 / 双极·渊陨重锋 / 异相·双极·星升辉铳 / 梦魇·青羽鹭
- **已知失效(名字层无解, 交图标识别兜底)**:
  - `梦魔·青羽鹭`(魇→魔 错字): 清洗后含子串「青羽鹭」而该名在索引中独立存在 → 子串分支唯一命中抢跑 → 误配 `[啸谷长风, 浮星祛暗]`(应 `[息界同调之律]`, 即「梦魇·青羽鹭」所属套); 若走 LCS 会得「青羽鹭」「梦魇·青羽鹭」两个 3 字平手 → 本应返回 `[]`
  - `侏侏驼`(驼→鸵): 清洗后仅剩 `侏侏`(2 字) → 命中 2 候选 → LCS 仅 2 字 → `[]`
  - `咔嘧` / `阿磁磁`(真名 咔嚓嚓 / 阿嗞嗞): 清洗后仅剩 1 字 → `[]`

---

## 阶段十二：套装图标识别 (2026-09-12)

**背景**: 阶段十一的名字容错仍有多义(**120/181 声骸属多套**)与错字无法消歧的案例 → 改读游戏详情面板的套装图标作为硬信号。

**输入**(视觉模型给出, 源 `vision.txt`): 图标在等级 `+25` 文字右侧, 详情面板内归一化 `(0.2100,0.1231)-(0.2535,0.1667)`(对应整帧 `(1402,199)-(1430,227)`@1920x1200); 圆形外径≈28px(含 2px 外发光); 与网格滚动无关(抽样 22/219 张波动 ≤±3px) → 可写死归一化坐标。

**方法**(`src/echo_icon_match.py`)
- 图标区 → 灰度 28x28; 模板 `assets/echo_icons/*.png`(34 个, 76x76) 缩到 29px(尺度 1.05)中心裁 28 → 两端同分辨率 1:1 比
- 判据 = **灰度 ZNCC** + **±2px 平移搜索**(消 bbox 抖动; 不搜索时 s1 从 0.9 掉到 0.23) + 圆形 mask(r≤12, 排外发光/面板背景)
- 置信线: `MIN_SCORE=0.60`(最佳 ZNCC) + `MIN_MARGIN=0.05`(与次优间隔), 不达线返回 None
- **弃用方案记录**: 视觉模型实测"34 个模板缩小后全屏搜 top1 错(愿戴荣光之旅 0.780, 真实 雪落无声之愿)" → 那是**全屏滑窗**的轮廓退化; 本实现改为**固定坐标裁剪 + 同分辨率 1:1 ZNCC** 后不再有该问题。**颜色/环色特征实测无效**(模板同构: 彩色圆环 + 白底 + 深色图案, 缩到 28px 后轮廓主导 → 环色 top1 命中仅 28/183)

**集成**(`EnhanceEchoTask.resolve_set_name`)
- 图标优先(**与名字候选不一致时也以图标为准**) → 低置信回退名字候选 → 再回退 config(评估=通用)
- 来源 `icon`/`name`/`default` 记入报告 JSON(`set`/`set_src`); 日志 `[套装图标] 名 → 套装 (s1=… margin=…)[ — 名字候选 […] 由图标纠正]`
- 评估报告(`_build_eval_html`)新增**套装列**: 显示 `set`, 悬停看来源; 旧报告缺该字段显示 `—`。
- 评估报告新增**「评估规则」折叠卡片**(`_build_rules_html`): 评分公式(档位值÷均值×10×权重, 每条上限 12.5)、
  达标线(有效词条最低 n−1 条平均档加权和; 通用 11/18/26.5; Lv5/10 结构判定)、判定四档语义、
  套装判定来源(图标 s1≥0.60/margin≥0.05 优先, 否则名字候选), 并附**本次报告涉及套装的权重表**
- 评估报告筛选区新增**套装下拉**: 选项 = 本次出现的套装 + 全部套装(带条目数、按数量降序), 精确匹配 `data-set`;
  与得分区间/判定多选/名称包含串行生效, 清除筛选时一并重置
  报告筛选由 `data-*`(data-score/data-verdict/data-name/data-set)驱动, 不依赖列索引 → 加列不影响筛选
- 新增 `cv2.imdecode(np.fromfile(...))` 读模板(中文文件名, `cv2.imread` 返回 None — 见 CLAUDE.md 已知坑)

**离线回归**(`tools/eval_icon_match.py`, 用 `logs/eval_debug/<时间戳>/` 全屏图, 无需开游戏)
- 219 张: **217 张高置信(99.1%), s1 中位 0.894**; 名字候选非空 211 张中 **196 一致(92.9%)**
- 15 张不一致**全部是名字层已实证的错字案例**, 图标给出正确套装: `梦魔·青羽鹭`/`梦魔·啾啾河豚`/`梦魔·咕咕河豚` → `息界同调之律`(s1=0.93, margin=0.43); 同套装图标的 s1 完全一致 → 匹配稳定
- 2 张低置信(`无归的谬误`, s1≈0.22): 该详情面板图标区**没有图标**(裁出来是深色背景 + 立绘边缘) → 回退名字候选 `隐世回光`(正确)

---

## 当前架构

```
ww-echo/
├── mainui.py              ← 唯一入口 (PySide6); 启动先按 QSettings run_mode 调 apply_run_mode
├── config.py              ← ok-script 配置 + MODE_LOCAL/MODE_CLOUD + apply_run_mode()
├── ui/                    ← 自建UI (7 tab)
│   ├── main_window.py / run_tab.py / set_config_tab.py
│   ├── settings_tab.py / hotkey_tab.py   (settings_tab: 运行模式切换 + 窗口/截图/交互)
│   ├── debug_tab.py / dev_tab.py / about_tab.py
├── src/
│   ├── echo_stats.py      ← 词条档位 & 评分引擎 (+ is_stat_match 离散档位过滤)
│   ├── echo_set_templates.py ← JSON模板 加载/校验 + 声骸名容错匹配
│   ├── echo_icon_match.py  ← 套装图标识别(灰度 ZNCC 模板匹配; 名字消歧硬信号)
│   └── task/
│       ├── EnhanceEchoTask.py  ← 强化 run() + 评估 evaluate_only v2 遍历
│       └── BaseEchoTask.py     ← 轻量基类
├── tools/
│   ├── parse_wutherin_echoes.py ← 从保存的 wuther.in 页面解析套装声骸清单(保留手补)
│   ├── eval_icon_match.py      ← 套装图标识别离线回归(eval_debug 数据集, 无需开游戏)
│   └── offline_eval_report.py  ← 离线重放评估(eval_debug 素材) → 生成 eval_report.html
└── assets/
    ├── echo_set_templates.json ← 套装模板 + _core_first/_echoes(4c/3c/1c)/_icon (34套)
    ├── echo_icons/            ← 34 个套装图标(76x76, 文件名 = 套装名)
    └── coco_annotations.json   ← 模板匹配特征
```

## 待实现

- [x] 满级保留/重铸机制(锁2追3+高档位+重铸建议列三合一): **评估侧已实现**(keep: 满级不达标且≥2条有效且≥18分 → 报告第四档"建议保留重铸"); 强化不豁免; 按用户决定不做游戏内重铸动作
- [x] 副C/奶双逻辑评价: **已解决**——由套装模板"有效词条+权重"方案覆盖(奶套预设共效/生命/固定攻权重、双暴降权)
- [x] 剪心辑梦之影 套装的 4C/3C/1C 声骸清单: **已补**——以 `1.txt` 为准(4C 无铭探索者 / 3C 迷胧幻蛾·莳植机麋·矿岩机麋·重工铁蹄 / 1C 矿岩熊蜂·莳植熊蜂·冰盈舞者)
- [x] 声骸名容错匹配: **已实现(阶段十一)**; 已知失效(错字丢字→`[]` 或子串抢跑误配)由套装图标识别兜底
- [x] **套装图标识别**: **已实现(阶段十二)** —— `src/echo_icon_match.py` 灰度 ZNCC + ±2px 平移搜索 + 圆形 mask, 置信线 0.60/0.05; `resolve_set_name` 图标优先映射(**与名字候选不一致时也以图标为准**); 离线回归(219 张)高置信 99.1% / 名字口径一致 92.9%, 15 张名字层错字全部由图标纠正; 回归工具 `tools/eval_icon_match.py`
