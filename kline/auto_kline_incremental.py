#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块：数据收集 - K线增量更新爬虫
文件：kline/auto_kline_incremental.py
用途：双脚本架构 (auto_kline_history.py / auto_kline_incremental.py) 的增量脚本
      抓取最新 1 页 1H/1D K线, 合并到现有 hourly/daily 文件,
      跳过当前未收盘周期 (避免写入不完整 K线), 复用 KlineCommon 浏览器 / 限流逻辑。

使用:
    python kline/auto_kline_incremental.py
    python kline/auto_kline_incremental.py --help
    python kline/auto_kline_incremental.py --limit 100
    python kline/auto_kline_incremental.py --include-empty    # 也抓无 hourly/daily 的 item
    python kline/auto_kline_incremental.py --no-headless      # 关闭 headless (调试)

对比:
    - auto_kline_history.py  : 全量抓取 + 跳过已抓 (首次跑 / 补漏)
    - auto_kline_incremental.py (本脚本): 抓最新 1 页 + merge 现有数据 (任务计划 00:01 日常跑)
"""

import sys
from pathlib import Path

# 项目根目录 (用于 sys.path), 只加根目录不加 kline/
# 避免 'import auto_kline_history' 与 'from kline.auto_kline_history import ...'
# 加载为两个独立模块导致 log() 双倍写入
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from urllib.parse import quote

from kline.auto_kline_history import (
    KlineCommon, merge_with_skip, append_progress, log,
    atomic_write_json, normalize_records, get_id_mapper,
    HOURLY_DATA_DIR, DAILY_DATA_DIR, PROGRESS_FILE,
)


# ============================================================================
# 常量
# ============================================================================
ITEM_DELAY = 1.0         # 单条饰品间隔 (秒, 比 history 短, 增量任务更轻量)
GOTO_TIMEOUT_MS = 60000  # page.goto 超时


# ============================================================================
# IncrementalCrawler 主类
# ============================================================================
class IncrementalCrawler(KlineCommon):
    """增量 K线爬虫: 抓最新 1 页, merge 到现有数据, 跳过当前未收盘周期"""

    def __init__(self, start_from: str = None, limit: int = None,
                 api_delay: float = 0.3, include_empty: bool = True,
                 headless: bool = True):
        super().__init__(headless=headless)

        # 复用既有 ID 映射单例
        self.id_mapper = get_id_mapper()

        # CLI 参数
        self.start_from = start_from
        self.limit = limit
        self.api_delay = max(0.0, float(api_delay))
        self.include_empty = bool(include_empty)
        self.item_delay = ITEM_DELAY

        # 加载饰品列表
        self.items = self._load_items()

        # 统计
        self.start_time = time.time()
        self.stats = {
            "total": 0,
            "completed": 0,
            "skipped": 0,
            "failed": 0,
            "duration_seconds": 0.0,
        }

    # ------------------------------------------------------------------------
    # 加载饰品 (复用 auto_kline_crawler.py 模式)
    # ------------------------------------------------------------------------
    def _load_items(self) -> list:
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
    # 切片: --start-from / --limit
    # ------------------------------------------------------------------------
    def _slice_items(self) -> list:
        sliced = list(self.items)
        if self.start_from is not None:
            start_int = int(self.start_from)
            sliced = [
                (l, t, m) for l, t, m in sliced
                if int(l) >= start_int
            ]
        if self.limit is not None and self.limit > 0:
            sliced = sliced[: self.limit]
        return sliced

    # ------------------------------------------------------------------------
    # 导航到饰品页面 + 切到 K线 chart
    # ------------------------------------------------------------------------
    async def _navigate_to_item(self, market_name: str):
        """导航到饰品页 + 等 chart 渲染
        Returns: (success: bool, reason: str) - reason 仅失败时有值
        """
        if self._page is None:
            return False, "no_page"
        try:
            encoded_name = quote(market_name)
            url = f"https://steamdt.com/cs2/{encoded_name}"
            try:
                response = await self._page.goto(
                    url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS,
                )
                if response is not None and response.status >= 500:
                    log(f"      ⚠️  HTTP {response.status}, 跳过")
                    return False, f"http_{response.status}"
            except Exception as e:
                err = str(e)
                if "timeout" in err.lower():
                    log(f"      ⚠️  goto timeout: {market_name}")
                    return False, "timeout"
                err_short = err.split("\n")[0][:80]  # 截短 + 去掉 call log
                log(f"      ⚠️  goto 异常: {err_short}")
                return False, f"goto_error:{type(e).__name__}"

            await self._page.wait_for_timeout(2000)

            # 关闭公告弹窗
            try:
                await self.close_announcement()
            except Exception:
                pass

            # 滚动一下触发懒加载
            try:
                await self._page.evaluate("window.scrollBy(0, 400)")
                await self._page.wait_for_timeout(1500)
            except Exception:
                pass

            # 切到 K线 chart tab (不强依赖成功, capture_api_headers 会再点周期按钮)
            try:
                await self.switch_to_kline_chart()
            except Exception as e:
                log(f"      ⚠️  switch_to_kline_chart 异常 (继续): {e}")

            return True, ""
        except Exception as e:
            log(f"      ⚠️  导航失败: {e}")
            return False, f"nav_error:{type(e).__name__}"

    # ------------------------------------------------------------------------
    # 处理单条饰品
    # ------------------------------------------------------------------------
    async def _process_item(self, local_id, type_val: str, market_name: str) -> str:
        """
        Returns:
            "completed" / "skipped" / "failed"
        """
        hourly_path = os.path.join(HOURLY_DATA_DIR, f"{local_id}.json")
        daily_path = os.path.join(DAILY_DATA_DIR, f"{local_id}.json")
        has_hourly = os.path.exists(hourly_path)
        has_daily = os.path.exists(daily_path)

        # 跳过无 hourly 的 item (留给 history 脚本首次抓)
        # 探员等 SteamDT 无 1D 的饰品: hourly 存在但 daily 不存在, 仍需增量更新
        if not has_hourly:
            if not self.include_empty:
                log(f"      ⏭️  {local_id} 无 hourly, 跳过 (留 history)")
                return "skipped"

        # 1 天限流提前检测
        if self._daily_limit_hit:
            return "skipped"

        # 导航到饰品页
        nav_ok, nav_reason = await self._navigate_to_item(market_name)
        if not nav_ok:
            # incremental 失败不写 failed 记录 (避免与 completed 冲突,
            # hourly 文件已存在, 数据没丢, 下次会重试)
            log(f"      ⏭️  导航失败不记录 (下次重试): {nav_reason}")
            return "failed"

        # 1H: 抓最新 1 页
        captured_1h = None
        new_1h: list = []
        try:
            captured_1h = await self.capture_api_headers("1H")
        except Exception as e:
            log(f"      ⚠️  [1H] capture 异常: {e}")
        if captured_1h:
            try:
                raw_1h = await self.fetch_kline_page(
                    captured_1h, "1H",
                    max_pages=1, api_delay=self.api_delay,
                )
                new_1h = normalize_records(raw_1h)
            except Exception as e:
                log(f"      ⚠️  [1H] fetch 异常: {e}")

        # 1H 后再次检测 1 天限流
        if self._daily_limit_hit:
            log("      ⏸️  1H 抓取触发 1 天限流, 中断")
            return "skipped"

        # 1D: 抓最新 1 页
        captured_1d = None
        new_1d: list = []
        try:
            captured_1d = await self.capture_api_headers("1D")
        except Exception as e:
            log(f"      ⚠️  [1D] capture 异常: {e}")
        if captured_1d:
            try:
                raw_1d = await self.fetch_kline_page(
                    captured_1d, "1D",
                    max_pages=1, api_delay=self.api_delay,
                )
                new_1d = normalize_records(raw_1d)
            except Exception as e:
                log(f"      ⚠️  [1D] fetch 异常: {e}")

        # 抓取后检查: 1H 和 1D 都无数据 (SteamDT 临时失败 / 页面未加载)
        # 则返回 failed 但不写盘, 下次重试
        if not new_1h and not new_1d:
            log(f"      ⚠️  1H/1D 都没抓到数据, 跳过写盘 (下次重试)")
            return "failed"

        # 读取现有数据
        existing_1h: list = []
        if has_hourly:
            try:
                with open(hourly_path, "r", encoding="utf-8") as f:
                    existing_1h = json.load(f)
            except Exception:
                existing_1h = []
        existing_1d: list = []
        if has_daily:
            try:
                with open(daily_path, "r", encoding="utf-8") as f:
                    existing_1d = json.load(f)
            except Exception:
                existing_1d = []

        # merge: 跳过当前未收盘周期 + t 去重覆盖
        merged_1h, stats_1h = merge_with_skip(new_1h, existing_1h, "1H")
        merged_1d, stats_1d = merge_with_skip(new_1d, existing_1d, "1D")

        # 写回 (atomic_write_json 防崩溃损坏)
        atomic_write_json(hourly_path, merged_1h)
        atomic_write_json(daily_path, merged_1d)

        log(
            f"      ✅ {local_id} hourly={len(merged_1h)} "
            f"(+{stats_1h['added']} u{stats_1h['updated']}) "
            f"daily={len(merged_1d)} (+{stats_1d['added']} u{stats_1d['updated']}) "
            f"skipped_h={stats_1h['skipped_current']} "
            f"skipped_d={stats_1d['skipped_current']}"
        )

        # 更新进度
        append_progress(PROGRESS_FILE, local_id, "completed")
        return "completed"

    # ------------------------------------------------------------------------
    # 收尾统计
    # ------------------------------------------------------------------------
    def _print_summary(self) -> None:
        self.stats["duration_seconds"] = round(time.time() - self.start_time, 2)
        log("=" * 80)
        log("🔄 增量更新完成 / 终止")
        log("=" * 80)
        log(f"📊 总饰品:    {self.stats['total']}")
        log(f"✅ 完成:      {self.stats['completed']}")
        log(f"⏭️  跳过:      {self.stats['skipped']}")
        log(f"❌ 失败:      {self.stats['failed']}")
        log(f"⏱️  耗时:      {self.stats['duration_seconds']:.1f}s")
        log(f"📁 progress: {PROGRESS_FILE}")
        log(f"📁 log:      data/kline_log.txt")

    # ------------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------------
    async def run(self) -> None:
        log("=" * 80)
        log("🔄 增量更新 K线数据 (跳过当前未收盘周期)")
        log("=" * 80)
        log(f"HEADLESS={self.headless}  API_DELAY={self.api_delay}s  "
            f"ITEM_DELAY={self.item_delay}s")
        log(f"--include-empty: {self.include_empty}  "
            f"--start-from: {self.start_from}  --limit: {self.limit}")

        target_items = self._slice_items()
        self.stats["total"] = len(target_items)
        log(f"📊 本轮目标: {len(target_items)} 个饰品")

        if not target_items:
            log("ℹ️  无目标饰品, 退出")
            self._print_summary()
            return

        await self._ensure_browser()

        try:
            for idx, (local_id, type_val, market_name) in enumerate(target_items, 1):
                if self._daily_limit_hit:
                    log("⏸️  今日 1 天限流已触发, 停止")
                    break

                log(
                    f"\n[{idx}/{len(target_items)}] 🎯 {local_id} - {market_name} "
                    f"(typeVal={type_val})"
                )

                try:
                    status = await self._process_item(
                        local_id, type_val, market_name,
                    )
                except Exception as e:
                    log(f"      ❌ 顶层异常: {type(e).__name__}: {e}")
                    status = "failed"

                if status == "completed":
                    self.stats["completed"] += 1
                elif status == "skipped":
                    self.stats["skipped"] += 1
                else:
                    self.stats["failed"] += 1

                # 单条间隔 (防限流; 增量任务走轻量节奏)
                if idx < len(target_items):
                    await asyncio.sleep(self.item_delay)
        finally:
            self._print_summary()
            await self.close()


# ============================================================================
# main
# ============================================================================
async def main():
    parser = argparse.ArgumentParser(
        description="增量更新 K线数据 (跳过当前未收盘周期, 任务计划 00:01 日常跑)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python kline/auto_kline_incremental.py          # 增量更新所有 items\n"
            "  python kline/auto_kline_incremental.py --limit 100  # 限制 100 个\n"
            "  python kline/auto_kline_incremental.py --include-empty  # 也抓无数据 items"
        )
    )
    parser.add_argument("--start-from", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--api-delay", type=float, default=0.3)
    parser.add_argument("--no-include-empty", action="store_true",
                        help="默认抓无 hourly 的饰品 (orphan data 兜底), 加此参数跳过它们")
    parser.add_argument("--no-headless", action="store_true")
    args = parser.parse_args()

    crawler = IncrementalCrawler(
        start_from=args.start_from,
        limit=args.limit,
        api_delay=args.api_delay,
        include_empty=not args.no_include_empty,
        headless=not args.no_headless,
    )
    await crawler.run()


if __name__ == "__main__":
    asyncio.run(main())
