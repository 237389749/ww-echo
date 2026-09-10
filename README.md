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

只读模式，**自动遍历整个背包**(每行6格网格) 截图+打分，生成 **HTML 报告**。

- 自动遍历: 点格 → 读右侧详情 → 按词条档位精确识别 → 评分 → 6 列补全防漏 → 自动下滑 → 左上数量上限/到底自动停止
- 词条过滤: 主属性/非词条数值(攻击150、生命1915、54 等) 自动剔除, 仅保留落在词条档位集合上的真词条(≤5条)
- 每个声骸: 截图 + 得分 + 判定（达标/待强化/不达标）
- 输出 `eval_report.html` + 截图文件夹，双击浏览器查看
- 不强化、不上锁、不丢弃 — 纯评估

### 云游戏 / 本地双模式 | Local / Cloud

在"设备设置"顶部切换运行模式（重启生效）：

- **本地客户端**(默认): 自动匹配 `UnrealWindow` 游戏窗口, 支持后台运行
- **云游戏**: 自动锁定标题含"鸣潮"的浏览器/云客户端窗口(无需手动选窗), 前台真实键鼠操作
  - 用法: 云游戏页面 **F11 全屏**保持前台可见 → 启动程序自动连接 → 点"开始"(程序自动切前台) → 任务运行中勿最小化游戏
  - 需以**管理员身份**运行(前台键鼠注入)

---

## 运行环境 | Requirements

- **OS:** Windows
- **Python:** 3.12
- **Resolution:** 本地 16:9 (min 1600x900)；云游戏 16:9 / 16:10 均可
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
| 设备设置 | 运行模式(本地/云游戏)、选择窗口、截图方式、交互方式、月卡、热键 |
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
│       ├── EnhanceEchoTask.py      # 强化 + 评估(自动遍历 v2)
│       ├── BaseEchoTask.py         # 任务基类
│       └── ...
└── assets/
    ├── echo_set_templates.json     # 套装模板 (保存/导入/导出)
    ├── coco_annotations.json       # 模板匹配特征
    └── images/                     # 模板图片
```

## 依赖 | Dependencies

- [ok-script](https://github.com/ok-oldking/ok-script) — 截图 + OCR + 模板匹配 + 键鼠模拟（仅用后端，GUI 自建）
- `pynput` — 云游戏模式前台键鼠注入（点击层必需）

> ⚠️ ok-script 装在 site-packages，本项目对它有 4 处行为补丁(4 个文件, 标注 `[ww-echo patch]`)；
> 另在 `ui/run_tab.py` 有 1 处本项目内改动。升级 ok-script 后需重打 site-packages 补丁，清单见 `CLAUDE.md`。

---

## TODO

- [ ] **锁2追3机制**: 满级5词条中 ≥2条在自身top4以上 → 锁定重铸其余。T3时如已丢1词条, 检查剩余有效是否≥2条且top4。
- [ ] 评估报告增加「重铸建议」列
- [ ] **副C/奶双逻辑评价**: 声骸同时按「输出维度」(套装权重)与「奶/辅助维度」(攻击%2.0 / 共效1.5 / 生命%1.5 / 攻击0.5 / 生命0.5)打分, 取最高值判定达标并标注推荐定位(副C/奶)。应用范围倾向仅辅助/万能套(轻云/回光/高天共奏/无惧浪涛/不绝余音)

## 致谢 | Credits

- [ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves)
- [ok-oldking/ok-script](https://github.com/ok-oldking/ok-script)
