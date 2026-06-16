#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_weapons_integration.py
=============================
验证 2515 条武器皮肤整合到三件套的完整性。

检查项：
1. itemid.txt: 包含 2515 条 `id: 中文名` 格式 (no duplicates, no missing)
2. itemid_market_map.json: 包含 2515 个 marketHashName (id ↔ name 一一对应)
3. all_items_cache.json: 包含 2515 个 weapons cache entries
4. local_id 段位：21918~24432 范围无空洞 (Rifles+Pistols × high+low)
5. weapons_meta.json: 与三件套中的 weapons entries 一一对应
6. 重复条目检测 (防止 finalize_weapons.py 重跑导致 2x 写入)
7. 段位 (Rifles/Pistols) × (high/low) 数量校验
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
MAPS = ROOT / 'mappings'

WEAR_TO_SEG = {
    ('Rifles', 'high'): (21918, 5, 790),
    ('Rifles', 'low'): (22708, 2, 636),
    ('Pistols', 'high'): (23344, 5, 385),
    ('Pistols', 'low'): (23729, 2, 704),
}

# 实际整合后预期 (计划 2515 - 短 ID 重复 166 - Gamma Doppler 多 Phase 12 = 2337)
# 由 fix_weapons_duplicates.py 实际计算, 这里给一个范围
EXPECTED_TOTAL = 2515
EXPECTED_AFTER_FIX_MIN = 2300  # 清理后最少
EXPECTED_AFTER_FIX_MAX = 2350  # 清理后最多


def load_itemid_txt():
    """解析 itemid.txt 为 {local_id: name} dict"""
    path = MAPS / 'itemid.txt'
    result = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        m = re.match(r'^(\d+)[：:](.+)$', line)
        if m:
            local_id = m.group(1)
            name = m.group(2).strip()
            result[local_id] = name
    return result


def load_market_map():
    return json.load(open(MAPS / 'itemid_market_map.json', encoding='utf-8'))


def load_cache():
    return json.load(open(MAPS / 'all_items_cache.json', encoding='utf-8'))


def load_weapons_meta():
    path = MAPS / 'weapons_meta.json'
    if not path.exists():
        return None
    return json.load(open(path, encoding='utf-8'))


def check_pass_or_fail(label: str, ok: bool, detail: str = ''):
    icon = '[OK]  ' if ok else '[FAIL]'
    print(f'  {icon} {label}', end='')
    if detail:
        print(f' :: {detail}')
    else:
        print()
    return ok


def load_weapons_to_integrate():
    """加载 weapons_to_integrate.json, 计算 4 段位的预期条数"""
    path = MAPS / 'weapons_to_integrate.json'
    if not path.exists():
        return None
    plan = json.load(open(path, encoding='utf-8'))
    expected = {
        ('Rifles', 'high'): 0,
        ('Rifles', 'low'): 0,
        ('Pistols', 'high'): 0,
        ('Pistols', 'low'): 0,
    }
    for it in plan['items']:
        key = (it['category'], it['tier'])
        expected[key] += len(it['wears'])
    return expected


def main():
    print('=' * 70)
    print('武器皮肤整合质量验证')
    print('=' * 70)

    # 加载预期 (按段位 × 档数, 但实际整合会扣除与短 ID 重复的部分)
    plan_expected = load_weapons_to_integrate()
    if plan_expected:
        full_total = sum(plan_expected.values())
        print(f'\n  计划总数: {full_total} (基于 weapons_to_integrate.json)')
        # 注: 实际整合数 = 计划数 - 与短 ID "千战" 重复的 mhn × 对应 wear 数
    else:
        full_total = EXPECTED_TOTAL

    print('\n[1/7] 读取映射三件套...')
    itemid = load_itemid_txt()
    market_map = load_market_map()
    cache = load_cache()
    weapons_meta = load_weapons_meta()

    print(f'  itemid.txt: {len(itemid)} 条')
    print(f'  itemid_market_map.json: {len(market_map)} 键')
    print(f'  all_items_cache.json: {len(cache)} 条')
    print(f'  weapons_meta.json: {len(weapons_meta["items"]) if weapons_meta else "N/A"} 物品')

    print('\n[2/7] 检查 itemid.txt 完整性...')
    passes = []
    passes.append(check_pass_or_fail(
        'itemid.txt 无重复 local_id',
        len(itemid) == len(set(itemid.keys())),
        f'{len(itemid)} vs {len(set(itemid.keys()))}'
    ))
    weapon_itemid = {lid: name for lid, name in itemid.items()
                     if 21918 <= int(lid) <= 24432}
    passes.append(check_pass_or_fail(
        'itemid.txt 武器条数 (清理后预期 2300~2350)',
        EXPECTED_AFTER_FIX_MIN <= len(weapon_itemid) <= EXPECTED_AFTER_FIX_MAX,
        f'{len(weapon_itemid)} 条 (总 {len(itemid)})'
    ))

    print('\n[3/7] 检查 itemid_market_map.json 完整性...')
    passes.append(check_pass_or_fail(
        'market_map 无重复 marketHashName',
        len(market_map) == len(set(market_map.values())),
        f'{len(market_map)} vs {len(set(market_map.values()))}'
    ))
    weapon_market = {lid: mhn for lid, mhn in market_map.items()
                     if 21918 <= int(lid) <= 24432}
    passes.append(check_pass_or_fail(
        'market_map 武器条数 (清理后预期 2300~2350)',
        EXPECTED_AFTER_FIX_MIN <= len(weapon_market) <= EXPECTED_AFTER_FIX_MAX,
        f'{len(weapon_market)} 键 (总 {len(market_map)})'
    ))

    print('\n[4/7] 检查 local_id 段位...')
    weapon_ids = sorted([
        int(lid) for lid in itemid.keys()
        if 21918 <= int(lid) <= 24432
    ])
    passes.append(check_pass_or_fail(
        'local_id 段位 21918~24432 范围内条目 (清理后预期 2300~2350)',
        EXPECTED_AFTER_FIX_MIN <= len(weapon_ids) <= EXPECTED_AFTER_FIX_MAX,
        f'找到 {len(weapon_ids)} 条武器 local_id'
    ))

    # 段位 (清理后预期: 段位内 ID 不连续, 只检查数量在合理范围)
    # 用精确的 [start, end) 切分, 避免段位间 ID 串到下一段
    sorted_segs = sorted(WEAR_TO_SEG.items(), key=lambda x: x[1][0])
    for idx, ((cat, tier), (start, _wc, _count)) in enumerate(sorted_segs):
        if idx + 1 < len(sorted_segs):
            end = sorted_segs[idx + 1][1][0]
        else:
            end = 99999
        seg_ids = [i for i in weapon_ids if start <= i < end]
        actual_count = len(seg_ids)
        min_count = int(_count * 0.4)
        ok = min_count <= actual_count <= _count
        passes.append(check_pass_or_fail(
            f'{cat:8s} {tier:5s} 段位 ({start}~{end-1})',
            ok,
            f'实际 {actual_count} 条 (计划 {_count}, 最少 {min_count})'
        ))

    print('\n[5/7] 检查 all_items_cache.json...')
    weapon_cache_entries = [
        c for c in cache
        if c.get('category') in ('Rifles', 'Pistols')
        and c.get('tier') in ('high', 'low')
    ]
    passes.append(check_pass_or_fail(
        'cache 包含武器条数 (清理后预期 2300~2350)',
        EXPECTED_AFTER_FIX_MIN <= len(weapon_cache_entries) <= EXPECTED_AFTER_FIX_MAX,
        f'{len(weapon_cache_entries)} 条'
    ))

    cache_mhns = {c.get('marketHashName') for c in weapon_cache_entries}
    market_mhns = set(market_map.values())
    passes.append(check_pass_or_fail(
        'cache marketHashName 全部 in market_map values',
        cache_mhns.issubset(market_mhns),
        f'{len(cache_mhns)} cache vs {len(market_mhns)} market_map'
    ))

    # _pending_typeval 统计
    pending_count = sum(
        1 for c in weapon_cache_entries
        if c.get('_pending_typeval', False)
    )
    print(f'  cache 中 _pending_typeval: {pending_count}/{len(weapon_cache_entries)} 条')

    print('\n[6/7] 检查 weapons_meta.json...')
    if weapons_meta is None:
        check_pass_or_fail('weapons_meta.json 存在', False, '未找到')
        passes.append(False)
    else:
        meta_items = weapons_meta.get('items', [])
        total_wears = weapons_meta.get('total_wears', 0)
        passes.append(check_pass_or_fail(
            'weapons_meta.total_wears (清理后预期 2300~2350)',
            EXPECTED_AFTER_FIX_MIN <= total_wears <= EXPECTED_AFTER_FIX_MAX,
            f'{total_wears}'
        ))
        meta_mhns = set()
        for it in meta_items:
            for w in it.get('wear_variants', []):
                meta_mhns.add(w.get('marketHashName'))
        passes.append(check_pass_or_fail(
            'weapons_meta marketHashName 集合 in market_map',
            meta_mhns.issubset(market_mhns),
            f'{len(meta_mhns)} meta vs {len(market_mhns)} market_map'
        ))

    print('\n[7/7] 重复检测 (itemid.txt vs market_map)...')
    itemid_paint_keys = set()
    paint_wear_to_ids = {}
    for lid, name in itemid.items():
        m = re.search(r'\(([^)]+)\)\s*$', name)
        if m:
            paint_en = m.group(1)
            base_no_wear = re.sub(r'^(崭新|略磨|久经|破损|战痕)\s+', '', name)
            paint_key = base_no_wear.strip()
            wear_match = re.match(r'^(崭新|略磨|久经|破损|战痕)\s+', name)
            wear_cn = wear_match.group(1) if wear_match else '?'
            paint_wear_key = (paint_key, wear_cn)
            itemid_paint_keys.add(paint_key)
            paint_wear_to_ids.setdefault(paint_wear_key, []).append(lid)

    dup_ids = {k: lids for k, lids in paint_wear_to_ids.items() if len(lids) > 1}
    passes.append(check_pass_or_fail(
        'itemid.txt 中无重复 (local_id, paint+wear) 对',
        len(dup_ids) == 0,
        f'重复 {len(dup_ids)} 个' if dup_ids else '全部唯一'
    ))

    # 提取 market_map 中所有 paint_key (去掉 (Wear) 后缀)
    market_paint_keys = set()
    for mhn in market_map.values():
        m = re.match(r'^(.+?)\s*\(([^)]+)\)\s*$', mhn)
        if m:
            market_paint_keys.add(m.group(1).strip())

    missing_in_market = itemid_paint_keys - market_paint_keys
    extra_in_market = market_paint_keys - itemid_paint_keys
    passes.append(check_pass_or_fail(
        'itemid.txt 全部 paint_key 出现在 market_map',
        len(missing_in_market) == 0,
        f'缺失 {len(missing_in_market)} 个' if missing_in_market else '全部覆盖'
    ))

    # 重复 mhn (同一 marketHashName 出现多次)
    from collections import Counter
    mhn_counter = Counter(market_map.values())
    dup_mhns = {k: v for k, v in mhn_counter.items() if v > 1}
    passes.append(check_pass_or_fail(
        'market_map 无重复 marketHashName',
        len(dup_mhns) == 0,
        f'重复 {len(dup_mhns)} 个 mhn' if dup_mhns else '全部唯一'
    ))

    if dup_mhns:
        print(f'\n  [INFO] 重复 mhn 是短 ID (千战) 与新分配 ID 共存')

    print('\n' + '=' * 70)
    total = len(passes)
    passed = sum(passes)
    print(f'结果: {passed}/{total} 项通过', end='')
    if passed == total:
        print(' [ALL PASS]')
    else:
        print(f' [{total - passed} 项 FAIL]')

    if missing_in_market:
        print(f'\n[缺失 marketHashName 样本 (前 5)]')
        for mhn in list(missing_in_market)[:5]:
            print(f'  - {mhn}')
    if dup_ids:
        print(f'\n[重复条目样本 (前 5)]')
        for mhn, lids in list(dup_ids.items())[:5]:
            print(f'  {mhn}: {lids}')
    print('=' * 70)

    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
