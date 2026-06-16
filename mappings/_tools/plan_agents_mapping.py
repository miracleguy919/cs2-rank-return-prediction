#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 mhn 智能匹配 + 生成 agent mapping 计划"""
import json
import re
import sys
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

MAPS = Path(__file__).parent.parent.parent / 'mappings'

# 17 个手录探员 (itemid -> 项目中文)
existing = {
    '11431': '爱娃',
    '11437': '医生',
    '11458': '准备就绪的列赞',
    '12514': '老K',
    '12592': '萨利',
    '12669': '达里尔迈阿密',
    '13569': '达里尔穷鬼',
    '12720': '飞贼',
    '11488': '教授',
    '12820': '小凯夫',
    '12598': '指挥官梅 "极寒" 贾米森',
    '11419': '马克西姆',
    '11457': '弹弓凤凰战士',
    '11454': '迈克·赛弗斯',
    '12846': '街头士兵',
    '13811': '达比西',
    '13819': '准尉',
}

zh = json.load(open(MAPS / 'bymykel_zh_agents.json', encoding='utf-8'))

# 项目内中文名 -> bymykel mhn 的手录映射 (从 AGENTS.md §5.1 + bymykel def_index 推断)
manual_mhn_map = {
    '爱娃': 'Special Agent Ava | FBI',
    '医生': "'The Doctor' Romanov | Sabre",
    '准备就绪的列赞': 'Rezan The Ready | Sabre',
    '老K': 'Number K | The Professionals',
    '萨利': 'Getaway Sally | The Professionals',
    '达里尔迈阿密': 'Sir Bloody Miami Darryl | The Professionals',
    '达里尔穷鬼': 'Bloody Darryl The Strapped | The Professionals',  # 注: 不是 Loudmouth!
    '飞贼': 'Safecracker Voltzmann | The Professionals',
    '教授': 'Prof. Shahmat | Elite Crew',
    '小凯夫': 'Little Kev | The Professionals',
    '指挥官梅 "极寒" 贾米森': "Cmdr. Mae 'Dead Cold' Jamison | SWAT",
    '马克西姆': 'Maximus | Sabre',
    '弹弓凤凰战士': 'Slingshot | Phoenix',
    '迈克·赛弗斯': 'Michael Syfers  | FBI Sniper',
    '街头士兵': 'Street Soldier | Phoenix',
    '达比西': 'Col. Mangos Dabisi | Guerrilla Warfare',
    '准尉': 'Aspirant | Gendarmerie Nationale',
}

# 找每个 existing 在 bymykel 里的实际条目
bymykel_by_mhn = {a['market_hash_name']: a for a in zh}

print('===== 项目 17 个手录探员 vs bymykel =====')
print(f'{"itemid":<8} {"项目中文":<25} {"bymykel mhn":<45} {"def_idx"}')
print('-' * 100)
matched_count = 0
for lid, proj_cn in existing.items():
    mhn = manual_mhn_map.get(proj_cn)
    bk = bymykel_by_mhn.get(mhn) if mhn else None
    if bk:
        print(f'  {lid:<8} {proj_cn:<25} {mhn:<45} {bk["def_index"]}')
        matched_count += 1
    else:
        print(f'  {lid:<8} {proj_cn:<25} {"<NOT IN BYMYKEL>":<45} ?')

print(f'\n匹配: {matched_count}/17')

# 列出 bymykel 中所有 63 个探员, 区分已收录 vs 新增
print('\n===== 探员覆盖统计 =====')
print(f'bymykel 总探员: {len(zh)}')
print(f'项目已收录 (17) + 新增 ({len(zh) - 17}) = {len(zh)} 全部')

# 按阵营/稀有度统计
team_count = {}
rarity_count = {}
for a in zh:
    t = a['team']['name']
    r = a['rarity']['name']
    team_count[t] = team_count.get(t, 0) + 1
    rarity_count[r] = rarity_count.get(r, 0) + 1

print(f'\n阵营: T {team_count.get("T", 0)} + CT {team_count.get("CT", 0)}')
print(f'稀有度: 大师 {rarity_count.get("大师", 0)} / 非凡 {rarity_count.get("非凡", 0)} / 卓越 {rarity_count.get("卓越", 0)} / 高级 {rarity_count.get("高级", 0)}')

# 输出 mapping 计划
print('\n===== 生成 agents_mapping_plan.json =====')
plan = {
    'source': 'bymykel/zh-CN',
    'total': len(zh),
    'team_distribution': team_count,
    'rarity_distribution': rarity_count,
    'agents': []
}

# 已有 itemid (17 个) 保留; 46 个新增按 mhn 排序后从 13820 起分配
existing_mhns = set()
for proj_cn, mhn in manual_mhn_map.items():
    if mhn in bymykel_by_mhn:
        existing_mhns.add(mhn)

# 已收录 (用原 itemid)
existing_id_by_mhn = {}
for lid, proj_cn in existing.items():
    mhn = manual_mhn_map.get(proj_cn)
    if mhn:
        existing_id_by_mhn[mhn] = int(lid)

# 排序
sorted_zh = sorted(zh, key=lambda x: (x['team']['name'], -{'大师': 4, '非凡': 3, '卓越': 2, '高级': 1}.get(x['rarity']['name'], 0), x['market_hash_name']))

next_id = 13820
for a in sorted_zh:
    mhn = a['market_hash_name']
    if mhn in existing_id_by_mhn:
        lid = existing_id_by_mhn[mhn]
        is_new = False
    else:
        lid = next_id
        next_id += 1
        is_new = True

    plan['agents'].append({
        'local_id': lid,
        'is_new': is_new,
        'def_index': int(a['def_index']),
        'market_hash_name': mhn,
        'name_en': next((e['name'] for e in json.load(open(MAPS / 'bymykel_en_agents.json', encoding='utf-8')) if e['market_hash_name'] == mhn), ''),
        'name_zh': a['name'],
        'rarity_zh': a['rarity']['name'],
        'team': a['team']['name'],
        'collection': a['collections'][0]['name'] if a['collections'] else '',
    })

(MAPS / 'agents_mapping_plan.json').write_text(
    json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8'
)
print(f'  写入: agents_mapping_plan.json ({len(plan["agents"])} 条)')

# 统计
new_agents = [a for a in plan['agents'] if a['is_new']]
print(f'  新增: {len(new_agents)} 条')
print(f'  保留: {len(plan["agents"]) - len(new_agents)} 条')
print(f'  local_id 范围: {min(a["local_id"] for a in plan["agents"])} ~ {max(a["local_id"] for a in plan["agents"])}')

# 展示前 10 条
print('\n===== 前 10 条 plan =====')
for a in plan['agents'][:10]:
    is_new = '[新]' if a['is_new'] else '[旧]'
    print(f'  {is_new} {a["local_id"]:<6} {a["team"]} {a["rarity_zh"]:<5} {a["market_hash_name"][:40]:<42} {a["name_zh"][:30]}')
