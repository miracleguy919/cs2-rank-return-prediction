"""
重新生成 AK-47 / AWP 饰品目录（基于规范化后的 itemid.txt）
"""
import json
from pathlib import Path
from collections import defaultdict

with open('mappings/itemid_market_map.json', encoding='utf-8') as f:
    market_map = json.load(f)

itemid_path = Path('mappings/itemid.txt')
items = []
current_cat = ''
with itemid_path.open(encoding='utf-8') as f:
    for raw in f:
        line = raw.strip()
        if not line: continue
        if line.startswith('//'):
            current_cat = line[2:].strip()
            continue
        if '：' in line: parts = line.split('：', 1)
        elif ':' in line: parts = line.split(':', 1)
        else: parts = line.split(None, 1)
        item_id = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else ''
        items.append((item_id, name, current_cat))

hourly_dir = Path('data/hourly')
done_ids = {p.stem for p in hourly_dir.glob('*.json')} if hourly_dir.exists() else set()

# 用 market_map 判断武器和磨损度
ak47_all = []
awp_all = []
for item_id, zh_name, cat in items:
    if item_id not in market_map: continue
    en_name = market_map[item_id]
    if '|' not in en_name: continue
    if ' (' not in en_name: continue  # 跳过没有磨损度的（探员/手套等）
    weapon = en_name.split(' | ')[0].strip()
    skin_en = en_name.split(' | ')[1].rsplit(' (', 1)[0].strip()
    wear_en = en_name.rsplit(' (', 1)[1].rstrip(')')
    wear_zh = {'Factory New': '崭新', 'Minimal Wear': '略磨', 'Field-Tested': '久经'}.get(wear_en, '其他')
    rec = (item_id, zh_name, skin_en, wear_zh, item_id in done_ids)
    if weapon == 'AK-47':
        ak47_all.append(rec)
    elif weapon == 'AWP':
        awp_all.append(rec)

# 用户筛选规则 (AK-47) - 这些条目从全部列表中排除
ak47_exclude = {
    '22328',  # 崭新红线
    '22304', '22305',  # 略磨/久经可燃冰
    '22333',  # 崭新酷炫涂鸦皮革
    '22344', '22345',  # 略磨/久经表面淬火
}
# 全部列表（应用用户排除规则）
ak47_all_filtered = [x for x in ak47_all if x[0] not in ak47_exclude]
awp_all_filtered = list(awp_all)

# 生成文档
lines = []
lines.append('# AK-47 / AWP 饰品目录（规范化后）')
lines.append('')
lines.append('**生成时间**: 2026-06-17')
lines.append('**格式**: `{磨损}{武器}{皮肤}`（统一规范）')
lines.append('**改名记录**: AK-47 38 条 + AWP 17 条已从老别名统一为标准格式')
lines.append('')
lines.append('### 用户筛选规则（AK-47，已应用）')
lines.append('')
lines.append('| 皮肤 | 规则 | 执行 |')
lines.append('|------|------|------|')
lines.append('| 红线 | 不要崭新 | 排除 22328 崭新AK-47红线 |')
lines.append('| 可燃冰 | 只保留崭新 | 排除 22304(略磨)、22305(久经) |')
lines.append('| 酷炫涂鸦皮革 | 不要崭新 | 排除 22333(崭新) |')
lines.append('| 表面淬火 | 只保留崭新 | 排除 22344(略磨)、22345(久经) |')
lines.append('')
lines.append('---')
lines.append('')

# AK-47 完整目录（含已抓+待抓，全部列出）
ak47_done_count = sum(1 for x in ak47_all_filtered if x[4])
ak47_todo_count = len(ak47_all_filtered) - ak47_done_count
lines.append(f'## AK-47 完整目录（共 {len(ak47_all_filtered)} 条，已抓 {ak47_done_count} / 待抓 {ak47_todo_count}）')
lines.append('')
lines.append('> 说明：[x] 已抓  [ ] 待抓。已抓的也可勾选取消（标记删除）。')
lines.append('')

by_wear = defaultdict(list)
for x in ak47_all_filtered:
    by_wear[x[3]].append(x)

for wear in ('崭新', '略磨', '久经', '其他'):
    if wear not in by_wear: continue
    lines.append(f'### AK-47 - {wear} ({len(by_wear[wear])} 个)')
    lines.append('')
    lines.append('| ☐ | ID | 中文名 | 英文名 | 状态 |')
    lines.append('|----|----|--------|--------|------|')
    for item_id, zh_name, skin_en, w, done in sorted(by_wear[wear], key=lambda x: int(x[0])):
        mark = '[x]' if done else '[ ]'
        status = '已抓' if done else '待抓'
        lines.append(f'| {mark} | {item_id} | {zh_name} | {skin_en} | {status} |')
    lines.append('')

lines.append('---')
lines.append('')

# AWP 完整目录（含已抓+待抓）
awp_done_count = sum(1 for x in awp_all_filtered if x[4])
awp_todo_count = len(awp_all_filtered) - awp_done_count
lines.append(f'## AWP 完整目录（共 {len(awp_all_filtered)} 条，已抓 {awp_done_count} / 待抓 {awp_todo_count}）')
lines.append('')
lines.append('> 说明：[x] 已抓  [ ] 待抓。已抓的也可勾选取消（标记删除）。')
lines.append('')

by_wear = defaultdict(list)
for x in awp_all_filtered:
    by_wear[x[3]].append(x)

for wear in ('崭新', '略磨', '久经', '其他'):
    if wear not in by_wear: continue
    lines.append(f'### AWP - {wear} ({len(by_wear[wear])} 个)')
    lines.append('')
    lines.append('| ☐ | ID | 中文名 | 英文名 | 状态 |')
    lines.append('|----|----|--------|--------|------|')
    for item_id, zh_name, skin_en, w, done in sorted(by_wear[wear], key=lambda x: int(x[0])):
        mark = '[x]' if done else '[ ]'
        status = '已抓' if done else '待抓'
        lines.append(f'| {mark} | {item_id} | {zh_name} | {skin_en} | {status} |')
    lines.append('')

lines.append('---')
lines.append('')

# 汇总
total_all = len(ak47_all_filtered) + len(awp_all_filtered)
total_todo = ak47_todo_count + awp_todo_count
lines.append('## 汇总')
lines.append('')
lines.append(f'- AK-47 总数: **{len(ak47_all_filtered)}** | 已抓: **{ak47_done_count}** | 待抓: **{ak47_todo_count}**')
lines.append(f'- AWP 总数: **{len(awp_all_filtered)}** | 已抓: **{awp_done_count}** | 待抓: **{awp_todo_count}**')
lines.append(f'- **合计: {total_all} 条 / 待抓: {total_todo} 个**')
lines.append('')
lines.append('### 抓取配额估算')
lines.append('')
lines.append(f'- history 模式 (24 calls/item): {total_todo*24} calls (约 {total_todo*24//1100+1} 天)')
lines.append(f'- incremental 模式 (2 calls/item): {total_todo*2} calls (约 {total_todo*2//1100+1} 天)')

content = '\n'.join(lines)
out_path = Path('mappings/筛选_AK47_AWP.md')
out_path.write_text(content, encoding='utf-8')
print(f'已生成: {out_path}')
print(f'AK-47: 总 {len(ak47_all_filtered)} / 已抓 {ak47_done_count} / 待抓 {ak47_todo_count}')
print(f'AWP: 总 {len(awp_all_filtered)} / 已抓 {awp_done_count} / 待抓 {awp_todo_count}')
print(f'合计: {len(ak47_all_filtered) + len(awp_all_filtered)} 条 / 待抓: {total_todo}')
