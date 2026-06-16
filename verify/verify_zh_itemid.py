#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 itemid.txt 武器段中文翻译结果"""
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

lines = (MAPS / 'itemid.txt').read_text(encoding='utf-8').splitlines()

# 统计各段
sections = {}
current = 'header'
for line in lines:
    s = line.strip()
    if s.startswith('//'):
        current = s
        sections.setdefault(current, 0)
        continue
    if not s:
        continue
    m = re.match(r'^(\d+)[：:]\s*(.*)$', s)
    if m:
        sections[current] = sections.get(current, 0) + 1

print('===== 段位统计 =====')
for sec, cnt in sections.items():
    print(f'  {sec:<25} {cnt:>4}')

# 验证武器段全是中文
print()
print('===== 武器段中文验证 =====')
weapon_lines = []
for line in lines:
    s = line.strip()
    if s.startswith('//') or not s:
        continue
    m = re.match(r'^(\d+)[：:]\s*(.*)$', s)
    if m and int(m.group(1)) >= 21918:
        weapon_lines.append((int(m.group(1)), m.group(2)))

print(f'武器段总数: {len(weapon_lines)}')
print('--- 前 25 条 ---')
for lid, name in weapon_lines[:25]:
    print(f'  {lid}: {name}')
print('--- 中间 25 条 (第 1100~1125 条) ---')
for lid, name in weapon_lines[1100:1125]:
    print(f'  {lid}: {name}')
print('--- 末 25 条 ---')
for lid, name in weapon_lines[-25:]:
    print(f'  {lid}: {name}')

# 验证是否还有英文未翻译的
print()
print('===== 检查残留英文武器段 =====')
en_residual = []
weapon_dict = {
    'AK-47', 'M4A4', 'M4A1-S', 'AWP', 'AUG', 'SG 553', 'SSG 08', 'SCAR-20', 'G3SG1',
    'FAMAS', 'Galil AR', 'Desert Eagle', 'USP-S', 'Glock-18', 'P250', 'Five-SeveN',
    'Tec-9', 'CZ75-Auto', 'P2000', 'Dual Berettas', 'R8 Revolver',
}
for lid, name in weapon_lines:
    if any(w in name for w in ['Factory New', 'Minimal Wear', 'Field-Tested', 'Well-Worn', 'Battle-Scarred']):
        en_residual.append((lid, name, 'wear-en'))
    elif any(w in name for w in weapon_dict):
        en_residual.append((lid, name, 'weapon-en'))

print(f'残留英文: {len(en_residual)} 条')
if en_residual:
    for lid, name, kind in en_residual[:10]:
        print(f'  {lid}: {name} ({kind})')
