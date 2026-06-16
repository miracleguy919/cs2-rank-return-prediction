#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_agents_integration.py
=============================
验证探员整合的完整性。

检查项:
  1. agents_meta.json 存在且含 63 条
  2. itemid.txt 探员段条目数 == 63
  3. market_map 含所有 63 个探员 mhn
  4. all_items_cache 中探员条目带 name_zh
  5. 17 个手录 ID 全部保留
  6. 46 个新 ID 全部唯一且不冲突
  7. 中文字段无空值
"""
import json
import re
import sys
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

MAPS = Path(__file__).parent.parent / 'mappings'

results = []
def check(label, ok, detail=''):
    icon = '[OK]  ' if ok else '[FAIL]'
    print(f'  {icon} {label}', end='')
    if detail:
        print(f' :: {detail}')
    else:
        print()
    results.append((label, ok, detail))


def main():
    print('=' * 70)
    print('verify_agents_integration.py')
    print('=' * 70)

    # 1. agents_meta.json
    print('\n[1] agents_meta.json 检查...')
    meta_path = MAPS / 'agents_meta.json'
    check('agents_meta.json 存在', meta_path.exists())
    if not meta_path.exists():
        return
    meta = json.load(open(meta_path, encoding='utf-8'))
    check('含 63 条探员', meta['total'] == 63, f'actual: {meta["total"]}')

    # 2. itemid.txt 探员段
    print('\n[2] itemid.txt 探员段检查...')
    lines = (MAPS / 'itemid.txt').read_text(encoding='utf-8').splitlines()
    in_agent = False
    agent_ids = []
    for line in lines:
        s = line.strip()
        if s == '//探员 1':
            in_agent = True
            continue
        if in_agent:
            # 探员段结束: 遇到其他 // 段标题 (//收藏品, //武库, //百战 等)
            if s.startswith('//'):
                # 排除自己加的说明行 (// 总数: ..., // 2026-...)
                if s.startswith('// 总数') or s.startswith('// 2026-') or s.startswith('// 探员总数'):
                    continue
                # 真正的段标题, 退出
                break
            if s:
                m = re.match(r'^(\d+)[：:]\s*(.+)$', s)
                if m:
                    agent_ids.append((int(m.group(1)), m.group(2).strip()))
    check('探员段 63 条', len(agent_ids) == 63, f'actual: {len(agent_ids)}')

    # 3. market_map
    print('\n[3] itemid_market_map.json 检查...')
    market = json.load(open(MAPS / 'itemid_market_map.json', encoding='utf-8'))
    plan = json.load(open(MAPS / 'agents_mapping_plan.json', encoding='utf-8'))
    plan_mhns = {a['market_hash_name'] for a in plan['agents']}
    market_mhns = set(market.values())
    check('plan 63 mhn 全部在 market_map', plan_mhns.issubset(market_mhns), f'plan: {len(plan_mhns)} market: {len(market_mhns)}')

    # 4. all_items_cache 探员条目
    print('\n[4] all_items_cache.json 探员条目检查...')
    cache = json.load(open(MAPS / 'all_items_cache.json', encoding='utf-8'))
    cache_by_mhn = {c.get('marketHashName'): c for c in cache}
    cache_agent_count = 0
    cache_with_zh = 0
    for mhn in plan_mhns:
        c = cache_by_mhn.get(mhn)
        if c and c.get('category_zh') == '探员':
            cache_agent_count += 1
            if c.get('name_zh'):
                cache_with_zh += 1
    check('cache 含 63 探员条目', cache_agent_count == 63, f'actual: {cache_agent_count}')
    check('cache 探员条目全部含 name_zh', cache_with_zh == 63, f'actual: {cache_with_zh}')

    # 5. 17 个手录 ID 保留
    print('\n[5] 17 个手录 ID 保留检查...')
    existing_ids = {11431, 11437, 11458, 12514, 12592, 12669, 13569, 12720,
                    11488, 12820, 12598, 11419, 11457, 11454, 12846, 13811, 13819}
    item_id_set = {lid for lid, _ in agent_ids}
    missing = existing_ids - item_id_set
    check('17 个手录 ID 全部保留', not missing, f'missing: {missing}')

    # 6. 46 个新 ID 唯一
    print('\n[6] 46 个新 ID 唯一性检查...')
    new_ids = [a['local_id'] for a in plan['agents'] if a['is_new']]
    check('46 个新 ID 无重复', len(new_ids) == len(set(new_ids)), f'{len(new_ids)}/{len(set(new_ids))}')

    # 与 17 个手录 ID 不冲突
    conflict = existing_ids & set(new_ids)
    check('46 个新 ID 与手录 ID 不冲突', not conflict, f'conflict: {conflict}')

    # 7. 中文字段无空值
    print('\n[7] 中文字段无空值检查...')
    empty_zh = 0
    for a in plan['agents']:
        if not a.get('name_zh') or not a.get('rarity_zh'):
            empty_zh += 1
    check('63 探员中文字段无空', empty_zh == 0, f'empty: {empty_zh}')

    # 8. market_map id 唯一性
    print('\n[8] market_map id 唯一性检查...')
    id_values = list(market.keys())
    check('market_map 无重复 id', len(id_values) == len(set(id_values)), f'{len(id_values)}/{len(set(id_values))}')

    # 总结
    print('\n' + '=' * 70)
    ok_count = sum(1 for _, ok, _ in results if ok)
    fail_count = sum(1 for _, ok, _ in results if not ok)
    print(f'  验证项: {len(results)}, PASS: {ok_count}, FAIL: {fail_count}')
    print('=' * 70)
    if fail_count > 0:
        print('FAIL 项:')
        for label, ok, detail in results:
            if not ok:
                print(f'  [FAIL] {label} :: {detail}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
