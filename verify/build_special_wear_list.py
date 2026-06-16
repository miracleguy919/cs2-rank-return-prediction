#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_special_wear_list.py
===========================
扫描 weapons_meta.json, 找出所有 max_float < 0.45 的 Battle-Scarred 条目
(意味着 BS 磨损的 float 范围 (0.45, max_float) 不存在, 这些条目真正不存在 BS 磨损)

输出: mappings/special_wear_skins.json
"""
import json
import sys
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = Path(__file__).parent.parent
MAPS = ROOT / 'mappings'

# BS 磨损的 float 范围是 (0.45, 1.0)
# 如果 max_float < 0.45, 则该皮肤没有 BS 磨损
BS_THRESHOLD = 0.45

wm = json.load(open(MAPS / 'weapons_meta.json', encoding='utf-8'))

# market_map 用来获取 mhn
market_map = json.load(open(MAPS / 'itemid_market_map.json', encoding='utf-8'))
market_by_lid = {int(k): v for k, v in market_map.items()}

results = []
all_bs_items = []
for item in wm.get('items', []):
    max_float = item.get('max_float', 1.0)
    name_zh = item.get('name_zh', item.get('name', ''))
    pattern_zh = item.get('pattern_zh', '')

    for wv in item.get('wear_variants', []):
        wear_en = wv.get('wear_en', '')
        if wear_en == 'Battle-Scarred':
            lid = str(wv.get('local_id'))
            all_bs_items.append({
                'local_id': lid,
                'mhn': market_by_lid.get(int(lid), wv.get('marketHashName', '')),
                'name_zh': name_zh,
                'pattern_zh': pattern_zh,
                'max_float': max_float,
                'min_float': item.get('min_float', 0),
                'wear_cn': wv.get('wear_cn', '战痕'),
                'wear_en': wear_en,
                'steamdt_typeVal': wv.get('steamdt_typeVal'),
                '_no_kline_id': wv.get('_no_kline_id', False),
            })
            if max_float <= BS_THRESHOLD:
                results.append({
                    'local_id': lid,
                    'mhn': market_by_lid.get(int(lid), wv.get('marketHashName', '')),
                    'name_zh': name_zh,
                    'pattern_zh': pattern_zh,
                    'max_float': max_float,
                    'min_float': item.get('min_float', 0),
                    'reason': f'max_float={max_float} < {BS_THRESHOLD}, BS 段 (0.45, {max_float}) 不存在',
                    'has_kline_id': bool(wv.get('steamdt_typeVal')),
                })

print(f'所有 BS 条目: {len(all_bs_items)}')
print(f'BS 但 max_float < {BS_THRESHOLD} (truly missing): {len(results)}')

# 按 local_id 排序
results.sort(key=lambda x: int(x['local_id']))

out = {
    'generated': '2026-06-04 (build_special_wear_list.py)',
    'description': '所有 Battle-Scarred 磨损的条目，但 max_float < 0.45 (意味着 BS 段不存在)',
    'bs_threshold': BS_THRESHOLD,
    'total_bs_items': len(all_bs_items),
    'truly_missing_count': len(results),
    'truly_missing_items': results,
}
out_path = MAPS / 'special_wear_skins.json'
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'\n✅ 写入: {out_path}')
print(f'   {len(results)} 条 truly_missing 特殊磨损皮肤')

# 打印前 20 个
print(f'\n--- 前 20 条 ---')
for r in results[:20]:
    print(f'  {r["local_id"]:>6} | {r["name_zh"]:<40} | max_float={r["max_float"]} | kline_id={r.get("has_kline_id", False)}')
print(f'\n--- 末 5 条 ---')
for r in results[-5:]:
    print(f'  {r["local_id"]:>6} | {r["name_zh"]:<40} | max_float={r["max_float"]} | kline_id={r.get("has_kline_id", False)}')
