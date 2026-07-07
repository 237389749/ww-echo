# CLAUDE.md - WW Echo Enhance

声骸强化自动化工具，从 ok-ww 剥离，仅保留声骸强化/改主属性功能。

## 项目结构

```
ww-echo/
├── main.py              # 入口 (Release)
├── main_debug.py        # 入口 (Debug)
├── config.py            # 配置 (仅注册 Echo/ChangeEcho 任务)
├── src/
│   ├── globals.py       # 全局状态 (YOLO懒加载, 强化不用)
│   ├── Labels.py        # 模板匹配标签枚举
│   ├── scene/WWScene.py # 场景状态缓存
│   └── task/
│       ├── EnhanceEchoTask.py  # ⭐ 批量强化声骸
│       ├── ChangeEchoTask.py   # ⭐ 批量修改主属性
│       ├── BaseWWTask.py       # 基类 (含大量战斗代码, 逐步清理)
│       ├── WWOneTimeTask.py    # 一次性任务 mixin
│       └── MouseResetTask.py   # 鼠标防偏移
└── assets/
    ├── coco_annotations.json   # 模板匹配特征
    └── images/                 # 特征图片
```

## 依赖框架

基于 ok-script==1.0.159，提供:
- BaseTask: OCR、屏幕截图、键鼠模拟
- FindFeature: 模板匹配、特征检测
- GUI (PySide6 + qfluentwidgets)

## 强化流程

1. 玩家在背包声骸界面，按等级排序+过滤后启动
2. OCR 识别"培养" → 点击进入 → "阶段放入" → "强化并调谐"
3. OCR 读取副词条属性名+数值
4. 根据规则判断: 双爆/有效词条/数值阈值
5. 不符合 → Z弃置 + 截图; 符合 → C上锁 + 截图
6. 循环直到无0级声骸

## 注意事项

- 仅支持简体/繁体中文游戏语言
- 仅支持 16:9 分辨率
- 需 Windows (WGC/BitBlt 截图 + PostMessage 输入)
- 游戏需稳定 60 FPS
