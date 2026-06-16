#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
finalize_agents.py
==================
读取 agents_mapping_plan.json 后写入映射三件套:
  - mappings/itemid.txt (//探员 1 段)
  - mappings/itemid_market_map.json
  - mappings/all_items_cache.json
  - mappings/agents_meta.json (新增, 探员专项元数据)

策略:
  - 17 个手录 ID 保留
  - 46 个新增从 13820 起分配
  - itemid.txt 探员段重写 (格式: "{id}：{name_zh}")
  - 幂等保护: 重跑不重复添加
"""
import json
import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = Path(__file__).parent.parent.parent
MAPS = ROOT / 'mappings'

AGENT_SECTION_HEADER = '//探员 1'


def main():
    print('=' * 70)
    print('finalize_agents.py - 写入探员到映射三件套')
    print('=' * 70)

    # 1. 加载 plan
    print('\n[1/7] 加载 plan...')
    plan = json.load(open(MAPS / 'agents_mapping_plan.json', encoding='utf-8'))
    print(f'  探员总数: {plan["total"]}')

    # 2. 备份
    print('\n[2/7] 备份现有文件...')
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    for fname in ['itemid.txt', 'itemid_market_map.json', 'all_items_cache.json']:
        src = MAPS / fname
        if src.exists():
            bak = MAPS / f'{fname}.bak_agent_{ts}'
            shutil.copy2(src, bak)
            print(f'  [BAK] {bak.name}')

    # 3. 重写 itemid.txt 探员段
    print('\n[3/7] 重写 itemid.txt 探员段...')
    itemid_path = MAPS / 'itemid.txt'
    lines = itemid_path.read_text(encoding='utf-8').splitlines()

    # 找探员段
    agent_start = None
    agent_end = None
    for i, line in enumerate(lines):
        if line.strip() == AGENT_SECTION_HEADER:
            agent_start = i
            # 探员段结束: 下一个 // 段
            for j in range(i + 1, len(lines)):
                if lines[j].strip().startswith('//'):
                    agent_end = j
                    break
            break

    if agent_start is None:
        print(f'  [ERROR] 找不到 {AGENT_SECTION_HEADER} 段')
        return
    print(f'  探员段: L{agent_start+1} ~ L{agent_end}')

    # 排序探员 (按 local_id 升序)
    sorted_agents = sorted(plan['agents'], key=lambda x: x['local_id'])

    # 构建新探员段
    new_agent_lines = [AGENT_SECTION_HEADER, f'// 总数: {len(sorted_agents)} (2026-06-02 bymykel zh 整合, 17 旧 + {len(sorted_agents)-17} 新)']
    for a in sorted_agents:
        lid = a['local_id']
        cn_name = a['name_zh']
        # 格式: "11431：爱娃特工" (从 bmykel name 取 | 前)
        short_name = cn_name.split('|')[0].strip() if '|' in cn_name else cn_name
        new_agent_lines.append(f'{lid}：{short_name}')

    # 替换探员段
    new_lines = lines[:agent_start] + new_agent_lines + lines[agent_end:]
    itemid_path.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
    print(f'  [WRITE] itemid.txt 探员段: {len(sorted_agents)} 条')

    # 4. 更新 market_map
    print('\n[4/7] 更新 market_map...')
    market_path = MAPS / 'itemid_market_map.json'
    market = json.load(open(market_path, encoding='utf-8'))

    added = 0
    for a in sorted_agents:
        lid = str(a['local_id'])
        mhn = a['market_hash_name']
        if lid not in market:
            market[lid] = mhn
            added += 1
    market_path.write_text(json.dumps(market, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  [WRITE] market_map: +{added} keys (总 {len(market)})')

    # 5. 更新 all_items_cache
    print('\n[5/7] 更新 all_items_cache...')
    cache_path = MAPS / 'all_items_cache.json'
    cache = json.load(open(cache_path, encoding='utf-8'))

    cache_by_mhn = {c.get('marketHashName'): c for c in cache}
    cache_added = 0
    cache_updated = 0

    for a in sorted_agents:
        mhn = a['market_hash_name']
        entry = cache_by_mhn.get(mhn)
        if entry is None:
            # 新增
            entry = {
                'name': a['name_en'],
                'marketHashName': mhn,
                'platformList': [],
                'name_zh': a['name_zh'],
                'rarity_zh': a['rarity_zh'],
                'team': a['team'],
                'def_index': a['def_index'],
                'collection': a['collection'],
                'category_zh': '探员',
                '_zh_source': 'bymykel/zh-CN',
            }
            cache.append(entry)
            cache_added += 1
        else:
            # 更新中文字段
            if not entry.get('name_zh'):
                entry['name_zh'] = a['name_zh']
                entry['rarity_zh'] = a['rarity_zh']
                entry['team'] = a['team']
                entry['def_index'] = a['def_index']
                entry['collection'] = a['collection']
                entry['category_zh'] = '探员'
                entry['_zh_source'] = 'bymykel/zh-CN'
                cache_updated += 1

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  [WRITE] cache: +{cache_added} 新增, ~{cache_updated} 更新 (总 {len(cache)})')

    # 6. 写 agents_meta.json
    print('\n[6/7] 写 agents_meta.json...')
    meta_path = MAPS / 'agents_meta.json'
    meta = {
        'source': 'bymykel/zh-CN + en',
        'fetch_date': datetime.now().strftime('%Y-%m-%d'),
        'total': len(sorted_agents),
        'team_distribution': plan['team_distribution'],
        'rarity_distribution': plan['rarity_distribution'],
        'agents': sorted_agents,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  [WRITE] agents_meta.json ({len(sorted_agents)} 条)')

    # 7. 备份 plan 也保留
    print('\n[7/7] 总结...')
    print(f'  itemid.txt 探员段: {len(sorted_agents)} 条 (17 旧 + {len(sorted_agents)-17} 新)')
    print(f'  market_map: +{added} keys')
    print(f'  cache: +{cache_added} 新增, ~{cache_updated} 更新')
    print(f'  备份: *.bak_agent_{ts}')

    # 展示前 10 条
    print('\n===== itemid.txt 探员段预览 (前 20 条) =====')
    for a in sorted_agents[:20]:
        is_new = '新' if a['is_new'] else '旧'
        print(f'  [{is_new}] {a["local_id"]:<6} {a["team"]} {a["rarity_zh"]:<5} {a["name_zh"][:35]}')

    print('=' * 70)


if __name__ == '__main__':
    main()
