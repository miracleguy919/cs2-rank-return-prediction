#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_bymykel_agents.py
========================
下载 bymykel agents.json (zh + en) 到本地缓存。

数据源: https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/{lang}/agents.json
字段: id / name (中文) / def_index / rarity / team / market_hash_name / image / model_player
"""
import json
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = Path(__file__).parent.parent
MAPS = ROOT / 'mappings'

URL_ZH = 'https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/zh-CN/agents.json'
URL_EN = 'https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/agents.json'


def fetch_with_curl(url, out_path, max_retries=5):
    """用 curl 下载 (绕过 SSL 问题)"""
    last_err = None
    for i in range(max_retries):
        try:
            cmd = ['curl.exe', '-L', '-s', '-o', str(out_path), '--ssl-no-revoke', url]
            r = subprocess.run(cmd, capture_output=True, timeout=120)
            if r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                return out_path.read_bytes()
            last_err = f'curl rc={r.returncode}, stderr={r.stderr.decode(errors="ignore")[:200]}'
        except Exception as e:
            last_err = f'{type(e).__name__}: {e}'
        wait = 2 ** i
        print(f'  retry {i+1}/{max_retries} after {wait}s: {last_err}')
        time.sleep(wait)
    raise RuntimeError(last_err)


print('=' * 70)
print('下载 bymykel agents.json (zh + en)')
print('=' * 70)

for url, label, out_path in [
    (URL_ZH, 'zh-CN', MAPS / 'bymykel_zh_agents.json'),
    (URL_EN, 'en',    MAPS / 'bymykel_en_agents.json'),
]:
    print(f'\n[{label}] 下载 {url} ...')
    raw = fetch_with_curl(url, out_path)
    data = json.loads(raw.decode('utf-8'))
    print(f'  总数: {len(data)} 条')

    if out_path.exists():
        bak = out_path.with_suffix(f'.json.bak_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        if bak.exists() is False:
            out_path.rename(bak)
            print(f'  备份: {bak.name}')

    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    size_kb = len(out_path.read_text(encoding='utf-8')) // 1024
    print(f'  写入: {out_path.name} ({size_kb} KB)')

# 统计
print('\n' + '=' * 70)
print('统计')
print('=' * 70)
zh = json.load(open(MAPS / 'bymykel_zh_agents.json', encoding='utf-8'))
team_count = {}
rarity_count = {}
for a in zh:
    team = a.get('team', {}).get('name', '?')
    rarity = a.get('rarity', {}).get('name', '?')
    team_count[team] = team_count.get(team, 0) + 1
    rarity_count[rarity] = rarity_count.get(rarity, 0) + 1

print(f'\n阵营:')
for t, c in sorted(team_count.items(), key=lambda x: -x[1]):
    print(f'  {t:<10} {c:>3}')
print(f'\n稀有度:')
for r, c in sorted(rarity_count.items(), key=lambda x: -x[1]):
    print(f'  {r:<10} {c:>3}')

# 验证 mhn 唯一性
mhns = [a.get('market_hash_name') for a in zh if a.get('market_hash_name')]
print(f'\n有 mhn: {len(mhns)}')
print(f'mhn 唯一: {len(set(mhns))}')
print(f'\n===== 前 5 条样本 =====')
for a in zh[:5]:
    print(f'  pi={a["def_index"]} mhn={a["market_hash_name"]}')
    print(f'    name (zh): {a["name"]}')
    print(f'    team: {a["team"]["name"]}, rarity: {a["rarity"]["name"]}')

print('=' * 70)
