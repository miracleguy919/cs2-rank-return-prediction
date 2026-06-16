#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mark_no_kline_id.py
===================
对 C5 搜索 API 仍找不到 kline_id 的饰品，标 _no_kline_id=true。
K线抓取时 get_hourly_kline.py 会自动跳过。

策略：
- 跑 verify_id_full_coverage.py 找出当前所有 kline_id 缺口
- 在 cache 和 weapons_meta 加 _no_kline_id=true 字段
- 备份: all_items_cache.json.bak_nokl_*, weapons_meta.json.bak_nokl_*

用法:
  python tools/mark_no_kline_id.py --dry-run
  python tools/mark_no_kline_id.py
"""
import argparse
import json
import sys
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = Path(__file__).parent.parent.parent
MAPS = ROOT / 'mappings'
CACHE_FILE = MAPS / 'all_items_cache.json'
MARKET_FILE = MAPS / 'itemid_market_map.json'
WEAPONS_META_FILE = MAPS / 'weapons_meta.json'
DEAD_HAND_META_FILE = MAPS / 'dead_hand_meta.json'


def get_kline_id(entry):
    if not entry:
        return None
    for p in entry.get('platformList', []):
        if p.get('name') == 'C5' and p.get('itemId'):
            return str(p['itemId'])
    tv = entry.get('steamdt_typeVal')
    if tv and tv != 'null':
        return str(tv)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='只统计, 不写回')
    args = ap.parse_args()

    print('=' * 60)
    print('mark_no_kline_id.py - 标记不可抓 kline_id 的饰品')
    print('=' * 60)

    cache = json.load(open(CACHE_FILE, encoding='utf-8'))
    cbm_index = {e['marketHashName']: i for i, e in enumerate(cache)}
    market = json.load(open(MARKET_FILE, encoding='utf-8'))

    # 找出所有 kline_id 缺口
    gaps = []
    for lid, mhn in market.items():
        e = cbm.get(mhn) if (cbm := cbm_index) else None
        e = cache[cbm_index[mhn]] if mhn in cbm_index else None
        if e and not get_kline_id(e):
            gaps.append((lid, mhn, cbm_index[mhn]))

    print(f'\n[1/3] 当前 kline_id 缺口: {len(gaps)} 条')
    for lid, mhn, idx in gaps[:20]:
        print(f'  {lid} {mhn[:60]}')
    if len(gaps) > 20:
        print(f'  ... 共 {len(gaps)} 条')

    if not gaps:
        print('  没有缺口, 退出')
        return

    if args.dry_run:
        print(f'\n[DRY-RUN] 不会写回')
        return

    # 备份
    import time
    ts = time.strftime('%Y%m%d_%H%M%S')
    backup_cache = CACHE_FILE.with_suffix(f'.json.bak_nokl_{ts}')
    backup_wm = WEAPONS_META_FILE.with_suffix(f'.json.bak_nokl_{ts}')
    json.dump(cache, open(backup_cache, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n[2/3] 备份: {backup_cache.name}')

    # 同步 weapons_meta
    wm = json.load(open(WEAPONS_META_FILE, encoding='utf-8'))
    json.dump(wm, open(backup_wm, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'       备份: {backup_wm.name}')

    wm_lookup = {}
    for it in wm.get('items', []):
        for w in it.get('wear_variants', []):
            wm_lookup[w['marketHashName']] = w

    # 标记 cache
    for lid, mhn, idx in gaps:
        cache[idx]['_no_kline_id'] = True
        cache[idx]['_no_kline_id_reason'] = 'C5 搜索 API 找不到 + SteamDT 服务端 500 (2026-06-03 crawl_weapons_c5_search.py)'
        cache[idx]['_no_kline_id_date'] = ts

    # 同步 weapons_meta
    wm_marked = 0
    for lid, mhn, idx in gaps:
        wm_w = wm_lookup.get(mhn)
        if wm_w:
            wm_w['_no_kline_id'] = True
            wm_marked += 1
    print(f'  weapons_meta 标记: {wm_marked} 条')

    # 写回
    json.dump(cache, open(CACHE_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(wm, open(WEAPONS_META_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'\n[3/3] 写回 cache ({len(gaps)} 条) + weapons_meta ({wm_marked} 条)')


if __name__ == '__main__':
    main()
