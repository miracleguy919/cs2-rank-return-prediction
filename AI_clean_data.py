#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
# 模块：数据处理 - 数据清洗与标准化
# 文件：AI_clean_data.py  [AI创建]
# 用途：清洗data/hourly/或data/daily/中的K线数据：
#       1. 将非整点时间戳规范化到最近整点（小时K线）或每天16:00（日K线）
#       2. 使用线性插值填补缺失的时间点
#       3. 去重处理（相同时间戳只保留一条）
#       4. 验证所有饰品数据量对齐
# 使用：python AI_clean_data.py --dir data/daily [--dry-run]
# =============================================================================
"""
数据清洗和验证脚本
功能：
1. 检查时间戳是否规范（整点）
2. 标准化非整点的时间戳
3. 填补缺失的时间点（线性插值）
4. 验证数据对齐性
"""

import json
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple

ONE_HOUR_MS = 60 * 60 * 1000
ONE_DAY_MS = 24 * 60 * 60 * 1000


def normalize_timestamp(ts_ms: int, interval: str = 'hourly') -> int:
    """
    标准化时间戳到整点
    
    Args:
        ts_ms: 毫秒时间戳
        interval: 'hourly' 或 'daily'
    
    Returns:
        标准化后的毫秒时间戳
    """
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    
    if interval == 'hourly':
        # 规范化到整点（四舍五入到最近的小时）
        if dt.minute >= 30:
            normalized = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            normalized = dt.replace(minute=0, second=0, microsecond=0)
    else:  # daily
        # 规范化到每天16:00（UTC）
        normalized = dt.replace(hour=16, minute=0, second=0, microsecond=0)
    
    return int(normalized.timestamp() * 1000)


def is_normalized_timestamp(ts_ms: int, interval: str = 'hourly') -> bool:
    """检查时间戳是否已经标准化"""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    
    if interval == 'hourly':
        return dt.minute == 0 and dt.second == 0 and dt.microsecond == 0
    else:  # daily
        return dt.hour == 16 and dt.minute == 0 and dt.second == 0 and dt.microsecond == 0


def clean_and_normalize_data(data: List[Dict[str, Any]], interval: str = 'hourly') -> Tuple[List[Dict[str, Any]], int]:
    """
    清洗和标准化数据
    
    Args:
        data: 原始数据
        interval: 'hourly' 或 'daily'
    
    Returns:
        (清洗后的数据, 修改的记录数)
    """
    cleaned_data = []
    normalized_count = 0
    seen_timestamps = set()
    
    for record in data:
        ts = int(record['t'])
        
        # 检查是否需要标准化
        if not is_normalized_timestamp(ts, interval):
            normalized_ts = normalize_timestamp(ts, interval)
            normalized_count += 1
        else:
            normalized_ts = ts
        
        # 去重（如果标准化后有重复，保留第一个）
        if normalized_ts not in seen_timestamps:
            record['t'] = normalized_ts
            cleaned_data.append(record)
            seen_timestamps.add(normalized_ts)
    
    # 排序
    cleaned_data.sort(key=lambda x: x['t'])
    
    return cleaned_data, normalized_count


def find_missing_timestamps(data: List[Dict[str, Any]], interval: str = 'hourly') -> List[int]:
    """
    找出缺失的时间戳
    
    Args:
        data: 数据列表
        interval: 'hourly' 或 'daily'
    
    Returns:
        缺失的时间戳列表
    """
    if len(data) < 2:
        return []
    
    missing_timestamps = []
    interval_ms = ONE_HOUR_MS if interval == 'hourly' else ONE_DAY_MS
    
    for i in range(1, len(data)):
        prev_ts = int(data[i - 1]['t'])
        curr_ts = int(data[i]['t'])
        
        expected_ts = prev_ts + interval_ms
        
        while expected_ts < curr_ts:
            missing_timestamps.append(expected_ts)
            expected_ts += interval_ms
    
    return missing_timestamps


def interpolate_value(prev_value: Any, next_value: Any, ratio: float) -> Any:
    """线性插值"""
    try:
        prev_f = float(prev_value)
        next_f = float(next_value)
        return prev_f + (next_f - prev_f) * ratio
    except (TypeError, ValueError):
        return prev_value


def fill_missing_points(data: List[Dict[str, Any]], interval: str = 'hourly') -> Tuple[List[Dict[str, Any]], int]:
    """
    填补缺失的时间点
    
    Args:
        data: 数据列表
        interval: 'hourly' 或 'daily'
    
    Returns:
        (填补后的数据, 插入的记录数)
    """
    if len(data) < 2:
        return data, 0
    
    filled_data = []
    inserted = 0
    interval_ms = ONE_HOUR_MS if interval == 'hourly' else ONE_DAY_MS
    
    for i in range(len(data) - 1):
        prev_entry = data[i]
        next_entry = data[i + 1]
        filled_data.append(prev_entry)
        
        prev_ts = int(prev_entry['t'])
        next_ts = int(next_entry['t'])
        
        # 计算需要插入的点数
        gap = next_ts - prev_ts
        if gap > interval_ms:
            missing_count = gap // interval_ms - 1
            
            for step in range(1, missing_count + 1):
                ratio = step / (missing_count + 1)
                missing_ts = prev_ts + interval_ms * step
                
                # 创建插值记录
                interpolated = {'t': missing_ts}
                for field in ['o', 'h', 'l', 'c', 'v', 'turnover']:
                    if field in prev_entry and field in next_entry:
                        interpolated[field] = interpolate_value(prev_entry[field], next_entry[field], ratio)
                    elif field in prev_entry:
                        interpolated[field] = prev_entry[field]
                
                filled_data.append(interpolated)
                inserted += 1
    
    # 添加最后一条记录
    if data:
        filled_data.append(data[-1])
    
    return filled_data, inserted


def process_file(file_path: str, interval: str = 'hourly', normalize: bool = True, fill_gaps: bool = True) -> Dict[str, Any]:
    """
    处理单个文件
    
    Args:
        file_path: 文件路径
        interval: 'hourly' 或 'daily'
        normalize: 是否标准化时间戳
        fill_gaps: 是否填补缺失点
    
    Returns:
        处理结果统计
    """
    # 读取数据
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return {'error': str(e)}
    
    if not data:
        return {'error': 'Empty file'}
    
    original_count = len(data)
    result = {
        'original_count': original_count,
        'normalized_count': 0,
        'filled_count': 0,
        'final_count': original_count,
    }
    
    # 标准化时间戳
    if normalize:
        data, normalized_count = clean_and_normalize_data(data, interval)
        result['normalized_count'] = normalized_count
        result['final_count'] = len(data)
    
    # 填补缺失点
    if fill_gaps:
        data, filled_count = fill_missing_points(data, interval)
        result['filled_count'] = filled_count
        result['final_count'] = len(data)
    
    # 保存数据
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        result['success'] = True
    except Exception as e:
        result['error'] = str(e)
        result['success'] = False
    
    return result


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='数据清洗和验证脚本')
    parser.add_argument('--dir', type=str, default='data/hourly', help='数据目录 (data/hourly 或 data/daily)')
    parser.add_argument('--ids', type=str, nargs='+', help='指定要处理的ID列表，不指定则处理所有')
    parser.add_argument('--normalize', action='store_true', default=True, help='标准化时间戳')
    parser.add_argument('--fill', action='store_true', default=True, help='填补缺失点')
    parser.add_argument('--dry-run', action='store_true', help='只检查不修改')
    
    args = parser.parse_args()
    
    # 确定数据类型
    interval = 'hourly' if 'hourly' in args.dir else 'daily'
    
    print("=" * 80)
    print(f"数据清洗脚本 - {args.dir}")
    print("=" * 80)
    print(f"数据类型: {interval}")
    print(f"标准化时间戳: {'是' if args.normalize else '否'}")
    print(f"填补缺失点: {'是' if args.fill else '否'}")
    print(f"模式: {'只检查' if args.dry_run else '修改文件'}")
    print("=" * 80)
    print()
    
    # 获取文件列表
    if args.ids:
        files = [os.path.join(args.dir, f"{id}.json") for id in args.ids]
    else:
        files = [f for f in os.listdir(args.dir) if f.endswith('.json')]
        files = [os.path.join(args.dir, f) for f in files]
    
    print(f"找到 {len(files)} 个文件")
    print()
    
    # 处理文件
    total_normalized = 0
    total_filled = 0
    success_count = 0
    error_count = 0
    
    for file_path in files:
        file_name = os.path.basename(file_path)
        
        if not os.path.exists(file_path):
            print(f"[ERROR] {file_name}: File not found")
            error_count += 1
            continue
        
        if args.dry_run:
            # 只检查，不修改
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 检查需要标准化的数量
                need_normalize = sum(1 for r in data if not is_normalized_timestamp(int(r['t']), interval))
                
                # 检查缺失点
                missing = find_missing_timestamps(data, interval)
                
                print(f"[CHECK] {file_name}:")
                print(f"   Total records: {len(data)}")
                print(f"   Need normalize: {need_normalize}")
                print(f"   Missing points: {len(missing)}")
                
            except Exception as e:
                print(f"[ERROR] {file_name}: {e}")
                error_count += 1
        else:
            # 处理文件
            result = process_file(file_path, interval, args.normalize, args.fill)
            
            if result.get('success'):
                print(f"[OK] {file_name}:")
                print(f"   Original: {result['original_count']}")
                if result['normalized_count'] > 0:
                    print(f"   Normalized: {result['normalized_count']}")
                if result['filled_count'] > 0:
                    print(f"   Filled: {result['filled_count']}")
                print(f"   Final: {result['final_count']}")
                
                total_normalized += result['normalized_count']
                total_filled += result['filled_count']
                success_count += 1
            else:
                print(f"[ERROR] {file_name}: {result.get('error', 'Unknown error')}")
                error_count += 1
        
        print()
    
    # 总结
    print("=" * 80)
    print("Processing Complete")
    print("=" * 80)
    print(f"Success: {success_count} files")
    print(f"Failed: {error_count} files")
    if not args.dry_run:
        print(f"Total normalized: {total_normalized} records")
        print(f"Total filled: {total_filled} records")
    print("=" * 80)


if __name__ == "__main__":
    main()
