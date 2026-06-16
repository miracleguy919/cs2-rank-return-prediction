#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 weapons_meta 和 cache 的中文翻译结果"""
import json
import sys
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

MAPS = Path(__file__).parent.parent / 'mappings'

meta = json.load(open(MAPS / 'weapons_meta.json', encoding='utf-8'))
print(f'weapons_meta items: {len(meta["items"])}')
print('--- 武器样本 (前 5 条) ---')
for it in meta['items'][:5]:
    print(f'  pi={it["paint_index"]} name={it["name"]} name_zh={it.get("name_zh")} pattern_zh={it.get("pattern_zh")}')

with_zh = sum(1 for it in meta['items'] if it.get('pattern_zh'))
print(f'\n有 pattern_zh 的: {with_zh}/{len(meta["items"])}')

# 验证 cache
cache = json.load(open(MAPS / 'all_items_cache.json', encoding='utf-8'))
weapon_cache = [c for c in cache if c.get('paint_index') and c.get('category_zh')]
print(f'\ncache 中带 category_zh 的: {len(weapon_cache)}')

# 找一个 AK-47 | Redline 验证
for c in cache:
    if c.get('marketHashName') == 'AK-47 | Redline (Field-Tested)':
        print(f'\n  AK-47 | Redline (Field-Tested):')
        for k in ('name', 'name_zh', 'pattern_zh', 'rarity_zh', 'category_zh'):
            v = c.get(k, '?')
            print(f'    {k}: {v}')
        break
