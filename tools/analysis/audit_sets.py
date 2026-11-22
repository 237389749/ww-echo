r"""离线核对一次评估的**套装判定**（读评估 JSON，不需要游戏、不需要重跑）。

输入: 评估产物 JSON（「运行」页保存报告时同目录写的那份 `<报告名>.json`）。
输出: 控制台报告 ——
  ① 记录数 / 词条数分布 / 完全重复（用来核对"条数对不对"）
  ② `set_src` 分布（icon / hue / name / default），以及**多义但没被环色定下来**的记录清单
  ③ 每条记录的「名字候选 → 实际判定 + 环色」，并标出**判定落在候选里但不是首个**的（环色生效的证据）
  ④ 判定不在候选内的（应为 0，非 0 说明名字 OCR 或映射有问题）

支撑结论: 套装判定是否可解释、环色消歧覆盖多少、还有哪些仍靠名字猜。

用法:
    python tools/analysis/audit_sets.py eval_report.json
    python tools/analysis/audit_sets.py eval_report.json --verbose   # 逐条打印
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from src.echo_set_templates import get_sets_by_echo  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('json_path')
    ap.add_argument('--verbose', action='store_true', help='逐条打印套装判定')
    args = ap.parse_args()

    with open(args.json_path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get('results') or []
    print(f"记录数: {len(rows)}  (总表 set={data.get('set')}, 时间={data.get('evaluated_at')})")

    print(f"词条数分布: {dict(sorted(collections.Counter(len(r.get('stats') or []) for r in rows).items()))}")

    def sig(r):
        return (r.get('name'),
                tuple((s['name'], round(float(s['value']), 1)) for s in (r.get('stats') or [])),
                tuple((m['name'], round(float(m['value']), 1)) for m in (r.get('main_props') or [])))

    dups = [k for k, n in collections.Counter(sig(r) for r in rows).items() if n > 1]
    print(f"完全重复(名字+词条+主属性): {len(dups)} 组")

    src = collections.Counter(r.get('set_src') or 'default' for r in rows)
    print(f"set_src 分布: {dict(src)}")

    out_of_cands, multi_guessed, hue_decided = [], [], []
    for r in rows:
        name, picked = r.get('name', ''), r.get('set', '')
        cands = get_sets_by_echo(name)
        if cands and picked not in cands:
            out_of_cands.append((r.get('index'), name, picked, cands))
        if len(cands) > 1:
            if (r.get('set_src') or '') == 'hue':
                hue_decided.append(r)
            elif picked != cands[0]:
                multi_guessed.append((r.get('index'), name, picked, cands, r.get('badge_hue')))
    print(f"判定不在名字候选内: {len(out_of_cands)}  (应为 0)")
    for x in out_of_cands[:5]:
        print(f"    #{x[0]} {x[1]} → {x[2]} 候选={x[3]}")
    print(f"环色定下来的多义记录: {len(hue_decided)}")
    print(f"多义但判定≠候选首个(说明用了别的信号): {len(multi_guessed)}")
    for x in multi_guessed[:8]:
        print(f"    #{x[0]} {x[1]} → {x[2]} (候选 {x[3]}, 环色 {x[4]})")

    no_hue = [r for r in rows if r.get('badge_hue') is None]
    print(f"没有环色读数(badge_hue=None): {len(no_hue)} 条 —— 旧报告没有这个字段也正常")
    if args.verbose:
        print('--- 逐条 ---')
        for r in rows:
            cands = get_sets_by_echo(r.get('name', ''))
            print(f"#{r.get('index'):>3} {r.get('name')} | {r.get('set')}({r.get('set_src')},"
                  f" hue={r.get('badge_hue')}) | 候选={cands}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
