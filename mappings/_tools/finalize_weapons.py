#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
finalize_weapons.py
===================
读取 mappings/weapons_to_integrate.json + 分配 local_id + 写入三件套。

分配规则（用户决策 2026-06-06 §4.7.3 新规则 - 隐密去破损）:
- 段位：动态分配，紧贴需求
  - 21918 ~ 22707：Rifles 高端 3/3/3 档 (Covert 3 + Classified 3 + Contraband 3)
  - 22708 ~ 23343：Rifles 低端 2/2/1/1 档 (Restricted 2 + Mil-Spec 2 + Industrial 1 + Consumer 1)
  - 23344 ~ 23728：Pistols 高端 3/3 档
  - 23729 ~ 24432：Pistols 低端 2/2/1/1 档
- 排序：rarity 降序 → weapon 字母序 → paint_index 升序 → wear 顺序
- 段位内按 rarity 顺序排列（Covert→Classified→Contraband→Restricted→...）
- 每个物品的 wear 数由其 rarity 决定（见 plan_weapons_mapping.RARITY_RULE）

写入策略（用户决策）:
- 写入前 .bak 备份 itemid.txt / itemid_market_map.json / all_items_cache.json
- 既有 400 行 / 397 keys / ~28260 entries **零修改**
- 全部 steamdt_typeVal = null（SteamDT API 暂不可用，标 _pending_typeval）
"""
import json
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent
MAPS = ROOT / 'mappings'

WEAR_ORDER = ['Factory New', 'Minimal Wear', 'Field-Tested', 'Well-Worn', 'Battle-Scarred']
WEAR_CN = {
    'Factory New': '崭新',
    'Minimal Wear': '略磨',
    'Field-Tested': '久经',
    'Well-Worn': '破损',
    'Battle-Scarred': '战痕',
}
RARITY_ORDER = {
    'Covert': 0, 'Classified': 1, 'Contraband': 2,
    'Restricted': 3, 'Mil-Spec Grade': 4,
    'Industrial Grade': 5, 'Consumer Grade': 6,
}

# 磨损段位映射 (AGENTS.md §4.7.3 新规则, 2026-06-06 - 隐密去破损)
# 注意: wear_count 字段是 "段位内最大 wear 数" (高端=3, 低端=2), 实际每物品 wear 数由 rarity 决定
WEAR_TO_SEG = {
    ('Rifles', 'high'): (21918, 3),   # Covert×3 / Classified×3 / Contraband×3
    ('Rifles', 'low'):  (22708, 2),   # Restricted×2 / Mil-Spec×2 / Industrial×1 / Consumer×1
    ('Pistols', 'high'): (23344, 3),  # Covert×3 / Classified×3
    ('Pistols', 'low'):  (23729, 2),  # Restricted×2 / Mil-Spec×2 / Industrial×1 / Consumer×1
}


def load_existing_market_hashes() -> set:
    """读取 itemid_market_map.json 中所有 marketHashName，用于幂等检测"""
    path = MAPS / 'itemid_market_map.json'
    return set(json.load(open(path, encoding='utf-8')).values())


def detect_duplicates(items: list) -> dict:
    """
    幂等检测：返回
    - 'already_done': 已存在于 market_map 的 wear 变体数
    - 'to_add': 应当新增的 wear 变体数
    - 'all_done': 是否全部已整合
    - 'mhn_to_local_id': 已存在的 marketHashName -> local_id 映射
    """
    existing_mp = json.load(open(MAPS / 'itemid_market_map.json', encoding='utf-8'))
    mhn_to_local_id = {v: k for k, v in existing_mp.items()}

    already = 0
    to_add = 0
    for it in items:
        for w in it['wears']:
            if w['marketHashName'] in mhn_to_local_id:
                already += 1
            else:
                to_add += 1
    return {
        'already_done': already,
        'to_add': to_add,
        'all_done': to_add == 0,
        'mhn_to_local_id': mhn_to_local_id,
    }


def backup_files():
    """写入前 .bak 备份 3 个映射文件"""
    today = datetime.now().strftime('%Y%m%d_%H%M%S')
    for fname in ['itemid.txt', 'itemid_market_map.json', 'all_items_cache.json']:
        src = MAPS / fname
        if src.exists():
            dst = MAPS / f'{fname}.bak_{today}'
            shutil.copy2(src, dst)
            print(f'  [BAK] {fname} -> {dst.name}')


def assign_ids(items: list, mhn_to_local_id: dict) -> list:
    """分配 local_id (动态段位 + rarity 降序排序)

    幂等模式：跳过已存在于 market_map 的 marketHashName
    """
    # 排序
    items.sort(key=lambda x: (
        0 if x['category'] == 'Rifles' else 1,  # Rifles 在 Pistols 前
        0 if x['tier'] == 'high' else 1,  # 高端在低端前
        RARITY_ORDER.get(x['rarity'], 99),  # 稀有度降序
        x['weapon'],
        x['paint_index'] or 0,
    ))

    # 按段位分组
    segments = {
        ('Rifles', 'high'): [],
        ('Rifles', 'low'): [],
        ('Pistols', 'high'): [],
        ('Pistols', 'low'): [],
    }
    for it in items:
        key = (it['category'], it['tier'])
        segments[key].append(it)

    # 段位内排序（rarity → weapon → paint）
    for key, seg_items in segments.items():
        seg_items.sort(key=lambda x: (
            RARITY_ORDER.get(x['rarity'], 99),
            x['weapon'],
            x['paint_index'] or 0,
        ))

    # 分配 ID（仅处理 mhn_to_local_id 中不存在的）
    assigned = []
    for (cat, tier), seg_items in segments.items():
        start_id, wear_count = WEAR_TO_SEG[(cat, tier)]
        cur_id = start_id
        for it in seg_items:
            for w in it['wears']:
                if w['marketHashName'] in mhn_to_local_id:
                    continue  # 幂等：跳过已整合
                assigned.append({
                    'local_id': str(cur_id),
                    'category': cat,
                    'tier': tier,
                    'weapon': it['weapon'],
                    'name': it['name'],
                    'rarity': it['rarity'],
                    'paint_index': it['paint_index'],
                    'wear_en': w['wear_en'],
                    'wear_cn': w['wear_cn'],
                    'wear_short': w['wear_short'],
                    'marketHashName': w['marketHashName'],
                    'min_float': it.get('min_float'),
                    'max_float': it.get('max_float'),
                    'image': it.get('image'),
                })
                cur_id += 1

    return assigned


def write_itemid_txt(assigned: list):
    """追加到 itemid.txt"""
    path = MAPS / 'itemid.txt'
    text = path.read_text(encoding='utf-8')
    lines = text.splitlines()

    # 找 "//自用" 位置
    insert_pos = len(lines)
    for i, line in enumerate(lines):
        if line.strip().startswith('//自用') or line.strip().startswith('// 自用'):
            insert_pos = i
            break

    # 生成新区块
    new_block = [
        '',
        '// ===== 武器皮肤 (Rifles + Pistols, 2026-06-06 录入) =====',
        '// 范围：905 物品 / 1870 变体 (§4.7.3 新规则 - 隐密去破损)',
        '// 磨损规则: Covert/Classified/Contraband=3档 (FN/MW/FT)',
        '//          Restricted/Mil-Spec=2档 (FN/MW) | Industrial/Consumer=1档 (FN)',
        '// 段位: 21918~22707 (Rifles 高端 3/3/3) / 22708~23343 (Rifles 低端 2/2/1/1)',
        '//       23344~23728 (Pistols 高端 3/3) / 23729~24432 (Pistols 低端 2/2/1/1)',
        '// SteamDT typeVal: 全部 _pending (SteamDT 详情页 API 暂不可用，待补抓)',
    ]

    for a in assigned:
        line = f"{a['local_id']}：{a['wear_cn']} {a['name']}"
        new_block.append(line)

    new_lines = lines[:insert_pos] + new_block + [''] + lines[insert_pos:]
    path.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
    print(f'  [WRITE] itemid.txt: +{len(assigned)} 行 (新区块)')


def write_market_map(assigned: list):
    """追加到 itemid_market_map.json"""
    path = MAPS / 'itemid_market_map.json'
    mp = json.load(open(path, encoding='utf-8'))

    before = len(mp)
    for a in assigned:
        mp[a['local_id']] = a['marketHashName']

    path.write_text(json.dumps(mp, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  [WRITE] itemid_market_map.json: {before} -> {len(mp)} keys (+{len(assigned)})')


def write_cache(assigned: list):
    """追加到 all_items_cache.json"""
    path = MAPS / 'all_items_cache.json'
    cache = json.load(open(path, encoding='utf-8'))

    before = len(cache)
    for a in assigned:
        cache.append({
            'name': a['name'],
            'shortName': a['name'].split(' | ', 1)[-1] if ' | ' in a['name'] else a['name'],
            'marketHashName': a['marketHashName'],
            'platformList': [],
            'rarity': a['rarity'],
            'category': a['category'],
            'wear_cn': a['wear_cn'],
            'wear_en': a['wear_en'],
            'weapon': a['weapon'],
            'tier': a['tier'],
            'steamdt_typeVal': None,
            '_pending_typeval': True,
            'source': 'bymykel/CSGO-API 2026-06-02 + SteamDT pending',
        })

    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  [WRITE] all_items_cache.json: {before} -> {len(cache)} entries (+{len(assigned)})')


def write_weapons_meta(assigned: list, items: list):
    """写 weapons_meta.json"""
    path = MAPS / 'weapons_meta.json'

    # 按物品聚合
    by_item = {}
    for a in assigned:
        key = a['name']
        if key not in by_item:
            by_item[key] = {
                'name': a['name'],
                'weapon': a['weapon'],
                'category': a['category'],
                'rarity': a['rarity'],
                'tier': a['tier'],
                'paint_index': a['paint_index'],
                'min_float': a['min_float'],
                'max_float': a['max_float'],
                'image': a['image'],
                'wear_variants': [],
            }
        by_item[key]['wear_variants'].append({
            'wear_en': a['wear_en'],
            'wear_cn': a['wear_cn'],
            'local_id': a['local_id'],
            'marketHashName': a['marketHashName'],
            'steamdt_typeVal': None,
        })

    meta = {
        'generated': '2026-06-06 (finalize_weapons.py, §4.7.3 新规则 - 隐密去破损)',
        'source': 'bymykel/CSGO-API (Rifles 476 + Pistols 429)',
        'rule': 'Covert/Classified/Contraband=3档 (FN/MW/FT) | Restricted/Mil-Spec=2档 (FN/MW) | Industrial/Consumer=1档 (FN)',
        'total_items': len(items),
        'total_wears': len(assigned),
        'segment_allocation': {f'{cat}_{tier}': {'start': start, 'max_wear_count': wc} for (cat, tier), (start, wc) in WEAR_TO_SEG.items()},
        'steamdt_status': '全部 _pending (SteamDT 详情页 API 暂不可用)',
        'items': list(by_item.values()),
    }
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  [WRITE] weapons_meta.json: {len(by_item)} 物品 / {len(assigned)} 变体')


def main():
    print('=' * 70)
    print('武器皮肤映射整合 (T4 + T5)')
    print('=' * 70)

    plan_path = MAPS / 'weapons_to_integrate.json'
    print(f'\n[1/5] 读取 {plan_path.name}...')
    plan = json.load(open(plan_path, encoding='utf-8'))
    items = plan['items']
    print(f'  {len(items)} 物品 / {sum(len(it["wears"]) for it in items)} 变体')

    print(f'\n[2/5] 幂等检测 (检查 itemid_market_map.json)...')
    dup = detect_duplicates(items)
    print(f'  已整合: {dup["already_done"]} 条')
    print(f'  待新增: {dup["to_add"]} 条')
    if dup['all_done']:
        print('\n' + '=' * 70)
        print('所有 2515 条武器皮肤已全部整合。无需重复执行。')
        print('如需强制重跑，请用 --force 标记 (会覆盖现有 local_id 分配)。')
        print('=' * 70)
        return

    print(f'\n[3/5] 分配 local_id (跳过 {dup["already_done"]} 条已整合)...')
    assigned = assign_ids(items, dup['mhn_to_local_id'])
    print(f'  待写入: {len(assigned)} 个变体')

    # 段位占用统计
    used = {}
    for a in assigned:
        seg = (a['category'], a['tier'])
        used[seg] = used.get(seg, 0) + 1
    print(f'  段位占用:')
    for seg, count in used.items():
        start, wear_count = WEAR_TO_SEG[seg]
        end = start + count - 1
        print(f'    {seg[0]:8s} {seg[1]:5s}: {start}~{end} ({count} 条)')

    print(f'\n[4/5] 备份既有 3 个映射文件...')
    backup_files()

    print(f'\n[5/5] 写入...')
    if not assigned:
        print('  无新增条目，跳过写入')
        return
    write_itemid_txt(assigned)
    write_market_map(assigned)
    write_cache(assigned)
    write_weapons_meta(assigned, items)

    print('\n' + '=' * 70)
    print(f'整合完成: +{len(assigned)} 条映射 (累计 {dup["already_done"] + len(assigned)} 条)')
    print('=' * 70)
    print('\n下一步: 跑 verify_weapons_integration.py 验证')


if __name__ == '__main__':
    main()
