# ww-echo

一个基于图像识别的鸣潮声骸强化自动化工具，从 [ok-ww](https://github.com/ok-oldking/ok-wuthering-waves) 剥离，基于 [ok-script](https://github.com/ok-oldking/ok-script) 开发。

*An image-recognition-based echo enhancement automation tool for Wuthering Waves, stripped from [ok-ww](https://github.com/ok-oldking/ok-wuthering-waves), built on [ok-script](https://github.com/ok-oldking/ok-script).*

*通过 Windows 接口模拟用户操作，无内存读取、无文件修改 | Simulates user input via Windows API — no memory reads, no file modifications*

---

## ⚠️ 免责声明 | Disclaimer

本软件开源、免费，仅供个人学习与交流使用。因使用本软件而产生的任何问题，均与本项目及开发者无关。

**使用本软件即表示您已阅读、理解并同意以上声明，并自愿承担一切潜在风险。**

*This software is open-source and free, for personal learning and communication only. The developers are not responsible for any issues arising from its use. By using this software, you acknowledge that you understand and accept all potential risks.*

---

## 功能 | Features

### 批量强化声骸 | Batch Echo Enhancement (EnhanceEchoTask)

自动将背包中的 0 级声骸强化至满级并调谐，根据设定的规则判断保留或丢弃。

*Automatically enhances level-0 echoes in your bag to max level, then decides to keep or discard based on configurable rules.*

**使用步骤 | Usage:**
1. 游戏内按 `B` 打开背包，切换到声骸标签页 | *Press `B` in-game, switch to Echo tab*
2. 使用过滤器筛选需要强化的声骸（按等级从低到高排序）| *Filter echoes (sort by level ascending)*
3. 选择强化策略和套装，启动任务 | *Select strategy and set, start the task*

---

### 强化策略 | Enhancement Strategies

提供 **传统 (Traditional)** 和 **渐进式 (Progressive)** 两种模式 | *Two modes available*:

#### 传统模式 | Traditional

满级后一次判断 | *Evaluate once after reaching max level*:

| 规则 | 默认 | 说明 |
|------|------|------|
| 必须有双爆 / Require Double Crit | ON | 最终必须同时拥有暴击和暴击伤害 / *Must have both CRIT Rate and CRIT DMG* |
| 双爆前全有效词条 / All Valid Before Crit | ON | 双爆出现前的词条都必须在有效列表中 / *Stats before first crit must all be valid* |
| 首条双爆 ≥ / First Crit ≥ | 6.9 | 第一条双爆的数值阈值（爆伤÷2）/ *Threshold for first crit stat (CDMG÷2)* |
| 双爆总计 ≥ / Total Crit ≥ | 13.8 | 暴击 + (暴击伤害÷2) ≥ 此值 / *CRIT Rate + (CRIT DMG÷2) ≥ threshold* |
| 有效词条 ≥ / Valid Stats ≥ | 3 | 满级时需要的有效词条数量 / *Required valid substat count at max level* |
| 第一条必为有效词条 / First Must Be Valid | ON | 首词条必须在有效列表中 / *First substat must be in valid list* |

#### 渐进式模式 | Progressive — 默认 / Default

每开一个词条就评估，不达标立即丢弃，**避免浪费材料** | *Evaluates at each tier — discard immediately on failure to save materials*:

| 阶段 / Tier | 条件 / Condition | 逻辑 / Logic |
|:--:|------|------|
| Lv5 第1条 | 必须在套装预期词条中 / *Must be in set's expected stats* | 不达标 → 直接丢弃 / *Fail → discard* |
| Lv10 第2条 | 不做判断 / *No check* | 继续强化 / *Continue* |
| Lv15 第3条 | 累积得分 ≥ **1.5** / *Cumulative score ≥ 1.5* | 不达标 → 丢弃止损 / *Fail → discard* |
| Lv20 第4条 | 累积得分 ≥ **2.25** / *Cumulative score ≥ 2.25* | 不达标 → 丢弃止损 / *Fail → discard* |
| Lv25 第5条 | 累积得分 ≥ **3.75** / *Cumulative score ≥ 3.75* | 不达标 → 丢弃；达标 → 上锁 / *Fail → discard; Pass → lock* |

---

### 评分系统 | Scoring System

采用 **均值归一化** 评分：每个词条得分 = `实际档位值 / 该词条全部档位均值 × 权重`，无效词条贡献 0。

*Mean-normalized scoring: each stat's contribution = `tier value / mean of all tiers × weight`. Invalid stats contribute 0.*

```
暴击值 6.3%  →  最低档 / min  →  6.3/8.4  = 0.75 词条当量 / stat-equivalents
暴击值 10.5% →  最高档 / max  →  10.5/8.4 = 1.25 词条当量 / stat-equivalents

5全最低 / all min = 3.75 | 5全平均 / all avg = 5.0 | 5全最高 / all max = 6.25
```

**词条权重** 在 GUI 中独立调整，共 13 个滑块，全部默认 1.0。

*Weights are individually adjustable via 13 sliders in the GUI, all defaulting to 1.0.*

---

### 套装模板 | Set Templates

17 个套装的预期词条硬编码在 `src/echo_set_templates.py`，渐进式模式的第一条必须在此列表中。

*17 echo sets with expected substats are hardcoded in `src/echo_set_templates.py`. Progressive mode requires the first stat to be in the expected list.*

| 配置 / Config | 默认 / Default | 说明 / Description |
|------|------|------|
| `当前套装` / Current Set | 通用 / Universal | 17 套装 + 通用可选 / *17 sets + universal* |
| `有效词条` / Valid Stats | 暴击/爆伤/攻击%/攻击/共鸣效率 | 通用默认（多选）/ *Universal default (multi-select)* |

---

### 批量修改声骸主属性 | Batch Main Stat Change (ChangeEchoTask)

自动将背包中声骸的主属性修改为目标属性（数据重构）。

*Automatically changes echo main stats to the target attribute via data reconstruction.*

**目标属性 | Target stats:** 攻击, 暴击伤害, 暴击, 生命, 防御, 共鸣效率, 冷凝/热熔/导电/气动/衍射/湮灭伤害加成 (ATK, CRIT DMG, CRIT Rate, HP, DEF, Energy Regen, Glacio/Fusion/Electro/Aero/Spectro/Havoc DMG Bonus)

---

## 配置说明 | Configuration

| 配置项 / Config | 类型 / Type | 说明 / Description |
|--------|------|------|
| `强化策略` / Strategy | 下拉框 / Dropdown | 传统 / 渐进式 (Traditional / Progressive) |
| `当前套装` / Current Set | 下拉框 / Dropdown | 通用 + 17 套装 / Universal + 17 sets |
| `有效词条` / Valid Stats | 多选框 / Multi-select | 13 个词条类型 / 13 stat types |
| `X权重` / X Weight | 数值滑块 / Slider | 13 个词条各一个，默认 1.0 / *1 per stat, default 1.0* |
| `最低得分≥` / Min Score | 数值 / Number | 最终阈值 / *Final score threshold* |
| `Pause after Success` | 开关 / Toggle | 成功后暂停，手动复核 / *Pause on success for manual review* |

配置保存在 `configs/` 文件夹，复制即可导出/导入。

*Configs are saved in the `configs/` folder — copy to export/import.*

---

## 运行环境 | Requirements

- **OS:** Windows
- **Python:** 3.12
- **Resolution:** 16:9 (min 1600x900)
- **Game language:** 简体中文 / 繁體中文 (zh_CN / zh_TW)
- **FPS:** Stable 60 FPS

## 从源码运行 | Run from Source

```bash
pip install -r requirements.txt --upgrade
python main.py        # Release
python main_debug.py  # Debug (shows detection overlays)
```

---

## TODO

- [ ] 清理 BaseWWTask 中无需的战斗/刷图代码 / *Clean up unused combat/farming code in BaseWWTask*
- [ ] 套装模板热加载 / *Hot-load set templates from external file*

---

## 项目结构 | Project Structure

```
ww-echo/
├── main.py / main_debug.py         # 入口 / Entry point
├── config.py                       # 全局配置 / App config
├── src/
│   ├── echo_stats.py               # 词条档位 + 评分 / Tier data + scoring
│   ├── echo_set_templates.py       # 17 套装模板 / Set templates
│   ├── Labels.py                   # UI 模板匹配标签 / Template labels
│   ├── globals.py                  # 全局状态 / Global state
│   ├── scene/WWScene.py            # 场景缓存 / Scene cache
│   └── task/
│       ├── EnhanceEchoTask.py      # ⭐ 批量强化声骸 / Echo enhancement
│       ├── ChangeEchoTask.py       # 批量修改主属性 / Main stat change
│       ├── BaseWWTask.py           # 任务基类 / Base task
│       ├── WWOneTimeTask.py        # 一次性任务 mixin
│       └── MouseResetTask.py       # 鼠标防偏移 / Mouse drift fix
└── assets/                         # 模板匹配资源 / Template assets
```

## 依赖 | Dependencies

基于 [ok-script](https://github.com/ok-oldking/ok-script) 框架，使用 OnnxOCR 文字识别 + 模板匹配 UI 定位。

*Built on [ok-script](https://github.com/ok-oldking/ok-script), using OnnxOCR for text recognition and template matching for UI localization.*

## 致谢 | Credits

- [ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) — 原始项目 / *Original project*
- [ok-oldking/ok-script](https://github.com/ok-oldking/ok-script) — 自动化框架 / *Automation framework*
