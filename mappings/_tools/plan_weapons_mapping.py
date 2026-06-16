#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plan_weapons_mapping.py
=======================
读取 mappings/raw_rifles.json + raw_pistols.json，
按 rarity 决定档数（最终规则见 AGENTS.md §4.7.3），
生成 mappings/weapons_to_integrate.json 待录入清单。

磨损档规则（用户决策 2026-06-06 §4.7.3 — v2 进一步收敛）:
- Covert（隐秘）           → 3 档 (FN/MW/FT)           —— 去 WW/BS
- Classified（保密）       → 3 档 (FN/MW/FT)           —— 去 WW/BS
- Contraband（违禁）       → 3 档 (FN/MW/FT)           —— 去 WW/BS
- Restricted（受限）       → 2 档 (FN/MW)
- Mil-Spec Grade（军规）   → 2 档 (FN/MW)
- Industrial Grade（工业） → 1 档 (FN)                 —— 去 MW
- Consumer Grade（消费）   → 1 档 (FN)                 —— 去 MW

注意：脚本只生成待录入清单，**不分配 local_id**（T4 负责）。
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
MAPS = ROOT / 'mappings'

# bymykel rarity 名（首字母大写，含空格）
RARITY_RULE = {
    'Covert':           3,  # FN/MW/FT     (去 WW/BS)
    'Classified':       3,  # FN/MW/FT     (去 WW/BS)
    'Contraband':       3,  # FN/MW/FT     (去 WW/BS)
    'Restricted':       2,  # FN/MW
    'Mil-Spec Grade':   2,  # FN/MW
    'Industrial Grade': 1,  # FN           (去 MW)
    'Consumer Grade':   1,  # FN           (去 MW)
}
HIGH_END_RARITIES = {'Covert', 'Classified', 'Contraband'}  # 3/3/3 档
LOW_END_RARITIES  = {'Restricted', 'Mil-Spec Grade', 'Industrial Grade', 'Consumer Grade'}  # 2/2/1/1 档

WEAR_3 = [  # Covert / Classified / Contraband
    ('Factory New', 'FN'),
    ('Minimal Wear', 'MW'),
    ('Field-Tested', 'FT'),
]
WEAR_2 = [  # Restricted / Mil-Spec
    ('Factory New', 'FN'),
    ('Minimal Wear', 'MW'),
]
WEAR_1 = [  # Industrial / Consumer
    ('Factory New', 'FN'),
]

# 磨损度英文 → 中文
WEAR_CN = {
    'Factory New': '崭新',
    'Minimal Wear': '略磨',
    'Field-Tested': '久经',
    'Well-Worn': '破损',
    'Battle-Scarred': '战痕',
}


def main():
    print('=' * 70)
    print('生成武器皮肤待录入清单 (按 rarity 分档)')
    print('=' * 70)

    all_items = []
    for category_en, json_name in [('Rifles', 'raw_rifles'), ('Pistols', 'raw_pistols')]:
        path = MAPS / f'{json_name}.json'
        print(f'\n[1/3] 读取 {path.name}...')
        data = json.load(open(path, encoding='utf-8'))
        print(f'  {category_en} 物品数: {len(data)}')

        for it in data:
            rarity_name = it.get('rarity', {}).get('name') if isinstance(it.get('rarity'), dict) else None
            weapon_name = it.get('weapon', {}).get('name') if isinstance(it.get('weapon'), dict) else None
            name = it.get('name')  # "AK-47 | Bloodsport"

            if not rarity_name or not weapon_name or not name:
                continue

            # 决定档数（AGENTS.md §4.7.3）
            if rarity_name in ('Covert', 'Classified', 'Contraband'):
                wears = WEAR_3
                tier = 'high'
            elif rarity_name in ('Restricted', 'Mil-Spec Grade'):
                wears = WEAR_2
                tier = 'low'
            elif rarity_name in ('Industrial Grade', 'Consumer Grade'):
                wears = WEAR_1
                tier = 'low'
            else:
                print(f'  [WARN] 未知 rarity: {rarity_name} ({name})，按低端 2 档处理')
                wears = WEAR_2
                tier = 'low'

            all_items.append({
                'category': category_en,
                'weapon': weapon_name,
                'name': name,
                'rarity': rarity_name,
                'paint_index': it.get('paint_index'),
                'min_float': it.get('min_float'),
                'max_float': it.get('max_float'),
                'image': it.get('image'),
                'crates': [c.get('name') for c in it.get('crates', [])],
                'tier': tier,
                'wear_count': len(wears),
                'wears': [
                    {
                        'wear_en': w_en,
                        'wear_short': w_short,
                        'wear_cn': WEAR_CN[w_en],
                        'marketHashName': f'{name} ({w_en})',
                    }
                    for w_en, w_short in wears
                ],
            })

    print(f'\n[2/3] 总物品: {len(all_items)}')

    # 统计
    from collections import Counter
    rarity_counter = Counter(it['rarity'] for it in all_items)
    tier_counter = Counter(it['tier'] for it in all_items)
    cat_counter = Counter(it['category'] for it in all_items)

    print('\n  Rarity 分布:')
    for r, c in sorted(rarity_counter.items(), key=lambda x: -x[1]):
        print(f'    {r:25s}: {c:4d}')

    print(f'\n  Tier 分布:')
    for t, c in tier_counter.items():
        print(f'    {t:10s}: {c:4d}')

    print(f'\n  Category 分布:')
    for c, n in cat_counter.items():
        print(f'    {c:10s}: {n:4d}')

    # 变体数
    total_wears = sum(it['wear_count'] for it in all_items)
    high_items = sum(1 for it in all_items if it['tier'] == 'high')
    low_items = sum(1 for it in all_items if it['tier'] == 'low')
    high_wears = sum(it['wear_count'] for it in all_items if it['tier'] == 'high')
    low_wears = sum(it['wear_count'] for it in all_items if it['tier'] == 'low')
    print(f'\n  变体数统计 (§4.7.3 新规则):')
    print(f'    高端 ({high_items} 物品): {high_wears} 条 (Covert/Classified/Contraband=3)')
    print(f'    低端 ({low_items} 物品): {low_wears} 条 (Restricted/Mil-Spec=2, Industrial/Consumer=1)')
    print(f'    总计: {total_wears} 条')

    # 按 category + tier 分组
    print(f'\n  按 category × tier 分组:')
    for cat in ['Rifles', 'Pistols']:
        for tier in ['high', 'low']:
            items = [it for it in all_items if it['category'] == cat and it['tier'] == tier]
            if items:
                wears = sum(it['wear_count'] for it in items)
                print(f'    {cat:8s} {tier:5s}: {len(items):4d} 物品 × {wears // len(items)} 档 = {wears} 条')

    # Contraband 检查
    contraband = [it for it in all_items if it['rarity'] == 'Contraband']
    if contraband:
        print(f'\n  ⚠️ Contraband 物品 ({len(contraband)} 条):')
        for it in contraband:
            print(f'    - {it["name"]} ({it["category"]})')

    # 排序（spec 决策：rarity 降序 → weapon 字母序 → paint_index → wear）
    rarity_order = {'Covert': 0, 'Classified': 1, 'Contraband': 2, 'Restricted': 3,
                    'Mil-Spec Grade': 4, 'Industrial Grade': 5, 'Consumer Grade': 6}
    all_items.sort(key=lambda x: (
        rarity_order.get(x['rarity'], 99),
        0 if x['category'] == 'Rifles' else 1,  # Rifles 在 Pistols 前
        x['weapon'],
        x['paint_index'] or 0,
    ))

    # 输出
    out_path = MAPS / 'weapons_to_integrate.json'
    print(f'\n[3/3] 写入 {out_path.name}...')
    out = {
        'generated': '2026-06-06 (plan_weapons_mapping.py, §4.7.3 新规则 — 隐密去破损)',
        'source': 'bymykel/CSGO-API (Rifles 476 + Pistols 429)',
        'rule': 'Covert/Classified/Contraband=3档 (FN/MW/FT) | Restricted/Mil-Spec=2档 (FN/MW) | Industrial/Consumer=1档 (FN)',
        'total_items': len(all_items),
        'total_wears': total_wears,
        'items': all_items,
    }
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  [OK] {len(all_items)} 物品 / {total_wears} 变体 → {out_path.name}')

    print('\n' + '=' * 70)
    print('T2 完成。下一步：T3.5 跑 10 sample 验证爬虫流程')
    print('=' * 70)


if __name__ == '__main__':
    main()
