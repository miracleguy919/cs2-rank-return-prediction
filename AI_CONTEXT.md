# AI Context Document

> For AI to quickly restore project context and understand completed work and current state.

---

## Project Overview

CS2 skin price prediction project. Scrapes K-line data from steamdt for machine learning prediction.

- **Total skins**: 237 (from `getdata/itemid.txt`, 282 lines including blank lines and comments)
- **Data source**: steamdt.com, using Playwright to intercept browser requests
- **Goal**: Collect both hourly and daily K-lines, train two separate models

---

## File Structure

```
cs2-rank-return-prediction-main/
├── AI_CONTEXT.md               # This document
├── AI_collect_dual_kline.py    # Manual historical data collection (recommended)
├── AI_collect_latest.py        # Daily automatic data update
├── AI_clean_data.py            # Data cleaning and normalization
├── AI_config.py                # Config module (data directory management)
├── AI_id_mapper.py             # ID mapping module (typeVal <-> local ID)
├── AI_data_validator.py        # Data validation module
├── analyze_single_asset.py     # Single asset technical analysis
├── analyze_sector.py           # Sector-level analysis
├── rank_ic_analysis.py         # Factor IC analysis
├── plot_sector_indices.py      # Sector index plotting
├── check_item_timestamp_continuity.py  # Data continuity check
├── select_factors.py           # Factor selection
├── features.md                 # Factor documentation
├── requirements.txt            # Python dependencies
├── README.md                   # Project readme
├── .gitignore                  # Ignores __pycache__, old modules, data dirs, progress files
├── .gitattributes              # Git LFS config (model and image files in TBD/)
├── collection_progress.json        # Progress file for old (deprecated) collector
├── collection_full_history_progress.json  # Progress for AI_collect_dual_kline.py
├── collection_latest_progress.json        # Progress for AI_collect_latest.py
├── getdata/
│   ├── itemid.txt              # Skin ID list (local ID:Chinese name)
│   ├── itemid_market_map.json  # local ID -> marketHashName mapping
│   └── all_items_cache.json    # All skin metadata cache (~6000 entries, moved from root)
├── data_daily/                 # Daily K-line data (~95 skins)
├── data_hourly/                # Hourly K-line data (in progress)
├── data_new/                   # Old hourly K-line data (~14 skins, deprecated)
├── TBD/                        # ML pipeline (in progress)
│   ├── preprocess_xgb.py
│   ├── train_xgb.py
│   ├── backtest_xgb.py
│   ├── infer_xgb.py
│   ├── infer_xgb_live.py
│   ├── explain_xgb.py
│   ├── features.md
│   ├── xgb_grid_sample.json
│   ├── xgb_rank_model.json     # [LFS] trained model
│   ├── xgb_rank_metrics.json   # [LFS] model metrics
│   └── backtest_results6.png   # [LFS] backtest chart
└── old_collectors/             # Deprecated, reference only
    ├── get_hourly_kline.py
    ├── backfill_hourly_kline.py
    └── AI_batch_download_safe.py
```

---

## Core Module Descriptions

### AI_config.py
- Manages three data directories: `hourly` (data_hourly/), `daily` (data_daily/), `legacy` (data_new/)
- Provides `get_data_dir(kline_type)` function
- `all_items_cache.json` path: `BASE_DIR / "getdata" / "all_items_cache.json"`

### AI_id_mapper.py
- Bidirectional mapping: website `typeVal` (C5 platform itemId) <-> local ID
- Loads from `getdata/all_items_cache.json` and `getdata/itemid_market_map.json`
- Known duplicate: USP-S | Neo-Noir (Minimal Wear) had IDs 6570 and 8204, deleted 6570 kept 8204

### AI_data_validator.py
- Validates data integrity (fields, prices, volumes)
- Checks time continuity and price anomalies

---

## Data Collection Methods

### Method 1: Manual historical data collection (recommended for first run)

```bash
python AI_collect_dual_kline.py
```

**Operation**:
1. Script opens browser, navigates to steamdt.com
2. User manually clicks skins to view K-line charts
3. Script auto-intercepts and saves type=1 (hourly) and type=2 (daily) K-lines
4. Manually scroll K-line chart to load more history, script accumulates automatically
5. Switch to next skin, script auto-detects and resets cache (detects typeVal change in URL)

**Data saved to**:
- Hourly K-line -> `data_hourly/{local_ID}.json`
- Daily K-line -> `data_daily/{local_ID}.json`

### Method 2: Daily automatic update

```bash
python AI_collect_latest.py
```

**Features**:
- Fully automatic, iterates all skins in `itemid.txt` order
- Directly visits `https://steamdt.com/cs2/{marketHashName}` URLs
- No scrolling, only gets current page data (latest ~720 hourly K-lines)
- 4 second delay per skin, extra 30 seconds every 10 skins
- Resume support: progress saved to `collection_latest_progress.json`
- Estimated time: 237 x 4s ~= ~20 minutes (excluding batch delays)

### Method 3: Data cleaning

```bash
# Check only (no modification)
python AI_clean_data.py --dir data_hourly --dry-run

# Clean all skins
python AI_clean_data.py --dir data_hourly

# Clean daily K-lines
python AI_clean_data.py --dir data_daily
```

---

## Important Technical Details

### API Data Format

Data format intercepted via Playwright (raw):
```python
# URL params: type=1 (hourly) or type=2 (daily)
# Raw record format:
['1769608800', 2850.0, 2848.98, 2850.0, 2848.98, 1, 3225.0]
# [timestamp(seconds), open, close, high, low, volume, turnover]
```

Saved format after conversion (timestamp to milliseconds):
```json
{"t": 1769608800000, "o": 2850.0, "c": 2848.98, "h": 2850.0, "l": 2848.98, "v": 1.0, "turnover": 3225.0}
```

### Direct API requests (deprecated)

Old method used `requests` to call `https://api.steamdt.com/user/steam/category/v1/kline`, but triggers error code 108 (browser environment check). Now uses Playwright interception exclusively.

### Data growth issue (resolved)

**Problem**: Total record count grows by 1 each time a page of historical data is loaded.

**Cause**: API always returns one "forming" K-line (non-round timestamp) as the last record.

**Solution** (implemented in `AI_collect_dual_kline.py`):
1. Delete non-round-hour records from existing data
2. Filter non-standard timestamps from new data (only accept round hours)
3. Smart update based on price continuity (only update old data if new data is continuous)

### Data mixing issue (resolved)

**Problem**: Data from different skins mixed together.

**Cause**: Manual skin switching did not reset accumulation variables.

**Solution**: `AI_collect_dual_kline.py` auto-resets cache by detecting typeVal change in URL.

### Popup issue

First visit to steamdt.com shows announcement popup. `AI_collect_latest.py` attempts auto-close on first skin (multiple selectors + ESC key).

---

## Data Quality Standards

- Hourly K-line: timestamp must be round hour (minute=0, second=0)
- Daily K-line: timestamp must be 16:00 UTC each day
- Same time range skins should have identical record counts
- Missing data filled with linear interpolation (`AI_clean_data.py`)

**Cleaning result example** (7377, 7448, 7452, 7470):
- After cleaning hourly K-line: 10,475 records (fully aligned)
- After cleaning daily K-line: 438 records (fully aligned)

---

## Current State

- `data_daily/`: ~95 skins with daily K-line data
- `data_hourly/`: collection in progress (hourly K-lines)
- `data_new/`: ~14 skins, old format, deprecated
- Python environment: system PATH not configured (need to specify path manually or configure env vars)

---

## Training Plan

1. **Hourly K-line model** (short-term prediction, 1-7 days): data from `data_hourly/`
2. **Daily K-line model** (medium-long term prediction, 7-30 days): data from `data_daily/`
3. Two models cross-validate, can be weighted/fused

**Training pipeline** (requires 50+ skins with complete data):
```bash
python TBD/preprocess_xgb.py --data-dir data_hourly
python TBD/train_xgb.py
python TBD/backtest_xgb.py
```

---

## File Naming Convention

- **`AI_` prefix**: All files created or primarily modified by AI
  - `AI_collect_dual_kline.py`, `AI_collect_latest.py`, `AI_clean_data.py`
  - `AI_config.py`, `AI_id_mapper.py`, `AI_data_validator.py`
  - `AI_CONTEXT.md`
- **No prefix**: Original project files (unchanged)
  - `analyze_single_asset.py`, `analyze_sector.py`, `rank_ic_analysis.py`, etc.

---

## Kline Type Switching

All analysis scripts support `--kline-type` or `--data-dir` to switch data directory:

```bash
# Single skin technical analysis
python analyze_single_asset.py --kline-type hourly --item-id 48
python analyze_single_asset.py --kline-type daily --item-id 48

# Sector analysis
python analyze_sector.py --kline-type hourly
python analyze_sector.py --kline-type daily

# Sector index plotting
python plot_sector_indices.py --kline-type daily

# Timestamp continuity check
python check_item_timestamp_continuity.py --kline-type daily
python check_item_timestamp_continuity.py --kline-type hourly

# IC factor analysis (default: data_daily)
python rank_ic_analysis.py --data-dir data_daily
python rank_ic_analysis.py --data-dir data_hourly

# XGBoost preprocessing (default: data_daily)
python TBD/preprocess_xgb.py --data-dir data_daily
python TBD/preprocess_xgb.py --data-dir data_hourly
```

**All scripts default to `data_daily`** (daily K-lines).

---

## .gitignore Coverage

- `__pycache__/` and `*.pyc` - Python bytecode cache (auto-generated)
- `旧数据收集模块/` - deprecated collectors, reference only
- `collection_*.json` - runtime progress files (auto-generated)
- `data_hourly/`, `data_daily/`, `data_new/` - large data directories
- `getdata/all_items_cache.json` - large cache file

---

**Last updated**: 2026-03-12  
**AI model**: Claude Opus 4.6  
**Changes this session**:
- Added file header comments to all scripts (module, purpose, usage)
- Moved `all_items_cache.json` from root into `getdata/`, updated path in `AI_config.py`
- Created `.gitignore` (ignores `__pycache__/`, deprecated module folder, progress files, data dirs, cache)
- Rewrote `AI_CONTEXT.md` in English to avoid encoding corruption issues in PowerShell
- Created `手动获取饰品数据.bat` launcher with UTF-8 encoding support (`python -X utf8` flag)
- Added skin ID 92 (AK-47 | Hydroponic Minimal Wear, typeVal=26570) and ID 93 (AK-47 | Hydroponic Field-Tested, typeVal=24283) to `itemid_market_map.json`; deleted old data files for typeVal 26570
- Added skin ID 13032 (AK-47 | X-Ray Minimal Wear, typeVal=808834094329233408) to `itemid_market_map.json`; deleted old data files for typeVal 808834094329233408
- Added skin ID 16535 (M4A4 | Eye of Horus Minimal Wear, typeVal=1124890334019899392) to `itemid_market_map.json`; no existing data files found for this typeVal
- Added skin ID 92 (AK-47 | Hydroponic Minimal Wear, typeVal=26570) and ID 93 (AK-47 | Hydroponic Field-Tested, typeVal=24283) to `itemid_market_map.json`; deleted old data files for typeVal 26570
- Added skin ID 13032 (AK-47 | X-Ray Minimal Wear, typeVal=808834094329233408) to `itemid_market_map.json`; deleted old data files for typeVal 808834094329233408
- Added skins: ID 92 (AK-47 | Hydroponic Minimal Wear, typeVal=26570), ID 93 (AK-47 | Hydroponic Field-Tested, typeVal=24283)
- Deleted old data files: `data_hourly/26570.json`, `data_daily/26570.json` (ID 92 re-added with correct mapping)