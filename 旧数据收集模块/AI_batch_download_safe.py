#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全批量获取脚本 - 避免API限流

策略：
1. 每个饰品间隔15秒（比默认的3.7秒更保守）
2. 只获取最新1页数据（约30天）
3. 小批次运行（每批10个）
4. 自动跳过已有数据的饰品
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "legacy_data"


def load_all_item_ids():
    """读取itemid.txt中的所有饰品ID"""
    itemid_file = BASE_DIR / ".." / "mappings" / "itemid.txt"
    
    item_ids = []
    with open(itemid_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            
            if "：" in line:
                item_id = line.split("：")[0].strip()
            elif ":" in line:
                item_id = line.split(":")[0].strip()
            else:
                continue
            
            if item_id:
                item_ids.append(item_id)
    
    return item_ids


def check_existing_data():
    """检查哪些饰品已有数据"""
    existing = set()
    if DATA_DIR.exists():
        for json_file in DATA_DIR.glob("*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if len(data) > 0:
                    item_id = json_file.stem
                    existing.add(item_id)
            except:
                pass
    return existing


def main():
    parser = argparse.ArgumentParser(description="安全批量获取饰品数据")
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="从第几个饰品开始（默认1）"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="本次获取多少个饰品（默认10）"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="跳过已有数据的饰品"
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=30.0,  # 改为30秒，避免限流
        help="饰品之间的延迟秒数（默认30秒）"
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=1,
        help="每个饰品最多请求的页数（默认1页=约30天）"
    )
    
    args = parser.parse_args()
    
    # 加载所有饰品ID
    all_items = load_all_item_ids()
    print(f"📦 总共 {len(all_items)} 个饰品")
    
    # 检查已有数据
    existing = check_existing_data()
    print(f"✅ 已有数据: {len(existing)} 个饰品")
    
    # 选择要获取的饰品
    start_idx = args.start - 1
    end_idx = min(start_idx + args.count, len(all_items))
    
    target_items = []
    for i in range(start_idx, end_idx):
        item_id = all_items[i]
        if args.skip_existing and item_id in existing:
            print(f"⏭️  {item_id} 已有数据")
            continue
        target_items.append(item_id)
    
    if not target_items:
        print("ℹ️  没有需要获取的饰品")
        return 0
    
    print(f"\n🎯 本次将获取 {len(target_items)} 个饰品")
    print(f"⏱️  预计耗时: {len(target_items) * args.sleep_seconds / 60:.1f} 分钟\n")
    
    # 构建命令
    cmd = [
        sys.executable,
        str(BASE_DIR / "backfill_hourly_kline.py"),
        "--max-iterations", str(args.max_iterations),
        "--sleep-seconds", str(args.sleep_seconds),
        "--page-sleep-seconds", "8"
    ]
    
    for item_id in target_items:
        cmd.extend(["--item-id", item_id])
    
    # 运行
    print(f"{'='*60}")
    print(f"开始获取...")
    print(f"{'='*60}\n")
    
    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    
    if result.returncode == 0:
        print(f"\n{'='*60}")
        print(f"🎉 完成！")
        print(f"{'='*60}")
        print(f"\n💡 建议：等待 30-60 分钟后继续下一批")
        print(f"📝 下一批命令：")
        print(f"python batch_download_safe.py --start {end_idx + 1} --count {args.count}")
    else:
        print(f"\n❌ 执行失败")
        print(f"💡 建议：等待 1-2 小时后重试相同命令")
    
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

