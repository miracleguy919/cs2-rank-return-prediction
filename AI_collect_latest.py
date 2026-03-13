#!/usr/bin/env python3
# =============================================================================
# 模块：数据收集 - 每日自动更新
# 文件：AI_collect_latest.py  [AI创建]
# 用途：全自动遍历所有饰品，访问steamdt.com页面并拦截最新K线数据。
#       不滑动历史，只获取当前页面数据（最近约720条），适合每日增量更新。
#       每饰品间隔4秒，每10个饰品额外等待30秒，支持断点续传。
# 使用：python AI_collect_latest.py
# =============================================================================
"""鑷姩鍖栨敹闆嗘渶鏂癒绾挎暟鎹紙涓嶆粦鍔紝鍙幏鍙栧綋鍓嶉〉闈㈡暟鎹級"""

import json
import os
import asyncio
import re
from datetime import datetime
from urllib.parse import quote
from playwright.async_api import async_playwright

# 瀵煎叆妯″潡
from AI_config import get_data_dir
from AI_id_mapper import get_id_mapper
from AI_data_validator import validate_kline_data

# 鏁版嵁鐩綍
HOURLY_DATA_DIR = str(get_data_dir("hourly"))
DAILY_DATA_DIR = str(get_data_dir("daily"))

# 杩涘害鏂囦欢
PROGRESS_FILE = "collection_latest_progress.json"

# 闄愭祦閰嶇疆
ITEM_DELAY = 4  # 姣忎釜楗板搧闂撮殧4绉?
BATCH_SIZE = 10  # 姣?0涓グ鍝?
BATCH_DELAY = 30  # 棰濆绛夊緟30绉?

# 鍒濆鍖朓D鏄犲皠鍣?
print("馃敡 鍒濆鍖朓D鏄犲皠鍣?..")
id_mapper = get_id_mapper()
print()


def normalize_records(records):
    """鏍囧噯鍖朘绾挎暟鎹?""
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
            "turnover": float(entry[6]) if entry[6] else 0.0,
        })
    
    normalized.sort(key=lambda x: x["t"])
    return normalized


def save_kline_data(item_id, hourly_data, daily_data):
    """淇濆瓨K绾挎暟鎹紙鍙洿鏂版渶鏂版暟鎹級"""
    
    # 淇濆瓨灏忔椂K绾?
    if hourly_data:
        hourly_file = os.path.join(HOURLY_DATA_DIR, f"{item_id}.json")
        existing_hourly = []
        
        if os.path.exists(hourly_file):
            try:
                with open(hourly_file, "r", encoding="utf-8") as f:
                    existing_hourly = json.load(f)
            except:
                pass
        
        # 鏅鸿兘鍚堝苟锛堝彧鏇存柊鏈€鏂版暟鎹級
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
            print(f"      鉁?灏忔椂K绾? 鏇存柊 {new_count} 鏉?)
        else:
            print(f"      鈩癸笍  灏忔椂K绾? 鏃犳柊鏁版嵁")
    
    # 淇濆瓨鏃绾?
    if daily_data:
        daily_file = os.path.join(DAILY_DATA_DIR, f"{item_id}.json")
        existing_daily = []
        
        if os.path.exists(daily_file):
            try:
                with open(daily_file, "r", encoding="utf-8") as f:
                    existing_daily = json.load(f)
            except:
                pass
        
        # 鏅鸿兘鍚堝苟锛堝彧鏇存柊鏈€鏂版暟鎹級
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
            print(f"      鉁?鏃绾? 鏇存柊 {new_count} 鏉?)
        else:
            print(f"      鈩癸笍  鏃绾? 鏃犳柊鏁版嵁")


def load_progress():
    """鍔犺浇杩涘害"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"completed": [], "failed": [], "last_index": 0}


def save_progress(progress):
    """淇濆瓨杩涘害"""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


async def collect_latest_data():
    """鏀堕泦鏈€鏂版暟鎹紙涓嶆粦鍔級"""
    
    # 鍔犺浇杩涘害
    progress = load_progress()
    completed = set(progress["completed"])
    failed = set(progress["failed"])
    start_index = progress["last_index"]
    
    # 鑾峰彇鎵€鏈夐グ鍝?
    items = []
    for local_id, type_val in id_mapper.local_to_typeval.items():
        market_name = id_mapper.typeval_to_market.get(type_val)
        if market_name:
            items.append((local_id, type_val, market_name))
    
    total = len(items)
    print(f"馃搳 鎬诲叡 {total} 涓グ鍝?)
    print(f"鉁?宸插畬鎴? {len(completed)} 涓?)
    print(f"鉂?澶辫触: {len(failed)} 涓?)
    print(f"鈴?寰呭鐞? {total - len(completed) - len(failed)} 涓?)
    print()
    
    if start_index > 0:
        print(f"馃攧 浠庣 {start_index + 1} 涓グ鍝佺户缁?..")
        print()
    
    # 鎷︽埅鍒扮殑鏁版嵁
    intercepted_data = {}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        page = await context.new_page()
        
        # 璁剧疆鎷︽埅鍣?
        async def handle_response(response):
            url = response.url
            
            if "kline" in url and "typeVal" in url:
                try:
                    match = re.search(r'typeVal=(\d+)', url)
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
                    print(f"      鈿狅笍  鎷︽埅澶辫触: {e}")
        
        page.on("response", handle_response)
        
        try:
            print()
            print("=" * 80)
            print("馃殌 寮€濮嬫敹闆嗘渶鏂版暟鎹?..")
            print("=" * 80)
            print()
            
            # 澶勭悊姣忎釜楗板搧
            for idx in range(start_index, total):
                local_id, type_val, market_name = items[idx]
                
                # 璺宠繃宸插畬鎴愮殑
                if local_id in completed:
                    print(f"[{idx+1}/{total}] 鈴笍  璺宠繃: {local_id} - {market_name}")
                    continue
                
                print(f"[{idx+1}/{total}] 馃幆 澶勭悊: {local_id} - {market_name}")
                
                try:
                    # 鏋勯€燯RL
                    encoded_name = quote(market_name)
                    url = f"https://steamdt.com/cs2/{encoded_name}"
                    
                    print(f"      馃寪 璁块棶: {url}")
                    
                    # 娓呯┖鎷︽埅鏁版嵁
                    intercepted_data = {}
                    
                    # 璁块棶椤甸潰
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(2000)
                    
                    # 鍙湪绗竴涓グ鍝佹椂妫€鏌ュ苟鍏抽棴鍏憡寮圭獥
                    if idx == start_index:
                        try:
                            close_attempts = [
                                ('button:has-text("鎴戝凡鐭ユ檽")', '鎴戝凡鐭ユ檽'),
                                ('button:has-text("鎴戠煡閬撲簡")', '鎴戠煡閬撲簡'),
                                ('button:has-text("绋嶅悗鍐嶈")', '绋嶅悗鍐嶈'),
                                ('.el-dialog__close', '鍏抽棴鍥炬爣'),
                                (None, 'ESC閿?),
                            ]
                            
                            for selector, name in close_attempts:
                                try:
                                    if selector is None:
                                        await page.keyboard.press('Escape')
                                        await page.wait_for_timeout(500)
                                    else:
                                        close_button = await page.wait_for_selector(selector, timeout=1000)
                                        if close_button and await close_button.is_visible():
                                            await close_button.click()
                                            await page.wait_for_timeout(1000)
                                            break
                                except:
                                    continue
                        except:
                            pass
                    
                    await page.wait_for_timeout(1000)
                    
                    # 鐐瑰嚮"K绾垮浘"鏍囩
                    try:
                        k_line_selectors = [
                            '#tab-klinecharts',
                            'div[id="tab-klinecharts"]',
                            'div.el-tabs__item:has-text("K绾垮浘")',
                            'text=K绾垮浘',
                        ]
                        
                        for selector in k_line_selectors:
                            try:
                                await page.click(selector, timeout=5000)
                                break
                            except:
                                continue
                        
                        await page.wait_for_timeout(3000)
                    except Exception as e:
                        print(f"      鈿狅笍  鐐瑰嚮K绾垮浘澶辫触: {e}")
                    
                    # 鍒囨崲鍒?鏃禟"
                    try:
                        time_k_selectors = [
                            'span.item.period:has-text("鏃禟")',
                            '.item.period:has-text("鏃禟")',
                            'text=鏃禟',
                        ]
                        
                        for selector in time_k_selectors:
                            try:
                                await page.click(selector, timeout=5000)
                                break
                            except:
                                continue
                        
                        await page.wait_for_timeout(4000)
                    except Exception as e:
                        print(f"      鈿狅笍  鍒囨崲鏃禟澶辫触: {e}")
                    
                    # 鍒囨崲鍒?鏃"
                    try:
                        day_k_selectors = [
                            'span.item.period:has-text("鏃")',
                            '.item.period:has-text("鏃")',
                            'text=鏃',
                        ]
                        
                        for selector in day_k_selectors:
                            try:
                                await page.click(selector, timeout=5000)
                                break
                            except:
                                continue
                        
                        await page.wait_for_timeout(4000)
                    except Exception as e:
                        print(f"      鈿狅笍  鍒囨崲鏃澶辫触: {e}")
                    
                    # 涓嶆粦鍔紝鐩存帴妫€鏌ユ暟鎹?
                    print(f"      馃搳 鑾峰彇褰撳墠椤甸潰鏁版嵁...")
                    await page.wait_for_timeout(2000)
                    
                    # 妫€鏌ユ槸鍚︽嫤鎴埌鏁版嵁
                    if type_val in intercepted_data:
                        data = intercepted_data[type_val]
                        hourly = data.get("hourly", [])
                        daily = data.get("daily", [])
                        
                        if hourly and daily:
                            print(f"      馃搳 鎷︽埅鎴愬姛: 灏忔椂K绾?{len(hourly)} 鏉? 鏃绾?{len(daily)} 鏉?)
                            save_kline_data(local_id, hourly, daily)
                            completed.add(local_id)
                            if local_id in failed:
                                failed.remove(local_id)
                        else:
                            print(f"      鈿狅笍  鏁版嵁涓嶅畬鏁? 灏忔椂={len(hourly)}, 鏃?{len(daily)}")
                            failed.add(local_id)
                    else:
                        print(f"      鉂?鏈嫤鎴埌鏁版嵁")
                        failed.add(local_id)
                    
                except Exception as e:
                    print(f"      鉂?澶勭悊澶辫触: {e}")
                    failed.add(local_id)
                
                # 淇濆瓨杩涘害
                progress["completed"] = list(completed)
                progress["failed"] = list(failed)
                progress["last_index"] = idx + 1
                save_progress(progress)
                
                # 鍋滄褰撳墠椤甸潰鎿嶄綔
                try:
                    await page.evaluate("window.stop()")
                except:
                    pass
                
                # 闄愭祦鎺у埗
                if (idx + 1) % BATCH_SIZE == 0:
                    print(f"\n鈴革笍  宸插鐞?{idx + 1} 涓グ鍝侊紝绛夊緟 {BATCH_DELAY} 绉?..\n")
                    await page.wait_for_timeout(BATCH_DELAY * 1000)
                else:
                    print(f"      鈴?绛夊緟 {ITEM_DELAY} 绉?..")
                    await page.wait_for_timeout(ITEM_DELAY * 1000)
                
                print()
            
            print("=" * 80)
            print("馃帀 鏀堕泦瀹屾垚锛?)
            print("=" * 80)
            print(f"鉁?鎴愬姛: {len(completed)} 涓?)
            print(f"鉂?澶辫触: {len(failed)} 涓?)
            
        except KeyboardInterrupt:
            print("\n\n鈴癸笍  鐢ㄦ埛涓柇")
        except Exception as e:
            print(f"\n鉂?寮傚父: {e}")
        finally:
            await browser.close()


async def main():
    print()
    print("=" * 80)
    print("馃攧 鏈€鏂版暟鎹敹闆嗗伐鍏?)
    print("=" * 80)
    print()
    print("鍔熻兘锛?)
    print("  鈥?鍙幏鍙栧綋鍓嶉〉闈㈢殑鏈€鏂版暟鎹紙涓嶆粦鍔級")
    print("  鈥?閫傚悎姣忔棩鏇存柊鏁版嵁")
    print("  鈥?閫熷害蹇紝绾?灏忔椂瀹屾垚")
    print()
    
    confirm = input("鎸夊洖杞﹂敭寮€濮嬶紝鎴栬緭鍏?q 閫€鍑? ")
    if confirm.lower() == 'q':
        print("宸插彇娑?)
        return
    
    print()
    await collect_latest_data()


if __name__ == "__main__":
    asyncio.run(main())
