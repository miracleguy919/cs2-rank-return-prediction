#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_item.py
================
单饰�?ID 状态诊�?(快速查"我手上的 mhn 到底缺什�?ID")�?
用法:
  # �?mhn �?  python verify/diagnose_item.py --mhn "�?Sport Gloves | Ultra Violent (Field-Tested)"

  # �?local_id �?  python verify/diagnose_item.py --local-id 21810

  # �?wear 名查
  python verify/diagnose_item.py --mhn "AK-47 | Redline (Field-Tested)"

  # 批量�?(�?stdin, 一行一�?mhn/lid)
  echo "21810
21811
AK-47 | Redline (Field-Tested)" | python verify/diagnose_item.py --stdin

输出: 每条饰品�?local_id / mhn / C5 / typeVal / 缺失�?/ 修复建议
"""
import argparse
import json
import re
import sys
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = Path(__file__).parent.parent
MAPS = ROOT / 'mappings'


def load_all():
    market = json.load(open(MAPS / 'itemid_market_map.json', encoding='utf-8'))
    cache_list = json.load(open(MAPS / 'all_items_cache.json', encoding='utf-8'))
    cache = {e.get('marketHashName'): e for e in cache_list if e.get('marketHashName')}
    cache_by_id = {e.get('id'): e for e in cache_list if e.get('id')}

    dh = json.load(open(MAPS / 'dead_hand_meta.json', encoding='utf-8'))
    wm = json.load(open(MAPS / 'weapons_meta.json', encoding='utf-8'))

    return {
        'market': market,
        'cache': cache,
        'cache_by_id': cache_by_id,
        'dh': dh,
        'wm': wm,
    }


def diagnose(query: str, data: dict) -> dict:
    """诊断一个饰�? 返回 {found, source, info, issues, fix_suggestion}"""
    query = query.strip()
    market = data['market']
    cache = data['cache']

    # 反向�?local_id
    lid = None
    if query.isdigit():
        lid = query if query in market else None
        if not lid:
            # �?dh_meta / weapons_meta 里找
            for fin in data['dh'].get('finishes', []):
                for w in fin.get('wears', []):
                    if str(w.get('local_id')) == query:
                        lid = query
                        return _diag_dh(query, w, fin, data)
            for it in data['wm'].get('items', []):
                for w in it.get('wear_variants', []):
                    if str(w.get('local_id')) == query:
                        return _diag_weapons(query, w, it, data)
    else:
        # �?mhn �?        mhn = query
        # lid 反查
        for k, v in market.items():
            if v == mhn:
                lid = k
                break

    if lid is None:
        return {
            'query': query,
            'found': False,
            'message': '未在 market_map / dead_hand_meta / weapons_meta 中找�?,
            'fix': '该饰品可能未被录入项�? 需要先�?fetch_bymykel_zh.py + plan_*.py',
        }

    mhn = market.get(lid)
    cache_entry = cache.get(mhn)

    # 2026-06-03 重构: C5 itemId === steamdt_typeVal (同一�?ID)
    # kline_id = 优先�?dh_meta / weapons_meta �? fallback cache
    kline_id_cache = None
    if cache_entry:
        # C5 platformList 优先
        for p in cache_entry.get('platformList', []):
            if p.get('name') == 'C5' and p.get('itemId'):
                kline_id_cache = str(p.get('itemId'))
                break
        # fallback steamdt_typeVal
        if not kline_id_cache:
            tv = cache_entry.get('steamdt_typeVal')
            if tv and tv != 'null':
                kline_id_cache = str(tv)

    # dh / weapons 兜底
    kline_id_dh = None
    kline_id_wm = None
    for fin in data['dh'].get('finishes', []):
        for w in fin.get('wears', []):
            if str(w.get('local_id')) == str(lid):
                tv = w.get('steamdt_typeVal')
                if tv and tv != 'null':
                    kline_id_dh = tv
    for it in data['wm'].get('items', []):
        for w in it.get('wear_variants', []):
            if str(w.get('local_id')) == str(lid):
                tv = w.get('steamdt_typeVal')
                if tv and tv != 'null':
                    kline_id_wm = tv

    kline_id = kline_id_dh or kline_id_wm or kline_id_cache

    issues = []
    if not kline_id:
        issues.append('�?kline_id (K线抓取阻�?')

    fix = []
    if not kline_id:
        if 21808 <= int(lid) <= 21917:
            fix.append('Dead Hand 类别, �?finalize_dead_hand.py 重抓')
        elif 21918 <= int(lid) <= 24432:
            fix.append('武器类别, �?crawl_weapons_typeval.py 重抓')
        else:
            fix.append('�?verify/diagnose_item.py --local-id ' + lid + ' 确认来源')

    return {
        'query': query,
        'found': True,
        'local_id': lid,
        'market_hash_name': mhn,
        'kline_id': kline_id,
        'kline_id_source': 'dh_meta' if kline_id_dh else ('weapons_meta' if kline_id_wm else ('cache' if kline_id_cache else None)),
        'issues': issues,
        'fix': '; '.join(fix) if fix else '无缺�? K线抓取就�?,
    }


def _diag_dh(lid, w, fin, data):
    tv = w.get('steamdt_typeVal')
    mhn = w.get('marketHashName')
    kline_id_cache = None
    for entry in data['cache'].values():
        if entry.get('marketHashName') == mhn:
            for p in entry.get('platformList', []):
                if p.get('name') == 'C5' and p.get('itemId'):
                    kline_id_cache = str(p.get('itemId'))
                    break
            if not kline_id_cache:
                cv = entry.get('steamdt_typeVal')
                if cv and cv != 'null':
                    kline_id_cache = str(cv)
            break
    kline_id = tv or kline_id_cache  # dh_meta 优先
    issues = []
    if not kline_id:
        issues.append('�?kline_id')
    fix_msg = []
    if not kline_id:
        fix_msg.append('需�?kline_id (K线抓取阻�?')
    if not fix_msg:
        fix_msg.append('无缺�? K线抓取就�?)

    return {
        'query': lid,
        'found': True,
        'local_id': lid,
        'market_hash_name': mhn,
        'glove_type': fin.get('gtype'),
        'finish': fin.get('finish'),
        'cn_name': fin.get('cn_name'),
        'wear': w.get('wear_en'),
        'kline_id': kline_id,
        'kline_id_source': 'dh_meta' if tv else ('cache' if kline_id_cache else None),
        'issues': issues,
        'fix': ' | '.join(fix_msg),
    }


def _diag_weapons(lid, w, it, data):
    tv = w.get('steamdt_typeVal')
    mhn = w.get('marketHashName')
    kline_id_cache = None
    cache_entry = data['cache'].get(mhn)
    if cache_entry:
        for p in cache_entry.get('platformList', []):
            if p.get('name') == 'C5' and p.get('itemId'):
                kline_id_cache = str(p.get('itemId'))
                break
        if not kline_id_cache:
            cv = cache_entry.get('steamdt_typeVal')
            if cv and cv != 'null':
                kline_id_cache = str(cv)
    kline_id = tv or kline_id_cache
    issues = []
    if not kline_id:
        issues.append('�?kline_id (K线抓取阻�?')
    fix_msg = []
    if not kline_id:
        fix_msg.append('�?kline/crawl_weapons_typeval.py 重抓')
    if not fix_msg:
        fix_msg.append('无缺�? K线抓取就�?)
    return {
        'query': lid,
        'found': True,
        'local_id': lid,
        'market_hash_name': mhn,
        'weapon': it.get('weapon'),
        'pattern': it.get('name'),
        'rarity': it.get('rarity'),
        'tier': it.get('tier'),
        'wear': w.get('wear_en'),
        'kline_id': kline_id,
        'kline_id_source': 'weapons_meta' if tv else ('cache' if kline_id_cache else None),
        'issues': issues,
        'fix': ' | '.join(fix_msg),
    }


def print_one(result: dict):
    print()
    print('=' * 78)
    print(f"  查询: {result.get('query', '')}")
    print('=' * 78)
    if not result.get('found'):
        print(f"  �?{result.get('message', '未找�?)}")
        if result.get('fix'):
            print(f"  建议: {result['fix']}")
        return
    lid = result.get('local_id', '?')
    mhn = result.get('market_hash_name', '?')
    print(f"  local_id    : {lid}")
    print(f"  mhn         : {mhn}")
    for k in ['weapon', 'pattern', 'rarity', 'tier', 'glove_type', 'finish', 'cn_name', 'wear']:
        v = result.get(k)
        if v:
            print(f"  {k:<12}: {v}")
    print(f"  kline_id    : {result.get('kline_id') or '�?缺失'}" + (f"  (from {result.get('kline_id_source')})" if result.get('kline_id_source') else ''))
    issues = result.get('issues', [])
    if issues:
        print(f"  ⚠️  问题: {', '.join(issues)}")
        print(f"  💡 建议: {result.get('fix', '?')}")
    else:
        print(f"  �?{result.get('fix', '正常')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mhn', help='�?marketHashName �?)
    ap.add_argument('--local-id', dest='local_id', help='�?local_id �?)
    ap.add_argument('--stdin', action='store_true', help='�?stdin �?(一行一�?query)')
    args = ap.parse_args()

    if not (args.mhn or args.local_id or args.stdin):
        ap.print_help()
        return

    data = load_all()
    queries = []
    if args.mhn:
        queries.append(args.mhn)
    if args.local_id:
        queries.append(args.local_id)
    if args.stdin:
        queries.extend([l.strip() for l in sys.stdin if l.strip()])

    for q in queries:
        r = diagnose(q, data)
        print_one(r)

    print()
    print('=' * 78)
    print('  诊断完成')
    print('=' * 78)


if __name__ == '__main__':
    main()
