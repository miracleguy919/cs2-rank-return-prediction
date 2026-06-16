#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plan_incremental_ids.py
=======================
增量 ID 同步入口：对比 bymykel 最新数据与本地 cache, 生成待补 ID 清单。

输入:
  - mappings/bymykel_zh_skins.json  (或 en)  最新 bymykel 数据
  - mappings/all_items_cache.json            本地 cache

输出:
  - mappings/incremental_id_plan.json   增量同步计划
    {
      "generated": "...",
      "local_max_id": 24432,
      "next_id": 24433,
      "new_items": [
        {
          "name": "...",
          "weapon": "...",
          "rarity": "...",
          "tier": "high" | "low",
          "wear_count": 5 | 2,
          "wears": [
            {"wear_en": "Factory New", "local_id": "24433", "marketHashName": "..."},
            ...
          ]
        }
      ],
      "summary": {
        "total_new_items": N,
        "total_new_wears": M,
        "id_segment": "24433-...",
      }
    }

用法:
  # 默认从 bymykel_zh_skins.json 拉
  python tools/plan_incremental_ids.py

  # 限定只查某类别
  python tools/plan_incremental_ids.py --category Rifles

  # 干跑 (不写文件, 只看)
  python tools/plan_incremental_ids.py --dry-run
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = Path(__file__).parent.parent.parent
MAPS = ROOT / 'mappings'

# 段位分配 (与 weapons 整合一致, 增量从 max+1 开始)
# AGENTS.md §4.7.3 新规则: 隐秘/保密/违禁=3, 受限/军规=2, 工业/消费=1
SEGMENT_RANGES = {
    'Rifles_high':  (21918, 22707),  # 715 条 (Covert×74 + Classified×82 + Contraband×1, 3/3/3 档)
    'Rifles_low':   (22708, 23343),  # 636 条 (Restricted/Mil-Spec/Industrial/Consumer, 2/2/1/1 档)
    'Pistols_high': (23344, 23728),  # 294 条 (Covert×19 + Classified×53, 3/3 档)
    'Pistols_low':  (23729, 24432),  # 704 条 (Restricted/Mil-Spec/Industrial/Consumer, 2/2/1/1 档)
    # 24433+ 留给新类别 (SMGs/Heavy/Equipment/Knives/Dead Hand 二代 等)
}

CATEGORY_TIER = {
    'Rifles':  'weapon',
    'Pistols': 'weapon',
    'SMGs':    'weapon',
    'Shotguns': 'weapon',
    'Sniper Rifles': 'weapon',
    'Machineguns': 'weapon',
    'Gloves':  'glove',
    'Knives':  'knife',
    'Agents':  'agent',
    'Stickers': 'sticker',
    'Keychains': 'keychain',
    'Crates':  'case',
    'Collections': 'collection',
}

# 高/低端划分 (稀有度 -> wear 档数)
# AGENTS.md §4.7.3 新规则 (2026-06-06 决策 - 隐密去破损)
RARITY_TO_WEAR_COUNT = {
    'Covert': 3,            # FN/MW/FT (去 WW/BS)
    'Classified': 3,        # FN/MW/FT (去 WW/BS)
    'Contraband': 3,        # FN/MW/FT (去 WW/BS)
    'Restricted': 2,        # FN/MW
    'Mil-Spec Grade': 2,    # FN/MW
    'Industrial Grade': 1,  # FN (去 MW)
    'Consumer Grade': 1,    # FN (去 MW)
}

WEAR_ORDER = ['Factory New', 'Minimal Wear', 'Field-Tested', 'Well-Worn', 'Battle-Scarred']


def get_local_max_id() -> int:
    """从 itemid.txt 读 max local_id"""
    max_id = 0
    for line in (MAPS / 'itemid.txt').read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        m = re.match(r'^(\d+)[：:]', line)
        if m:
            i = int(m.group(1))
            if i > max_id:
                max_id = i
    return max_id


def load_local_mhn_set() -> set:
    """读本地 cache 已有 mhn 集合"""
    cache = json.load(open(MAPS / 'all_items_cache.json', encoding='utf-8'))
    return {e.get('marketHashName') for e in cache if e.get('marketHashName')}


def parse_wear_from_mhn(mhn: str) -> str:
    """从 mhn 提取 wear 名"""
    for wear in WEAR_ORDER:
        if f'({wear})' in mhn:
            return wear
    return ''


def strip_wear_from_mhn(mhn: str) -> str:
    """去掉 mhn 末尾的 (Wear)"""
    return re.sub(r'\s*\([^)]+\)\s*$', '', mhn)


def build_plan(category: str = None, dry_run: bool = False) -> dict:
    """构建增量同步计划"""
    print('[1/4] 加载 bymykel 数据 ...')
    src = MAPS / 'bymykel_zh_skins.json'
    if not src.exists():
        src = MAPS / 'bymykel_skins.json'
    if not src.exists():
        print(f'❌ 未找到 bymykel 数据: {src}')
        print('   请先跑: python tools/fetch_bymykel_zh.py')
        sys.exit(1)
    bymykel = json.load(open(src, encoding='utf-8'))
    print(f'  {src.name}: {len(bymykel)} 条')

    print('[2/4] 加载本地 cache ...')
    local_mhns = load_local_mhn_set()
    print(f'  cache: {len(local_mhns)} mhn')

    local_max = get_local_max_id()
    next_id = local_max + 1
    print(f'  local_max_id: {local_max}, next_id: {next_id}')

    print('[3/4] 找出新增物品 (by mhn) ...')
    new_items = []
    seen_base = set()  # 防止同一 base skin (多 wear) 重复

    for entry in bymykel:
        cat = (entry.get('category', {}) or {}).get('name', '')
        if category and cat != category:
            continue
        if CATEGORY_TIER.get(cat) is None:
            continue
        mhn_base = strip_wear_from_mhn(entry.get('name', ''))
        if not mhn_base or mhn_base in seen_base:
            continue

        # 找出所有 wears (by mhn 末尾的 wear 名)
        wears = []
        for e2 in bymykel:
            if strip_wear_from_mhn(e2.get('name', '')) == mhn_base and e2.get('name') not in local_mhns:
                w = parse_wear_from_mhn(e2.get('name', ''))
                if w and w not in wears:
                    wears.append(w)

        if not wears:
            continue

        seen_base.add(mhn_base)
        # 只取按 WEAR_ORDER 排序的前 N 个
        wears.sort(key=lambda x: WEAR_ORDER.index(x) if x in WEAR_ORDER else 99)
        rarity = entry.get('rarity', {}).get('name', '') if isinstance(entry.get('rarity'), dict) else entry.get('rarity', '')
        wear_count = RARITY_TO_WEAR_COUNT.get(rarity, 2)
        wears = wears[:wear_count]

        # 分配 local_id
        wear_records = []
        for w in wears:
            mhn = f"{mhn_base} ({w})"
            wear_records.append({
                'wear_en': w,
                'local_id': str(next_id),
                'marketHashName': mhn,
            })
            next_id += 1

        new_items.append({
            'name': mhn_base,
            'weapon': (entry.get('weapon', {}) or {}).get('name', ''),
            'category': cat,
            'rarity': rarity,
            'tier': 'high' if rarity in ('Covert', 'Classified', 'Contraband') else 'low',
            'wear_count': wear_count,
            'wears': wear_records,
        })

    print(f'  发现 {len(new_items)} 个新 base skin')

    total_wears = sum(len(it['wears']) for it in new_items)
    summary = {
        'total_new_items': len(new_items),
        'total_new_wears': total_wears,
        'id_segment': f'{local_max + 1}-{next_id - 1}' if new_items else 'none',
    }
    print(f'  共 {total_wears} 条 wear 变体, 段位 {summary["id_segment"]}')

    return {
        'generated': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'source': src.name,
        'local_max_id': local_max,
        'next_id': local_max + 1,
        'category_filter': category,
        'new_items': new_items,
        'summary': summary,
    }


def print_plan(plan: dict):
    print()
    print('=' * 78)
    print('  增量 ID 同步计划 (plan_incremental_ids.py)')
    print('=' * 78)
    s = plan['summary']
    print(f"  来源: {plan['source']}")
    print(f"  当前 max_id: {plan['local_max_id']}")
    print(f"  新增物品: {s['total_new_items']} 个")
    print(f"  新增 wear 变体: {s['total_new_wears']} 条")
    print(f"  段位: {s['id_segment']}")
    print()
    print('  前 5 个新物品:')
    for it in plan['new_items'][:5]:
        first_id = it['wears'][0]['local_id'] if it['wears'] else '?'
        last_id = it['wears'][-1]['local_id'] if it['wears'] else '?'
        print(f"    [{it['rarity']:<14}] {it['name']:<40} ({it['wear_count']} wear, {first_id}-{last_id})")
    if len(plan['new_items']) > 5:
        print(f"    ... 还有 {len(plan['new_items']) - 5} 个")
    print()
    print('  下一步:')
    print('    1) 跑 tools/finalize_incremental.py 写入三件套')
    print('    2) 跑 tools/crawl_incremental_typeval.py (待补 typeVal)')
    print('    3) 跑 tools/verify_id_full_coverage.py 验收')
    print('=' * 78)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--category', help='限定类别 (Rifles/Pistols/Gloves/...)')
    ap.add_argument('--dry-run', action='store_true', help='只打印, 不写文件')
    ap.add_argument('--no-save', action='store_true', help='不保存 plan json')
    args = ap.parse_args()

    plan = build_plan(category=args.category, dry_run=args.dry_run)
    print_plan(plan)

    if not args.dry_run and not args.no_save:
        out = MAPS / 'incremental_id_plan.json'
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\n[SAVE] {out.name}')


if __name__ == '__main__':
    main()
