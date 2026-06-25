#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块：数据收集 - K线爬虫 (内含基础设施 + 共用基类 + 工具函数)
文件：kline/auto_kline_history.py
用途：双脚本架构 (auto_kline_history.py / auto_kline_incremental.py) 之一。
      本文件内含:
        1. 基础设施 (内联):
           - 路径配置: BASE_DIR / DATA_DIRS / MAPPING_FILES / get_data_dir() / get_mapping_file()
           - ID 映射: IDMapper 类 + get_id_mapper() 单例
        2. 工具函数:
           - merge_with_skip / save_kline_data / append_progress / log / atomic_write_json
           - normalize_records / is_rate_limited / _safe_print / _load_progress_raw
        3. 共用基类: KlineCommon (浏览器 / API 拦截 / 单页抓取 / 限流)
        4. HistoryCrawler: 全量抓取历史 K线, 跳过已抓
      另存 auto_kline_incremental.py: 增量更新 (merge 现有 + 跳过当前未收盘周期)
      调用模式: 1H 18 轮 + 1D 6 轮 = 24 calls/item, 1 天上限约 47 items。

使用:
    python kline/auto_kline_history.py --help
    python kline/auto_kline_history.py --limit 10
    python kline/auto_kline_history.py --start-from 1 --limit 5
    python kline/auto_kline_history.py --api-delay 0.5 --max-pages-1H 20
    python kline/auto_kline_history.py --no-headless
"""

import sys
from pathlib import Path

# 项目根目录 (cs2-rank-return-prediction-main/), 用于 sys.path 与路径构造
# 注意: 只加根目录, 不加 kline/, 否则 'import auto_kline_history' 和
# 'from kline.auto_kline_history import ...' 会加载为两个独立模块,
# 导致 log() 等函数被重复定义/绑定, 写入 kline_log.txt 双倍行数
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import argparse
import asyncio
import json
import os
import re
import time
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import quote

from playwright.async_api import async_playwright


# ============================================================================
# §1. 基础设施 - 路径配置 (内联自原 config.py)
# ============================================================================

DATA_DIRS = {
    "hourly": BASE_DIR / "data" / "hourly",   # 小时K线
    "daily": BASE_DIR / "data" / "daily",     # 日K线
}

DEFAULT_KLINE_TYPE = "hourly"

MAPPING_FILES = {
    "all_items_cache": BASE_DIR / "mappings" / "all_items_cache.json",
    "itemid_txt": BASE_DIR / "mappings" / "itemid.txt",
    "itemid_market_map": BASE_DIR / "mappings" / "itemid_market_map.json",
}

# 启动时确保数据目录存在
for _data_dir in DATA_DIRS.values():
    _data_dir.mkdir(parents=True, exist_ok=True)


def get_data_dir(kline_type: str = None) -> Path:
    """获取数据目录路径 (kline_type: "hourly" / "daily")"""
    if kline_type is None:
        kline_type = DEFAULT_KLINE_TYPE
    if kline_type not in DATA_DIRS:
        raise ValueError(f"无效的K线类型: {kline_type}，可选: {list(DATA_DIRS.keys())}")
    return DATA_DIRS[kline_type]


def get_mapping_file(name: str) -> Path:
    """获取映射文件路径 (name: "all_items_cache" / "itemid_txt" / "itemid_market_map")"""
    if name not in MAPPING_FILES:
        raise ValueError(f"无效的映射文件名: {name}，可选: {list(MAPPING_FILES.keys())}")
    return MAPPING_FILES[name]


# ============================================================================
# §2. 基础设施 - ID 映射 (内联自原 id_mapper.py)
# ============================================================================
class IDMapper:
    """ID mapper: website typeVal <-> local ID"""

    def __init__(self):
        self.typeval_to_local: Dict[str, str] = {}
        self.local_to_typeval: Dict[str, str] = {}
        self.typeval_to_market: Dict[str, str] = {}
        self.market_to_local: Dict[str, str] = {}
        self._load_mappings()

    def _load_mappings(self):
        try:
            cache_file = get_mapping_file("all_items_cache")
            with open(cache_file, "r", encoding="utf-8") as f:
                all_items = json.load(f)
            for item in all_items:
                market_name = item.get("marketHashName")
                if not market_name:
                    continue
                # 优先从 C5 platformList 取 itemId (5位)
                # 备选: steamdt_typeVal 字段 (18位, SteamDT 板块 typeVal)
                type_val = None
                for platform in item.get("platformList", []):
                    if platform.get("name") == "C5":
                        type_val = str(platform.get("itemId", ""))
                        if type_val:
                            break
                if not type_val:
                    type_val = item.get("steamdt_typeVal", "")
                if type_val:
                    self.typeval_to_market[type_val] = market_name
            map_file = get_mapping_file("itemid_market_map")
            with open(map_file, "r", encoding="utf-8") as f:
                id_to_market = json.load(f)
            self.market_to_local = {v: k for k, v in id_to_market.items()}
            for type_val, market_name in self.typeval_to_market.items():
                local_id = self.market_to_local.get(market_name)
                if local_id:
                    self.typeval_to_local[type_val] = local_id
                    self.local_to_typeval[local_id] = type_val
            print(f"ID mapping loaded: {len(self.typeval_to_local)} typeVal<->local pairs")
        except Exception as e:
            print(f"Failed to load ID mapping: {e}")

    def get_local_id(self, type_val: str) -> Optional[str]:
        return self.typeval_to_local.get(type_val)

    def get_type_val(self, local_id: str) -> Optional[str]:
        return self.local_to_typeval.get(local_id)

    def get_market_name(self, type_val: str) -> Optional[str]:
        return self.typeval_to_market.get(type_val)

    def get_display_info(self, type_val: str) -> Dict[str, Optional[str]]:
        return {
            "type_val": type_val,
            "local_id": self.get_local_id(type_val),
            "market_name": self.get_market_name(type_val),
        }


_mapper_instance: Optional[IDMapper] = None


def get_id_mapper() -> IDMapper:
    """获取 IDMapper 单例 (避免重复加载 ~30K 条映射)"""
    global _mapper_instance
    if _mapper_instance is None:
        _mapper_instance = IDMapper()
    return _mapper_instance


def typeval_to_local_id(type_val: str) -> Optional[str]:
    return get_id_mapper().get_local_id(type_val)


def local_id_to_typeval(local_id: str) -> Optional[str]:
    return get_id_mapper().get_type_val(local_id)


# ============================================================================
# §3. 工具函数 (内联自原 auto_kline_common.py)
# ============================================================================
# --- 常量 ---
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
BROWSER_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]

# 1 天限流检测 (106 errorCode: "今日访问次数超限")
# 连续触发 3 次 106 → 自动停止爬取, 避免浪费请求预算
MAX_CONSECUTIVE_106 = 3

PROGRESS_FILE = "data/kline_progress.json"
LOG_FILE = "data/kline_log.txt"
HOURLY_DATA_DIR = str(get_data_dir("hourly"))
DAILY_DATA_DIR = str(get_data_dir("daily"))


# --- 工具函数 ---
def _safe_print(line: str) -> None:
    """Windows 终端兼容打印 (过滤 emoji 等非 GBK 字符)"""
    line = re.sub(
        r'[\U0001F300-\U0001F9FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF'
        r'\U0001F1E0-\U0001F1FF\u2600-\u27BF\U0001F900-\U0001F9FF]',
        '',
        line
    )
    try:
        print(line)
    except UnicodeEncodeError:
        try:
            print(line.encode('gbk', errors='replace').decode('gbk'))
        except Exception:
            print(line.encode('ascii', errors='replace').decode('ascii'))


def log(message: str, also_print: bool = True) -> None:
    """带时间戳追加写日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    try:
        os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if also_print:
        _safe_print(line)


# --- v3 计划进展统计 (history / incremental 共用) ---
def _load_plan_ids() -> set:
    """读取 mappings/itemid.txt 的 v3 计划 ID 集合"""
    plan_ids = set()
    try:
        txt_path = BASE_DIR / "mappings" / "itemid.txt"
        for line in txt_path.read_text(encoding="utf-8").split("\n"):
            s = line.strip()
            if not s or s.startswith("//") or s.startswith("#"):
                continue
            parts = re.split(r"[:：]", s, 1)
            if len(parts) == 2 and parts[0].strip().isdigit():
                plan_ids.add(parts[0].strip())
    except Exception:
        pass
    return plan_ids


def _count_crawled() -> int:
    """统计 data/hourly/ 中已落盘的 v3 计划物品数"""
    try:
        return len(list(Path(HOURLY_DATA_DIR).glob("*.json")))
    except Exception:
        return 0


def log_plan_progress(tag: str) -> None:
    """输出 v3 计划整体覆盖率 (history/incremental 启动/收尾时调用)

    Args:
        tag: "[HISTORY]" 或 "[INCREMENTAL]"
    """
    try:
        plan_ids = _load_plan_ids()
        plan_total = len(plan_ids)
        crawled = _count_crawled()
        if plan_total == 0:
            log(f"{tag} ⚠️  v3 计划列表为空 (mappings/itemid.txt?)")
            return
        # 计算交集 (已抓且在计划内)
        done_in_plan = 0
        hourly_dir = Path(HOURLY_DATA_DIR)
        for lid in plan_ids:
            if (hourly_dir / f"{lid}.json").exists():
                done_in_plan += 1
        pct = done_in_plan * 100.0 / plan_total
        remaining = plan_total - done_in_plan
        log(f"{tag} 📋 v3 计划进展: {done_in_plan}/{plan_total} = {pct:.1f}%  (剩余 {remaining} 条)")
    except Exception as e:
        log(f"{tag} ⚠️  进展统计失败: {e}")


def atomic_write_json(path: str, data, max_retries: int = 5) -> None:
    """原子写盘: 先写 .tmp 再 rename, 防止进程崩溃导致文件损坏

    Windows 修复: rename 可能因 AV 扫描/并发读触发 WinError 32
    - 重试 5 次, 每次 sleep 0.1s/0.2s/0.3s...
    - 若仍失败, 降级用 open(path, 'w') 直接覆盖 (数据完整性优先)
    """
    import shutil
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = path + ".tmp"
    # 1) 写 .tmp (这一步如果失败会立刻抛, 不会留下半成品)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 2) rename .tmp → target, 带重试
    for attempt in range(max_retries):
        try:
            if os.path.exists(path):
                os.remove(path)
            os.rename(tmp_path, path)
            return
        except OSError as e:
            if attempt == max_retries - 1:
                # 最后一次: 降级用 copy + remove 跨卷兼容, 或直接覆盖写
                log(f"      ⚠️  rename 失败 {max_retries} 次 (WinError {e.winerror if hasattr(e, 'winerror') else e}), 降级覆盖写")
                try:
                    shutil.copy2(tmp_path, path)
                    os.remove(tmp_path)
                    return
                except Exception as e2:
                    log(f"      ❌ 降级写盘也失败: {e2}")
                    # 最后一搏: 直接 open(path, 'w') 覆盖
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                    return
            time.sleep(0.1 * (attempt + 1))


def normalize_records(records):
    """标准化 K线数据
    输入: list of [ts, o, c, h, l, v, turnover] (timestamp 单位: 秒)
    输出: list of {"t": ts_ms, "o", "c", "h", "l", "v", "turnover"}
    """
    normalized = []
    for entry in records:
        if len(entry) < 7:
            continue
        try:
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
        except (TypeError, ValueError):
            continue
    normalized.sort(key=lambda x: x["t"])
    return normalized


# --- 限流检测 ---
def is_rate_limited(response_json) -> tuple:
    """
    SteamDT K线 API 限流 / 错误码检测
    Returns:
        (is_limited: bool, kind: "107" / "108" / "106" / "none")
        - 107: 限流 → 60s 退避
        - 108: 环境异常 → 120s 退避
        - 106: 今日访问次数超限 → 连续 3 次自动停
        - none: 正常 / 未知错误
    """
    if not isinstance(response_json, dict):
        return False, "none"
    ec = response_json.get("errorCode")
    if ec == 107:
        return True, "107"
    if ec == 108:
        return True, "108"
    if ec == 106:
        return True, "106"
    return False, "none"


# --- 核心: merge_with_skip ---
def merge_with_skip(new_data: list, existing_data: list, period: str) -> tuple:
    """
    合并新数据 + 现有数据, 跳过当前未收盘周期 (避免写入不完整 K线)

    Args:
        new_data: 新抓的 records, list of dict {t, o, c, h, l, v, turnover}
        existing_data: 现有 records, 同上
        period: "1H" / "1D"

    Returns:
        (merged_list, stats_dict)
        - merged_list: sorted by t, dict 格式 records
        - stats_dict: {"skipped_current": N, "added": M, "updated": K, "preserved": P}
    """
    if period not in ("1H", "1D"):
        raise ValueError(f"period 必须是 '1H' 或 '1D', 收到: {period!r}")

    # 1. 把 existing_data 转 dict (按 t 去重)
    merged: dict = {}
    for r in existing_data or []:
        if "t" not in r:
            continue
        merged[r["t"]] = r
    preserved = len(merged)

    # 2. 计算当前未收盘周期起点 (ms)
    now_ms = int(time.time() * 1000)
    if period == "1H":
        current_period_start_ms = now_ms - (now_ms % 3_600_000)
    else:  # "1D"
        current_period_start_ms = now_ms - (now_ms % 86_400_000)

    # 3. 遍历 new_data
    skipped_current = 0
    added = 0
    updated = 0
    for r in new_data or []:
        if "t" not in r:
            continue
        ts = r["t"]
        if ts >= current_period_start_ms:
            # 当前未收盘周期, 跳过 (不写入)
            skipped_current += 1
            continue
        if ts in merged:
            updated += 1
        else:
            added += 1
        merged[ts] = r  # 无条件覆盖

    # 4. 返回 sorted list
    merged_list = sorted(merged.values(), key=lambda x: x["t"])
    stats = {
        "skipped_current": skipped_current,
        "added": added,
        "updated": updated,
        "preserved": preserved,
    }
    return merged_list, stats


# --- 数据落盘 (全量写入路径: v > existing_v 覆盖) ---
def save_kline_data(local_id: str, hourly_data: list, daily_data: list,
                    hourly_dir: str = None, daily_dir: str = None) -> None:
    """落盘: 合并去重, 同时间戳保留 v 大的"""
    h_dir = hourly_dir or HOURLY_DATA_DIR
    d_dir = daily_dir or DAILY_DATA_DIR

    if hourly_data:
        _merge_and_write_v(
            os.path.join(h_dir, f"{local_id}.json"),
            hourly_data, "小时K线"
        )
    if daily_data:
        _merge_and_write_v(
            os.path.join(d_dir, f"{local_id}.json"),
            daily_data, "日K线"
        )


def _merge_and_write_v(file_path: str, new_records, label: str) -> None:
    """全量写入路径: 同 t 保留 v 大的 (atomic_write_json 防止崩溃损坏)"""
    existing = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing_dict = {r["t"]: r for r in existing}
    new_count = 0
    for new_record in new_records:
        ts = new_record["t"]
        if ts not in existing_dict or new_record["v"] > existing_dict[ts]["v"]:
            existing_dict[ts] = new_record
            new_count += 1
    if new_count > 0:
        merged = sorted(existing_dict.values(), key=lambda x: x["t"])
        try:
            atomic_write_json(file_path, merged)
            log(f"      ✅ {label}: 更新 {new_count} 条")
        except Exception as e:
            log(f"      ⚠️  {label}: 写盘失败: {e}")
    else:
        log(f"      ℹ️  {label}: 无新数据")


# --- 进度管理 ---
def append_progress(progress_path: str, local_id, status: str, **extra) -> None:
    """更新 kline_progress.json, 添加或更新 local_id 状态

    Args:
        progress_path: 进度文件路径 (默认 PROGRESS_FILE)
        local_id: 项目 5 位 ID
        status: "completed" / "failed" / "pending"
        **extra: 附加字段 (e.g. reason=..., rounds=..., market_name=...)
    """
    progress = _load_progress_raw(progress_path)

    lid = str(local_id)

    # 从 pending 中移除
    progress["pending"] = [p for p in progress.get("pending", []) if str(p) != lid]

    if status == "completed":
        completed = set(str(c) for c in progress.get("completed", []))
        completed.add(lid)
        progress["completed"] = sorted(completed, key=lambda x: str(x))
        progress["last_completed_local_id"] = sorted(completed, key=lambda x: str(x))[-1]
        # 从 failed 中移除 (成功后清掉失败记录)
        progress["failed"] = [
            f for f in progress.get("failed", [])
            if str(f.get("local_id", "")) != lid
        ]
    elif status == "failed":
        existing = [f for f in progress.get("failed", [])
                    if str(f.get("local_id", "")) == lid]
        if existing:
            existing[0].update(extra)
        else:
            entry = {"local_id": lid}
            entry.update(extra)
            progress["failed"] = progress.get("failed", []) + [entry]
    elif status == "pending":
        pending = set(str(p) for p in progress.get("pending", []))
        pending.add(lid)
        progress["pending"] = sorted(pending, key=lambda x: str(x))
    else:
        log(f"      ⚠️  未知 status: {status!r}, 跳过")

    progress["date"] = datetime.now().strftime("%Y-%m-%d")
    if "started_at" not in progress:
        progress["started_at"] = datetime.now().isoformat(timespec="seconds")

    try:
        atomic_write_json(progress_path, progress)
    except Exception as e:
        log(f"⚠️  进度写盘失败: {e}")


def _load_progress_raw(progress_path: str) -> dict:
    """加载进度文件, 跨天归档 + 兜底空 dict"""
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(progress_path):
        try:
            with open(progress_path, "r", encoding="utf-8") as f:
                progress = json.load(f)
            progress_date = progress.get("date", "")
            if progress_date and progress_date != today:
                # 跨天: 归档昨日
                archive_path = (
                    os.path.join(os.path.dirname(progress_path) or ".",
                                 f"progress_{progress_date}.json")
                )
                log(f"📅 检测到新的一天 ({today}), 归档昨日进度到 {archive_path}")
                try:
                    atomic_write_json(archive_path, progress)
                except Exception as e:
                    log(f"⚠️  归档昨日进度失败: {e}")
                return _new_progress_dict(today)
            # 兼容旧 schema
            if "started_at" not in progress:
                progress["started_at"] = datetime.now().isoformat(timespec="seconds")
            if "completed" not in progress:
                progress["completed"] = []
            if "failed" not in progress:
                progress["failed"] = []
            if "pending" not in progress:
                progress["pending"] = []
            return progress
        except Exception as e:
            log(f"⚠️  加载进度文件失败, 重建: {e}")
    return _new_progress_dict(today)


def _new_progress_dict(today: str) -> dict:
    return {
        "date": today,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "last_completed_local_id": None,
        "completed": [],
        "failed": [],
        "pending": [],
    }


# ============================================================================
# §4. KlineCommon 共用基类 (浏览器 / API 拦截 / 单页抓取)
# ============================================================================
class KlineCommon:
    """双脚本架构共用基类: 浏览器 / API 拦截 / 单页抓取

    子类化用法 (history / incremental):
        class KlineHistory(KlineCommon):
            async def run(self):
                await self._ensure_browser()
                ...
    """

    def __init__(self, headless: bool = True):
        self.headless = bool(headless)

        # 1 天限流检测
        self._consecutive_106: int = 0
        self._daily_limit_hit: bool = False

        # 浏览器句柄
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------------
    # 浏览器管理
    # ------------------------------------------------------------------------
    async def _ensure_browser(self):
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=BROWSER_LAUNCH_ARGS,
            )
            self._context = await self._browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 900},
            )
            self._page = await self._context.new_page()
            log("🌐 浏览器已启动 (KlineCommon)")

    async def _restart_browser(self):
        await self._close_browser()
        await self._ensure_browser()
        log("🔄 浏览器已重启 (释放内存)")

    async def _close_browser(self):
        try:
            if self._page:
                await self._page.close()
        except Exception:
            pass
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    # ------------------------------------------------------------------------
    # 公告弹窗自动关闭 (3 种方法串行 fallback)
    # ------------------------------------------------------------------------
    async def close_announcement(self) -> bool:
        """3 种方法串行, 任一成功即返回 True"""
        for selector in [
            'button:has-text("我已知晓")',
            '.el-dialog__wrapper .el-button--primary',
        ]:
            try:
                await self._page.click(selector, timeout=3000)
                log("      ✅ 公告已关闭 (CSS 按钮)")
                return True
            except Exception:
                continue

        try:
            await self._page.evaluate(
                "() => document.querySelectorAll("
                "'.el-dialog, .el-overlay, .modal, .announcement'"
                ").forEach(d => { d.style.display = 'none'; d.remove(); })"
            )
            log("      ✅ 公告已关闭 (JS 强制移除)")
            return True
        except Exception:
            pass

        try:
            await self._page.keyboard.press("Escape")
            log("      ✅ 公告已关闭 (ESC)")
            return True
        except Exception:
            pass

        try:
            await self._page.wait_for_selector(
                ".el-dialog", state="hidden", timeout=3000
            )
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------------
    # K线图渲染等待
    # ------------------------------------------------------------------------
    async def switch_to_kline_chart(self) -> bool:
        """切换到 K线 tab, 等 K线图容器挂载"""
        try:
            await self._page.wait_for_selector(
                "div[id='tab-klinecharts']", state="visible", timeout=10000
            )
            await self._page.click("div[id='tab-klinecharts']", timeout=5000)
            for sel in [".klinecharts-container", "canvas", ".k-line"]:
                try:
                    await self._page.wait_for_selector(
                        sel, state="visible", timeout=10000
                    )
                    return True
                except Exception:
                    continue
            return False
        except Exception as e:
            log(f"      ⚠️  K线图切换失败: {e}")
            return False

    # ------------------------------------------------------------------------
    # 周期按钮点击
    # ------------------------------------------------------------------------
    async def click_period_buttons(self) -> bool:
        """点 1H (index 0) + 1D (index 1) 周期按钮"""
        try:
            try:
                await self._page.wait_for_function(
                    "() => document.querySelectorAll('span.item.period').length >= 6",
                    timeout=10000,
                )
            except Exception:
                try:
                    await self._page.wait_for_function(
                        "() => document.querySelectorAll('span.item.period').length >= 2",
                        timeout=5000,
                    )
                except Exception:
                    log("      ⚠️  周期按钮未挂载")
                    return False

            await self._page.evaluate(
                "() => document.querySelectorAll('span.item.period')[0]?.click()"
            )
            await self._page.wait_for_timeout(3000)
            await self._page.evaluate(
                "() => document.querySelectorAll('span.item.period')[1]?.click()"
            )
            await self._page.wait_for_timeout(3000)
            return True
        except Exception as e:
            log(f"      ⚠️  周期按钮点击失败: {e}")
            return False

    # ------------------------------------------------------------------------
    # capture_api_headers (拦截 chart latest 1H/1D 请求)
    # ------------------------------------------------------------------------
    async def capture_api_headers(self, period: str) -> dict | None:
        """
        触发 chart 发 1 次 API 请求, 捕获其 URL + headers
        Args:
            period: "1H" / "1D"
        Returns:
            {"url": str, "headers": dict} or None
        """
        if self._page is None:
            return None
        captured_event = asyncio.Event()
        captured: dict = {}
        period_idx = 0 if period == "1H" else 1
        period_type = "type=1" if period == "1H" else "type=2"

        async def on_request(req):
            url = req.url
            if (
                "kline" in url
                and period_type in url
                and "maxTime" in url
                and "maxTime=" not in url
            ):
                if not captured_event.is_set():
                    captured["url"] = url
                    captured["headers"] = dict(req.headers)
                    captured_event.set()

        try:
            # 一次性监听器: 触发后自动移除, 避免累积泄漏
            self._page.once(
                "request",
                lambda r: asyncio.create_task(on_request(r)),
            )
            try:
                await self._page.evaluate(
                    f"() => document.querySelectorAll('span.item.period')[{period_idx}]?.click()"
                )
            except Exception as e:
                log(f"      ⚠️  点 {period} 周期按钮失败: {e}")
            try:
                await asyncio.wait_for(captured_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                log(f"      ⚠️  [{period}] 10s 内未捕获 chart 请求")
                return None
            if captured.get("url"):
                log(
                    f"      [capture-{period}] URL 长度={len(captured['url'])} "
                    f"headers={len(captured['headers'])}"
                )
                return {"url": captured["url"], "headers": captured["headers"]}
            return None
        except Exception as e:
            log(f"      ⚠️  [{period}] 捕获异常: {e}")
            return None

    # ------------------------------------------------------------------------
    # fetch_kline_page (单页抓取 + maxTime 翻页, 返回 list)
    # ------------------------------------------------------------------------
    async def fetch_kline_page(self, captured: dict, period: str,
                               max_pages: int = 18,
                               api_delay: float = 0.3) -> list:
        """
        用 captured headers + maxTime 翻页, 拉全部历史

        限流:
            - 107 (限流) → 60s 退避, 单轮最多重试 1 次
            - 108 (环境异常) → 120s 退避, 单轮最多重试 1 次
            - 连续 2 轮限流就停止
            - 106 (今日访问超限) → 连续 3 次触发 self._daily_limit_hit
        """
        if not captured or self._context is None:
            return []
        if period not in ("1H", "1D"):
            log(f"      ⚠️  fetch_kline_page: period 必须是 '1H'/'1D', 收到 {period!r}")
            return []

        all_data: list = []
        seen_first_ts: set = set()
        rounds = 0
        next_max_time: int | None = None
        rate_retry = 0
        MAX_RATE_RETRY = 1
        consecutive_limited = 0
        MAX_CONSECUTIVE_LIMITED = 2
        tag = f"[api-{period}]"

        for round_idx in range(max_pages + 1):
            if round_idx == 0 or next_max_time is None:
                url = captured["url"]
            else:
                url = re.sub(
                    r"maxTime(?=[^=]|$)",
                    f"maxTime={next_max_time}",
                    captured["url"],
                )
                if url == captured["url"]:
                    url = captured["url"].replace(
                        "maxTime", f"maxTime={next_max_time}", 1
                    )

            try:
                resp = await self._context.request.get(
                    url, headers=captured["headers"]
                )
            except Exception as e:
                log(f"      {tag} 轮 {round_idx} 请求异常: {e}")
                break

            try:
                j = await resp.json()
            except Exception as e:
                log(f"      {tag} 轮 {round_idx} JSON 解析失败: {e}")
                break

            limited, kind = is_rate_limited(j)
            if limited and kind in ("107", "108"):
                rate_retry += 1
                if rate_retry > MAX_RATE_RETRY:
                    consecutive_limited += 1
                    log(
                        f"      {tag} 轮 {round_idx} 限流重试 {MAX_RATE_RETRY} 次仍失败 "
                        f"(consecutive={consecutive_limited}/{MAX_CONSECUTIVE_LIMITED})"
                    )
                    if consecutive_limited >= MAX_CONSECUTIVE_LIMITED:
                        log(
                            f"      {tag} 连续 {MAX_CONSECUTIVE_LIMITED} 轮限流, "
                            f"停止该周期 (数据可能不完整)"
                        )
                        break
                    rate_retry = 0
                    continue
                wait_s = 60 if kind == "107" else 120
                log(
                    f"      {tag} 限流 (errorCode={kind}), 退避 {wait_s}s "
                    f"(重试 {rate_retry}/{MAX_RATE_RETRY})"
                )
                await asyncio.sleep(wait_s)
                continue

            if limited and kind == "106":
                self._consecutive_106 += 1
                if self._consecutive_106 >= MAX_CONSECUTIVE_106:
                    self._daily_limit_hit = True
                    log(
                        f"      {tag} 连续 {self._consecutive_106} 次 106, "
                        f"今日限额触发, 自动停止爬取"
                    )
                    break
                log(
                    f"      {tag} 轮 {round_idx} errorCode=106 "
                    f"({self._consecutive_106}/{MAX_CONSECUTIVE_106})"
                )
                break

            rate_retry = 0
            consecutive_limited = 0

            if not j.get("success"):
                log(
                    f"      {tag} 轮 {round_idx} success=False "
                    f"err={j.get('errorCode')} msg={j.get('message', '')[:50]}"
                )
                break

            data = j.get("data", [])
            if not data:
                log(f"      {tag} 轮 {round_idx} data 为空, 早停")
                break

            try:
                data = [[int(x) if isinstance(x, str) else x for x in r] for r in data]
            except Exception:
                pass

            first_ts = data[0][0]
            last_ts = data[-1][0]
            rounds += 1

            if first_ts in seen_first_ts:
                log(f"      {tag} 轮 {round_idx} first_ts={first_ts} 重复, 早停")
                break
            seen_first_ts.add(first_ts)
            all_data.extend(data)

            log(
                f"      {tag} 轮 {round_idx}: {len(data)} 条, "
                f"{datetime.fromtimestamp(first_ts)} -> "
                f"{datetime.fromtimestamp(last_ts)}"
            )

            next_max_time = first_ts - 1

            if round_idx < max_pages:
                await asyncio.sleep(api_delay)

        log(f"      {tag} 完成: {rounds} 轮 / 累计 {len(all_data)} 条")
        return all_data

    # ------------------------------------------------------------------------
    # 收尾
    # ------------------------------------------------------------------------
    async def close(self) -> None:
        await self._close_browser()


# ============================================================================
# §5. HistoryCrawler 主类
# ============================================================================
class HistoryCrawler(KlineCommon):
    """历史数据全量抓取爬虫

    行为:
        - 遍历 `id_mapper.local_to_typeval.items()` 加载饰品
        - 跳过 `data/hourly/{local_id}.json` 和 `data/daily/{local_id}.json` 同时存在的
        - 抓取时复用 KlineCommon 的浏览器 / API 拦截 / 单页抓取逻辑
        - 落盘用 save_kline_data (v > existing_v 去重)
        - 进度用 append_progress 写 completed
        - 1 天限流检测 (106 errorCode 连续 3 次) → 自动停止爬取
    """

    def __init__(self, start_from=None, limit=None, api_delay: float = 0.3,
                 max_pages_1H: int = 18, max_pages_1D: int = 6,
                 headless: bool = True):
        super().__init__(headless=headless)

        # CLI 参数
        self.start_from = str(start_from) if start_from is not None else None
        self.limit = int(limit) if limit is not None else None
        self.api_delay = max(0.0, float(api_delay))
        self.max_pages_1H = max(1, int(max_pages_1H))
        self.max_pages_1D = max(1, int(max_pages_1D))

        # 加载 ID 映射
        self.id_mapper = get_id_mapper()

        # 加载饰品列表
        self.items = self._load_items()

        # 统计
        self.start_time = time.time()
        self.stats = {
            "total": 0,
            "skipped": 0,
            "completed": 0,
            "failed": 0,
            "duration_seconds": 0.0,
        }

    # ------------------------------------------------------------------------
    # 加载饰品
    # ------------------------------------------------------------------------
    def _load_items(self) -> list:
        """加载所有饰品: (local_id, type_val, market_name)"""
        items = [
            (local_id, type_val, self.id_mapper.typeval_to_market.get(type_val))
            for local_id, type_val in self.id_mapper.local_to_typeval.items()
            if self.id_mapper.typeval_to_market.get(type_val)
        ]
        # 按 local_id 数值排序 (本地 ID 均为正整数, 字符串排序会因前缀 '1'<'2'<'91' 错位)
        items.sort(key=lambda x: int(x[0]))
        log(f"📊 总饰品数: {len(items)}")
        return items

    # ------------------------------------------------------------------------
    # 已抓检测
    # ------------------------------------------------------------------------
    def _is_already_crawled(self, local_id) -> bool:
        """检测 hourly 文件是否已抓 + 数据完整
        探员/部分饰品 SteamDT 没有 1D K线, 只要 hourly 存在就算抓过
        (避免重复抓 hourly 浪费 18 轮 API)

        完整性检查:
            - 文件存在
            - 文件大小 >= 100KB (避免空文件/几行脏数据被误判)
        """
        hourly_path = os.path.join(HOURLY_DATA_DIR, f"{local_id}.json")
        if not os.path.exists(hourly_path):
            return False
        try:
            return os.path.getsize(hourly_path) >= 100 * 1024
        except OSError:
            return False

    # ------------------------------------------------------------------------
    # 单条饰品抓取流程
    # ------------------------------------------------------------------------
    async def fetch_one(self, local_id, type_val, market_name) -> tuple:
        """抓取单条饰品 hourly + daily K线

        Returns: (success: bool, reason: str, hourly_count: int, daily_count: int)
        """
        try:
            encoded_name = quote(market_name)
            url = f"https://steamdt.com/cs2/{encoded_name}"

            log(f"      📄 访问页面...")
            try:
                response = await self._page.goto(
                    url, wait_until="domcontentloaded", timeout=60000
                )
                if response is not None and response.status >= 500:
                    return False, f"http_{response.status}", 0, 0
            except Exception as e:
                err = str(e).lower()
                if "timeout" in err:
                    return False, "timeout", 0, 0
                return False, f"goto_error:{type(e).__name__}", 0, 0

            await self._page.wait_for_timeout(2000)

            # 关闭公告
            await self.close_announcement()

            # 切到 K线 tab (不强依赖, 失败也继续)
            try:
                if not await self.switch_to_kline_chart():
                    log("      ⚠️  K线 tab 切换失败 (继续尝试捕获 API)")
            except Exception as e:
                log(f"      ⚠️  switch_to_kline_chart 异常 (继续): {e}")

            # 滚动让 chart 挂载
            try:
                await self._page.evaluate("window.scrollBy(0, 400)")
                await self._page.wait_for_timeout(1500)
            except Exception:
                pass

            # 抓 1H + 1D headers
            captured_1h = None
            captured_1d = None
            try:
                captured_1h = await self.capture_api_headers("1H")
            except Exception as e:
                log(f"      ⚠️  [1H] capture_api_headers 异常: {e}")
            if self._daily_limit_hit:
                return False, "daily_limit_hit", 0, 0
            try:
                captured_1d = await self.capture_api_headers("1D")
            except Exception as e:
                log(f"      ⚠️  [1D] capture_api_headers 异常: {e}")

            # 抓 1H
            hourly: list = []
            if captured_1h:
                try:
                    hourly = await self.fetch_kline_page(
                        captured_1h, "1H",
                        max_pages=self.max_pages_1H,
                        api_delay=self.api_delay,
                    )
                except Exception as e:
                    log(f"      ⚠️  [1H] fetch_kline_page 异常: {e}")
            else:
                log("      ❌ 1H headers 缺失, 跳过 1H 周期")

            # 限流时仍写盘 1H 已抓数据, 避免浪费 (改进: 不再丢弃)
            if self._daily_limit_hit:
                if hourly:
                    try:
                        norm = normalize_records(hourly)
                        save_kline_data(
                            local_id, norm, [],
                            HOURLY_DATA_DIR, DAILY_DATA_DIR,
                        )
                        log(f"      💾 1H 已抓 {len(norm)} 条落盘 (限流前抢救)")
                    except Exception as e:
                        log(f"      ⚠️  1H 落盘失败: {e}")
                return False, "daily_limit_hit", len(hourly), 0

            # 抓 1D
            daily: list = []
            if captured_1d:
                try:
                    daily = await self.fetch_kline_page(
                        captured_1d, "1D",
                        max_pages=self.max_pages_1D,
                        api_delay=self.api_delay,
                    )
                except Exception as e:
                    log(f"      ⚠️  [1D] fetch_kline_page 异常: {e}")
            else:
                log("      ❌ 1D headers 缺失, 跳过 1D 周期")

            if not hourly and not daily:
                return False, "no_api_data", 0, 0

            # 标准化
            try:
                hourly = normalize_records(hourly)
            except Exception as e:
                log(f"      ⚠️  [1H] 标准化失败: {e}")
                hourly = []
            try:
                daily = normalize_records(daily)
            except Exception as e:
                log(f"      ⚠️  [1D] 标准化失败: {e}")
                daily = []

            # 落盘
            save_kline_data(
                local_id, hourly, daily,
                HOURLY_DATA_DIR, DAILY_DATA_DIR,
            )
            return True, "", len(hourly), len(daily)

        except Exception as e:
            return False, f"exception:{type(e).__name__}", 0, 0

    # ------------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------------
    async def run(self) -> None:
        log("=" * 80)
        log("[HISTORY] 📊 History 全量抓取启动 (auto_kline_history.py)")
        log("=" * 80)
        log_plan_progress("[HISTORY]")
        log(f"HEADLESS={self.headless}  api_delay={self.api_delay}s  "
            f"max_pages_1H={self.max_pages_1H}  max_pages_1D={self.max_pages_1D}")

        # 1. 过滤 --start-from (数值比较, 避免 '1' > '91' 字符串错位)
        target_items = list(self.items)
        if self.start_from is not None:
            start_int = int(self.start_from)
            start_idx = 0
            for idx, (lid, _, _) in enumerate(target_items):
                if int(lid) >= start_int:
                    start_idx = idx
                    break
            else:
                start_idx = len(target_items)
            skipped_before = start_idx
            target_items = target_items[start_idx:]
            self.stats["skipped"] = skipped_before
            log(f"🔄 --start-from={self.start_from} (跳过 {skipped_before} 条, "
                f"剩余 {len(target_items)} 条)")

        # 2. 限制 --limit
        if self.limit is not None:
            target_items = target_items[: self.limit]
            log(f"⚙️  --limit 截断: 本轮最多 {self.limit} 条")

        # 3. 启动浏览器
        await self._ensure_browser()

        processed = 0
        try:
            for local_id, type_val, market_name in target_items:
                # 1 天限流: 跳出
                if self._daily_limit_hit:
                    log("⏸️  今日 1 天限流已触发, 停止")
                    break

                # 已抓: 跳过
                if self._is_already_crawled(local_id):
                    log(f"      ⏭️  {local_id} 已抓, skip")
                    self.stats["skipped"] += 1
                    continue

                log(
                    f"[{processed + 1}/{len(target_items)}] 🎯 {local_id} - "
                    f"{market_name} (typeVal={type_val})"
                )
                success, reason, h_n, d_n = await self.fetch_one(
                    local_id, type_val, market_name,
                )
                processed += 1

                if success:
                    self.stats["completed"] += 1
                    append_progress(PROGRESS_FILE, local_id, "completed")
                    log(f"      ✅ hourly={h_n} daily={d_n}")
                else:
                    self.stats["failed"] += 1
                    append_progress(
                        PROGRESS_FILE, local_id, "failed",
                        reason=reason, market_name=market_name,
                    )
                    log(f"      ❌ {reason}")

                # 每条间轻 sleep, 避免触发限流
                if processed < len(target_items):
                    await asyncio.sleep(0.5)

        except KeyboardInterrupt:
            log("\n⏹️  用户中断 (KeyboardInterrupt)")
        except Exception as e:
            import traceback
            log(f"\n❌ 顶层异常: {e}")
            log(traceback.format_exc())
        finally:
            # 收尾统计
            elapsed = time.time() - self.start_time
            self.stats["duration_seconds"] = round(elapsed, 2)
            self.stats["total"] = len(self.items)

            log("=" * 80)
            log("[HISTORY] 🎉 History 抓取完成 / 终止")
            log("=" * 80)
            log(f"[HISTORY] 📊 总饰品:    {self.stats['total']}")
            log(f"[HISTORY] ✅ 已完成:    {self.stats['completed']}")
            log(f"[HISTORY] ❌ 失败:      {self.stats['failed']}")
            log(f"[HISTORY] ⏭️  跳过:      {self.stats['skipped']}")
            log(f"[HISTORY] ⏱️  耗时:      {self.stats['duration_seconds']:.1f}s")
            log_plan_progress("[HISTORY]")
            log(f"[HISTORY] 📁 progress: {PROGRESS_FILE}")

            await self.close()


# ============================================================================
# §6. main
# ============================================================================
async def main():
    parser = argparse.ArgumentParser(
        description="K线历史数据全量抓取 (双脚本架构: history + incremental)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python kline/auto_kline_history.py\n"
            "  python kline/auto_kline_history.py --start-from 1 --limit 10\n"
            "  python kline/auto_kline_history.py --api-delay 0.5 --max-pages-1H 20\n"
            "  python kline/auto_kline_history.py --no-headless\n"
            "\n"
            "调用模式: 1H 18 轮 + 1D 6 轮 = 24 calls/item\n"
            "1 天上限: 约 47 items (按 ~1100 calls / day 估算)\n"
            "跳过逻辑: hourly + daily 文件都存在则跳过"
        ),
    )
    parser.add_argument(
        "--start-from", type=str, default=None,
        help="从指定 local_id 开始 (跳过更小的 ID)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="限制本轮处理 item 数 (调试用)",
    )
    parser.add_argument(
        "--api-delay", type=float, default=0.3,
        help="API 翻页间隔秒数 (默认 0.3)",
    )
    parser.add_argument(
        "--max-pages-1H", type=int, default=18,
        help="1H 最大翻页轮数 (默认 18)",
    )
    parser.add_argument(
        "--max-pages-1D", type=int, default=6,
        help="1D 最大翻页轮数 (默认 6)",
    )
    parser.add_argument(
        "--no-headless", action="store_true",
        help="关闭 headless (调试用, 显示浏览器)",
    )
    args = parser.parse_args()

    crawler = HistoryCrawler(
        start_from=args.start_from,
        limit=args.limit,
        api_delay=args.api_delay,
        max_pages_1H=args.max_pages_1H,
        max_pages_1D=args.max_pages_1D,
        headless=not args.no_headless,
    )
    await crawler.run()


if __name__ == "__main__":
    asyncio.run(main())
