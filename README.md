# ww-echo

基于图像识别的鸣潮声骸强化自动化工具。从 [ok-ww](https://github.com/ok-oldking/ok-wuthering-waves) 剥离声骸模块，基于 [ok-script](https://github.com/ok-oldking/ok-script) 的截图/OCR/键鼠能力，自建 PySide6 管理界面。

*An image-recognition-based Wuthering Waves echo enhancement tool with custom PySide6 UI.*

*通过 Windows 接口模拟用户操作，无内存读取、无文件修改*

---

## ⚠️ 免责声明

本软件开源、免费，仅供个人学习与交流使用。使用本软件产生的一切后果由使用者承担。

*This software is open-source and free, for personal learning only. Use at your own risk.*

---

## 功能 | Features

### 强化声骸 | Enhancement

自动将背包中的 0 级声骸强化至满级并调谐，按规则判断保留或丢弃。

- **渐进式**: 每级单独评估，不达标立即丢弃止损
- **传统**: 拉满后一次性判断
- **均值归一化评分**: 单词条=档位值÷均值×权重，带权重的词条当量评分
- **套装模板**: 31 个套装独立配置预期词条和权重，JSON 文件即保存即导入

### 评估声骸 | Evaluate

只读模式，遍历背包声骸截图+打分，生成 **HTML 报告**。

- 每个声骸: 截图 + 得分 + 判定（达标/待强化/不达标）
- 输出 `eval_report.html` + 截图文件夹，双击浏览器查看
- 不强化、不上锁、不丢弃 — 纯评估

---

## 运行环境 | Requirements

- **OS:** Windows
- **Python:** 3.12
- **Resolution:** 16:9 (min 1600x900)
- **Game language:** 简体中文 / 繁體中文
- **FPS:** Stable 60

## 运行 | Run

```bash
pip install -r requirements.txt --upgrade
python mainui.py
```

---

## UI 面板 | Tabs

| Tab | 功能 |
|-----|------|
| 设备设置 | 选择游戏窗口、截图方式、交互方式、月卡、热键 |
| 热键设置 | 游戏内技能按键配置 |
| 强化运行 | 模式选择(强化/评估)、策略、套装、启停、状态 |
| 套装配置 | 表格编辑套装词条&权重、导入/导出 JSON |
| 调试工具 | OCR 测试、截图预览、覆盖层开关、运行日志 |
| 开发者 | Run Code (Python 执行器)、模板列表 |
| 关于 | 版本信息、项目链接 |

---

## 强化策略 | Enhancement Strategies

### 渐进式 (默认) | Progressive

| 阶段 | 条件 | 不达标处理 |
|:--:|------|------|
| Lv5 | 首条得分 ≥ 1.0 | 丢弃 |
| Lv10 | 跳过 | — |
| Lv15 | 累积得分 ≥ 2.0 | 丢弃 |
| Lv20 | 累积得分 ≥ 2.5 | 丢弃 |
| Lv25 | 累积得分 ≥ 3.0 | 丢弃；达标上锁 |

未满级声骸: 先读已有词条做渐进判断，通过再继续强化。

### 传统 | Traditional

满级后一次性判断: 必须有双爆 / 首条阈值 / 双爆总计 / 有效词条数量 / 首条必须有效 / 可选评分。

---

## 评分系统 | Scoring

**均值归一化 + 权重**: 单词条 = `档位值 ÷ 该词条均值 × 权重`，无效词条 = 0 分。

```
暴击均值 8.4%, 权重 2.0:
  最低 6.3% → 6.3/8.4×2.0 = 1.50
  最高 10.5% → 10.5/8.4×2.0 = 2.50

默认权重: 暴击 2.0  爆伤 1.5  攻击% 1.0  攻击 0.5  共效 1.0
          套装专属加成 2.0  小生命/小防御 0.5
```

---

## 项目结构 | Structure

```
ww-echo/
├── mainui.py                       # 主入口
├── config.py                       # ok-script 配置
├── ui/                             # 自定义 PySide6 UI
│   ├── main_window.py / run_tab.py / set_config_tab.py
│   ├── settings_tab.py / hotkey_tab.py / debug_tab.py
│   └── about_tab.py / dev_tab.py
├── src/
│   ├── echo_stats.py               # 词条档位 + 评分工具
│   ├── echo_set_templates.py       # JSON 模板加载 & 校验
│   ├── Labels.py / globals.py      # 模板匹配 / 全局状态
│   └── task/
│       ├── EnhanceEchoTask.py      # 强化 + 评估
│       ├── BaseEchoTask.py         # 任务基类
│       └── ...
└── assets/
    ├── echo_set_templates.json     # 套装模板 (保存/导入/导出)
    ├── coco_annotations.json       # 模板匹配特征
    └── images/                     # 模板图片
```

## 依赖 | Dependencies

[ok-script](https://github.com/ok-oldking/ok-script) — 截图 + OCR + 模板匹配 + 键鼠模拟（仅用后端，GUI 自建）

## 致谢 | Credits

- [ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves)
- [ok-oldking/ok-script](https://github.com/ok-oldking/ok-script)
