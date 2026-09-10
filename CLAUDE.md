# CLAUDE.md — ww-echo 开发手册

鸣潮(云游戏/本地)声骸强化 + 评估工具。基于 ok-script(截图/OCR/模板匹配/键鼠后端) + 自建 PySide6 UI。
**本手册面向后续开发(含 AI 协作者)。演进历史与改动原因见 CHANGELOG.md, 使用说明见 README.md。**

## 工作准则(项目级)

- 动手前陈述假设与取舍; 有歧义先问, 不静默选
- 最小改动解决当前问题; 只改与请求相关的行; 不超前抽象
- 改出孤儿引用(import/变量/函数)须清理, 但不动预存在的死代码
- 本机 ok-script 在 site-packages 有 `[ww-echo patch]` 补丁, **改动/升级前先 grep 定位**, 详见下
- 坐标、OCR 区、滚动量等常量集中在 `EnhanceEchoTask.evaluate_only` 顶部注释, 调参先看那里

## 项目结构

```
mainui.py                 唯一入口(PySide6); 启动先按 QSettings run_mode 调 apply_run_mode 再 OK(config)
config.py                 全套 ok-script 配置 + MODE_LOCAL/MODE_CLOUD + apply_run_mode()
ui/                       7 tab; settings_tab 含"运行模式"(本地/云游戏)开关, 重启生效
src/echo_stats.py         词条档位表 _TIERS + snap_to_tier/get_mean/is_stat_match
src/echo_set_templates.py 31 套装 JSON 模板(词条/权重)
src/task/EnhanceEchoTask.py  强化(run) + 评估(evaluate_only v2 遍历, 核心)
src/task/BaseEchoTask.py  轻量基类(click 覆写/语言检测)
assets/echo_set_templates.json 套装配置存档
```

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
| 声骸网格 | (0.10,0.15)-(0.72,0.92) | 每行 6 格; 列距≈176px, 行距≈212px; `+xx` 强化等级角标在格右下 |
| 详情属性面板 | (0.70,0.30)-(0.985,0.615) | 主属性区+词条区混排, **勿用 y 硬切**, 用档位过滤(见下) |
| 左上声骸计数 | (0.02,0.02)-(0.25,0.09) | `声骸145/3000` → 上限做步数限制 |
| 滚动热区 | (0.52,0.5) 常用 | 鸣潮列表滚动有热区(光标需网格中右部); ≈8px/notch |

## 词条过滤规则(关键, 勿回退成区间判断)

详情 OCR 出的属性行 = 主属性区 + 真词条。主属性数值**可能落在词条档位区间内**(如低等级主属性 攻击54 ∈ [30,60])。
判定词条: `echo_stats.is_stat_match(name, value)` = 归一化名在 `_TIERS` 且数值 **≈ 档位集合中某档**(容差 0.8)。
区间判断会误收主属性; 必须离散匹配。词条最多 5 条。

## 评估遍历 v2 现状与约束

- 前置: 游戏已在**背包声骸列表界面**(无需预选)
- 流程: 网格 OCR `+xx` 角标 → 聚行 → 6 列基准(跨屏记忆 `col_centers`)补全缺列防漏 → 逐格点选 → 右侧详情 OCR → 档位过滤词条 → 评分/截图/记录
- 空格/未切换格**跳过继续**(不提前滚屏防漏真实格); 本屏无新内容才滚动 15 notches; 详情"0 词条"=到底; 左上数量上限兜底; 连续 3 次滚动无新格兜底
- 评估判定 = 得分 ≥ tier 阈值 {1:1.0, 2:2.0, 3:2.0, 4:2.5, 5:3.0}(不调 `check_echo_progressive`, 两套阈值会打架)
- **已知缺陷(原版 ok-ww 同款)**: 强化 `run()` 无"切下一只"推进, 依赖丢弃后游戏自动前移; 评估遍历在网格布局/字体变化时坐标常量需复核

## 已知坑

- `pynput` 是必需依赖(点击层运行时才 import, 缺库表现为"点击无反应")— 勿从 requirements 移除
- WGC 抓云游戏/浏览器窗口常黑屏 → cloud 锁定 BitBlt_RenderFull
- 200% 高 DPI 下固定 860x640 逻辑窗口会物理化超屏 → 初始 700x520 + 工作区 clamp/居中(`ui/main_window.py`)
- 云游戏 16:10 画面已跳过 16:9 校验; 若云平台带黑边渲染, UI 归一化位置会偏移(黑边校准未做)
