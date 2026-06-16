#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_weapons_typeval.py
========================
把 crawl_weapons_typeval.py 的抓取结果写回 weapons_meta.json + all_items_cache.json。

输入:
  mappings/weapons_steamdt_ids.json
  {
    "results": { mhn -> {wear_en: typeVal} },
    "failures": [...]
  }

输出 (幂等, 可重跑):
  1. mappings/weapons_meta.json        → wear_variant.steamdt_typeVal
  2. mappings/all_items_cache.json     → entry.steamdt_typeVal
  3. 进度报告 mappings/typeval_apply_report.json

用法:
  # 干跑 (不写, 只看会改什么)
  python tools/apply_weapons_typeval.py --dry-run

  # 实际写入
  python tools/apply_weapons_typeval.py

  # 指定源文件
  python tools/apply_weapons_typeval.py --source mappings/weapons_steamdt_ids.json
"""
import argparse
import json
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


def backup_files():
    """写之前自动备份"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for name in ['weapons_meta.json', 'all_items_cache.json']:
        src = MAPS / name
        if src.exists():
            dst = src.with_suffix(f'.json.bak_typeval_{ts}')
            shutil.copy2(src, dst)
            print(f'  [BACKUP] {name} -> {dst.name}')


def load_crawl_results(source_path: Path) -> dict:
    """读 crawl_weapons_typeval.py 的输出"""
    data = json.load(open(source_path, encoding='utf-8'))
    return data


def apply_to_weapons_meta(crawl: dict, dry_run: bool) -> dict:
    """写回 weapons_meta.json
    crawl.results 格式: {base_name (无 wear): {wear_en: typeVal}}
    例如: {'AK-47 | X-Ray': {'Factory New': '814309374440767488', 'Minimal Wear': '...', ...}}
    """
    meta = json.load(open(MAPS / 'weapons_meta.json', encoding='utf-8'))
    results = crawl.get('results', {})

    applied = 0
    missing_in_meta = []

    for base_name, wears_map in results.items():
        if not isinstance(wears_map, dict):
            missing_in_meta.append(base_name)
            continue
        # 构造完整 mhn: "AK-47 | X-Ray (Factory New)"
        for wear_en, tv in wears_map.items():
            if not tv or tv == 'null':
                continue
            mhn = f"{base_name} ({wear_en})"
            # 在 weapons_meta 里找匹配的 wear_variant
            found = False
            for it in meta['items']:
                for w in it.get('wear_variants', []):
                    if w.get('marketHashName') == mhn and (not w.get('steamdt_typeVal') or w.get('steamdt_typeVal') == 'null'):
                        w['steamdt_typeVal'] = str(tv)
                        applied += 1
                        found = True
                        break
                if found:
                    break
            if not found:
                # 不算 missing（可能 wear 不在项目里）
                pass

    if not dry_run:
        out = MAPS / 'weapons_meta.json'
        out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'  [WRITE] weapons_meta.json: {applied} typeVal 已写入')

    return {
        'applied': applied,
        'missing_in_meta': missing_in_meta,
    }


def apply_to_cache(crawl: dict, dry_run: bool) -> dict:
    """写回 all_items_cache.json (按 mhn 完整名匹配)
    crawl.results 格式: {base_name: {wear_en: typeVal}}
    cache 条目 marketHashName 形如: "AK-47 | X-Ray (Factory New)"
    """
    cache = json.load(open(MAPS / 'all_items_cache.json', encoding='utf-8'))
    results = crawl.get('results', {})

    # 预构造 mhn -> typeVal 索引 (完整 mhn)
    mhn_to_tv = {}
    for base_name, wears_map in results.items():
        if not isinstance(wears_map, dict):
            continue
        for wear_en, tv in wears_map.items():
            if tv and tv != 'null':
                mhn = f"{base_name} ({wear_en})"
                mhn_to_tv[mhn] = str(tv)

    applied = 0
    missing_in_cache = []

    for entry in cache:
        mhn = entry.get('marketHashName')
        if not mhn:
            continue
        if mhn in mhn_to_tv:
            tv = mhn_to_tv[mhn]
            if not entry.get('steamdt_typeVal') or entry.get('steamdt_typeVal') == 'null':
                entry['steamdt_typeVal'] = tv
                applied += 1
                if '_pending_typeval' in entry:
                    del entry['_pending_typeval']

    if not dry_run:
        out = MAPS / 'all_items_cache.json'
        out.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
        size_kb = len(out.read_text(encoding='utf-8')) // 1024
        print(f'  [WRITE] all_items_cache.json: {applied} typeVal 已写入 ({size_kb} KB)')

    return {
        'applied': applied,
        'missing_in_cache': missing_in_cache,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', default=str(MAPS / 'weapons_steamdt_ids.json'),
                    help='crawl_weapons_typeval.py 的输出文件')
    ap.add_argument('--dry-run', action='store_true', help='干跑, 不写文件')
    args = ap.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f'❌ 源文件不存在: {source}')
        print('   请先跑: python tools/crawl_weapons_typeval.py')
        sys.exit(1)

    print('=' * 78)
    print('  apply_weapons_typeval.py - 把 typeVal 抓取结果写回 cache')
    print('=' * 78)
    print(f'  源文件: {source.name}')
    print(f'  模式: {"DRY-RUN (不写)" if args.dry_run else "WRITE"}')
    print()

    crawl = load_crawl_results(source)
    results = crawl.get('results', {})
    failures = crawl.get('failures', [])
    print(f'  [INPUT] {len(results)} 成功, {len(failures)} 失败')
    if not results:
        print('  ⚠️  无成功结果, 退出')
        return

    if not args.dry_run:
        backup_files()

    print('\n[1/2] 写回 weapons_meta.json ...')
    meta_report = apply_to_weapons_meta(crawl, args.dry_run)
    print(f'  applied: {meta_report["applied"]}')
    if meta_report['missing_in_meta']:
        print(f'  ⚠️  {len(meta_report["missing_in_meta"])} mhn 在 weapons_meta.json 找不到 (mhn 不匹配?)')

    print('\n[2/2] 写回 all_items_cache.json ...')
    cache_report = apply_to_cache(crawl, args.dry_run)
    print(f'  applied: {cache_report["applied"]}')
    if cache_report['missing_in_cache']:
        print(f'  ⚠️  {len(cache_report["missing_in_cache"])} mhn 在 cache 找不到')

    # 写报告
    report = {
        'generated': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'source': str(source),
        'dry_run': args.dry_run,
        'crawl_summary': {
            'total_results': len(results),
            'total_failures': len(failures),
        },
        'weapons_meta': meta_report,
        'all_items_cache': cache_report,
    }
    report_path = MAPS / 'typeval_apply_report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n[SAVE] {report_path.name}')

    if not args.dry_run:
        print()
        print('=' * 78)
        print('  ✅ 写入完成, 建议跑:')
        print('     python tools/verify_id_full_coverage.py')
        print('=' * 78)


if __name__ == '__main__':
    main()
