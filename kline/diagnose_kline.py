#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
模块：诊断工�?- 单饰�?K�?API 拦截诊断 (T12)
文件：kline/diagnose_kline.py  [AI创建]
用�?
    通过 Playwright 打开 SteamDT 详情�? 自动关闭弹窗、切换周�?
    拦截 kline API 响应, 输出诊断报告 (含最�?5 �?K�?, 便于人工核查
    失败原因或单饰品数据状态�?用法:
    # �?local_id �?    python kline/diagnose_kline.py --local-id 24432

    # �?type_val �?    python kline/diagnose_kline.py --type-val 12345

    # �?market_name �?    python kline/diagnose_kline.py --market-name "AK-47 | Redline"

退出码:
    0 = 正常 (有完�?hourly + daily)
    1 = 无法访问 (网络/页面/选择器失�?
    2 = 数据异常 (拦截到数据但不完�? 或验证器报错)
================================================================================
"""

import argparse
import asyncio
import json
import os
import re
import sys
import traceback
from datetime import datetime
from urllib.parse import quote

# 本文件位�?kline/ �? 需要把项目根目录加�?sys.path
# 只加根目录不�?kline/, 避免 'auto_kline_history' �?'kline.auto_kline_history'
# 加载为两个独立模块导�?log() 双倍写�?_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from playwright.async_api import async_playwright

# 导入项目基础设施 (�?history.py 单文�? 替代�?id_mapper + data_validator)
from kline.auto_kline_history import get_id_mapper, USER_AGENT

# ---------- 路径常量 ----------
ROOT_DIR = _ROOT_DIR
PROGRESS_FILE = os.path.join(ROOT_DIR, "data", "kline_progress.json")
DIAG_DIR = os.path.join(ROOT_DIR, "data", "diag")

# 浏览器启动参�?BROWSER_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]

# 关闭弹窗�?3 种方�?(�?auto_kline_crawler 借鉴, 不需�?import)
#   1. 等待 el-dialog 隐藏
#   2. 尝试点击常见关闭按钮 (X / .el-dialog__close / .close-btn / [aria-label*='close'])
#   3. 强制移除所�?.el-dialog 节点
POPUP_CLOSE_SELECTORS = [
    "div.el-dialog__close",
    ".el-dialog__close",
    "button.el-button--primary",
    "div[aria-label*='close' i]",
    ".close-btn",
    "button:has-text('知道�?)",
    "button:has-text('关闭')",
    "button:has-text('我知道了')",
    "button:has-text('Got it')",
    "button:has-text('Close')",
]

# 浏览器访�?等待超时 (ms)
PAGE_GOTO_TIMEOUT = 60000
PERIOD_CLICK_TIMEOUT = 5000
POPUP_WAIT_TIMEOUT = 15000


# ============================================================================
# 工具函数
# ============================================================================

def _ensure_diag_dir() -> None:
    """确保诊断输出目录存在"""
    os.makedirs(DIAG_DIR, exist_ok=True)


def _format_ts(ts_ms) -> str:
    """毫秒时间�?�?字符�?(YYYY-MM-DD HH:MM)"""
    try:
        ts_int = int(ts_ms)
        if ts_int < 10**12:  # 秒级
            ts_int *= 1000
        return datetime.fromtimestamp(ts_int / 1000).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return str(ts_ms)


def _normalize_record(entry):
    """
    �?SteamDT K线原�?entry 标准化为 dict
    entry 格式 (list): [ts, o, c, h, l, v, turnover]
    """
    if not isinstance(entry, (list, tuple)) or len(entry) < 7:
        return None
    try:
        return {
            "t": int(entry[0]),
            "o": float(entry[1]) if entry[1] is not None else 0.0,
            "c": float(entry[2]) if entry[2] is not None else 0.0,
            "h": float(entry[3]) if entry[3] is not None else 0.0,
            "l": float(entry[4]) if entry[4] is not None else 0.0,
            "v": float(entry[5]) if entry[5] is not None else 0.0,
            "turnover": float(entry[6]) if entry[6] is not None else 0.0,
        }
    except (ValueError, TypeError):
        return None


def _normalize_records(records):
    """批量标准�? 自动�?t 升序"""
    out = []
    for r in records or []:
        nr = _normalize_record(r)
        if nr:
            out.append(nr)
    out.sort(key=lambda x: x["t"])
    return out


def _resolve_target(args) -> dict:
    """
    根据 CLI 参数 (--local-id / --type-val / --market-name) 解析出查询目�?    返回:
        {"local_id": "...", "type_val": "...", "market_name": "..."}
    """
    id_mapper = get_id_mapper()

    if args.local_id:
        local_id = str(args.local_id)
        type_val = id_mapper.get_type_val(local_id)
        market_name = id_mapper.get_market_name(type_val) if type_val else None
    elif args.type_val:
        type_val = str(args.type_val)
        local_id = id_mapper.get_local_id(type_val)
        market_name = id_mapper.get_market_name(type_val)
    elif args.market_name:
        market_name = args.market_name
        local_id = id_mapper.market_to_local.get(market_name)
        type_val = id_mapper.get_type_val(local_id) if local_id else None
    else:
        raise ValueError("必须提供 --local-id / --type-val / --market-name 之一")

    if not market_name:
        raise ValueError(
            f"无法解析饰品: local_id={args.local_id} type_val={args.type_val} "
            f"market_name={args.market_name}"
        )

    return {
        "local_id": str(local_id) if local_id else None,
        "type_val": str(type_val) if type_val else None,
        "market_name": market_name,
    }


def _load_progress_failure(target: dict) -> dict | None:
    """
    �?kline_progress.json 读取失败项的 reason 字段 (如果 target 命中)
    返回 None �?{"reason": "...", ...}
    """
    if not os.path.exists(PROGRESS_FILE):
        return None
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            progress = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    failed = progress.get("failed", [])
    for entry in failed:
        if not isinstance(entry, dict):
            continue
        if (
            target["local_id"]
            and str(entry.get("local_id")) == str(target["local_id"])
        ) or (
            target["type_val"]
            and str(entry.get("type_val")) == str(target["type_val"])
        ) or (
            target["market_name"]
            and entry.get("market_name") == target["market_name"]
        ):
            return entry
    return None


# ============================================================================
# 浏览器自动化: 关闭弹窗 + 切周�?+ 拦截 API
# ============================================================================

async def _close_popups(page) -> None:
    """
    关闭弹窗�?3 种方�?(按顺序尝�? 全部不报�?:
      1. 等待 el-dialog 隐藏 (主方�? 应对公告)
      2. 点击常见关闭按钮 (兜底)
      3. JS 强制移除所�?.el-dialog 节点 (兜底)
    """
    # 方法 1: 等待 el-dialog 自动隐藏
    try:
        await page.wait_for_selector(
            "div.el-dialog", state="hidden", timeout=POPUP_WAIT_TIMEOUT
        )
        print("  �?弹窗已自动隐�?)
        return
    except Exception:
        pass

    # 方法 2: 逐个尝试常见关闭按钮
    for sel in POPUP_CLOSE_SELECTORS:
        try:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click(timeout=2000)
                await page.wait_for_timeout(500)
                print(f"  �?通过 {sel} 关闭弹窗")
                return
        except Exception:
            continue

    # 方法 3: JS 强制移除 .el-dialog 节点
    try:
        removed = await page.evaluate(
            """() => {
                const dialogs = document.querySelectorAll('div.el-dialog, .el-overlay, .el-message-box');
                let n = 0;
                dialogs.forEach(el => { el.remove(); n++; });
                return n;
            }"""
        )
        if removed:
            print(f"  �?JS 强制移除 {removed} 个弹窗节�?)
    except Exception:
        pass


async def _click_kline_tab(page) -> None:
    """点击 K线图 tab"""
    try:
        await page.click("div[id='tab-klinecharts']", timeout=PERIOD_CLICK_TIMEOUT)
        await page.wait_for_timeout(1500)
        print("  �?已点�?K线图 tab")
    except Exception as e:
        print(f"  ⚠️  K线图 tab 点击失败: {e}")


async def _click_period_buttons(page) -> None:
    """点击小时K / 日K 周期按钮 (span.item.period)"""
    try:
        # 切到小时K
        period_buttons = await page.query_selector_all("span.item.period")
        print(f"  🔍 找到 {len(period_buttons)} 个周期按�?)
        if len(period_buttons) >= 1:
            await period_buttons[0].click()
            await page.wait_for_timeout(2500)
            print("  �?已点击小时K")
        if len(period_buttons) >= 2:
            await period_buttons[1].click()
            await page.wait_for_timeout(2500)
            print("  �?已点击日K")
    except Exception as e:
        print(f"  ⚠️  周期按钮点击失败: {e}")


async def _diagnose_one(target: dict) -> int:
    """
    核心诊断流程: 启动浏览�?�?访问页面 �?关闭弹窗 �?切周�?�?拦截 API
    返回退出码 (0/1/2)
    """
    _ensure_diag_dir()
    market_name = target["market_name"]
    local_id = target["local_id"] or "unknown"
    type_val = target["type_val"] or "unknown"

    print()
    print("=" * 80)
    print("🔍 开始诊�?)
    print("=" * 80)
    print(f"  local_id   : {local_id}")
    print(f"  type_val   : {type_val}")
    print(f"  market_name: {market_name}")
    print()

    # 进度文件失败项提�?    fail_info = _load_progress_failure(target)
    if fail_info:
        print(f"  ⚠️  此饰品在 kline_progress.json 的失败列表中:")
        print(f"      reason: {fail_info.get('reason', '未提�?)}")
        if fail_info.get("attempts"):
            print(f"      attempts: {fail_info['attempts']}")
        if fail_info.get("last_attempt_at"):
            print(f"      last_attempt_at: {fail_info['last_attempt_at']}")
        print()

    # 用于�?handle_response 闭包外累积结�?    intercepted = {"hourly_raw": None, "daily_raw": None, "hourly": [], "daily": []}

    encoded_name = quote(market_name)
    url = f"https://steamdt.com/cs2/{encoded_name}"

    print(f"  📄 访问: {url}")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=BROWSER_LAUNCH_ARGS,
            )
            context = await browser.new_context(user_agent=USER_AGENT)
            page = await context.new_page()

            # 拦截�? 捕获 kline API 响应
            async def handle_response(response):
                u = response.url
                if "kline" not in u or "typeVal" not in u:
                    return
                try:
                    data = await response.json()
                except Exception:
                    return
                if not data.get("success"):
                    return
                records = data.get("data", [])
                norm = _normalize_records(records)
                if "type=1" in u:
                    intercepted["hourly_raw"] = data
                    intercepted["hourly"] = norm
                elif "type=2" in u:
                    intercepted["daily_raw"] = data
                    intercepted["daily"] = norm

            page.on("response", handle_response)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT)
                await page.wait_for_timeout(2000)
                print("  �?页面已加�?)

                print("  🪟 关闭弹窗...")
                await _close_popups(page)

                print("  📊 滑动页面...")
                try:
                    await page.evaluate("window.scrollBy(0, 400)")
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass

                print("  📈 切换到K线图...")
                await _click_kline_tab(page)

                print("  🔄 切换时间周期...")
                await _click_period_buttons(page)

                # 多等一会儿�?API 响应落袋
                await page.wait_for_timeout(3000)
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
    except Exception as e:
        print(f"  �?浏览�?页面访问异常: {e}")
        traceback.print_exc()
        return 1

    # 拦截结果统计
    hourly_n = len(intercepted["hourly"])
    daily_n = len(intercepted["daily"])
    print()
    print("=" * 80)
    print("📊 诊断报告")
    print("=" * 80)
    print(f"  local_id   : {local_id}")
    print(f"  type_val   : {type_val}")
    print(f"  market_name: {market_name}")
    print()
    print(f"  hourly: 拦截 {hourly_n} �?K�?)
    print(f"  daily : 拦截 {daily_n} �?K�?)
    print()

    # 显示最�?5 �?hourly
    print("  最�?5 �?hourly:")
    for r in intercepted["hourly"][-5:]:
        print(
            f"    {_format_ts(r['t'])} | "
            f"O:{r['o']} H:{r['h']} L:{r['l']} C:{r['c']} V:{r['v']}"
        )
    if not intercepted["hourly"]:
        print("    (无数�?")

    print()
    print("  最�?5 �?daily:")
    for r in intercepted["daily"][-5:]:
        print(
            f"    {_format_ts(r['t'])} | "
            f"O:{r['o']} H:{r['h']} L:{r['l']} C:{r['c']} V:{r['v']}"
        )
    if not intercepted["daily"]:
        print("    (无数�?")

    # 保存原始 API 响应
    try:
        if intercepted["hourly_raw"] is not None:
            fpath = os.path.join(DIAG_DIR, f"{local_id}_hourly.json")
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(intercepted["hourly_raw"], f, ensure_ascii=False, indent=2)
            print(f"\n  💾 已保�? {fpath}")
        if intercepted["daily_raw"] is not None:
            fpath = os.path.join(DIAG_DIR, f"{local_id}_daily.json")
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(intercepted["daily_raw"], f, ensure_ascii=False, indent=2)
            print(f"  💾 已保�? {fpath}")
    except Exception as e:
        print(f"  ⚠️  保存原始响应失败: {e}")

    # 数据验证 (内联简化版, 替代�?data_validator.DataValidator)
    if hourly_n and daily_n:
        print()
        print("  🔍 数据验证...")
        h_res = _validate_kline_simple(intercepted["hourly"])
        d_res = _validate_kline_simple(intercepted["daily"])
        h_ok = h_res["passed"]
        d_ok = d_res["passed"]
        print(f"  hourly 验证: {'�?通过' if h_ok else '�?失败'} (errors={len(h_res['errors'])})")
        print(f"  daily  验证: {'�?通过' if d_ok else '�?失败'} (errors={len(d_res['errors'])})")
        if not h_ok or not d_ok:
            for err in (h_res["errors"] + d_res["errors"])[:5]:
                print(f"    �?{err}")
            return 2
        return 0
    else:
        print("\n  �?数据不完�?(hourly �?daily 缺失)")
        return 2


def _validate_kline_simple(records: list) -> dict:
    """简化的 K线数据验�?(内联替代�?DataValidator.validate_dataset)
    检�? 必需字段 / 价格正数 / high≥low / volume�?
    """
    errors: list = []
    if not records:
        errors.append("无记�?)
        return {"errors": errors, "passed": False}
    required = ("t", "o", "c", "h", "l", "v")
    for i, r in enumerate(records):
        for field in required:
            if field not in r:
                errors.append(f"record[{i}] 缺字�? {field}")
                continue
        if "o" in r and "c" in r:
            try:
                if float(r["o"]) <= 0 or float(r["c"]) <= 0:
                    errors.append(f"record[{i}] 价格非正: o={r['o']} c={r['c']}")
            except (TypeError, ValueError):
                errors.append(f"record[{i}] 价格解析失败")
        if "h" in r and "l" in r:
            try:
                if float(r["h"]) < float(r["l"]):
                    errors.append(f"record[{i}] h<l: h={r['h']} l={r['l']}")
            except (TypeError, ValueError):
                errors.append(f"record[{i}] h/l 解析失败")
        if "v" in r:
            try:
                if float(r["v"]) < 0:
                    errors.append(f"record[{i}] v<0: v={r['v']}")
            except (TypeError, ValueError):
                pass
    return {"errors": errors[:20], "passed": len(errors) == 0}


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    ap = argparse.ArgumentParser(
        description="CS2 单饰�?K�?API 拦截诊断工具 (T12)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
用法示例:
  python kline/diagnose_kline.py --local-id 24432
  python kline/diagnose_kline.py --type-val 12345
  python kline/diagnose_kline.py --market-name "AK-47 | Redline"

退出码:
  0 = 正常 (拦截到完�?hourly + daily, 验证通过)
  1 = 无法访问 (网络/页面/选择器失�?
  2 = 数据异常 (数据不完整或验证器报�?
""",
    )
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--local-id", dest="local_id", help="�?local_id �?(e.g. 24432)")
    group.add_argument("--type-val", dest="type_val", help="�?type_val �?(e.g. 12345)")
    group.add_argument("--market-name", dest="market_name", help='�?market_name �?(e.g. "AK-47 | Redline")')

    args = ap.parse_args()

    try:
        target = _resolve_target(args)
    except ValueError as e:
        print(f"�?{e}")
        return 1
    except Exception as e:
        print(f"�?ID 映射异常: {e}")
        return 1

    try:
        rc = asyncio.run(_diagnose_one(target))
    except KeyboardInterrupt:
        print("\n⏹️  用户中断")
        return 1
    except Exception as e:
        print(f"\n�?异常: {e}")
        traceback.print_exc()
        return 1

    print()
    print("=" * 80)
    print(f"🏁 诊断结束, 退出码: {rc} (0=正常 1=无法访问 2=数据异常)")
    print("=" * 80)
    return rc


if __name__ == "__main__":
    sys.exit(main())
