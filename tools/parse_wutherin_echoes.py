# -*- coding: utf-8 -*-
"""解析 wuther.in 声骸列表页(用户浏览器保存的 html)，生成各套装的 4C/3C/1C 声骸清单，
写回 assets/echo_set_templates.json 的 `_echoes` 字段，并生成核对表 echoes_check.md。

用法:
    python tools/parse_wutherin_echoes.py <保存的页面.html> [--dry]

原理:
    - 筛选按钮: <img ...IconElementAttri{ICON}.webp...><span class="truncate">套装名</span>
      → 建立 图标名 → 套装名 对照(本工具模板的套装名以模板为准, 未匹配的忽略并列出)
    - 声骸卡片: <a class="group block overflow-hidden..." href="/zh/echo/{ID}/">…</a>
      卡内: 名字 <p class="truncate...">名</p>; 图标 IconElementAttri*.webp(=该声骸所属套装);
      COST 角标 <div ...>C{1,3,4}</div>
    - 一个声骸可属多个套装(多图标) → 分别计入每个套装

注意: wuther.in robots.txt 对 AI 爬虫 Disallow; 本脚本只解析用户已保存到本地的页面文件。
"""
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
# 允许从 tools/ 目录运行时 import src.* (项目根加入 sys.path)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEMPLATE = os.path.join('assets', 'echo_set_templates.json')
CHECK_MD = 'echoes_check.md'
COST_KEYS = ('4c', '3c', '1c')


def parse(html: str):
    """返回 (icon2set, 声骸列表[{id,name,cost,icons}])"""
    icon2set = dict(re.findall(
        r'IconElementAttri([A-Za-z]+)\.webp[^>]*><span class="truncate">([^<]+)</span>', html))
    cards = re.findall(
        r'<a class="group block overflow-hidden[^"]*"[^>]*href="/zh/echo/(\d+)/"[^>]*>(.*?)</a>',
        html, re.S)
    rows = []
    for eid, c in cards:
        m_name = re.search(r'<p class="truncate[^"]*">([^<]+)</p>', c)
        m_cost = re.search(r'tabular-nums text-white">C(\d)</div>', c)
        name = m_name.group(1) if m_name else ''
        if not name or name == '?':
            continue
        rows.append({'id': eid, 'name': name,
                     'icons': re.findall(r'IconElementAttri([A-Za-z]+)\.webp', c),
                     'cost': m_cost.group(1) if m_cost else '?'})
    return icon2set, rows


def aggregate(icon2set, rows):
    """按 id 聚合声骸 → 套装清单 {套装名: {'4c': [...], '3c': [...], '1c': [...]}}"""
    by_id = {}
    for r in rows:
        e = by_id.setdefault(r['id'], {'name': r['name'], 'cost': r['cost'], 'sets': set()})
        for ic in r['icons']:
            if icon2set.get(ic):
                e['sets'].add(icon2set[ic])
    agg = {}
    for e in by_id.values():
        for s in e['sets']:
            agg.setdefault(s, {k: set() for k in COST_KEYS})[e['cost'] + 'c'].add(e['name'])
    return agg, by_id


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--dry' in sys.argv
    if not args:
        print(__doc__)
        return 1
    html = open(args[0], encoding='utf-8', errors='ignore').read()
    icon2set, rows = parse(html)
    if not icon2set or not rows:
        print('[ERROR] 未解析到数据, 确认是 wuther.in 声骸列表页(渲染后保存)')
        return 1
    agg, by_id = aggregate(icon2set, rows)
    print(f'解析: 图标-套装 {len(icon2set)} 组 | 声骸卡片 {len(rows)} | 去重声骸 {len(by_id)}')

    data = json.load(open(TEMPLATE, encoding='utf-8'))
    # 只覆盖"页面解析到数据"的套装; 页面无数据时保留现有 _echoes(不抹掉用户手动补的)
    hit, miss_data, kept = 0, [], []
    set2icon = {s: ic for ic, s in icon2set.items()}
    for name in data['sets']:
        a = agg.get(name)
        if a:
            data['sets'][name]['_echoes'] = {k: sorted(a.get(k, [])) for k in COST_KEYS}
            hit += 1
        else:
            miss_data.append(name)
            if any((data['sets'][name].get('_echoes') or {}).values()):
                kept.append(name)      # 保留用户手补的数据
    # 全部套装补/更新 _icon
    for name, e in data['sets'].items():
        if set2icon.get(name):
            e['_icon'] = set2icon[name]
    # 页面里模板没有的套装 → 作为新套装加入(通用默认权重 + 解析清单)
    from src.echo_stats import DEFAULT_WEIGHTS  # noqa: 仅脚本用
    extra = sorted({s for s in icon2set.values() if s not in data['sets']})
    for s in extra:
        a = agg.get(s, {})
        entry = dict(DEFAULT_WEIGHTS)
        entry['_echoes'] = {k: sorted(a.get(k, [])) for k in COST_KEYS}
        entry['_icon'] = set2icon.get(s, '')
        data['sets'][s] = entry
    print(f'写回 _echoes: {hit} 套 | 页面无数据但保留手动值: {kept} | 仍缺: '
          f'{[n for n in miss_data if n not in kept]} | 新增套装: {extra}')
    if not dry:
        json.dump(data, open(TEMPLATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        # 核对表
        lines = ['# 套装声骸清单核对表', '',
                 '- 来源: 解析 wuther.in 声骸列表页(本地保存) → `assets/echo_set_templates.json` 的 `_echoes`',
                 f'- 页面无数据但保留手动值: {kept}', f'- 新增套装: {extra}', '',
                 '| 套装 | 图标 | 4C | 3C | 1C |', '|---|---|---|---|---|']
        for name in data['sets']:
            e = data['sets'][name]['_echoes']
            lines.append(f"| {name} | {data['sets'][name].get('_icon', '') or '—'} "
                         f"| {'/'.join(e['4c']) or '—'} | {'/'.join(e['3c']) or '—'} | {'/'.join(e['1c']) or '—'} |")
        no_icon = sorted({b['name'] for b in by_id.values() if not b['sets']})
        lines += ['', f'## 无图标未映射声骸({len(no_icon)})', '', '、'.join(no_icon)]
        open(CHECK_MD, 'w', encoding='utf-8').write('\n'.join(lines))
        print(f'已写入 {TEMPLATE} 与 {CHECK_MD}')
    else:
        print('(--dry 未写文件)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
