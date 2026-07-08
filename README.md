# ww-echo

基于图像识别的鸣潮声骸强化自动化工具，从 [ok-ww](https://github.com/ok-oldking/ok-wuthering-waves) 剥离，基于 [ok-script](https://github.com/ok-oldking/ok-script) 的截图/OCR/键鼠能力，自建配置管理 UI。

*An image-recognition-based Wuthering Waves echo enhancement tool. Uses ok-script for capture/OCR/input, with custom-built config management UI.*

*通过 Windows 接口模拟用户操作，无内存读取、无文件修改 | Simulates user input via Windows API — no memory reads, no file modifications*

---

## ⚠️ 免责声明 | Disclaimer

本软件开源、免费，仅供个人学习与交流使用。因使用本软件而产生的任何问题，均与本项目及开发者无关。

*This software is open-source and free, for personal learning only. Use at your own risk.*

---

## 功能 | Features

### 批量强化声骸 | Batch Echo Enhancement

自动将背包中的 0 级声骸强化至满级并调谐，按配置规则判断保留或丢弃。符合条件自动上锁，不符合自动弃置。

*Automatically enhances level-0 echoes to max, evaluates by configurable rules, locks good ones and discards bad ones.*

**使用步骤 | Usage:**
1. 游戏内 `B` → 背包声骸页 → 按等级升序排序 → 过滤目标套装
2. 在 **套装配置 | Sets** tab 中确认该套装的词条与权重
3. 在 **批量强化声骸** tab 中选择策略和套装，启动

---

### 强化策略 | Enhancement Strategies

#### 渐进式 | Progressive（默认）

不达标立即丢弃，**避免浪费材料**:

| 阶段 | 条件 | 不达标处理 |
|:--:|------|------|
| Lv5 | 首条必须在套装预期词条中 | 直接丢弃 |
| Lv10 | 不做判断 | — |
| Lv15 | 累积得分 ≥ 1.5 | 丢弃止损 |
| Lv20 | 累积得分 ≥ 2.25 | 丢弃止损 |
| Lv25 | 累积得分 ≥ 3.75 | 丢弃；达标上锁 |

#### 传统 | Traditional

满级后一次性判断：必须有双爆 / 首条阈值 / 双爆总计 / 有效词条数量 / 第一条必须有效。

---

### 评分系统 | Scoring System

**均值归一化**: 单词条得分 = `档位值 / 该词条全部档位的均值 × 权重`。无效词条不计入(0分)。

*Mean-normalized: `tier value / mean of all tiers × weight`. Invalid stats = 0.*

```
暴击均值 8.4%: 最低 6.3→0.75 | 最高 10.5→1.25
单条范围 0.75~1.25 | 5词条总分 3.75~6.25
```

---

### 套装配置 | Set Config (EchoConfigTab)

独立的 PySide6 配置面板，直接读写 `assets/echo_set_templates.json`:

| 操作 | 说明 |
|------|------|
| 勾选 | 该词条为有效词条 |
| 权重 | 评分时的乘数（0 = 无效） |
| 切换套装 | 自动加载该套装的勾选和权重 |
| 保存 | 将当前修改写入 JSON |
| 导出 | 弹出文件保存框，导出 JSON 副本 |
| 导入 | 弹出文件选择框，导入 JSON 模板（旧文件自动备份 .bak） |
| 恢复默认 | 重置为项目自带的默认模板 |

套装数量由 JSON 文件即时决定，不硬编码。

*Set count is determined by the JSON file in real time, not hardcoded.*

---

### 批量修改声骸主属性 | Batch Main Stat Change

自动将声骸主属性修改为目标属性（数据重构）。支持 攻击/暴击伤害/暴击/生命/防御/共鸣效率/六属性伤害加成。

---

## 运行环境 | Requirements

- **OS:** Windows
- **Python:** 3.12
- **Resolution:** 16:9 (min 1600x900)
- **Game language:** 简体中文 / 繁體中文
- **FPS:** Stable 60

## 从源码运行 | Run

```bash
pip install -r requirements.txt --upgrade
python main.py        # ok-script 原版 GUI
python main_debug.py  # Debug (显示识别框)
python mainui.py      # ⚠️ 自定义 UI (开发中)
```

---

## 项目结构 | Project Structure

```
ww-echo/
├── main.py / main_debug.py         # ok-script 入口
├── mainui.py                       # 自定义 UI 入口 (开发中)
├── config.py                       # 配置
├── ui/                             # 自定义 UI 模块
├── src/
│   ├── echo_stats.py               # 词条档位 + 评分工具
│   ├── echo_set_templates.py       # JSON 模板加载 & 校验
│   ├── Labels.py                   # 模板匹配标签枚举
│   ├── globals.py                  # 全局状态
│   ├── gui/
│   │   └── EchoConfigTab.py        # 套装配置面板 (自定义)
│   ├── scene/WWScene.py            # 场景缓存
│   └── task/
│       ├── EnhanceEchoTask.py      # ⭐ 批量强化声骸
│       ├── ChangeEchoTask.py       # 批量修改主属性
│       ├── BaseEchoTask.py         # 任务基类
│       ├── image_utils.py          # 图像预处理
│       ├── process_feature.py      # 模板特征处理器
│       ├── WWOneTimeTask.py        # 一次性任务 mixin
│       └── MouseResetTask.py       # 鼠标防偏移
└── assets/
    ├── coco_annotations.json       # 模板匹配特征
    ├── echo_set_templates.json     # 套装模板 (导入/导出此文件)
    └── images/                     # 模板图片
```

## 依赖 | Dependencies

[ok-script](https://github.com/ok-oldking/ok-script) — 截图(WGC/BitBlt) + OCR(OnnxOCR) + 模板匹配 + 键鼠模拟(PostMessage)

## 致谢 | Credits

- [ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) — 原始项目
- [ok-oldking/ok-script](https://github.com/ok-oldking/ok-script) — 自动化框架
