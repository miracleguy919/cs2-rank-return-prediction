#!/usr/bin/env python3
# =============================================================================
# 模块：数据收集 - 手动历史数据收集
# 文件：AI_collect_dual_kline.py  [AI创建]
# 用途：打开真实浏览器访问steamdt.com，拦截API响应，同时收集并保存
#       小时K线（data_hourly/）和日K线（data_daily/）。
#       用户手动点击/滑动K线图，脚本自动累积历史数据，自动检测饰品切换。
# 使用：python AI_collect_dual_kline.py
# =============================================================================
"""使用Playwright拦截并保存日K线和小时K线数据（支持ID映射和数据验证）"""

import json
import os
import time
import asyncio
from datetime import datetime, timezone
from playwright.async_api import async_playwright

# 导入配置和ID映射模块
from AI_config import get_data_dir
from AI_id_mapper import get_id_mapper
from AI_data_validator import validate_kline_data

# 数据目录
HOURLY_DATA_DIR = str(get_data_dir("hourly"))
DAILY_DATA_DIR = str(get_data_dir("daily"))

# 初始化ID映射器
print("🔧 初始化ID映射器...")
id_mapper = get_id_mapper()
print()

def normalize_hourly_records(records):
    """标准化小时K线数据"""
    normalized = []
    for entry in records:
        if len(entry) < 7:
            continue
        
        ts_raw = int(entry[0])
        normalized.append({
            "t": ts_raw * 1000,  # 转换为毫秒
            "o": float(entry[1]) if entry[1] else 0.0,
            "c": float(entry[2]) if entry[2] else 0.0,
            "h": float(entry[3]) if entry[3] else 0.0,
            "l": float(entry[4]) if entry[4] else 0.0,
            "v": float(entry[5]) if entry[5] else 0.0,
            "turnover": float(entry[6]) if entry[6] else 0.0,
        })
    
    normalized.sort(key=lambda x: x["t"])
    return normalized

def normalize_daily_records(records):
    """标准化日K线数据（格式相同）"""
    return normalize_hourly_records(records)

def save_kline_data(item_id, item_name, hourly_data, daily_data):
    """保存K线数据到两个目录（带数据验证）"""
    
    # 保存小时K线
    if hourly_data:
        hourly_file = os.path.join(HOURLY_DATA_DIR, f"{item_id}.json")
        existing_hourly = []
        
        if os.path.exists(hourly_file):
            try:
                with open(hourly_file, "r", encoding="utf-8") as f:
                    existing_hourly = json.load(f)
            except:
                pass
        
        # 验证新数据
        print(f"  🔍 验证小时K线数据...")
        validation_result = validate_kline_data(hourly_data, verbose=False)
        
        if not validation_result["passed"]:
            print(f"  ⚠️  小时K线数据验证失败:")
            for error in validation_result["errors"][:3]:
                print(f"     • {error}")
            print(f"  ⚠️  仍然保存数据，但请注意检查")
        else:
            print(f"  ✅ 小时K线数据验证通过")
        
        # 合并数据（智能去重和更新）
        existing_dict = {r["t"]: r for r in existing_hourly}
        new_count = 0
        update_count = 0
        delete_count = 0
        
        # 辅助函数：判断时间戳是否为整点
        def is_timestamp_normalized(ts):
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            return dt.minute == 0 and dt.second == 0 and dt.microsecond == 0
        
        # 辅助函数：检查前一条K线的收盘价是否等于当前K线的开盘价
        def should_update_by_price_continuity(old_record, new_record, all_records_dict):
            """
            检查价格连续性：如果旧数据不连续，但新数据连续，则应该更新
            """
            current_ts = old_record["t"]
            # 找到前一个小时的时间戳（减去1小时 = 3600000毫秒）
            prev_ts = current_ts - 3600000
            
            if prev_ts in all_records_dict:
                prev_record = all_records_dict[prev_ts]
                
                # 检查旧数据是否不连续
                old_discontinuous = abs(prev_record["c"] - old_record["o"]) > 0.01
                
                # 检查新数据是否连续
                new_continuous = abs(prev_record["c"] - new_record["o"]) <= 0.01
                
                # 只有当旧数据不连续，且新数据连续时，才更新
                if old_discontinuous and new_continuous:
                    return True
            
            return False
        
        # 第一步：删除旧数据中的非整点记录
        to_delete = []
        for ts in existing_dict.keys():
            if not is_timestamp_normalized(ts):
                to_delete.append(ts)
        
        for ts in to_delete:
            del existing_dict[ts]
            delete_count += 1
        
        # 第二步：合并新数据（过滤掉非标准时间的新数据）
        for new_record in hourly_data:
            ts = new_record["t"]
            
            # 过滤：只接受整点的新数据
            if not is_timestamp_normalized(ts):
                continue  # 跳过非整点的新数据
            
            if ts in existing_dict:
                old_record = existing_dict[ts]
                
                # 判断是否需要更新
                should_update = False
                update_reason = ""
                
                # 条件1：价格不连续（前日收盘价 ≠ 今天开盘价）→ 应该覆盖
                if should_update_by_price_continuity(old_record, new_record, existing_dict):
                    should_update = True
                    update_reason = "价格不连续"
                
                # 条件2：原有逻辑保留（新数据有成交量，旧数据没有）
                elif new_record["v"] > 0 and old_record["v"] == 0:
                    should_update = True
                    update_reason = "补充成交量"
                
                if should_update:
                    existing_dict[ts] = new_record
                    update_count += 1
            else:
                existing_dict[ts] = new_record
                new_count += 1
        
        if new_count > 0 or update_count > 0 or delete_count > 0:
            merged = sorted(existing_dict.values(), key=lambda x: x["t"])
            
            with open(hourly_file, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            
            if delete_count > 0:
                print(f"  ✅ 小时K线: 新增 {new_count} 条, 更新 {update_count} 条, 删除 {delete_count} 条非整点数据 → {hourly_file}")
            else:
                print(f"  ✅ 小时K线: 新增 {new_count} 条, 更新 {update_count} 条 → {hourly_file}")
        else:
            print(f"  ℹ️  小时K线: 无新数据")
    
    # 保存日K线
    if daily_data:
        daily_file = os.path.join(DAILY_DATA_DIR, f"{item_id}.json")
        existing_daily = []
        
        if os.path.exists(daily_file):
            try:
                with open(daily_file, "r", encoding="utf-8") as f:
                    existing_daily = json.load(f)
            except:
                pass
        
        # 验证新数据
        print(f"  🔍 验证日K线数据...")
        validation_result = validate_kline_data(daily_data, verbose=False)
        
        if not validation_result["passed"]:
            print(f"  ⚠️  日K线数据验证失败:")
            for error in validation_result["errors"][:3]:
                print(f"     • {error}")
            print(f"  ⚠️  仍然保存数据，但请注意检查")
        else:
            print(f"  ✅ 日K线数据验证通过")
        
        # 合并数据（智能去重和更新）
        existing_dict = {r["t"]: r for r in existing_daily}
        new_count = 0
        update_count = 0
        delete_count = 0
        
        # 辅助函数：判断时间戳是否为标准时间（每天16:00 UTC）
        def is_timestamp_normalized_daily(ts):
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            return dt.hour == 16 and dt.minute == 0 and dt.second == 0 and dt.microsecond == 0
        
        # 辅助函数：检查前一天的收盘价是否等于当天的开盘价
        def should_update_by_price_continuity_daily(old_record, new_record, all_records_dict):
            """
            检查价格连续性：如果旧数据不连续，但新数据连续，则应该更新
            """
            current_ts = old_record["t"]
            # 找到前一天的时间戳（减去1天 = 86400000毫秒）
            prev_ts = current_ts - 86400000
            
            if prev_ts in all_records_dict:
                prev_record = all_records_dict[prev_ts]
                
                # 检查旧数据是否不连续
                old_discontinuous = abs(prev_record["c"] - old_record["o"]) > 0.01
                
                # 检查新数据是否连续
                new_continuous = abs(prev_record["c"] - new_record["o"]) <= 0.01
                
                # 只有当旧数据不连续，且新数据连续时，才更新
                if old_discontinuous and new_continuous:
                    return True
            
            return False
        
        # 第一步：删除旧数据中的非标准时间记录
        to_delete = []
        for ts in existing_dict.keys():
            if not is_timestamp_normalized_daily(ts):
                to_delete.append(ts)
        
        for ts in to_delete:
            del existing_dict[ts]
            delete_count += 1
        
        # 第二步：合并新数据（过滤掉非标准时间的新数据）
        for new_record in daily_data:
            ts = new_record["t"]
            
            # 过滤：只接受标准时间（16:00）的新数据
            if not is_timestamp_normalized_daily(ts):
                continue  # 跳过非标准时间的新数据
            
            if ts in existing_dict:
                old_record = existing_dict[ts]
                
                # 判断是否需要更新
                should_update = False
                update_reason = ""
                
                # 条件1：价格不连续（前日收盘价 ≠ 今天开盘价）→ 应该覆盖
                if should_update_by_price_continuity_daily(old_record, new_record, existing_dict):
                    should_update = True
                    update_reason = "价格不连续"
                
                # 条件2：原有逻辑保留（新数据有成交量，旧数据没有）
                elif new_record["v"] > 0 and old_record["v"] == 0:
                    should_update = True
                    update_reason = "补充成交量"
                
                if should_update:
                    existing_dict[ts] = new_record
                    update_count += 1
            else:
                existing_dict[ts] = new_record
                new_count += 1
        
        if new_count > 0 or update_count > 0 or delete_count > 0:
            merged = sorted(existing_dict.values(), key=lambda x: x["t"])
            
            with open(daily_file, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            
            if delete_count > 0:
                print(f"  ✅ 日K线: 新增 {new_count} 条, 更新 {update_count} 条, 删除 {delete_count} 条非标准时间数据 → {daily_file}")
            else:
                print(f"  ✅ 日K线: 新增 {new_count} 条, 更新 {update_count} 条 → {daily_file}")
        else:
            print(f"  ℹ️  日K线: 无新数据")

async def collect_kline_data():
    """收集K线数据"""
    
    print("=" * 80)
    print("🌐 启动浏览器...")
    print("=" * 80)
    
    # 用于存储拦截到的数据
    hourly_kline = None
    daily_kline = None
    current_item_id = None
    previous_item_id = None  # 新增：跟踪上一个饰品ID
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        page = await context.new_page()
        
        # 监听网络响应
        async def handle_response(response):
            nonlocal hourly_kline, daily_kline, current_item_id, previous_item_id
            url = response.url
            
            if "kline" in url and "typeVal" in url:
                try:
                    # 提取typeVal（网站ID）
                    import re
                    match = re.search(r'typeVal=(\d+)', url)
                    if match:
                        type_val = match.group(1)
                        
                        # 转换为本地ID
                        local_id = id_mapper.get_local_id(type_val)
                        if local_id:
                            detected_item_id = local_id
                            market_name = id_mapper.get_market_name(type_val)
                            print(f"🔍 识别饰品: typeVal={type_val} → 本地ID={local_id}")
                            if market_name:
                                print(f"   市场名称: {market_name}")
                        else:
                            print(f"⚠️  未找到映射: typeVal={type_val}，使用原始ID")
                            detected_item_id = type_val
                        
                        # 检测饰品切换（方案2的核心逻辑）
                        if previous_item_id is not None and detected_item_id != previous_item_id:
                            print()
                            print("=" * 80)
                            print(f"🔄 检测到饰品切换: {previous_item_id} → {detected_item_id}")
                            print("=" * 80)
                            print(f"   重置数据缓存，开始收集新饰品数据")
                            print()
                            
                            # 重置变量
                            hourly_kline = None
                            daily_kline = None
                        
                        # 更新当前饰品ID
                        current_item_id = detected_item_id
                        previous_item_id = detected_item_id
                    
                    data = await response.json()
                    if data.get("success"):
                        records = data.get("data", [])
                        
                        if "type=1" in url:
                            # 小时K线 - 累积数据
                            new_hourly = normalize_hourly_records(records)
                            if hourly_kline is None:
                                hourly_kline = new_hourly
                            else:
                                # 合并新数据（按时间戳去重）
                                existing_ts = {r["t"] for r in hourly_kline}
                                for record in new_hourly:
                                    if record["t"] not in existing_ts:
                                        hourly_kline.append(record)
                                        existing_ts.add(record["t"])
                                hourly_kline.sort(key=lambda x: x["t"])
                            print(f"🎯 拦截到小时K线: {len(new_hourly)} 条，累计: {len(hourly_kline)} 条 (本地ID={current_item_id})")
                            
                        elif "type=2" in url:
                            # 日K线 - 累积数据
                            new_daily = normalize_daily_records(records)
                            if daily_kline is None:
                                daily_kline = new_daily
                            else:
                                # 合并新数据（按时间戳去重）
                                existing_ts = {r["t"] for r in daily_kline}
                                for record in new_daily:
                                    if record["t"] not in existing_ts:
                                        daily_kline.append(record)
                                        existing_ts.add(record["t"])
                                daily_kline.sort(key=lambda x: x["t"])
                            print(f"🎯 拦截到日K线: {len(new_daily)} 条，累计: {len(daily_kline)} 条 (本地ID={current_item_id})")
                        
                        # 每次拦截到数据就保存（利用save_kline_data的合并功能）
                        if hourly_kline and daily_kline and current_item_id:
                            save_kline_data(current_item_id, f"item_{current_item_id}", hourly_kline, daily_kline)
                            print(f"💾 已保存累积数据")
                            print()
                        
                except Exception as e:
                    print(f"⚠️  处理响应失败: {e}")
        
        page.on("response", handle_response)
        
        try:
            # 访问主页
            print("📄 访问 steamdt.com...")
            try:
                await page.goto("https://steamdt.com", wait_until="networkidle", timeout=60000)
            except Exception as e:
                print(f"⚠️  访问主页超时，尝试继续...")
                try:
                    await page.goto("https://steamdt.com", wait_until="domcontentloaded", timeout=60000)
                except:
                    print("⚠️  仍然超时，但浏览器已打开，可以手动操作")
            
            await page.wait_for_timeout(2000)
            
            print()
            print("=" * 80)
            print("💡 使用说明")
            print("=" * 80)
            print()
            print("1. 在浏览器中搜索并点击饰品")
            print("2. 查看K线图（会自动切换日K和小时K）")
            print("3. 脚本会自动拦截并保存数据")
            print("4. 手动滑动K线图可加载更多历史数据")
            print("5. 继续点击下一个饰品")
            print("6. 按 Ctrl+C 停止")
            print()
            print("数据保存位置：")
            print(f"  - 小时K线: {HOURLY_DATA_DIR}/")
            print(f"  - 日K线: {DAILY_DATA_DIR}/")
            print()
            print("=" * 80)
            print()
            
            # 保持浏览器打开，等待用户操作
            while True:
                await page.wait_for_timeout(1000)
                
        except KeyboardInterrupt:
            print("\n\n⏹️  用户停止")
        except Exception as e:
            print(f"❌ 异常: {e}")
        finally:
            print("\n🔒 关闭浏览器...")
            await browser.close()

async def main():
    print()
    print("=" * 80)
    print("📊 双K线数据收集工具")
    print("=" * 80)
    print()
    print("功能：同时收集并保存日K线和小时K线数据")
    print()
    
    await collect_kline_data()
    
    print()
    print("=" * 80)
    print("✅ 完成")
    print("=" * 80)

if __name__ == "__main__":
    print()
    print("⚠️  使用前请确保已安装：")
    print("   pip install playwright")
    print("   python -m playwright install chromium")
    print()
    input("按回车键继续...")
    print()
    
    asyncio.run(main())
