"""用 `logs/eval_debug/<时间戳>/` 的既有素材**离线重放一次评估** → 生成可直接打开的报告。

素材(无需游戏, 也无需 OCR 引擎):
- 详情文本: `image_report.md` —— 对 `<tag>_detail.png` 的 OCR 转录(已人工清洗前缀)
- 套装图标: `<tag>_full.png` 的详情面板图标区 → `src/echo_icon_match` 识别(低置信回退名字候选)

复用线上同一份实现: `_normalize_stat` 词条名容错 / 前 2 行主属性排除 + `is_stat_match` 离散档位过滤 /
`compute_weighted_score` + `judge_echo` 评分判定 / `dedup_key` 去重(名字+档位值) / 0 级不入报告 /
`_build_eval_html` 渲染。**改评分、判定或报告渲染后, 用它可以不开游戏就拿到一份真实数据的报告核对。**

    python tools/offline_eval_report.py                 # 用 logs/eval_debug/ 下最新目录
    python tools/offline_eval_report.py <debug目录>

产物(与线上 UI 的落盘约定一致, 均已在 .gitignore 中):
    eval_report.html          报告(截图按相对路径 eval_screenshots/ 引用)
    eval_screenshots/*.png    详情面板截图

差异: 详情文本来自转录文件而非实时 OCR, 属性名/数值比线上更干净(线上会偶有错字), 故本工具
适合验证"逻辑与渲染", 不能替代真机核对 OCR 容错。
"""

import argparse
import glob
import os
import re
import sys
import time

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.echo_stats import get_mean, is_stat_match, snap_to_tier                     # noqa: E402
from src.echo_set_templates import get_expected_stats, get_set_by_echo, get_sets_by_echo  # noqa: E402
from src.echo_icon_match import match_icon                                           # noqa: E402
from src.task.EnhanceEchoTask import EnhanceEchoTask, parse_number                   # noqa: E402
from ui.run_tab import _build_eval_html                                              # noqa: E402

SS_BOX = (0.665, 0.07, 0.995, 0.65)     # 详情面板截图区(与 evaluate_only 一致)

task = EnhanceEchoTask.__new__(EnhanceEchoTask)      # 只借用纯计算方法, 不跑 __init__
task.config = {'当前套装': '通用'}


def latest_debug_dir() -> str:
    dirs = sorted(glob.glob(os.path.join(ROOT, 'logs', 'eval_debug', '*')), key=os.path.getmtime)
    return dirs[-1] if dirs else ''


def parse_report(path: str) -> dict:
    """image_report.md → {tag: [详情文字行...]}"""
    text = open(path, encoding='utf-8').read()
    out = {}
    for m in re.finditer(r'^### (\S+)\n(.*?)(?=^### |\Z)', text, re.S | re.M):
        body = re.search(r'\*\*【详情文字】\*\*\n((?:- .*\n)+)', m.group(2))
        if body:
            out[m.group(1)] = [ln[2:].strip() for ln in body.group(1).strip().split('\n')]
    return out


def split_rows(lines: list) -> tuple:
    """复刻 read_detail: 名字=首个中文行; 丢掉 `+25`/`COST 4`/`Z | C` 等面板非属性行; 属性行取 `名 | 值`。"""
    name, props = '', []
    for ln in lines:
        if not ln or ln.startswith('+') or ln.startswith('COST') or ln.startswith('Z'):
            continue
        if ln.startswith('声骸技能'):
            break
        if '|' in ln:
            # 按**最后一个** | 切分: 转录里属性图标被误读成前缀且与真名用 | 相连
            # (如 `器 | 暴击伤害 | 15.0%` / `众 | 共鸣效率 | 8.4%`), 整个前缀保留给
            # _normalize_stat 的逐字白名单清洗(线上 OCR 同样是前缀污染, 用同一套清洗)
            head, _, tail = ln.rpartition('|')
            props.append((head.strip(), tail.strip()))
        elif not name and re.search(r'[\u4e00-\u9fff]', ln):
            name = ln
    return name, props


def dedup_key(name: str, props: list) -> str:
    """与 evaluate_only.dedup_key 一致: 名字 + 全行档位值, 防滚动重叠(每屏与上屏重叠~1行)重复记录。"""
    parts = [name]
    for raw_n, v_str in props:
        norm = EnhanceEchoTask._normalize_stat(raw_n, v_str)
        v = parse_number(v_str)
        tier_v = snap_to_tier(norm, v)
        parts.append(f'{norm}={tier_v if tier_v is not None else round(v, 2)}')
    return '|'.join(parts)


def pick_set(echo_name: str, frame) -> tuple:
    """复刻 resolve_set_name(评估时 config 套装=通用): 图标优先 → 名字候选 → 通用。"""
    icon_set, score, margin = match_icon(frame)
    cands = get_sets_by_echo(echo_name)
    if icon_set:
        return icon_set, 'icon', score
    return (get_set_by_echo(echo_name, prefer='通用') or '通用'), ('name' if cands else 'default'), score


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('debug_dir', nargs='?', default='', help='logs/eval_debug/<时间戳>')
    args = ap.parse_args()
    dbg = args.debug_dir or latest_debug_dir()
    if not dbg or not os.path.isdir(dbg):
        print(f'找不到 debug 数据目录: {dbg or "logs/eval_debug/*"} (先跑一次评估模式生成)')
        return 2
    frames = sorted(glob.glob(os.path.join(dbg, '*_full.png')))
    report_path = os.path.join(dbg, 'image_report.md')
    if not os.path.exists(report_path):
        print(f'缺少详情文本 {report_path}(image_report.md 是对 *_detail.png 的 OCR 转录)')
        return 2
    report = parse_report(report_path)
    print(f'素材: {len(frames)} 张整帧, {len(report)} 组详情文本 from {dbg}')

    ss_dir = os.path.join(ROOT, 'eval_screenshots')
    os.makedirs(ss_dir, exist_ok=True)
    for old in glob.glob(os.path.join(ss_dir, '*.png')):
        os.remove(old)

    seen, results, log = set(), [], []
    n_zero = n_dup = 0
    src_stat, set_stat, verdict_stat = {}, {}, {}

    for path in frames:
        tag = os.path.basename(path).replace('_full.png', '')
        lines = report.get(tag)
        if not lines:
            continue
        name, props = split_rows(lines)
        key = dedup_key(name, props)
        if key in seen:
            n_dup += 1
            continue
        seen.add(key)

        stats = []
        for raw_n, v_str in props[2:]:        # 前 2 行固定为主属性 → 排除
            norm = EnhanceEchoTask._normalize_stat(raw_n, v_str)
            val = parse_number(v_str)
            if norm and is_stat_match(norm, val):
                stats.append((norm, val))
        stats = stats[:5]
        if not stats:                          # 0 级(无词条): 不入报告(与线上一致)
            n_zero += 1
            continue

        frame = cv2.imread(path)
        set_name, set_src, s1 = pick_set(name, frame)
        tier = len(stats)
        valid_stats = get_expected_stats(set_name if set_name != '通用' else None)
        score, details = task.compute_weighted_score(
            [(n, str(v)) for n, v in stats], valid_stats, set_name=set_name)
        (verdict, verdict_cn), threshold, keep = task.judge_echo(set_name, tier, score, stats)
        if keep:
            verdict, verdict_cn = 'keep', '建议保留'

        idx = len(results) + 1
        ss_name = f'eval_{idx:03d}_{verdict}_{score:.1f}.png'
        h, w = frame.shape[:2]
        cv2.imwrite(os.path.join(ss_dir, ss_name),
                    frame[int(SS_BOX[1] * h):int(SS_BOX[3] * h), int(SS_BOX[0] * w):int(SS_BOX[2] * w)])
        results.append({
            "index": idx, "name": name, "tier": tier, "score": round(score, 2),
            "threshold": threshold, "verdict": verdict, "verdict_cn": verdict_cn,
            "set": set_name, "set_src": set_src, "screenshot": ss_name,
            "stats": [{"name": n, "value": float(v), "detail": d,
                       "ratio": round((snap_to_tier(n, v) or 0) / (get_mean(n) or 1), 3)}
                      for (n, v), d in zip(stats, details)],
        })
        src_stat[set_src] = src_stat.get(set_src, 0) + 1
        set_stat[set_name] = set_stat.get(set_name, 0) + 1
        verdict_stat[verdict] = verdict_stat.get(verdict, 0) + 1
        log.append(f'{tag} {name} | {set_name}({set_src}, s1={s1:.3f}) | {tier}词条 {score:.1f} {verdict_cn}')

    data = {
        "set": "通用",
        "total": len(results),
        "evaluated_at": f'{time.strftime("%Y-%m-%d %H:%M:%S")} (离线重放 {os.path.basename(dbg)})',
        "results": results,
    }
    html_path = os.path.join(ROOT, 'eval_report.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(_build_eval_html(data))

    print(f'\n入报告 {len(results)} 只 | 跳过 0级 {n_zero} / 重复(滚动重叠) {n_dup}')
    print('判定分布:', verdict_stat)
    print('套装来源:', src_stat)
    print('套装分布:', dict(sorted(set_stat.items(), key=lambda kv: -kv[1])))
    print(f'\n报告: {html_path}\n截图: {ss_dir}')
    print('\n--- 逐条(前 25) ---')
    for line in log[:25]:
        print(' ', line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
