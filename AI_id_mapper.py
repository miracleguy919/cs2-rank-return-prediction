#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
# Module: Infrastructure - ID Mapping
# File: AI_id_mapper.py  [AI Created]
# Purpose: Handles bidirectional mapping between steamdt website typeVal
#          (C5 platform itemId) and local IDs.
#          Loads mappings from all_items_cache.json and itemid_market_map.json.
#          Provides get_id_mapper() singleton to avoid repeated loading.
# Used by: AI_collect_dual_kline, AI_collect_latest
# =============================================================================

import json
from typing import Dict, Optional
from pathlib import Path
from AI_config import get_mapping_file


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
                for platform in item.get("platformList", []):
                    if platform.get("name") == "C5":
                        type_val = str(platform.get("itemId", ""))
                        if type_val:
                            self.typeval_to_market[type_val] = market_name
                        break
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
    global _mapper_instance
    if _mapper_instance is None:
        _mapper_instance = IDMapper()
    return _mapper_instance


def typeval_to_local_id(type_val: str) -> Optional[str]:
    return get_id_mapper().get_local_id(type_val)


def local_id_to_typeval(local_id: str) -> Optional[str]:
    return get_id_mapper().get_type_val(local_id)
