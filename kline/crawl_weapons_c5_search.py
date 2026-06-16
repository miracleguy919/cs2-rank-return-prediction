#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crawl_weapons_c5_search.py
==========================
�?268 �?cache 里缺 kline_id 的武器，�?C5 搜索 API �?C5 itemId�?
策略�?- mhn 简化为 weapon+pattern 关键词（去掉 wear�?- 访问 https://www.c5game.com/csgo/{keyword}/ 解析 HTML �?itemId
- 找到�?itemId 写回 cache �?platformList[name='C5']
- 支持 --dry-run / --resume / --limit

用法:
  python kline/crawl_weapons_c5_search.py --limit 5 --dry-run
  python kline/crawl_weapons_c5_search.py --limit 30
  python kline/crawl_weapons_c5_search.py --resume
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import requests

ROOT = Path(__file__).parent.parent
MAPS = ROOT / 'mappings'
CACHE_FILE = MAPS / 'all_items_cache.json'
MARKET_FILE = MAPS / 'itemid_market_map.json'
WEAPONS_META_FILE = MAPS / 'weapons_meta.json'

# 268 缺口 mhn 集合（运行初始化时填充）
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


def get_kline_id(entry):
    """C5 itemId ?? steamdt_typeVal 兜底"""
    if not entry:
        return None
    for p in entry.get('platformList', []):
        if p.get('name') == 'C5' and p.get('itemId'):
            return str(p['itemId'])
    tv = entry.get('steamdt_typeVal')
    if tv and tv != 'null':
        return str(tv)
    return None


def load_gap_mhns() -> list:
    """�?cache 找出所�?kline_id 缺失�?mhn（不仅是武器，全部）"""
    cache = json.load(open(CACHE_FILE, encoding='utf-8'))
    cbm = {e['marketHashName']: e for e in cache}
    market = json.load(open(MARKET_FILE, encoding='utf-8'))
    gaps = []
    for lid, mhn in market.items():
        e = cbm.get(mhn)
        if e and not get_kline_id(e):
            # 只处理武器类�?1918-24432�?            lid_i = int(lid)
            if 21918 <= lid_i <= 24432:
                gaps.append((lid, mhn, e))
    return gaps


def simplify_mhn_for_search(mhn: str, with_wear: bool = False) -> str:
    """mhn = 'AK-47 | Redline (Field-Tested)' -> 关键�?'AK-47 Redline'
    如果 with_wear=True, 加上 wear: 'AK-47 Redline Field-Tested'
    """
    parts = mhn.split(' | ', 1)
    if len(parts) != 2:
        return mhn
    weapon, rest = parts
    wear_match = rest.rfind(' (')
    paint = rest[:wear_match] if wear_match > 0 else rest
    if with_wear and wear_match > 0:
        wear = rest[wear_match+2:-1]  # "Field-Tested"
        return f'{weapon} {paint} {wear}'
    return f'{weapon} {paint}'


def fetch_c5_search(keyword: str) -> str | None:
    """访问 C5 搜索结果页，提取 C5 itemId�?
    实际试过的方法：
    1. https://www.c5game.com/csgo/?keyword={keyword}  �?列表
    2. https://www.c5game.com/csgo/{keyword}/         �?详情页跳�?    """
    encoded = urllib.parse.quote(keyword, safe='')
    # 方法 1: 列表�?    url1 = f'https://www.c5game.com/csgo/?keyword={encoded}'
    try:
        r = requests.get(url1, timeout=15, allow_redirects=True, headers=HEADERS)
        if r.status_code == 200:
            # 2026-06-04: C5 URL 格式变化, /csgo/{9位ID}/{name}/sell
            # 旧格�? /csgo/{18位typeVal}/, 新格�? /csgo/{9位ID}/{name}/sell
            # 用更宽的 regex 匹配任意位数
            m = re.search(r'/csgo/(\d+)/', r.text)
            if m:
                return m.group(1)
    except Exception as e:
        print(f'    [err list] {e}')

    # 方法 2: 详情页（fallback�?    url2 = f'https://www.c5game.com/csgo/{encoded}/'
    try:
        r = requests.get(url2, timeout=15, allow_redirects=True, headers=HEADERS)
        if r.status_code == 200:
            m = re.search(r'/csgo/(\d+)/', r.url)
            if m:
                return m.group(1)
            m = re.search(r'"itemId"\s*:\s*"(\d+)"', r.text)
            if m:
                return m.group(1)
    except Exception as e:
        print(f'    [err detail] {e}')

    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='最多处�?N �?(0=全部)')
    ap.add_argument('--dry-run', action='store_true', help='不写�?cache, 只打�?)
    ap.add_argument('--resume', action='store_true', help='跳过已找到的, 只处理新缺口')
    ap.add_argument('--delay', type=float, default=1.5, help='请求间隔秒数')
    args = ap.parse_args()

    print('=' * 60)
    print('crawl_weapons_c5_search.py - �?C5 搜索 API �?268 武器 kline_id')
    print('=' * 60)

    # �?cache �?weapons_meta
    cache = json.load(open(CACHE_FILE, encoding='utf-8'))
    cbm_index = {e['marketHashName']: i for i, e in enumerate(cache)}

    wm = json.load(open(WEAPONS_META_FILE, encoding='utf-8'))
    wm_lookup = {}  # (weapon, pattern) -> wear_variants
    for it in wm.get('items', []):
        for w in it.get('wear_variants', []):
            wm_lookup[w['marketHashName']] = w

    gaps = load_gap_mhns()
    print(f'\n[1/3] 当前 kline_id 缺口: {len(gaps)} 个武�?)

    if args.resume:
        gaps = [(lid, mhn, e) for lid, mhn, e in gaps if not e.get('_no_kline_id')]
        print(f'  过滤已标 _no_kline_id �? {len(gaps)}')

    if args.limit:
        gaps = gaps[:args.limit]
        print(f'  --limit 截断�? {len(gaps)}')

    if not gaps:
        print('  没有要处理的, 退�?)
        return

    print(f'\n[2/3] 逐个访问 C5 搜索 API (双关键词: 先用 weapon+paint �?base, 再用 +wear 找具�?wear)')
    success = 0
    fail = 0
    results = []
    for i, (lid, mhn, entry) in enumerate(gaps, 1):
        # 先用 weapon+paint �?(可能�?base ID)
        keyword_base = simplify_mhn_for_search(mhn, with_wear=False)
        # 再用 weapon+paint+wear 找具�?        keyword_wear = simplify_mhn_for_search(mhn, with_wear=True)
        print(f'  [{i:>3d}/{len(gaps)}] {mhn[:55]:55s}')
        # 优先尝试�?wear 的关键词 (更精�?
        c5_id = fetch_c5_search(keyword_wear)
        if not c5_id:
            time.sleep(0.5)
            c5_id = fetch_c5_search(keyword_base)
        if c5_id:
            success += 1
            print(f'              �?C5 itemId = {c5_id}')
            results.append({'local_id': lid, 'marketHashName': mhn, 'c5_itemId': c5_id})

            if not args.dry_run:
                idx = cbm_index[mhn]
                platform_list = cache[idx].setdefault('platformList', [])
                c5_entry = next((p for p in platform_list if p.get('name') == 'C5'), None)
                if c5_entry:
                    c5_entry['itemId'] = c5_id
                else:
                    platform_list.append({'name': 'C5', 'itemId': c5_id})
                cache[idx]['_pending_typeval'] = False
                cache[idx]['steamdt_typeVal'] = c5_id
                cache[idx].pop('_no_kline_id', None)

                wm_w = wm_lookup.get(mhn)
                if wm_w and not wm_w.get('steamdt_typeVal'):
                    wm_w['steamdt_typeVal'] = c5_id
        else:
            fail += 1
            print(f'              �?两种关键词都未找�?)

        time.sleep(args.delay)

    # 保存结果
    out_path = MAPS / 'c5_search_results.json'
    json.dump({
        'generated': 'crawl_weapons_c5_search.py',
        'date': '2026-06-03',
        'method': 'C5 搜索/详情�?�?C5 itemId',
        'success': success,
        'fail': fail,
        'results': results,
    }, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    if not args.dry_run:
        json.dump(cache, open(CACHE_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        json.dump(wm, open(WEAPONS_META_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'\n[3/3] 已写�?cache + weapons_meta')

    print(f'\n  成功: {success}')
    print(f'  失败: {fail}')
    print(f'  保存: {out_path.name}')


if __name__ == '__main__':
    main()
