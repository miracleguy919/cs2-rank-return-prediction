# CS2 饰品价格走势预测项目

> 🎯 **项目目标**：预测 CS2 饰品（手套 / 刀具 / 武器 / 探员）的价格走势，输出**排名 + 收益率**信号
> 📚 **完整知识库**：[AGENTS.md](AGENTS.md)（1600+ 行 CS 饰品宇宙 + 工具工作流）
> 📝 **变更历史**：[CHANGELOG.md](CHANGELOG.md)

---

## 📊 项目概览

| 项 | 值 |
|---|---|
| **项目名** | cs2-rank-return-prediction |
| **核心数据源** | steamdt.com (C5 平台 K线) + bymykel/CSGO-API 元数据 |
| **跟踪物品数** | 2,737+ 条（含手套/刀/武器/探员 4 大类）|
| **数据粒度** | 小时 K线（`data/hourly/`）+ 日 K线（`data/daily/`）|
| **本地缓存** | 20,000+ 条 CS2 饰品 + 22 Dead Hand 4 代手套 + 17 武器 |

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

依赖：`numpy / pandas / xgboost / matplotlib / mplfinance / scipy / requests`

### 2. 数据收集

```bash
# 一键式每日更新（Windows）
1_每日更新数据.bat      # 抓取所有 itemid.txt 中的饰品 K线
2_清洗数据.bat          # 清洗 + 缺失值插值
3_验证数据.bat          # 连续性检查
check_item_timestamp_continuity.py   # 手动验证时间戳

# 历史回填（一次性）
1B_手动收集历史数据.bat
旧数据收集模块/backfill_hourly_kline.py
```

### 3. 因子工程

```bash
4_技术分析(可选).bat    # TA 指标
5_生成因子.bat          # 33 个基础量化因子（见 features.md）
```

### 4. 模型训练 + 预测

```bash
6_训练模型.bat          # XGBoost 训练
7_回测验证.bat          # 回测
8_每日预测.bat          # 每日实时预测

# 离线工具
TBD/preprocess_xgb.py   # 生成 TBD/factor_dataset.parquet
TBD/infer_xgb.py        # 历史数据对比推理
TBD/infer_xgb_live.py   # 实时推理（指定 date）
TBD/backtest_xgb.py     # 回测
TBD/explain_xgb.py      # 特征重要性
```

---

## 🗂️ 项目结构

```
cs2-rank-return-prediction-main/
├── AGENTS.md                       # 📚 CS 饰品知识库 + 工作流（1600+ 行）
├── CHANGELOG.md                    # 📝 变更历史
├── README.md                       # 本文件
├── requirements.txt                # 依赖
│
├── mappings/                       # 映射数据 (14 文件 = 10 核心 + 4 应用)
│   ├── itemid.txt                  # 监控列表（5 位 ID : 中文名）
│   ├── itemid_market_map.json      # ID → 英文 marketHashName
│   ├── all_items_cache.json        # 全量缓存（含 C5/Buff/SteamDT id）
│   ├── dead_hand_meta.json         # 4 代手套 22 花色专项
│   ├── weapons_meta.json           # 901 武器物品元数据
│   ├── agents_meta.json            # 63 探员元数据
│   ├── bymykel_zh/en_skins.json    # bymykel 2092 条 (中/英)
│   ├── bymykel_zh/en_agents.json   # bymykel 63 探员 (中/英)
│   ├── weapons_to_integrate.json   # 流程中间产物 (plan 输入)
│   ├── weapons_steamdt_ids.json    # 流程中间产物 (crawl→apply)
│   ├── agents_mapping_plan.json    # 流程中间产物 (plan 输入)
│   └── special_wear_skins.json     # 33 条特殊磨损清单
│
├── data/                           # K线数据（按 local_id 命名）
│   ├── hourly/                     # 小时 K线
│   └── daily/                      # 日 K线
│
├── kline/                          # ⭐ 数据获取层 (8 文件: K线爬虫 + bymykel + 补ID)
│   ├── auto_kline_history.py       # 历史数据 (全量, 跳过已抓)
│   ├── auto_kline_incremental.py   # 增量更新 (每日任务计划用)
│   ├── diagnose_kline.py           # 单饰品 K线 API 拦截诊断
│   ├── auto_kline_restart.ps1      # 任务计划包装脚本
│   ├── crawl_weapons_typeval.py    # Playwright 爬 SteamDT typeVal (补缺)
│   ├── crawl_weapons_c5_search.py  # C5 搜索 API 兜底 (补缺)
│   ├── fetch_bymykel_zh.py         # 拉 bymykel zh-CN 皮肤数据
│   └── fetch_bymykel_agents.py     # 拉 bymykel 探员数据
│
├── mappings/                       # 数据整理层: 核心映射数据 + ID 工具
│   ├── itemid.txt                  # 监控列表 (5 位 ID : 中文名)
│   ├── itemid_market_map.json      # ID → 英文 mhn 映射
│   ├── all_items_cache.json        # 全量缓存 (9000+ 物品)
│   ├── weapons_meta.json           # 武器元数据
│   ├── agents_meta.json            # 探员元数据
│   ├── dead_hand_meta.json         # 4 代手套元数据
│   ├── bymykel_{zh,en}_{skins,agents}.json  # bymykel 源数据
│   ├── *_plan.json / *_to_integrate.json    # 流程中间产物
│   └── _tools/                     # ID 映射工具 (9 文件, 详见下)
│       ├── plan_weapons_mapping.py     # 武器 plan
│       ├── finalize_weapons.py         # 武器 finalize (写三件套)
│       ├── plan_agents_mapping.py      # 探员 plan
│       ├── finalize_agents.py          # 探员 finalize
│       ├── plan_incremental_ids.py     # 增量 plan
│       ├── finalize_incremental.py     # 增量 finalize
│       ├── apply_weapons_typeval.py    # typeVal 写回 cache
│       ├── mark_no_kline_id.py         # 标记不可抓 kline_id
│       └── update_itemid_to_zh.py      # 重写 itemid.txt 中文格式
│
├── verify/                         # 数据整理层: 质量检查 + 诊断 (7 py + 1 备份目录)
│   ├── verify_weapons_integration.py  # 16 项武器质量检查
│   ├── verify_agents_integration.py   # 11 项探员质量检查
│   ├── verify_id_full_coverage.py  # ID 覆盖率全量验收
│   ├── verify_zh_itemid.py         # itemid.txt 中文翻译校验
│   ├── verify_zh_meta.py           # weapons_meta/cache 中文校验
│   ├── diagnose_item.py            # 单饰品 ID 诊断（应急）
│   ├── build_special_wear_list.py  # 生成 special_wear_skins.json
│   └── bak_v3_full_clean/          # v3 实施安全网 (5 备份)
│
├── TBD/                            # 数据分析层 (XGBoost 训练 + 回测 + 推理)
│   ├── preprocess_xgb.py
│   ├── train_xgb.py
│   ├── infer_xgb.py
│   ├── infer_xgb_live.py
│   ├── backtest_xgb.py
│   ├── explain_xgb.py
│   └── features.md
```

---

## 📚 数据源

| 级别 | 来源 | 用途 |
|------|------|------|
| ⭐ 生产 | [bymykel/CSGO-API](https://github.com/ByMykel/CSGO-API) | CS2 完整皮肤元数据 |
| ⭐ K线 | [steamdt.com](https://www.steamdt.com/cs2) | C5 平台 K线（需 access-token）|
| ⭐ 价格 | [steamanalyst.com](https://www.steamanalyst.com) | 参考价格 |
| ⭐ 概率 | [skin.club](https://skin.club) | 开箱概率 |

---

## 🔧 工作流

详见 [AGENTS.md §7.3](AGENTS.md) 三路径总览：

| 路径 | 触发 | 工具 |
|------|------|------|
| **首次录入** | 全新类别发布 | `plan_*_mapping.py` → `finalize_*.py` |
| **增量同步** | bymykel 拉新 | `plan_incremental_ids.py` → `finalize_incremental.py` |
| **应急诊断** | K线抓不到 | `diagnose_item.py` |

---

## 📝 维护建议

- **添加新饰品** → 更新 [AGENTS.md §2/§3/§4](AGENTS.md) + `mappings/itemid.txt`
- **数据准确性审查** → 跑 `verify/verify_id_full_coverage.py --no-save`
- **定期清理** → 删除 `mappings/*.bak*` 备份（每次大改后）

---

> 💡 **详细 CS 知识 + 工作流 + 工具清单**：[AGENTS.md](AGENTS.md)
> 📝 **变更记录**：[CHANGELOG.md](CHANGELOG.md)
