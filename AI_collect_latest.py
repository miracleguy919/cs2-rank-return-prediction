#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块：数据收集 - 每日自动更新
文件：AI_collect_latest.py  [AI创建]
用途：自动遍历所有饰品，访问steamdt.com，拦截并保存最新的小时K线和日K线数据
使用：python AI_collect_latest.py
"""

import json, os, asyncio, re, time
from datetime import datetime
from urllib.parse import quote
from playwright.async_api import async_playwright
from AI_config import get_data_dir
from AI_id_mapper import get_id_mapper

HOURLY_DATA_DIR = str(get_data_dir("hourly"))
DAILY_DATA_DIR = str(get_data_dir("daily"))
PROGRESS_FILE = "collection_latest_progress.json"
ITEM_DELAY = 5
BATCH_SIZE = 10
BATCH_DELAY = 7

print("🔧 初始化ID映射器...")
id_mapper = get_id_mapper()
print()

def normalize_records(records):
    """标准化K线数据"""
    normalized = []
    for entry in records:
        if len(entry) < 7: 
            continue
        ts_raw = int(entry[0])
        normalized.append({
            "t": ts_raw * 1000, 
            "o": float(entry[1]) if entry[1] else 0.0, 
            "c": float(entry[2]) if entry[2] else 0.0, 
            "h": float(entry[3]) if entry[3] else 0.0, 
            "l": float(entry[4]) if entry[4] else 0.0, 
            "v": float(entry[5]) if entry[5] else 0.0, 
            "turnover": float(entry[6]) if entry[6] else 0.0
        })
    normalized.sort(key=lambda x: x["t"])
    return normalized

def save_kline_data(item_id, hourly_data, daily_data):
    """保存K线数据"""
    if hourly_data:
        hourly_file = os.path.join(HOURLY_DATA_DIR, f"{item_id}.json")
        existing_hourly = []
        if os.path.exists(hourly_file):
            try:
                with open(hourly_file, "r", encoding="utf-8") as f: 
                    existing_hourly = json.load(f)
            except: 
                pass
        existing_dict = {r["t"]: r for r in existing_hourly}
        new_count = 0
        for new_record in hourly_data:
            ts = new_record["t"]
            if ts not in existing_dict or new_record["v"] > existing_dict[ts]["v"]: 
                existing_dict[ts] = new_record
                new_count += 1
        if new_count > 0:
            merged = sorted(existing_dict.values(), key=lambda x: x["t"])
            with open(hourly_file, "w", encoding="utf-8") as f: 
                json.dump(merged, f, ensure_ascii=False, indent=2)
            print(f"      ✅ 小时K线: 更新 {new_count} 条")
        else: 
            print(f"      ℹ️  小时K线: 无新数据")
    if daily_data:
        daily_file = os.path.join(DAILY_DATA_DIR, f"{item_id}.json")
        existing_daily = []
        if os.path.exists(daily_file):
            try:
                with open(daily_file, "r", encoding="utf-8") as f: 
                    existing_daily = json.load(f)
            except: 
                pass
        existing_dict = {r["t"]: r for r in existing_daily}
        new_count = 0
        for new_record in daily_data:
            ts = new_record["t"]
            if ts not in existing_dict or new_record["v"] > existing_dict[ts]["v"]: 
                existing_dict[ts] = new_record
                new_count += 1
        if new_count > 0:
            merged = sorted(existing_dict.values(), key=lambda x: x["t"])
            with open(daily_file, "w", encoding="utf-8") as f: 
                json.dump(merged, f, ensure_ascii=False, indent=2)
            print(f"      ✅ 日K线: 更新 {new_count} 条")
        else: 
            print(f"      ℹ️  日K线: 无新数据")

def load_progress():
    """加载进度"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f: 
                return json.load(f)
        except: 
            pass
    return {"completed": [], "failed": [], "last_index": 0}

def save_progress(progress):
    """保存进度"""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f: 
        json.dump(progress, f, ensure_ascii=False, indent=2)

async def collect_latest_data():
    """收集最新数据"""
    progress = load_progress()
    completed = set(progress["completed"])
    failed = set(progress["failed"])
    start_index = progress["last_index"]
    items = [(local_id, type_val, id_mapper.typeval_to_market.get(type_val)) 
             for local_id, type_val in id_mapper.local_to_typeval.items() 
             if id_mapper.typeval_to_market.get(type_val)]
    total = len(items)
    print(f"📊 总饰品数: {total}")
    print(f"✅ 已完成: {len(completed)}")
    print(f"❌ 失败: {len(failed)}")
    print(f"⏳ 待处理: {total - len(completed) - len(failed)}")
    print()
    if start_index > 0: 
        print(f"🔄 从第 {start_index + 1} 个饰品继续...")
        print()
    
    intercepted_data = {}
    first_visit = True
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False, 
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()
        
        async def handle_response(response):
            url = response.url
            if "kline" in url and "typeVal" in url:
                try:
                    match = re.search(r"typeVal=(\d+)", url)
                    if match:
                        type_val = match.group(1)
                        data = await response.json()
                        if data.get("success"):
                            records = data.get("data", [])
                            if type_val not in intercepted_data: 
                                intercepted_data[type_val] = {}
                            if "type=1" in url: 
                                intercepted_data[type_val]["hourly"] = normalize_records(records)
                            elif "type=2" in url: 
                                intercepted_data[type_val]["daily"] = normalize_records(records)
                except Exception as e: 
                    pass
        
        page.on("response", handle_response)
        
        try:
            print()
            print("=" * 80)
            print("🚀 开始收集数据...")
            print("=" * 80)
            print()
            
            for idx in range(start_index, total):
                local_id, type_val, market_name = items[idx]
                if local_id in completed: 
                    print(f"[{idx+1}/{total}] ⏭️  跳过: {local_id} - {market_name}")
                    continue
                
                print(f"[{idx+1}/{total}] 🎯 处理: {local_id} - {market_name}")
                
                try:
                    encoded_name = quote(market_name)
                    url = f"https://steamdt.com/cs2/{encoded_name}"
                    intercepted_data = {}
                    
                    print(f"      📄 访问页面...")
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(2000)
                    
                    if first_visit:
                        print(f"      ⚠️  请手动关闭公告弹窗...")
                        try:
                            await page.wait_for_selector("div.el-dialog", state="hidden", timeout=15000)
                            print(f"      ✅ 公告已关闭")
                        except:
                            print(f"      ⚠️  公告关闭超时，继续处理...")
                        first_visit = False
                    
                    print(f"      📊 滑动页面...")
                    await page.evaluate("window.scrollBy(0, 400)")
                    await page.wait_for_timeout(1500)
                    
                    print(f"      📈 切换到K线图...")
                    try:
                        await page.click("div[id='tab-klinecharts']", timeout=5000)
                        await page.wait_for_timeout(1500)
                    except:
                        print(f"      ⚠️  K线图标签点击失败，继续...")
                    
                    print(f"      🔄 切换时间周期...")
                    try:
                        period_buttons = await page.query_selector_all("span.item.period")
                        print(f"      🔍 找到 {len(period_buttons)} 个时间周期按钮")
                        if len(period_buttons) >= 2:
                            await period_buttons[0].click()
                            await page.wait_for_timeout(2500)
                            print(f"      ✅ 已切换到小时K")
                        else:
                            print(f"      ⚠️  找不到足够的时间周期按钮")
                    except Exception as e:
                        print(f"      ⚠️  小时K切换失败: {e}")
                    
                    try:
                        period_buttons = await page.query_selector_all("span.item.period")
                        if len(period_buttons) >= 2:
                            await period_buttons[1].click()
                            await page.wait_for_timeout(2500)
                            print(f"      ✅ 已切换到日K")
                        else:
                            print(f"      ⚠️  找不到足够的时间周期按钮")
                    except Exception as e:
                        print(f"      ⚠️  日K切换失败: {e}")
                    
                    if type_val in intercepted_data:
                        data = intercepted_data[type_val]
                        hourly = data.get("hourly", [])
                        daily = data.get("daily", [])
                        if hourly and daily: 
                            print(f"      ✅ 拦截成功: 小时K线 {len(hourly)} 条, 日K线 {len(daily)} 条")
                            save_kline_data(local_id, hourly, daily)
                            completed.add(local_id)
                            if local_id in failed: 
                                failed.remove(local_id)
                        else: 
                            print(f"      ⚠️  数据不完整: 小时K线={len(hourly)}, 日K线={len(daily)}")
                            failed.add(local_id)
                    else: 
                        print(f"      ❌ 未拦截到数据")
                        failed.add(local_id)
                
                except Exception as e: 
                    print(f"      ❌ 处理失败: {e}")
                    failed.add(local_id)
                
                progress["completed"] = list(completed)
                progress["failed"] = list(failed)
                progress["last_index"] = idx + 1
                save_progress(progress)
                
                try: 
                    await page.evaluate("window.stop()")
                except: 
                    pass
                
                if (idx + 1) % BATCH_SIZE == 0: 
                    print(f"\n⏸️  已处理 {idx + 1} 个饰品，等待 {BATCH_DELAY} 秒...\n")
                    await page.wait_for_timeout(BATCH_DELAY * 1000)
                else: 
                    print(f"      ⏳ 等待 {ITEM_DELAY} 秒...")
                    await page.wait_for_timeout(ITEM_DELAY * 1000)
                
                print()
            

            print("=" * 80)
            print("🎉 第一轮收集完成!")
            print("=" * 80)
            print(f"✅ 成功: {len(completed)} 个")
            print(f"❌ 失败: {len(failed)} 个")
            
            # 重试失败的饰品
            retry_round = 1
            max_retries = 3
            while len(failed) > 0 and retry_round <= max_retries:
                print()
                print("=" * 80)
                print(f"🔄 开始第 {retry_round + 1} 轮重试 (剩余 {len(failed)} 个失败饰品)...")
                print("=" * 80)
                print()
                
                failed_items = [(local_id, type_val, market_name) 
                               for local_id, type_val, market_name in items 
                               if local_id in failed]
                
                for idx, (local_id, type_val, market_name) in enumerate(failed_items):
                    print(f"[{idx+1}/{len(failed_items)}] 🔄 重试: {local_id} - {market_name}")
                    
                    try:
                        encoded_name = quote(market_name)
                        url = f"https://steamdt.com/cs2/{encoded_name}"
                        intercepted_data = {}
                        
                        print(f"      📄 访问页面...")
                        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_timeout(2000)
                        
                        print(f"      📊 滑动页面...")
                        await page.evaluate("window.scrollBy(0, 400)")
                        await page.wait_for_timeout(1500)
                        
                        print(f"      📈 切换到K线图...")
                        try:
                            await page.click("div[id='tab-klinecharts']", timeout=5000)
                            await page.wait_for_timeout(1500)
                        except:
                            print(f"      ⚠️  K线图标签点击失败，继续...")
                        
                        print(f"      🔄 切换时间周期...")
                        try:
                            period_buttons = await page.query_selector_all("span.item.period")
                            if len(period_buttons) >= 2:
                                await period_buttons[0].click()
                                await page.wait_for_timeout(2500)
                                print(f"      ✅ 已切换到小时K")
                        except Exception as e:
                            print(f"      ⚠️  小时K切换失败: {e}")
                        
                        try:
                            period_buttons = await page.query_selector_all("span.item.period")
                            if len(period_buttons) >= 2:
                                await period_buttons[1].click()
                                await page.wait_for_timeout(2500)
                                print(f"      ✅ 已切换到日K")
                        except Exception as e:
                            print(f"      ⚠️  日K切换失败: {e}")
                        
                        if type_val in intercepted_data:
                            data = intercepted_data[type_val]
                            hourly = data.get("hourly", [])
                            daily = data.get("daily", [])
                            if hourly and daily: 
                                print(f"      ✅ 拦截成功: 小时K线 {len(hourly)} 条, 日K线 {len(daily)} 条")
                                save_kline_data(local_id, hourly, daily)
                                completed.add(local_id)
                                failed.remove(local_id)
                            else: 
                                print(f"      ⚠️  数据不完整: 小时K线={len(hourly)}, 日K线={len(daily)}")
                        else: 
                            print(f"      ❌ 未拦截到数据")
                    
                    except Exception as e: 
                        print(f"      ❌ 处理失败: {e}")
                    
                    progress["completed"] = list(completed)
                    progress["failed"] = list(failed)
                    save_progress(progress)
                    
                    try: 
                        await page.evaluate("window.stop()")
                    except: 
                        pass
                    
                    print(f"      ⏳ 等待 {ITEM_DELAY} 秒...")
                    await page.wait_for_timeout(ITEM_DELAY * 1000)
                    print()
                
                retry_round += 1
                
                print("=" * 80)
                print(f"🎉 第 {retry_round} 轮完成!")
                print("=" * 80)
                print(f"✅ 成功: {len(completed)} 个")
                print(f"❌ 失败: {len(failed)} 个")
            
            print()
        
        except KeyboardInterrupt: 
            print("\n\n⏹️  用户中断")
        except Exception as e: 
            print(f"\n❌ 异常: {e}")
        finally: 
            await browser.close()

async def main():
    print()
    print("=" * 80)
    print("📊 每日数据更新脚本")
    print("=" * 80)
    print()
    confirm = input("按回车键开始，或输入 q 退出: ")
    if confirm.lower() == "q": 
        print("已取消")
        return
    print()
    await collect_latest_data()

if __name__ == "__main__": 
    asyncio.run(main())
