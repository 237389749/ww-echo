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

## 当前架构

```
ww-echo/
├── mainui.py              ← 唯一入口 (PySide6)
├── ui/                    ← 自建UI (7 tab)
│   ├── main_window.py / run_tab.py / set_config_tab.py
│   ├── settings_tab.py / hotkey_tab.py
│   ├── debug_tab.py / dev_tab.py / about_tab.py
├── src/
│   ├── echo_stats.py      ← 词条档位 & 评分引擎
│   ├── echo_set_templates.py ← JSON模板 加载/校验
│   └── task/
│       ├── EnhanceEchoTask.py  ← 强化 + 评估 (核心~650行)
│       └── BaseEchoTask.py     ← 轻量基类 (43行)
└── assets/
    ├── echo_set_templates.json ← 套装模板 (即配置存档)
    └── coco_annotations.json   ← 模板匹配特征
```

## 待实现

- [ ] 锁2追3机制: 满级 ≥2条top4 → 锁定重铸；T3容忍1无效但需≥2有效top4
- [ ] 评估报告增加重铸建议列
