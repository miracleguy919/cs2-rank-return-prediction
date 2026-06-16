#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_itemid_to_zh.py
=======================
重写 itemid.txt 中"武器皮肤"段的所有条目的中文名称。

策略:
  - itemid.txt 武器段是 {id}：{wear}{name_cn}{weapon}  格式
  - 例如: "9839：崭新二西莫夫ak"  ->  译: "9839：崭新 二西莫夫ak"
  - 通过 market_map.json 找到 mhn -> weapons_meta[name_zh] -> 翻译
  - 武器段 (id >= 21918) 全部按 name_zh 重写
  - 段位 (5 位短 ID < 21918) 保留, 不动
  - 探员/手套/刀等其他段不动

输出:
  重写后的 itemid.txt
"""
import json
import re
import sys
from pathlib import Path
from datetime import datetime

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = Path(__file__).parent.parent.parent
MAPS = ROOT / 'mappings'

WEAR_CN = {
    'Factory New': '崭新',
    'Minimal Wear': '略磨',
    'Field-Tested': '久经',
    'Well-Worn': '破损',
    'Battle-Scarred': '战痕',
}

# 武器段起始 ID (来自 finalize_weapons.py)
WEAPON_ID_START = 21918


def parse_itemid_line(line: str) -> tuple:
    """解析 itemid.txt 一行: 'id：name' -> (id_int, name_str)"""
    line = line.strip()
    if not line or line.startswith('//') or line.startswith('#'):
        return None, line
    m = re.match(r'^(\d+)[：:]\s*(.*)$', line)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, line


def main():
    print('=' * 70)
    print('重写 itemid.txt 武器段为中文')
    print('=' * 70)

    # 1. 加载数据
    print('\n[1/4] 加载数据...')
    meta = json.load(open(MAPS / 'weapons_meta.json', encoding='utf-8'))
    market_map = json.load(open(MAPS / 'itemid_market_map.json', encoding='utf-8'))
    print(f'  meta: {len(meta["items"])} 条')
    print(f'  market_map: {len(market_map)} 条')

    # 2. 构建 id -> name_zh 映射
    print('\n[2/4] 构建 id -> 中文名 映射...')
    # id -> (weapon, paint_zh, wear_cn)
    id_to_zh = {}
    for item in meta['items']:
        pi = item.get('paint_index')
        pattern_zh = item.get('pattern_zh', '')
        weapon_en = item.get('weapon', '')
        weapon_zh = item.get('weapon_zh', weapon_en)
        wear_variants = item.get('wear_variants', [])

        for wv in wear_variants:
            mhn = wv.get('marketHashName')
            wear_en = wv.get('wear_en', '')
            wear_cn = WEAR_CN.get(wear_en, '')
            # id 从 market_map 里查
            for lid_str, m in market_map.items():
                if m == mhn:
                    id_to_zh[int(lid_str)] = {
                        'weapon_zh': weapon_zh,
                        'pattern_zh': pattern_zh,
                        'wear_cn': wear_cn,
                        'wear_en': wear_en,
                        'mhn': mhn,
                    }
                    break

    print(f'  id -> zh 映射: {len(id_to_zh)} 条')

    # 3. 解析 itemid.txt
    print('\n[3/4] 解析并重写 itemid.txt...')
    itemid_path = MAPS / 'itemid.txt'
    lines = itemid_path.read_text(encoding='utf-8').splitlines()

    out_lines = []
    in_weapon_section = False
    current_section = None
    updated_count = 0
    skipped_count = 0
    not_found = []
    found_in_section = {}

    # 段位关键字 -> 哪些段需要重写
    weapon_sections = {
        '//百战',
        '//百战 1', '//百战 2', '//百战 3', '//百战 4', '//百战 5',
        '//收藏品 1', '//收藏品 2',
        '//武库 1',
        '//一代下级 1', '//二代下级 1', '//三代下级 1',
        '//千战', '//千战 1', '//千战 2', '//千战 3', '//千战 4', '//千战 5', '//千战 6', '//千战 7',
    }

    # 找武器段: 通过分析每条 id 是否 >= 21918
    for line in lines:
        stripped = line.strip()
        lid, name = parse_itemid_line(line)

        # 注释行 / 空行 直接保留
        if lid is None:
            out_lines.append(line)
            continue

        # 非武器段 (< WEAPON_ID_START) 保留
        if lid < WEAPON_ID_START:
            out_lines.append(line)
            skipped_count += 1
            continue

        # 武器段: 重写中文
        zh = id_to_zh.get(lid)
        if zh and zh.get('pattern_zh'):
            new_name = f"{zh['wear_cn']}{zh['pattern_zh']}{zh['weapon_zh']}".lower() if False else \
                       f"{zh['wear_cn']}{zh['weapon_zh']}{zh['pattern_zh']}"
            # 项目风格: "崭新ak印花集" / "久经ak红线" / "略磨awp龙"
            # 即 {wear}{weapon_zh}{pattern_zh}
            new_line = f"{lid}：{new_name}"
            out_lines.append(new_line)
            updated_count += 1
            sec = current_section or 'unknown'
            found_in_section[sec] = found_in_section.get(sec, 0) + 1
        else:
            # 没找到中文, 保留原文
            out_lines.append(line)
            not_found.append((lid, name))

    print(f'  武器段更新: {updated_count} 条')
    print(f'  非武器段保留: {skipped_count} 条')
    print(f'  未找到中文: {len(not_found)} 条')
    if not_found:
        print(f'    前 5 个: {not_found[:5]}')
    print(f'\n  武器段分布:')
    for sec, cnt in sorted(found_in_section.items()):
        print(f'    {sec}: {cnt}')

    # 4. 写回
    print('\n[4/4] 写回 itemid.txt...')
    itemid_path.write_text('\n'.join(out_lines) + '\n', encoding='utf-8')
    print(f'  [WRITE] itemid.txt')

    # 打印前 20 条新武器段验证
    print('\n=== 重写后前 30 条 ===')
    count = 0
    for line in out_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('//'):
            lid, name = parse_itemid_line(line)
            if lid and lid >= WEAPON_ID_START:
                print(f'  {stripped}')
                count += 1
                if count >= 30:
                    break

    print('\n' + '=' * 70)
    print(f'完成: 重写 {updated_count} 条武器段')
    print('=' * 70)


if __name__ == '__main__':
    main()
