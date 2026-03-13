#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
# 模块：基础设施 - 配置管理
# 文件：AI_config.py  [AI创建]
# 用途：统一管理项目中三种数据目录路径和映射文件路径。
#       提供 get_data_dir(kline_type) 函数，其他脚本通过此函数获取数据目录。
#       kline_type 可选: hourly(data_hourly/) / daily(data_daily/) / legacy(data_new/)
# 被依赖：AI_collect_dual_kline, AI_collect_latest, AI_clean_data,
#         AI_id_mapper, analyze_sector, plot_sector_indices
# =============================================================================
"""
项目配置模块 - 统一管理数据目录和路径
"""

import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent

# 数据目录配置
DATA_DIRS = {
    "hourly": BASE_DIR / "data_hourly",   # 小时K线（新）
    "daily": BASE_DIR / "data_daily",     # 日K线（新）
    "legacy": BASE_DIR / "data_new",      # 旧数据（兼容）
}

# 默认使用的数据类型
DEFAULT_KLINE_TYPE = "hourly"  # 可选: "hourly", "daily", "legacy"

# 映射文件路径
MAPPING_FILES = {
    "all_items_cache": BASE_DIR / "getdata" / "all_items_cache.json",
    "itemid_txt": BASE_DIR / "getdata" / "itemid.txt",
    "itemid_market_map": BASE_DIR / "getdata" / "itemid_market_map.json",
}

# 确保数据目录存在
for data_dir in DATA_DIRS.values():
    data_dir.mkdir(parents=True, exist_ok=True)


def get_data_dir(kline_type: str = None) -> Path:
    """
    获取数据目录路径
    
    Args:
        kline_type: K线类型 ("hourly", "daily", "legacy")
                   如果为None，使用默认配置
    
    Returns:
        数据目录的Path对象
    """
    if kline_type is None:
        kline_type = DEFAULT_KLINE_TYPE
    
    if kline_type not in DATA_DIRS:
        raise ValueError(f"无效的K线类型: {kline_type}，可选: {list(DATA_DIRS.keys())}")
    
    return DATA_DIRS[kline_type]


def get_mapping_file(name: str) -> Path:
    """
    获取映射文件路径
    
    Args:
        name: 映射文件名称 ("all_items_cache", "itemid_txt", "itemid_market_map")
    
    Returns:
        映射文件的Path对象
    """
    if name not in MAPPING_FILES:
        raise ValueError(f"无效的映射文件名: {name}，可选: {list(MAPPING_FILES.keys())}")
    
    return MAPPING_FILES[name]


# 兼容旧代码的常量
DATA_DIR = str(DATA_DIRS["legacy"])  # 默认使用旧数据目录
ALL_ITEMS_CACHE_FILE = str(MAPPING_FILES["all_items_cache"])
ITEM_IDS_FILE = str(MAPPING_FILES["itemid_txt"])
ITEM_ID_MARKET_MAP_FILE = str(MAPPING_FILES["itemid_market_map"])
