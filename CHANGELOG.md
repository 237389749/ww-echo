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
│   ├── echo_set_templates.py ← JSON模板 加载/校验
│   └── task/
│       ├── EnhanceEchoTask.py  ← 强化 run() + 评估 evaluate_only v2 遍历 (755行)
│       └── BaseEchoTask.py     ← 轻量基类 (43行)
└── assets/
    ├── echo_set_templates.json ← 套装模板 (即配置存档)
    └── coco_annotations.json   ← 模板匹配特征
```

## 待实现

- [ ] 锁2追3机制: 满级 ≥2条top4 → 锁定重铸；T3容忍1无效但需≥2有效top4
- [ ] 评估报告增加重铸建议列
- [ ] 副C/奶双逻辑评价: 双维度打分取最高, 标注推荐定位；奶维度=攻击%2.0/共效1.5/生命%1.5/攻击0.5/生命0.5
