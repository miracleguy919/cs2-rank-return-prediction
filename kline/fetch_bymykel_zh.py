#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_bymykel_zh.py
===================
下载 bymykel zh-CN 完整数据并保存到本地缓存 (使用 requests)。

数据源: https://cdn.jsdelivr.net/gh/ByMykel/CSGO-API/public/api/zh-CN/skins.json
权威性: 来自 Valve 官方 items_game.txt 的中文翻译 (与 SteamDT 译名一致)
"""
import json
import sys
import time
from pathlib import Path
from datetime import datetime

try:
    import requests
except ImportError:
    print('ERROR: 需要 requests 库, pip install requests')
    sys.exit(1)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = Path(__file__).parent.parent
MAPS = ROOT / 'mappings'

URL_ZH = 'https://cdn.jsdelivr.net/gh/ByMykel/CSGO-API/public/api/zh-CN/skins.json'
URL_EN = 'https://cdn.jsdelivr.net/gh/ByMykel/CSGO-API/public/api/en/skins.json'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json,text/plain,*/*',
}


def fetch_with_retry(url, max_retries=5):
    """带重试的 GET 请求"""
    last_err = None
    for i in range(max_retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60, verify=True)
            r.raise_for_status()
            return r.content
        except Exception as e:
            last_err = e
            wait = 2 ** i
            print(f'  retry {i+1}/{max_retries} after {wait}s: {type(e).__name__}: {e}')
            time.sleep(wait)
    raise last_err


print('=' * 70)
print('下载 bymykel zh-CN 完整数据')
print('=' * 70)

for url, label, out_path in [
    (URL_ZH, 'zh-CN', MAPS / 'bymykel_zh_skins.json'),
    (URL_EN, 'en',    MAPS / 'bymykel_en_skins.json'),
]:
    print(f'\n[{label}] 下载 {url} ...')
    raw = fetch_with_retry(url)
    data = json.loads(raw.decode('utf-8'))
    print(f'  总数: {len(data)}')

    if out_path.exists():
        bak = out_path.with_suffix(f'.json.bak_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        out_path.rename(bak)
        print(f'  备份: {bak.name}')

    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    size_kb = len(out_path.read_text(encoding='utf-8')) // 1024
    print(f'  写入: {out_path.name} ({size_kb} KB)')

# 统计
print('\n' + '=' * 70)
print('统计')
print('=' * 70)
zh_data = json.load(open(MAPS / 'bymykel_zh_skins.json', encoding='utf-8'))
category_count = {}
weapon_count = {}
for s in zh_data:
    cat = s['category']['name']
    wpn = s['weapon']['name']
    category_count[cat] = category_count.get(cat, 0) + 1
    weapon_count[wpn] = weapon_count.get(wpn, 0) + 1

print(f'\n分类:')
for cat, cnt in sorted(category_count.items(), key=lambda x: -x[1]):
    print(f'  {cat:<10} {cnt:>4}')
print(f'\n武器 top 10:')
for wpn, cnt in sorted(weapon_count.items(), key=lambda x: -x[1])[:10]:
    print(f'  {wpn:<20} {cnt:>4}')
print('=' * 70)
