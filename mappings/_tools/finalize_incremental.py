#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
finalize_incremental.py
=======================
把 incremental_id_plan.json 写入三件套 (幂等保护, 可重跑)。

输入:
  mappings/incremental_id_plan.json
  {
    "new_items": [
      {
        "name": "...",
        "wears": [
          {"wear_en": "FN", "local_id": "24433", "marketHashName": "..."},
          ...
        ]
      },
      ...
    ]
  }

输出 (写):
  1. mappings/itemid.txt              新增条目
  2. mappings/itemid_market_map.json  +keys
  3. mappings/all_items_cache.json     +entries (steamdt_typeVal=null 等补抓)

特性:
  - 幂等: 已存在的 local_id / mhn 自动跳过
  - 自动备份: 写入前 .bak_incremental_{ts}
  - 中文名: 从 bymykel 查 name_zh, 找不到用英文

用法:
  # 干跑
  python tools/finalize_incremental.py --dry-run

  # 实际写入
  python tools/finalize_incremental.py

  # 指定 plan
  python tools/finalize_incremental.py --plan mappings/incremental_id_plan.json
"""
import argparse
import json
import re
import shutil
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

WEAR_CN = {
    'Factory New': '崭新', 'Minimal Wear': '略磨', 'Field-Tested': '久经',
    'Well-Worn': '破损', 'Battle-Scarred': '战痕',
}


def load_existing_local_ids() -> set:
    ids = set()
    for line in (MAPS / 'itemid.txt').read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        m = re.match(r'^(\d+)[：:]', line)
        if m and m.group(2).strip():
            ids.add(m.group(1))
    return ids


def load_existing_mhns() -> set:
    cache = json.load(open(MAPS / 'all_items_cache.json', encoding='utf-8'))
    return {e.get('marketHashName') for e in cache if e.get('marketHashName')}


def load_bymykel_zh_map() -> dict:
    """mhn -> name_zh 映射"""
    src = MAPS / 'bymykel_zh_skins.json'
    if not src.exists():
        return {}
    data = json.load(open(src, encoding='utf-8'))
    return {e.get('name'): e.get('name_zh') or e.get('name') for e in data}


def strip_wear(mhn: str) -> str:
    return re.sub(r'\s*\([^)]+\)\s*$', '', mhn)


def build_zh_name(it: dict, bymykel_zh: dict) -> str:
    """生成中文名: {磨损}{武器}{皮肤}"""
    base_mhn = it['name']  # 已剥 wear
    cn = bymykel_zh.get(f"{base_mhn} (Factory New)") or bymykel_zh.get(base_mhn)
    if not cn:
        cn = base_mhn  # fallback to 英文
    # 武器名保留英文 (如 AK-47, AWP, M4A1-S)
    # 皮肤名用中文
    # 简单策略: 如果 cn 含中文就用 cn, 否则用 base_mhn
    if not any('\u4e00' <= c <= '\u9fff' for c in cn):
        cn = base_mhn
    # 拆 "武器 | 皮肤"
    if ' | ' in cn:
        weapon_zh, skin_zh = cn.split(' | ', 1)
    elif '|' in cn:
        weapon_zh, skin_zh = cn.split('|', 1)
    else:
        # 没有分隔符, 用 base_mhn 拆
        parts = base_mhn.split(' | ')
        if len(parts) == 2:
            weapon_zh, skin_zh = parts
        else:
            weapon_zh, skin_zh = '', base_mhn
    weapon_zh = weapon_zh.strip()
    skin_zh = skin_zh.strip()

    # 第一个 wear 决定中文名前缀
    first_wear = it['wears'][0]['wear_en'] if it['wears'] else 'Factory New'
    wear_cn = WEAR_CN.get(first_wear, '崭新')
    return f"{wear_cn}{weapon_zh}{skin_zh}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', default=str(MAPS / 'incremental_id_plan.json'),
                    help='incremental_id_plan.json 路径')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.exists():
        print(f'❌ plan 文件不存在: {plan_path}')
        print('   请先跑: python tools/plan_incremental_ids.py')
        sys.exit(1)

    plan = json.load(open(plan_path, encoding='utf-8'))
    new_items = plan.get('new_items', [])
    if not new_items:
        print('⚠️  plan 中无 new_items, 退出')
        return

    print('=' * 78)
    print('  finalize_incremental.py - 增量写入三件套')
    print('=' * 78)
    print(f'  Plan: {plan_path.name}')
    print(f'  新物品: {len(new_items)} 个, 共 {sum(len(it["wears"]) for it in new_items)} 条 wear')
    print(f'  模式: {"DRY-RUN" if args.dry_run else "WRITE"}')
    print()

    # 加载既有数据
    print('[1/4] 加载既有数据 ...')
    existing_ids = load_existing_local_ids()
    existing_mhns = load_existing_mhns()
    bymykel_zh = load_bymykel_zh_map()
    print(f'  既有 local_id: {len(existing_ids)}')
    print(f'  既有 mhn: {len(existing_mhns)}')

    if not args.dry_run:
        print('\n[BACKUP] 备份三件套 ...')
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        for name in ['itemid.txt', 'itemid_market_map.json', 'all_items_cache.json']:
            src = MAPS / name
            if src.exists():
                dst = src.with_suffix(src.suffix + f'.bak_incremental_{ts}')
                shutil.copy2(src, dst)
                print(f'  {name} -> {dst.name}')

    # 收集待写入
    new_itemid_lines = []
    new_market_map = {}
    new_cache_entries = []
    skipped_existing = 0
    skipped_dup = 0
    new_wear_count = 0

    print('\n[2/4] 构造待写入条目 ...')
    for it in new_items:
        cn_name = build_zh_name(it, bymykel_zh)
        for w in it['wears']:
            lid = w['local_id']
            mhn = w['marketHashName']
            if lid in existing_ids:
                skipped_existing += 1
                continue
            if mhn in existing_mhns:
                skipped_dup += 1
                continue
            new_itemid_lines.append(f"{lid}：{cn_name}")
            new_market_map[lid] = mhn
            new_cache_entries.append({
                'name': mhn,
                'shortName': strip_wear(mhn),
                'marketHashName': mhn,
                'platformList': [],
                'rarity': it.get('rarity', ''),
                'category': it.get('category', ''),
                'wear_cn': WEAR_CN.get(w['wear_en'], '崭新'),
                'wear_en': w['wear_en'],
                'steamdt_typeVal': None,
                '_pending_typeval': True,
                'source': f'incremental_sync ({plan.get("generated", "")})',
            })
            new_wear_count += 1

    print(f'  待写入: {new_wear_count} 条')
    print(f'  跳过 (lid 已存在): {skipped_existing}')
    print(f'  跳过 (mhn 已存在): {skipped_dup}')

    if not new_itemid_lines:
        print('\n⚠️  无新条目 (全部已存在), 退出')
        return

    if not args.dry_run:
        # 写 itemid.txt
        print('\n[3/4] 写入 itemid.txt ...')
        with open(MAPS / 'itemid.txt', 'a', encoding='utf-8') as f:
            for line in new_itemid_lines:
                f.write(line + '\n')
        print(f'  追加 {len(new_itemid_lines)} 行')

        # 写 market_map
        print('\n[4/4] 写入 itemid_market_map.json + all_items_cache.json ...')
        market = json.load(open(MAPS / 'itemid_market_map.json', encoding='utf-8'))
        market.update(new_market_map)
        json.dump(market, open(MAPS / 'itemid_market_map.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        print(f'  market_map +{len(new_market_map)} keys')

        # 写 cache
        cache = json.load(open(MAPS / 'all_items_cache.json', encoding='utf-8'))
        cache.extend(new_cache_entries)
        json.dump(cache, open(MAPS / 'all_items_cache.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        print(f'  cache +{len(new_cache_entries)} entries')

        print()
        print('=' * 78)
        print('  ✅ 写入完成, 建议跑:')
        print('     python tools/verify_id_full_coverage.py')
        print('     python tools/crawl_weapons_typeval.py  (补 typeVal)')
        print('=' * 78)
    else:
        print()
        print('  [DRY-RUN] 不写文件')
        print('  前 3 个新条目预览:')
        for line in new_itemid_lines[:3]:
            print(f'    {line}')


if __name__ == '__main__':
    main()
