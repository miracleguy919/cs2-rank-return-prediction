#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_id_full_coverage.py
==========================
两套 ID 体系全量验收 + K线可抓取覆盖率报告�?
检查项 (2026-06-04 重构):
  1. local_id   (itemid.txt  5�? 项目自创)
  2. kline_id   (cache �?platformList[C5].itemId ?? steamdt_typeVal)
                �?C5 itemId === steamdt_typeVal === HaloSkins ID (同一�?ID)
  3. local_id <-> market_map <-> cache  三向一致�?
缺口分类 (2026-06-04 新增):
  - truly_missing: 皮肤本身不存在该 wear (max_float < 0.45 for BS)
  - crawl_failed:  存在但爬取失�?  - pending:       未尝试爬�?(_pending_c5 / _pending_typeval 标记)

按类别细�?
  - 一�?二代/三代手套 (Legacy Gloves)        itemid.txt + cache
  - 四代手套 (Dead Hand)                       dead_hand_meta.json + cache
  - 武器 (Rifles+Pistols)                     weapons_meta.json + cache
  - 探员 (Agents)                             itemid.txt + cache
  - 刀 (Knives)                               itemid.txt + cache
  - 收藏�?武库/下级 (Collections/Stash)      itemid.txt + cache

输出:
  - 终端摘要报告
  - mappings/id_gaps_report.json   详细缺口清单 (�?local_id / mhn / status)

用法:
  python verify/verify_id_full_coverage.py
  python verify/verify_id_full_coverage.py --json-only
  python verify/verify_id_full_coverage.py --category weapons
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

BS_THRESHOLD = 0.45  # BS 磨损�?float 段是 (0.45, 1.0)


def load_itemid_ids() -> dict:
    """�?itemid.txt 读取所�?local_id -> 文本�?    返回: {local_id_str: full_line_text}
    """
    out = {}
    for line in (MAPS / 'itemid.txt').read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        m = re.match(r'^(\d+)[�?](.*)$', line)
        if m:
            text = m.group(2).strip()
            if text:  # 过滤空号
                out[m.group(1)] = text
    return out


def load_market_map() -> dict:
    """market_map: local_id_str -> marketHashName"""
    return json.load(open(MAPS / 'itemid_market_map.json', encoding='utf-8'))


def load_cache_index() -> dict:
    """cache: marketHashName -> entry
    返回: {mhn: entry_dict}
    """
    out = {}
    cache = json.load(open(MAPS / 'all_items_cache.json', encoding='utf-8'))
    for entry in cache:
        mhn = entry.get('marketHashName')
        if mhn:
            out[mhn] = entry
    return out


def has_kline_id(entry) -> bool:
    """是否�?K线抓�?ID (C5 itemId / steamdt_typeVal, 同一�?ID 的两个存放位�?
    2026-06-03 重构: 不再区分 C5 vs typeVal
    """
    if not entry:
        return False
    if get_kline_id(entry):
        return True
    return False


def get_kline_id(entry):
    """获取 K线抓�?ID (优先 C5 platformList, fallback steamdt_typeVal)
    2026-06-03 重构: 合并 C5 �?typeVal 为单一指标
    """
    if not entry:
        return None
    for p in entry.get('platformList', []):
        if p.get('name') == 'C5':
            v = p.get('itemId')
            if v:
                return str(v)
    tv = entry.get('steamdt_typeVal')
    if tv and tv != 'null':
        return str(tv)
    return None


def get_steamdt_typeval(entry) -> str:
    """保留: 直接�?steamdt_typeVal 字段, 用于诊断"""
    if not entry:
        return None
    tv = entry.get('steamdt_typeVal')
    if tv and tv != 'null':
        return str(tv)
    return None


def is_in_dh_meta(local_id) -> bool:
    """是否�?dead_hand_meta.json �?""
    dh = json.load(open(MAPS / 'dead_hand_meta.json', encoding='utf-8'))
    for fin in dh.get('finishes', []):
        for w in fin.get('wears', []):
            if str(w.get('local_id')) == str(local_id):
                return True
    return False


def get_dh_typeval(local_id) -> str:
    dh = json.load(open(MAPS / 'dead_hand_meta.json', encoding='utf-8'))
    for fin in dh.get('finishes', []):
        for w in fin.get('wears', []):
            if str(w.get('local_id')) == str(local_id):
                return w.get('steamdt_typeVal')
    return None


def is_in_weapons_meta(local_id) -> bool:
    """是否�?weapons_meta.json �?""
    wm = json.load(open(MAPS / 'weapons_meta.json', encoding='utf-8'))
    for it in wm.get('items', []):
        for w in it.get('wear_variants', []):
            if str(w.get('local_id')) == str(local_id):
                return True
    return False


def get_weapons_typeval(local_id) -> str:
    wm = json.load(open(MAPS / 'weapons_meta.json', encoding='utf-8'))
    for it in wm.get('items', []):
        for w in it.get('wear_variants', []):
            if str(w.get('local_id')) == str(local_id):
                return w.get('steamdt_typeVal')
    return None


def categorize_local_ids(itemid_map: dict, market_map: dict, cache_index: dict) -> dict:
    """�?local_id 按类别分�?    规则 (优先�?cache.category_zh, fallback �?itemid.txt 文本):
      - Dead Hand Gloves (cache.category_zh == '手套' AND ID in 21808-21917)
      - Weapons (cache.category_zh in ['步枪','手枪'])
      - Agents (cache.category_zh == '探员')
      - Legacy Gloves (cache.category_zh == '手套' OR (mhn �?'�? 开�?)
      - Knives (cache.category_zh == '匕首' OR mhn �?'�? 开头且 '刀' in mhn)
      - 其他�?ID �?fallback
    """
    cats = {
        'legacy_gloves': [],
        'dead_hand': [],
        'weapons': [],
        'agents': [],
        'knives': [],
        'collections': [],
        'stash': [],
        'sub_tier': [],
        'unknown': [],
    }
    for lid in itemid_map:
        lid_int = int(lid)
        text = itemid_map[lid]
        mhn = market_map.get(lid, '')
        cache_entry = cache_index.get(mhn, {})
        category_zh = cache_entry.get('category_zh', '')

        # 优先�?cache.category_zh, �?ID 段位更可�?        if 21808 <= lid_int <= 21917:
            cats['dead_hand'].append(lid)
        elif 21918 <= lid_int <= 24432:
            # 武器�?ID 优先 (cache 可能错标�?匕首"�?
            cats['weapons'].append(lid)
        elif category_zh in ('步枪', '手枪', '重型武器', '微型冲锋�?, '霰弹'):
            cats['weapons'].append(lid)
        elif category_zh == '探员':
            cats['agents'].append(lid)
        elif category_zh == '匕首':
            cats['knives'].append(lid)
        elif mhn.startswith('�?):
            # �?开头的可能�?legacy 手套或刀
            knife_kw = ('刀' in mhn or '爪子' in mhn or '蝴蝶' in mhn or 'M9' in mhn
                        or '刺刀' in mhn or '锯齿' in mhn or '骷髅' in mhn or '折叠' in mhn
                        or 'Karambit' in mhn or 'Bayonet' in mhn or 'Butterfly' in mhn
                        or 'Talon' in mhn or 'Flip' in mhn or 'Skeleton' in mhn
                        or 'Stiletto' in mhn or 'Ursus' in mhn or 'Nomad' in mhn
                        or 'Survival' in mhn or 'Paracord' in mhn or 'Classic' in mhn
                        or 'Kukri' in mhn or 'Huntsman' in mhn or 'Falchion' in mhn
                        or 'Shadow Daggers' in mhn or 'Bowie' in mhn or 'Navaja' in mhn
                        or 'Gut' in mhn)
            if knife_kw:
                cats['knives'].append(lid)
            else:
                cats['legacy_gloves'].append(lid)
        elif category_zh == '手套':
            cats['legacy_gloves'].append(lid)
        elif 11000 <= lid_int <= 13865:
            # 11000-13865 �? 优先�?mhn 是否 �?开�?(legacy 手套)
            # �?开头的已在上面处理,这里只剩探员
            cats['agents'].append(lid)
        elif lid_int < 10000:
            # 一�?二代/三代手套 + 刀 (按区段头判断)
            if '刀' in text or '爪子' in text or '蝴蝶' in text or 'M9' in text or '刺刀' in text or '锯齿' in text or '骷髅' in text or '折叠' in text:
                cats['knives'].append(lid)
            else:
                cats['legacy_gloves'].append(lid)
        else:
            cats['unknown'].append(lid)
    return cats


def is_pending(entry) -> bool:
    """是否标记为待爬取"""
    if not entry:
        return True
    return entry.get('_pending_c5') or entry.get('_pending_typeval')


def classify_gap(local_id: str, mhn: str, cache_entry, wm_entry) -> str:
    """分类缺口状�?
      - 'truly_missing': 皮肤本身不存在该 wear (max_float < 0.45 for BS)
      - 'pending':       标记为待爬取 (皮肤应该存在)
      - 'crawl_failed':  其他 (�?kline_id, �?truly_missing, �?pending)

    优先�? truly_missing > pending > crawl_failed
    """
    # 优先检�?truly_missing (客观事实, 优先�?pending 标记)
    if wm_entry and wm_entry.get('max_float') is not None:
        # BS 磨损检�?(mhn 包含 "Battle-Scarred" �?"战痕" �?"BS ")
        is_bs = ('Battle-Scarred' in mhn or '战痕' in mhn
                 or '(BS)' in mhn or '战痕累累' in mhn)
        if is_bs and wm_entry['max_float'] <= BS_THRESHOLD:
            return 'truly_missing'
    # 其次检�?pending 标记
    if is_pending(cache_entry):
        return 'pending'
    return 'crawl_failed'


def get_wm_entry(local_id: str):
    """�?weapons_meta �?local_id 对应条目"""
    wm = json.load(open(MAPS / 'weapons_meta.json', encoding='utf-8'))
    for it in wm.get('items', []):
        for w in it.get('wear_variants', []):
            if str(w.get('local_id')) == str(local_id):
                return {
                    'max_float': it.get('max_float'),
                    'min_float': it.get('min_float'),
                    'name_zh': it.get('name_zh', it.get('name', '')),
                }
    return None


def build_report(cats: dict, itemid_map: dict, market_map: dict, cache_index: dict) -> dict:
    """构建覆盖率报�?""
    report = {
        'generated': 'verify_id_full_coverage.py',
        'total_ids': len(itemid_map),
        'categories': {},
    }

    for cat, lids in cats.items():
        if not lids:
            continue
        local_total = len(lids)

        market_covered = sum(1 for lid in lids if str(lid) in market_map)
        cache_covered = sum(1 for lid in lids if market_map.get(str(lid)) in cache_index)
        kline_id_covered = 0
        gaps = []
        dh_meta_match = 0
        weapons_meta_match = 0

        for lid in lids:
            mhn = market_map.get(str(lid))
            cache_entry = cache_index.get(mhn) if mhn else None

            # 优先�? dh_meta > weapons_meta > cache
            kline_id = None
            if cat == 'dead_hand' and is_in_dh_meta(lid):
                tv_dh = get_dh_typeval(lid)
                if tv_dh and tv_dh != 'null':
                    kline_id = str(tv_dh)
                    dh_meta_match += 1
            elif cat == 'weapons' and is_in_weapons_meta(lid):
                tv_w = get_weapons_typeval(lid)
                if tv_w and tv_w != 'null':
                    kline_id = str(tv_w)
                    weapons_meta_match += 1

            if not kline_id:
                kline_id = get_kline_id(cache_entry)

            if kline_id:
                kline_id_covered += 1
            else:
                # 分类缺口
                wm_e = get_wm_entry(lid) if cat == 'weapons' else None
                status = classify_gap(lid, mhn or '', cache_entry, wm_e)
                gap_info = {
                    'local_id': lid,
                    'mhn': mhn,
                    'in_market_map': str(lid) in market_map,
                    'in_cache': cache_entry is not None,
                    'has_kline_id': False,
                    'status': status,
                }
                if wm_e:
                    gap_info['max_float'] = wm_e.get('max_float')
                gaps.append(gap_info)

        report['categories'][cat] = {
            'total': local_total,
            'in_market_map': market_covered,
            'in_cache': cache_covered,
            'has_kline_id': kline_id_covered,
            'kline_id_pct': round(100 * kline_id_covered / local_total, 1) if local_total else 0,
            'gaps': gaps,
        }
        if dh_meta_match:
            report['categories'][cat]['from_dh_meta'] = dh_meta_match
        if weapons_meta_match:
            report['categories'][cat]['from_weapons_meta'] = weapons_meta_match
    return report


def print_summary(report: dict):
    print('=' * 78)
    print('  ID 覆盖率全量验收报�?(verify_id_full_coverage.py)')
    print('=' * 78)
    print()
    print(f"  生成时间: 2026-06-03 (重构: 2 �?ID 体系)")
    print(f"  itemid.txt 总条�? {report['total_ids']}")
    print()
    print(f"  {'类别':<22}{'总数':>8}{'market_map':>12}{'cache':>8}{'kline_id 覆盖':>14}")
    print('  ' + '-' * 64)

    # 中英文类别映�?    cat_cn = {
        'legacy_gloves': '一�?�?三代手套',
        'dead_hand':     '四代手套 (Dead Hand)',
        'weapons':       '武器 (Rifles+Pistols)',
        'agents':        '探员',
        'knives':        '刀�?,
        'collections':   '收藏�?,
        'stash':         '武库',
        'sub_tier':      '下级',
        'unknown':       '未分�?,
    }

    for cat, stats in report['categories'].items():
        label = cat_cn.get(cat, cat)
        print(f"  {label:<22}{stats['total']:>8}{stats['in_market_map']:>12}{stats['in_cache']:>8}"
              f"{stats['kline_id_pct']:>13.1f}%")

    # 缺口分类统计
    print()
    print('  ' + '=' * 70)
    print('  缺口分类摘要:')
    print('  ' + '-' * 70)
    status_count = {'truly_missing': 0, 'pending': 0, 'crawl_failed': 0}
    status_cn = {'truly_missing': '真正不存�?, 'pending': '待爬�?, 'crawl_failed': '爬取失败'}
    for cat, stats in report['categories'].items():
        for g in stats['gaps']:
            s = g.get('status', 'crawl_failed')
            status_count[s] = status_count.get(s, 0) + 1
    for s, cnt in status_count.items():
        print(f'  [{status_cn[s]}] {cnt} �?)
    print()
    if status_count['crawl_failed'] == 0 and status_count['pending'] == 0:
        print('  �?所有缺口都属于 truly_missing (皮肤本身不存�?')

    print()
    print('  ' + '=' * 70)
    print('  说明 (2026-06-04 重构�?:')
    print('    - 2 �?ID 体系: local_id (项目) + kline_id (K线抓取用)')
    print('    - kline_id = C5 itemId ?? steamdt_typeVal (C5 == typeVal, 同一�?ID)')
    print('    - kline_id 优先�?dead_hand_meta / weapons_meta �?(更可�?')
    print('    - 缺口分类: truly_missing / pending / crawl_failed')
    print('    - 真正不存在清�? mappings/special_wear_skins.json')
    print('    - 详细缺口: mappings/id_gaps_report.json')
    print('=' * 78)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json-only', action='store_true', help='只输�?JSON, 不打印摘�?)
    ap.add_argument('--category', help='只检查某个类�?(legacy_gloves/dead_hand/weapons/...)')
    ap.add_argument('--no-save', action='store_true', help='不保�?id_gaps_report.json')
    args = ap.parse_args()

    print('[1/3] 加载映射三件�?...')
    itemid_map = load_itemid_ids()
    market_map = load_market_map()
    cache_index = load_cache_index()
    print(f'  itemid.txt: {len(itemid_map)} local_id')
    print(f'  market_map: {len(market_map)} keys')
    print(f'  cache: {len(cache_index)} mhn')

    print('[2/3] 分类 local_id ...')
    cats = categorize_local_ids(itemid_map, market_map, cache_index)
    for cat, lids in cats.items():
        if lids:
            print(f'  {cat}: {len(lids)} �?)

    print('[3/3] 构建覆盖率报�?...')
    report = build_report(cats, itemid_map, market_map, cache_index)

    if not args.json_only:
        print_summary(report)

    if not args.no_save:
        out_path = MAPS / 'id_gaps_report.json'
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if not args.json_only:
            print(f'\n[SAVE] {out_path.name}')


if __name__ == '__main__':
    main()
