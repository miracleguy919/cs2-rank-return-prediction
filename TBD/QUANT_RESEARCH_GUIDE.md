# 量化研究指南与开源项目调研（v2 完整版）

> **用途**：本文件是 CS2 排名预测项目的**量化知识普及**与**开源项目调研**文档。
> - 📚 **第一部分**：量化基础知识普及（适合零基础）
> - 🛠️ **第二部分**：行业软件全景
> - 📋 **第三部分**：126 个开源项目详细整理（第一轮 56 + 第二轮 70）
> - 🏆 **第四部分**：Top 20 综合推荐
> - 🗺️ **第五部分**：**长线计划 P0-P5（重点）**
> - 📅 **版本**：v2 ｜ **创建日期**：2026-06-17 ｜ **更新日期**：2026-06-17
> - 🔗 **配套文档**：[AGENTS.md](../AGENTS.md)（饰品知识库）/ [README.md](../README.md)（项目总览）

---

## 目录

- [第一部分：量化基础知识普及](#第一部分量化基础知识普及)
- [第二部分：行业软件全景](#第二部分行业软件全景)
- [第三部分：126 个开源项目详细整理](#第三部分126-个开源项目详细整理)
- [第四部分：Top 20 综合推荐](#第四部分top-20-综合推荐)
- [第五部分：长线计划 P0-P5](#第五部分长线计划-p0-p5)

---

# 第一部分：量化基础知识普及

## 1.1 什么是量化交易

**量化交易（Quantitative Trading）** 是用数学模型、统计方法和计算机程序替代人工主观判断来做交易决策的方法。

**核心思想**：把"什么时候买、买什么、买多少、什么时候卖"这些问题，全部转化为可量化、可回测、可复现的规则。

**本项目属于**：量化研究阶段，目标是**预测 CS2 饰品价格排名**，输出"买哪些饰品能获得最高收益"的信号。

## 1.2 核心概念速查

### 因子（Factor / Alpha）
**因子** = 能预测未来收益的变量。
- **动量因子**：过去 20 天涨得多的，未来可能继续涨
- **反转因子**：过去 5 天跌得多的，未来可能反弹
- 本项目 `features.md` 里的 200 个因子就是这类变量

**Alpha 的含义**：超额收益。如果一个因子能稳定产生超越基准的收益，就叫"有 Alpha"。

### IC（Information Coefficient 信息系数）
**IC** = 因子值与未来收益的相关系数，衡量因子的预测能力。

```
IC = corr(因子值_t, 未来收益_t+1)
IC > 0：因子有正向预测能力
|IC| > 0.03：有弱预测力
|IC| > 0.05：有中等预测力
|IC| > 0.1：有强预测力（罕见）
```

**Rank IC**（秩 IC）= 用排名替代原始值算相关（Spearman 相关），比普通 IC 更稳健。

**ICIR**（IC Information Ratio）= IC 均值 / IC 标准差，衡量 IC 的稳定性。ICIR > 0.5 算不错。

本项目 `rank_ic_analysis.py` 就是算这个的。当前模型 test spearman 0.059，属于弱预测力。

### 横截面（Cross-Sectional）vs 时序（Time-Series）

**横截面分析**：同一时间点，比较不同物品的因子值与收益
- 例：2025-11-19 这天，2244 个饰品里，动量因子排名前 10 的，未来 8 天收益是否更高？
- **本项目属于横截面排名预测**

**时序分析**：同一物品，比较不同时间点的因子值与收益
- 例：饰品 #1 在过去 30 天的动量因子，能否预测它明天的收益？

### 排序学习（Learning to Rank, LTR）
**排序学习** = 让模型学习"如何给物品排序"，而不是"预测具体数值"。

本项目用 XGBoost 的 `rank:ndcg` 目标函数，就是排序学习。

**三种 LTR 方法**：
1. **Pointwise**：每个样本独立打分（回归）
2. **Pairwise**：比较两两样本的相对顺序（如 LambdaRank）
3. **Listwise**：直接优化整个列表的排序指标（如 NDCG）← 本项目用这个

### 回测（Backtest）
**回测** = 用历史数据模拟交易，验证策略是否赚钱。

本项目 `backtest_xgb.py` 的配置：
```python
initial_capital = 1.0        # 初始资金 1.0（归一化）
commission_rate = 0.015      # 1.5% 手续费（偏低，实际 5-15%）
holding_days = 8             # 持有 8 天
top_n_main = 6               # 买排名前 6 的
```

### 组合优化（Portfolio Optimization）
**组合优化** = 给定一组候选资产，如何分配资金权重使风险调整后收益最大化。

- **等权**：每个资产分配相同权重（本项目当前用这个，最简单）
- **最小方差**：让组合波动最小
- **最大夏普**：让风险调整后收益最大
- **CVaR 优化**：最小化条件风险价值（适合厚尾分布，如 CS2 饰品）

### 行业中性化（Industry Neutralization）
**行业中性化** = 剔除因子中的"行业效应"，只保留"个股特异性"。

本项目对应：`neutralize_cross_section` / `neutralize_target_by_industry`，"行业"= 饰品大类（手套/刀/武器/探员）。

## 1.3 量化研究标准流程

```
┌─────────────────────────────────────────────────────────────┐
│  1. 数据准备                                                  │
│     ├─ 数据采集（K线、基本面、事件）                           │
│     ├─ 数据清洗（缺失值、异常值、对齐）                        │
│     └─ 数据存储（文件/数据库/Point-in-Time）                  │
├─────────────────────────────────────────────────────────────┤
│  2. 因子研究                                                  │
│     ├─ 因子构造（公式、技术指标、Alpha101）                    │
│     ├─ 因子检验（IC、Rank IC、ICIR、IC 衰减曲线）              │
│     ├─ 因子预处理（去极值、标准化、中性化）                    │
│     └─ 因子筛选（保留有效因子，剔除冗余）                      │
├─────────────────────────────────────────────────────────────┤
│  3. 模型训练                                                  │
│     ├─ 标签构造（未来 N 天收益率 / 排名）                      │
│     ├─ 数据切分（train/val/test，注意时序不能打乱）            │
│     ├─ 模型选择（XGBoost / LightGBM / LSTM / Transformer）    │
│     ├─ 超参调优（Grid Search / Bayesian / Optuna）            │
│     └─ 交叉验证（Walk-Forward 滚动验证）                      │
├─────────────────────────────────────────────────────────────┤
│  4. 回测验证                                                  │
│     ├─ 信号生成（模型预测 → 排名 → 买入信号）                  │
│     ├─ 组合构建（等权 / 优化权重）                             │
│     ├─ 成本建模（手续费、滑点、冲击成本）                      │
│     ├─ 绩效评估（Sharpe、Sortino、最大回撤、Calmar）           │
│     └─ 稳健性检验（不同时段、不同参数、蒙特卡洛）              │
├─────────────────────────────────────────────────────────────┤
│  5. 报告与部署                                                │
│     ├─ Tear Sheet（标准化绩效报告）                           │
│     ├─ 因子归因（哪些因子贡献了收益）                         │
│     ├─ 风险归因（收益来源分解）                               │
│     └─ 实盘部署（信号生成 → 下单执行）                        │
└─────────────────────────────────────────────────────────────┘
```

## 1.4 关键指标详解

### 收益类指标
| 指标 | 公式 | 含义 |
|------|------|------|
| 总收益 | (期末净值 - 期初净值) / 期初净值 | 总共赚了多少 |
| 年化收益 | (1 + 总收益)^(365/天数) - 1 | 折算到一年的收益率 |
| 超额收益 | 组合收益 - 基准收益 | 跑赢基准多少 |

### 风险类指标
| 指标 | 公式 | 含义 |
|------|------|------|
| 波动率 | std(日收益) × sqrt(252) | 收益的波动程度 |
| 最大回撤 | max((peak - trough) / peak) | 历史最大亏损幅度 |
| 下行波动率 | std(负收益部分) × sqrt(252) | 只算下跌的波动 |

### 风险调整后收益
| 指标 | 公式 | 含义 | 标准 |
|------|------|------|------|
| **Sharpe Ratio** | (年化收益 - 无风险利率) / 年化波动率 | 每承担 1 单位风险获得多少收益 | > 1 不错，> 2 优秀 |
| **Sortino Ratio** | (年化收益 - 无风险利率) / 下行波动率 | 只考虑下行风险的 Sharpe | > 2 不错 |
| **Calmar Ratio** | 年化收益 / 最大回撤 | 收益与最大亏损的比 | > 1 不错 |
| **Information Ratio** | 超额收益 / 跟踪误差 | 主动管理的效率 | > 0.5 不错 |

### 排序类指标（本项目核心）
| 指标 | 含义 |
|------|------|
| **IC** | 因子值与收益的 Pearson 相关 |
| **Rank IC** | 因子值与收益的 Spearman 相关（更稳健）|
| **ICIR** | IC 均值 / IC 标准差（稳定性）|
| **NDCG** | 归一化折损累计增益（评估排名质量，头部权重高）|

## 1.5 常见陷阱与防范

### 未来函数（Look-Ahead Bias）
**问题**：用了"未来才知道"的数据来训练模型。

**防范**：
- 严格时序对齐：因子用 t 时刻数据，收益用 t+1 到 t+N 的未来数据
- Point-in-Time 数据库：记录"每个时刻实际能看到的最新数据"

本项目 `preprocess_xgb.py` 的 `add_lag_matrix` 就是为了避免未来函数。

### 过拟合（Overfitting）
**问题**：模型在训练集表现好，在测试集表现差。

**表现**：train spearman 0.3，test spearman 0.05（本项目当前状态）。

**防范**：
- 简化模型（减少树深度、增加正则化）
- 增加数据（更多饰品、更长时间）
- Walk-Forward 交叉验证（而非单次切分）
- 特征筛选（剔除冗余因子）

### 幸存者偏差（Survivorship Bias）
**问题**：只研究"还活着"的资产，忽略了"已退市"的。

**CS2 对应**：只研究还在交易的饰品，忽略了 Valve 下架的（如某些违规皮肤）。

### 交易成本忽略
**问题**：回测赚钱，实盘亏钱——因为没算手续费。

**CS2 现实成本**：
- Steam 市场手续费：15%（卖方）
- 第三方平台（BUFF/C5）：2-12%
- 7 天持有期（Steam 限制）
- 滑点：流动性差的饰品，大额交易会冲击价格

本项目 `commission_rate=0.015`（1.5%）偏低，实际可能要 5-15%。

### 数据泄漏（Data Leakage）— 第二轮调研新发现
**问题**：train/val/test 切分时，时序数据重叠导致信息泄漏。

**防范**：**mlfinlab 的 Purged K-Fold** —— 在切分时"清除"训练集和测试集之间的重叠样本，并加" embargo"（禁运期）。

**本项目风险**：test spearman 0.059 可能是数据泄漏假象！必须用 Purged K-Fold 验证。

---

# 第二部分：行业软件全景

## 2.1 量化软件分类（5 层架构）

```
┌─────────────────────────────────────────────┐
│  报告层（Report）                            │
│  Tear Sheet / IC 分析 / 归因报告             │
│  代表：alphalens / pyfolio / Empyrial        │
├─────────────────────────────────────────────┤
│  回测层（Backtest）                          │
│  事件驱动 / 向量化 / Walk-Forward            │
│  代表：backtrader / vectorbt / zipline / bt  │
├─────────────────────────────────────────────┤
│  模型层（Model）                             │
│  XGBoost / LightGBM / LSTM / Transformer     │
│  代表：qlib Model Zoo / Stock-Prediction     │
├─────────────────────────────────────────────┤
│  因子层（Factor）                            │
│  Alpha101 / Alpha158 / 自动因子挖掘          │
│  代表：qlib Alpha158 / alphagen / GGanalysis │
├─────────────────────────────────────────────┤
│  数据层（Data）                              │
│  K线 / 基本面 / 事件 / Point-in-Time         │
│  代表：qlib Data / tushare / OpenBB          │
└─────────────────────────────────────────────┘
```

## 2.2 主流框架对比

| 框架 | Star | 定位 | 适合本项目 |
|------|------|------|-----------|
| **qlib** | 28k | 全栈平台，五层架构 | ⭐⭐⭐⭐⭐ 架构模板 |
| **OpenBB** | 68k | 数据基础设施平台 | ⭐⭐⭐⭐⭐ 数据层统一 |
| **nautilus_trader** | 21.6k | Rust+Python 生产级引擎 | ⭐⭐⭐⭐ 实盘部署 |
| **backtrader** | 21.5k | 事件驱动回测 | ⭐⭐ 策略简单用不上 |
| **Vibe-Trading** | 8.8k | LLM Agent AI 交易 | ⭐⭐⭐⭐⭐ AI 自适应交易 |
| **vectorbt** | 7.8k | 向量化超高速回测 | ⭐⭐⭐⭐ 参数优化 |
| **darts** | 7.5k | 80+ 时序模型统一 API | ⭐⭐⭐⭐⭐ 时序基线 |
| **alphalens** | 3.8k | 因子分析 tear sheet | ⭐⭐⭐⭐⭐ 立即可用 |
| **pyfolio** | 5k+ | 组合绩效 tear sheet | ⭐⭐⭐⭐⭐ 立即可用 |
| **mlfinlab** | - | Purged K-Fold + DSR | ⭐⭐⭐⭐⭐ 验证 0.059 |

---

# 第三部分：126 个开源项目详细整理

## 第一轮调研：56 个项目（10 大方向）

### 方向一：CS:GO / CS2 饰品交易与分析（8 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|---|---|---|
| 1 | [ByMykel/CSGO-API](https://github.com/ByMykel/CSGO-API) | 1.5k+ | CS2 全量元数据 JSON API | **本项目已用**；`paint_index`/`min_float` 字段可做特征 |
| 2 | [csfloat/inspect](https://github.com/csfloat/inspect) | 高 | 模拟 GC 协议批量抓 float | float value 是 CS2 定价核心因子 |
| 3 | SteamTradingSiteTracker | 1k+ | BUFF/IGXE/C5/UUYP/ECO 五平台挂刀比例 | 多平台比价架构 + 优先级队列调度 |
| 4 | [d-roho/CSGOPredictor](https://github.com/d-roho/CSGOPredictor) | 500+ | CS:GO 比赛回合胜率预测 | 校准曲线评估思路 |
| 5 | [markzhdan/buff163-unofficial-api](https://github.com/markzhdan/buff163-unofficial-api) | PyPI | Buff163 Python API 封装 | 补充 BUFF 数据源做跨平台验证 |
| 6 | [barnumbirr/skinport](https://github.com/barnumbirr/skinport) | 3 | Skinport API + WebSocket 实时成交流 | `last_24h/7d/30d/90d` 分时段统计字段 |
| 7 | [PaxxPatriot/skinport.py](https://github.com/PaxxPatriot/skinport.py) | 活跃 | skinport 异步版 | 事件驱动多流监听 |
| 8 | [GODrums/BetterFloat](https://github.com/GODrums/BetterFloat) | 2.5k 日活 | 浏览器扩展，20+ 市场叠加 Buff 比价 | 多市场比价 + 本地缓存设计 |

### 方向二：Steam 市场与游戏虚拟经济（7 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 9 | [SteamDatabase/SteamTracking](https://github.com/SteamDatabase/SteamTracking) | 988 | 追踪 Steam 客户端/API/protobuf 变化 | 订阅监控 Steam API 变更 |
| 10 | [MatyiFKBT/pysteammarket](https://github.com/MatyiFKBT/pysteammarket) | 13 | Steam 市场价格轻量查询 | 最小可用参考实现 |
| 11 | [kulman101/steam-price-overview](https://github.com/kulman101/steam-price-overview) | 新 | Node.js Steam 市场库（限流+多币种）| 限流 + 多币种设计 |
| 12 | [AzerothAuctionAssassin](https://github.com/ff14-advanced-market-search/azerothauctionassassin) | 活跃 | WoW 拍卖行全服扫描 + Discord 告警 | "全服扫描+均价基准+告警"三段式架构 |
| 13 | pricer（WoW Auctions） | PyPI | WoW 拍卖行自动化决策（买/卖/制造）| **policy 计算思路可迁移到 Trade Up 合成决策** |
| 14 | [TF2Autobot/tf2autobot](https://github.com/TF2Autobot/tf2autobot) | 高 | TF2 全自动交易机器人 | prices.tf 全物品均价聚合 + 成交触发重定价 |
| 15 | OSRS GE 生态（osrs/gppc/OSRSBytes） | 50+ | Old School Runescape 大交易所价格追踪 | **OSRS GE 与 CS2 市场机制高度类似** |

### 方向三：量化因子挖掘与排序学习（7 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 16 | [microsoft/qlib](https://github.com/microsoft/qlib) | 28k | AI 量化全栈平台 | **五层架构是 TBD/ 重构最佳模板**；Alpha158 因子分类 |
| 17 | [yli188/WorldQuant_alpha101_code](https://github.com/yli188/WorldQuant_alpha101_code) | 804 | WorldQuant 101 公式因子 Python 实现 | 补全 alpha001~alpha101 全集 |
| 18 | [RL-MLDM/alphagen](https://github.com/RL-MLDM/alphagen) | 691 | RL+GP+LLM 自动生成 alpha 因子 | **"协同 IC"思想做因子去相关** |
| 19 | STHSF/alpha101 | 中文 | alpha101 中文实现 | 中间变量缓存避免重算 |
| 20 | LambdaRankIC 论文（arxiv 2605.00501）| 论文 | 直接优化 Rank IC 的 XGBoost 自定义 objective | **本项目 `rank:ndcg` 可切换为 LambdaRankIC** |
| 21 | Stanford CS191 MacroRank | 学术 | 宏观条件化 LambdaMART + walk-forward CV | **walk-forward rolling CV** + regime gate |
| 22 | XGBoost 官方 LTR 教程 | 官方 | `rank:ndcg`/`rank:pairwise`/`rank:map` | `lambdarank_pair_method="topk"` |

### 方向四：量化研究框架（5 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 23 | [quantopian/alphalens](https://github.com/quantopian/alphalens) | 3.8k | **因子分析 tear sheet 生成器** | **本项目 `rank_ic_analysis.py` 是其极简版** |
| 24 | [quantopian/pyfolio](https://github.com/quantopian/pyfolio) | 5k+ | 组合绩效 tear sheet | 替换 `backtest_xgb.py` 手写统计 |
| 25 | [stefan-jansen/zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded) | 19.7k | 事件驱动回测引擎 | 优先级低 |
| 26 | [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 7.8k | **向量化超高速回测** | 参数扫描（top_n/holding_days/commission）|
| 27 | [mementum/backtrader](https://github.com/mementum/backtrader) | 21.5k | 事件驱动回测框架 | 优先级低 |

### 方向五：AI 量化与深度学习（5 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 28 | [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) | 高 | LLM 驱动研发自动化 | **自动扩展 200→1000+ 因子** |
| 29 | [zhutoutoutousan/worldquant-miner](https://github.com/zhutoutoutousan/worldquant-miner) | 中 | WorldQuant Brain alpha 自动提交 | Alpha 进化引擎思路 |
| 30 | [huseinzol05/Stock-Prediction-Models](https://github.com/huseinzol05/Stock-Prediction-Models) | 高 | 30+ DL 模型 + 23 交易代理 | LSTM/Transformer 作为深度模型基线对比 |

### 方向六：时间序列预测框架（8 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 31 | [unit8co/darts](https://github.com/unit8co/darts) | 7.5k | 80+ 模型统一 API | **协变量机制完美匹配 CS2**（稀有度/磨损/Major 日期注入）|
| 32 | [Nixtla/neuralforecast](https://github.com/Nixtla/neuralforecast) | 2.7k | 30+ SOTA 神经网络预测 | **TFT Variable Selection Network 自动选因子** |
| 33 | [Nixtla/statsforecast](https://github.com/Nixtla/statsforecast) | 4.8k | 统计模型库（比 statsmodels 快 20-50×）| **Croston 方法处理冷门饰品** |
| 34 | [timeseriesAI/tsai](https://github.com/timeseriesAI/tsai) | 5.5k | fastai + PyTorch 时序库 | PatchTST 长序列 SOTA |
| 35 | [facebook/prophet](https://github.com/facebook/prophet) | 18.9k | 可加性模型（趋势+季节性+节假日）| **Major/Operation/Trade Up 改革日期作为 holidays** |
| 36 | [ourownstory/neural_prophet](https://github.com/ourownstory/neural_prophet) | 4.1k | Prophet 神经网络版 + AR-Net | 全局模型训练 2244 个饰品 |
| 37 | [winedarksea/AutoTS](https://github.com/winedarksea/AutoTS) | 0.8k | **M6 股市预测竞赛冠军** | **本身就是"收益率排名"任务** |
| 38 | [facebookresearch/Kats](https://github.com/facebookresearch/Kats) | 5.0k | 一站式时序工具包 | **CUSUM/BOCPD 变点检测**自动标注事件 |

### 方向七：替代资产 / NFT / 加密量化 / 拍卖（10 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 39 | [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | 30k+ | 加密货币交易机器人 + Hyperopt + FreqAI | **回测引擎（费率+滑点）+ Hyperopt 超参搜索** |
| 40 | [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | 6k | "最准确回测引擎"（无 look-ahead bias）| **无 look-ahead bias 回测** + 规则显著性检验 |
| 41 | [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | 8k+ | 做市+套利框架（L2 订单簿）| 订单簿深度特征 + 跨平台套利 |
| 42 | [dcts/opensea-scraper](https://github.com/dcts/opensea-scraper) | 0.4k | OpenSea 地板价+offers 爬虫 | **trait 级抓取**（Blue Gem #387 / Fade 100%）|
| 43 | freesparrowrob/nft-sniper-bot | 0.1k | OpenSea 低价 NFT 监控 + Telegram 通知 | "rarity + price 阈值 + 通知"捡漏模式 |
| 44 | NFT 价格预测学术生态 | 论文 | NFT 价格预测（26287 小时数据）| **市场状态分层分析**（牛/熊/中性）+ SHAP |
| 45 | [tradingstrategy-ai/trading-strategy](https://github.com/tradingstrategy-ai/trading-strategy) | 1.5k | DeFi 链上策略回测 | **TimescaleDB** 时序存储 |
| 46 | StockxScrapper-JS + eBay Sold Scraper | - | StockX 球鞋 + eBay 已成交爬虫 | **区分"成交价 vs 挂单价"** |
| 47 | 艺术品拍卖预测（Stanford + arXiv:2512.23078）| 论文 | Siamese CNN + LSTM 预测画作拍卖价 | **图像 embedding**（ResNet 提取皮肤视觉特征）|
| 48 | [chescos/csgo-fade-percentage-calculator](https://github.com/chescos/csgo-fade-percentage-calculator) + case.oki.gg | - | Fade % 计算器 + CS2 武器箱掉落概率 | **EV 建模闭环**：掉落概率 × 皮肤价 = 开箱 EV |

### 方向八：回测与组合优化（3 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 49 | [dcajasn/Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) | 高 | 26 种凸风险度量 + HRP 层次聚类 | **CVaR 优化适合 CS2 厚尾收益** |
| 50 | [robertmartin8/PyPortfolioOpt](https://github.com/robertmartin8/PyPortfolioOpt) | 高 | 经典 Markowitz + BL + HRP | Ledoit-Wolf 收缩协方差 |
| 51 | [gguan/qtrade](https://github.com/gguan/qtrade) | 新 | 模块化回测 + RL 环境 + **walk-forward 原生支持** | **walk-forward 是本项目最大缺口** |

### 方向九：CS2 饰品学术研究（2 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 52 | Guede-Fernández 2025 CS2 皮肤算法交易论文 | 论文 | LSTM + N-HiTS 预测 12000 皮肤 | **唯一直接对标研究**：7 天持有期+10% 手续费；Sharpe>1+Sortino>2+ROI>5% 筛选 |
| 53 | Scholten OSRS 统计分析论文（arXiv:1905.06721）| 论文 | OSRS GE 3467 价格序列统计分析 | "金融统计方法→虚拟经济"方法论框架 |

### 方向十：CS2 饰品估值与事件分析（3 个）

| # | 项目 | 核心功能 | 借鉴点 |
|---|---|---------|--------|
| 54 | cs2-inventory.com 衰减计算器 | 按类别分档衰减率 | **衰减率作为先验特征** |
| 55 | gratorama777 事件驱动分析 | Major/Update/Case 退役/选手代言事件分类 | 事件因子分类标准 |
| 56 | Vertox Quant OSRS 预测文章 | OSRS 价格预测 EDA + 季节性分解 | "游戏市场易预测（季节性+动量）"方法论 |

---

## 第二轮调研：70 个新项目（4 大方向）

### 方向十一：自动化交易系统与 AI 交易（20 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 57 | [nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | 21.6k | Rust+Python 生产级交易引擎 | **Rust 核心+Python 控制面**；"研究即生产"零代码迁移 |
| 58 | [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | 18.2k | C#+Python 云端平台，500+ 数据源 | 多语言策略接入 + 云端统一回测/实盘 |
| 59 | [StockSharp](https://github.com/StockSharp/StockSharp) | 10k | C# 全资产平台 + FIX 协议 | Hydra 多源数据抓取架构 |
| 60 | [tickgrinder](https://github.com/Ameobea/tickgrinder) | 594 | Rust 低延迟算法交易平台 | 纯 Rust 低延迟，抢低价饰品场景 |
| 61 | [alphahunter](https://github.com/phonegapX/alphahunter) | 336 | 异步事件驱动做市系统 | **做市策略**（CS2 流动性差可做市赚价差）|
| 62 | [Qbot](https://github.com/UFund-Me/Qbot) | 17.5k | AI 自动量化交易机器人 | qlib+RL+多因子，与本项目技术栈最接近 |
| 63 | [Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | 8.8k | **LLM Agent 金融工作台** | **Shadow Account 对比"规则 vs AI"收益**；MCP 协议 |
| 64 | [QuantDinger](https://github.com/brokermr810/QuantDinger) | 6.6k | AI 量化平台 + MCP Server | 多 broker 适配器模式 |
| 65 | [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) | 39k | LLM 驱动股票分析 + GitHub Actions | **零成本定时运行** + LLM 决策仪表盘 |
| 66 | [OpenBB](https://github.com/OpenBB-finance/OpenBB) | 68.1k | 开源数据平台 | **"connect once, consume everywhere"** + MCP Server |
| 67 | [FinceptTerminal](https://github.com/Fincept-Corporation/FinceptTerminal) | 24.2k | Bloomberg 风格金融终端 | 多面板布局 UI 设计 |
| 68 | [Stock-Prediction-Models](https://github.com/huseinzol05/Stock-Prediction-Models) | 7.4k | ML/DL 股价预测模型集合 | LSTM/Seq2Seq/进化策略多模型对比 |
| 69 | [awesome-ai-in-finance](https://github.com/georgezouq/awesome-ai-in-finance) | 6k | 金融 LLM 与 DL 策略精选清单 | RL/DL/NN 策略选型参考 |
| 70 | [je-suis-tm/quant-trading](https://github.com/je-suis-tm/quant-trading) | 9.9k | Python 量化策略集合 | **Monte Carlo 回测** + 配对交易实现 |
| 71 | [Financial-Models-Numerical-Methods](https://github.com/cantaro86/Financial-Models-Numerical-Methods) | 6.8k | 量化金融数值方法 Notebook | **Kalman Filter**（价格滤波）+ Heston 模型 |
| 72 | [bt](https://github.com/pmorissette/bt) | 2.5k | 灵活回测框架 | **非线性成本模型**（Steam 15% 手续费建模）|
| 73 | [optopsy](https://github.com/goldspanlabs/optopsy) | 1.3k | 期权研究与回测库 | 期权价差（磨损档套利思路）|
| 74 | [myhhub/stock](https://github.com/myhhub/stock) | 12.7k | 股票数据+指标+自动交易 | **筹码分布算法**（CS2 float 分布可借鉴）|
| 75 | [gekko](https://github.com/askmike/gekko) | 10k | Node.js 比特币交易机器人 | 轻量 Web UI 监控方案 |
| 76 | [binance-trading-bot](https://github.com/chrisleekr/binance-trading-bot) | 4.8k | 网格交易机器人 + Docker | **网格交易**（CS2 区间震荡适配）+ Docker 部署 |

### 方向十二：ML 金融与因子投资（18 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 77 | **mlfinlab** | - | Marcos López de Prado 量化金融库 | **Purged K-Fold + DSR** 验证 0.059 是否数据泄漏 |
| 78 | [firmai/machine-learning-asset-management](https://github.com/firmai/machine-learning-asset-management) | 高 | ML 资产管理 notebook 集 | ML 资产管理工作流 |
| 79 | puffin | - | 贝叶斯量化框架 | 贝叶斯不确定性建模 |
| 80 | [deepdow](https://github.com/jankrepl/deepdow) | 高 | 端到端组合优化 | 替代"先预测再优化"两阶段 |
| 81 | [cvxportfolio](https://github.com/cvxgrp/cvxportfolio) | 高 | 凸优化组合 | Yahoo Finance 数据集 |
| 82 | [eiten](https://github.com/dynamite-eitan/eiten) | 高 | 风险平价 + Black-Litterman | 风险平价实现 |
| 83 | [Empyrial](https://github.com/ssantoshp/Empyrial) | 高 | 一行代码出 tear sheet | 替代 pyfolio |
| 84 | [pytorch-forecasting](https://github.com/jdb78/pytorch-forecasting) | 高 | TFT/N-BEATS 实现 | TFT Variable Selection Network |
| 85 | **Optuna GPSampler** | - | 贝叶斯超参优化 | 替代手写 grid search |
| 86 | [pymc](https://github.com/pymc-devs/pymc) | 高 | 贝叶斯推断 | 饰品价格不确定性建模 |
| 87 | **HIST** | - | 图神经网络股票排名 | **CS2"武器箱→饰品→系列"图结构是未挖掘 alpha** |
| 88 | OmniGNN | - | 金融图神经网络 | 图结构特征 |
| 89 | MS-HGFN | - | 异质图融合网络 | 多层图融合 |
| 90 | [Kats](https://github.com/facebookresearch/Kats) | 5.0k | Facebook 时序工具包 | **变点检测**（自动发现事件）|

### 方向十三：中文量化社区（20 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 91 | **QuantLab** | 中文 | 中文量化研究框架 | **anchor_date 机制解决 K 线未收盘前视偏差** |
| 92 | **QuantDinger（中文版）** | 6.6k | AI 量化平台 | **已支持 MCP 协议**，与 Trae/Cursor 契合 |
| 93 | **Frontiers in AI CS2 论文** | 论文 | LSTM+Neural HI CS2 skin 交易 | **实证 20% 半年收益**（vs Buy&Hold 5-10%）|
| 94 | Quant-for-Beginners | 中文 | 量化新手教程 | **最适合新手学习** |
| 95 | Qbot（中文版） | 17.5k | AI 量化机器人 | 中文文档 |
| 96 | TqSdk | 中文 | 期货量化框架 | 期货数据接口 |
| 97 | finshare | 中文 | 金融数据共享 | 数据源补充 |
| 98 | PandaFactor | 中文 | 因子分析工具 | 中文因子分析 |

### 方向十四：虚拟经济与替代资产（18 个）

| # | 项目 | Star | 核心功能 | 借鉴点 |
|---|---|------|---------|--------|
| 99 | [Universalis-FFXIV](https://github.com/Universalis-FFXIV/Universalis) | 1.0k+ | FFXIV 跨服 Market Board 众包数据 | 众包数据采集 + 数据新鲜度监控 |
| 100 | [EVE-Tools/element43](https://github.com/EVE-Tools/element43) | 86 | EVE Online 全游戏经济订单簿 | 多语言微服务架构（gRPC）|
| 101 | [ilyaux/Eve-flipper](https://github.com/ilyaux/Eve-flipper) | 50-150 | EVE 套利工具 | **Portfolio VaR** + buy-vs-produce（Trade Up 决策）|
| 102 | [ao-data/albiondata-client](https://github.com/ao-data/albiondata-client) | 200+ | Albion Online 网络流量嗅探 | Proof-of-Work 反滥用（众包防伪）|
| 103 | [TheMizeGuy/BootyBayBroker](https://github.com/TheMizeGuy/BootyBayBroker) | 50-200 | WoW AH 价格追踪 | **TimescaleDB 时序存储** + per-unit 归一化 |
| 104 | [analyzing-nft-rarity](https://github.com/jeremylongshore/claude-code-plugins_plus-skills) | 1.0k+ | NFT 稀有度计算与排名 | **4 种稀有度算法**（Doppler/Fade/Blue Gem 定价）|
| 105 | [stefan-mcf/depthsim](https://github.com/stefan-mcf/depthsim) | 50-150 | 市场深度模拟器 | **从 K 线合成虚拟订单簿**（给 XGBoost 加微观特征）|
| 106 | PyMarketSim | 50-100 | RL 交易环境（TRON agent）| 多 agent 博弈论均衡分析 |
| 107 | mbt_gym | 30-80 | 做市 gym + PDE baseline | 向量化环境 + 经典金融数学 baseline |
| 108 | [QuantEcon two_auctions](https://python.quantecon.org/two_auctions.html) | 2k+ | 拍卖理论 Python 模拟 | Vickrey 拍卖视角看 Steam Market |
| 109 | [Optimal_Auctions](https://github.com/jamesmichelson/Optimal_Auctions) | 20-50 | 多维拍卖模拟库 | **多质量等级模型完美匹配 CS2 磨损档** |
| 110 | [OpenPoB](https://github.com/OpenPoB/OpenPoB) | 1.5k+ | PoE 装备制作 planner | **权重数据库设计**（CS2 武器箱掉率表）|
| 111 | [Dboire9/POE2_HTC](https://github.com/Dboire9/POE2_HTC) | 50-150 | POE2 最优制作路径计算器 | **Beam Search 算法直接套用到 Trade Up 树搜索** |
| 112 | [WladHD/pyoe2-craftpath](https://github.com/WladHD/pyoe2-craftpath) | 30-80 | POE2 制作路径（Rust+PyO3）| **Rust+PyO3 架构**（CS2 性能优化方向）|
| 113 | [OneBST/GGanalysis](https://github.com/OneBST/GGanalysis) | 500+ | 抽卡概率分析库 | **"抽卡层组合"范式套用到武器箱**（三层抽卡 EV）|
| 114 | @allemandi/gacha-engine | npm | TypeScript gacha 模拟引擎 | **反推抽数 API**（95% 开出 Karambit 需多少箱）|
| 115 | [matyifkbt/PySteamMarket](https://github.com/MatyiFKBT/PySteamMarket) | 12 | Steam 市场轻量 Python 模块 | Steam 市场备用数据源 |
| 116 | [AzerothAuctionAssassin](https://github.com/ff14-advanced-market-search/azerothauctionassassin) | 100+ | WoW AH sniper | **Last-Modified 头检测**（节省 API 配额）|

---

# 第四部分：Top 20 综合推荐

按"对 CS2 项目的立即可用性 × 方法论价值 × CS2 适配度"排序：

| 排名 | 项目 | 一句话理由 | 立即可做的事 |
|------|------|-----------|------------|
| 🥇 1 | **mlfinlab** | 验证 0.059 是否数据泄漏假象 | 用 Purged K-Fold 重新评估模型 |
| 🥈 2 | **quantopian/alphalens** | IC 分析是当前最薄弱环节 | `pip install alphalens-reloaded`，对 parquet 一键生成 tear sheet |
| 🥉 3 | **Vibe-Trading** | 从规则升级到 AI 自适应交易 | 用 Shadow Account 对比"规则 vs AI"收益 |
| 4 | **microsoft/qlib** | 全栈参考价值最高，五层架构模板 | 用 Alpha158 分类重组 200 因子 |
| 5 | **Dboire9/POE2_HTC** | Trade Up EV 计算最佳范本 | 移植 Beam Search 到 CS2 Trade Up 树搜索 |
| 6 | **OneBST/GGanalysis** | 武器箱开箱 EV 现成框架 | `pip install` 算三层抽卡 EV |
| 7 | **neuralforecast TFT** | 自动从 200 因子选 30-50 有效 | Variable Selection Network 替代手写筛选 |
| 8 | **Guede-Fernández 2025 CS2 论文** | 唯一直接对标的学术研究 | 复现 LSTM+N-HiTS baseline |
| 9 | **unit8co/darts** | 协变量机制完美匹配 CS2 | `pip install darts`，用 N-HiTS 跑全量饰品 baseline |
| 10 | **HIST** | 武器箱-饰品图结构是未挖掘 alpha | 构建 CS2 关系图喂给 GNN |
| 11 | **dcajasn/Riskfolio-Lib** | CVaR 优化适合 CS2 厚尾 | 替换 `backtest_xgb.py` 等权为 CVaR 优化 |
| 12 | **nautilus_trader** | Rust+Python 生产级引擎 | Rust 加速数据抓取，Python 写策略 |
| 13 | **OpenBB** | 数据基础设施统一 | "connect once" 理念重构数据层 |
| 14 | **BootyBayBroker** | TimescaleDB 替代扁平 JSON | 迁移 K 线存储到时序数据库 |
| 15 | **analyzing-nft-rarity** | 4 种稀有度算法 | 算 Doppler/Fade/Blue Gem 花色溢价 |
| 16 | **gguan/qtrade** | walk-forward 是方法论核心缺口 | 参考 `walk_forward` 模块实现滚动训练 |
| 17 | **LambdaRankIC 论文** | 直接优化 Rank IC | `objective` 从 `rank:ndcg` 切换为 LambdaRankIC |
| 18 | **Nixtla/statsforecast** | Croston 方法处理冷门饰品 | 给低流动性饰品做专用 baseline |
| 19 | **binance-trading-bot** | 网格交易适配 CS2 区间震荡 | Docker + Telegram 通知运维方案 |
| 20 | **QuantLab** | anchor_date 解决 K 线未收盘 | 解决 §7.6 当天未收盘前视偏差 |

---

# 第五部分：长线计划 P0-P5（重点）

> 📌 **本部分是项目的长线路线图，防止忘记。每个阶段含目标、具体任务、预期收益、验证标准。**

## 当前状态（P0 已完成）

- ✅ `rank_ic_analysis.py` 已恢复（19 个函数）
- ✅ TBD/ 路径硬编码已修复（5 处）
- ✅ 模型文件名已统一（3 处）
- ✅ `backtest_xgb.py` 的 `main()` 已恢复
- ✅ 全链路验证通过（preprocess → train → infer → backtest）
- ✅ 量化研究指南文档已创建（126 项目调研）

**当前指标**：
- test spearman: 0.059（弱预测力）
- train spearman: 0.3（过拟合）
- Sharpe: -2.296（亏损）
- 因子数: 200（未筛选）
- 回测: 等权 Top-N，单次切分，手续费 1.5%

---

## P0：验证基础（最高优先级，立即可做）

> 🎯 **目标**：验证当前 0.059 是否真实，排除数据泄漏假象

### P0.1 用 mlfinlab Purged K-Fold 验证
**问题**：当前 test spearman 0.059 可能是数据泄漏（时序重叠）或多次试验过拟合（9 组参数选最好）导致的假象。

**任务**：
1. `pip install mlfinlab`
2. 用 `PurgedKFold` 替代当前 `split_by_date`，在切分时"清除"训练集和测试集之间的重叠样本，加 embargo（禁运期）
3. 用 `DeflatedSharpeRatio` 评估"9 组参数选最好"的过拟合

**预期收益**：确认 0.059 是否真实
- 如果真实 → 继续优化模型
- 如果是假象 → 重新设计实验

**验证标准**：Purged K-Fold 后的 spearman 与当前 0.059 偏差 < 0.02

### P0.2 用 alphalens 做 IC 分析
**任务**：
1. `pip install alphalens-reloaded`
2. 对 `factor_dataset.parquet` 生成 IC tear sheet
3. 筛选 IC > 0.03 且 ICIR > 0.3 的因子
4. 按"手套/刀/武器/探员"分层分析（`by_group`）

**预期收益**：从 200 因子筛到 30-50 有效因子，test spearman 提升到 0.08-0.12

**验证标准**：输出 `factor_ic_report.html`，包含 IC 时序图、分位收益图、换手率图

### P0.3 用 neuralforecast TFT 自动选因子
**任务**：
1. `pip install neuralforecast`
2. 用 TFT 的 Variable Selection Network 从 200 因子中自动选出 30-50 有效因子
3. 对比 TFT 选出的因子与 alphalens 筛选的因子

**预期收益**：自动化因子筛选，可能发现人工忽略的有效因子

**验证标准**：TFT 输出因子重要性排名，与 alphalens IC 排名相关性 > 0.6

---

## P1：CS2 独有 Alpha 构建（高优先级）

> 🎯 **目标**：挖掘 CS2 独有的 alpha 来源（其他金融市场没有的）

### P1.1 武器箱开箱 EV 表（用 GGanalysis）
**原理**：CS2 武器箱 = 三层抽卡（稀有度层 0.26% Covert × 花色层均匀 × StatTrak 层 10%）

**任务**：
1. `pip install GGanalysis`
2. 对每个武器箱构建三层抽卡模型
3. 计算 EV = Σ(掉落概率 × 皮肤价) + 方差
4. 输出 `case_ev_table.csv`：每个武器箱的 EV、方差、分布律

**预期收益**：新增"武器箱 EV"因子，预测"开箱热潮"对饰品价格的影响

**验证标准**：47 个武器箱全部计算完成，EV 与社区共识一致

### P1.2 Trade Up 合成 EV 表（用 POE2_HTC Beam Search）
**原理**：CS2 Trade Up Contract（10→1 + 5 Covert→Knife）是多步概率分支决策树，与 POE2 制作路径数学同构。

**任务**：
1. 参考 [Dboire9/POE2_HTC](https://github.com/Dboire9/POE2_HTC) 的 Beam Search 算法
2. 对每个 collection 构建 Trade Up 树
3. 计算最优 Trade Up 路径（most likely / most efficient / cheapest）
4. 输出 `tradeup_ev_table.csv`

**预期收益**：新增"Trade Up EV"因子，预测 Trade Up 改革对 Covert/Knife 价格的冲击

**验证标准**：能计算 2025-10-23 改革（5 Covert→Knife）前后的 EV 变化

### P1.3 花色稀有度溢价（用 analyzing-nft-rarity）
**原理**：CS2 高端饰品（Doppler Phase / Fade / Blue Gem）的"花色溢价"本质是 NFT 稀有度定价问题。

**任务**：
1. 参考 [analyzing-nft-rarity](https://github.com/jeremylongshore/claude-code-plugins_plus-skills) 的 4 种算法
2. 对 Doppler Phase 用 `rarity_score`（1/frequency）
3. 对 Fade 渐变百分比用 `information`（熵-based -log2）
4. 对 Blue Gem 蓝色占比用 `rarity_score`
5. 输出 `pattern_rarity.csv`：每件饰品的花色稀有度得分

**预期收益**：新增"花色稀有度"因子，预测花色溢价倍数

**验证标准**：稀有度得分与市场价相关性 > 0.7

### P1.4 事件因子构建（用 Kats 变点检测）
**任务**：
1. 用 [Kats](https://github.com/facebookresearch/Kats) 的 CUSUM/BOCPD 自动检测饰品价格变点
2. 构建 CS2 事件日历（Major/武器箱/Trade Up/Operation）
3. 生成事件因子：`days_to_major` / `days_since_case_release` / `is_tradeup_reform`
4. 喂给横截面模型

**预期收益**：当前 200 因子都是技术面，加事件因子提升预测力 + 可解释性

**验证标准**：事件因子的 IC > 0.05

---

## P2：回测与基础设施升级（中优先级）

> 🎯 **目标**：让回测更真实，数据基础设施更稳健

### P2.1 回测严谨性升级
**任务**：
1. **手续费建模**：从 1.5% 改为 8%（BUFF 买入 2.5% + Steam 卖出 15% 综合）
2. **Walk-Forward**：参考 [qtrade](https://github.com/gguan/qtrade) 实现滚动训练
3. **滑点建模**：参考 [bt](https://github.com/pmorissette/bt) 的非线性成本模型
4. **pyfolio 报告**：`pip install pyfolio-reloaded`，替换手写统计

**预期收益**：Sharpe 从 -2.296 提升到 0.5-1.0（真实成本下）

**验证标准**：walk-forward 回测的 Sharpe 与单次切分偏差 < 0.3

### P2.2 组合优化升级
**任务**：
1. `pip install Riskfolio-Lib`
2. 替换 `backtest_xgb.py` 等权为 CVaR 优化
3. 对比等权 vs CVaR vs 风险平价

**预期收益**：Sharpe 提升 0.2-0.5

**验证标准**：CVaR 优化的 Sharpe > 等权

### P2.3 数据基础设施迁移
**任务**：
1. 参考 [BootyBayBroker](https://github.com/TheMizeGuy/BootyBayBroker) 的 TimescaleDB 方案
2. 将 `data/hourly/{id}.json` + `data/daily/{id}.json` 迁移到 TimescaleDB
3. 用 hypertable 自动分区 + continuous aggregates 加速因子回测

**预期收益**：2244 物品 × 365 天的因子回测速度提升 10-50×

**验证标准**：全量因子回测从分钟级降到秒级

### P2.4 用 OpenBB 统一数据层
**任务**：
1. 参考 [OpenBB](https://github.com/OpenBB-finance/OpenBB) 的"connect once, consume everywhere"理念
2. SteamDT/Buff/bymykel 数据源接入一次，同时服务训练/LLM/Web/REST
3. 用 MCP Server 让 AI Agent 统一访问 CS2 数据

**预期收益**：数据层统一，避免多源分散

**验证标准**：单一数据接口服务 3+ 消费方

---

## P3：AI 自动交易（高优先级）

> 🎯 **目标**：从固定规则升级到 AI 自适应交易

### P3.1 规则引擎升级（路线 A）
**任务**：
1. 在现有 XGBoost 预测基础上加规则引擎：
   - 预测收益 > 5% 且波动率低 → 重仓
   - 预测收益 2-5% → 标准仓
   - 预测收益 < 2% → 空仓
   - 持有期过半且浮亏 > 3% → 止损
2. 把"Trade Up 合成"作为交易动作建模（CS2 独有）

**预期收益**：从"固定 Top6+8天"升级到"条件自适应"

**验证标准**：规则引擎的 Sharpe > 固定规则

### P3.2 Vibe-Trading Shadow Account 对比
**任务**：
1. 参考 [Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) 的 Shadow Account
2. 从现有交易日志提取规则 → 回测对比"规则 vs AI"收益差异
3. 用 LLM Agent 生成自适应策略

**预期收益**：量化 AI 比规则好多少

**验证标准**：AI 策略 Sharpe > 规则策略

### P3.3 网格交易（用 binance-trading-bot 思路）
**任务**：
1. 参考 [binance-trading-bot](https://github.com/chrisleekr/binance-trading-bot) 的网格交易策略
2. CS2 饰品区间震荡明显，网格交易（低买高卖区间挂单）非常适合
3. Docker 部署 + Telegram 通知

**预期收益**：针对区间震荡市场的稳定收益

**验证标准**：网格策略在震荡期 Sharpe > 趋势策略

### P3.4 强化学习（长期，路线 B）
**任务**：
1. 先有稳定的监督学习 baseline（P0-P2 完成）
2. 用 `stable-baselines3` PPO 做端到端交易代理
3. 奖励函数：收益 - 手续费 - 7 天持有期机会成本 - 回撤惩罚
4. 对比监督学习 vs RL 的 Sharpe

**预期收益**：长期可能超越监督学习，但短期风险高

**验证标准**：RL 代理的 Sharpe > 监督学习（谨慎，可能过拟合）

---

## P4：模型层升级（中优先级）

> 🎯 **目标**：多模型对比 + 目标函数对齐

### P4.1 多模型对比
**任务**：
1. 在 XGBoost 之外接入 LightGBM / CatBoost / Linear
2. 参考 [Stock-Prediction-Models](https://github.com/huseinzol05/Stock-Prediction-Models) 的多模型对比
3. qlib benchmark 显示 LightGBM 在 Alpha158 上 IR 1.02 > XGBoost 0.91

**预期收益**：找到最优模型

**验证标准**：对比 4+ 模型的 spearman

### P4.2 目标函数对齐
**任务**：
1. 切换 `rank:ndcg` 为 LambdaRankIC 自定义 objective
2. 参考 LambdaRankIC 论文（arxiv 2605.00501）

**预期收益**：训练目标与评估指标对齐

**验证标准**：LambdaRankIC 的 spearman > rank:ndcg

### P4.3 Optuna 超参优化
**任务**：
1. `pip install optuna`
2. 用 Optuna GPSampler 替代手写 grid search
3. 多目标优化（spearman + Sharpe）

**预期收益**：更高效的超参搜索

**验证标准**：Optuna 找到的超参 spearman > 手写 grid

### P4.4 图神经网络（用 HIST）
**任务**：
1. 参考 HIST 构建 CS2 关系图："武器箱→饰品→系列"
2. 用 GNN 挖掘图结构 alpha

**预期收益**：CS2 的层次结构是未挖掘的 alpha

**验证标准**：GNN 的 spearman > XGBoost

---

## P5：工程化与自动化（长期）

> 🎯 **目标**：可复现 + 可追踪 + 自动化

### P5.1 qlib YAML workflow
**任务**：
1. 把工作流改写成 `TBD/pipeline.yaml`（Qlib qrun 风格）
2. 参考 [microsoft/qlib](https://github.com/microsoft/qlib) 的 YAML workflow

**预期收益**：工作流可复现

### P5.2 测试覆盖
**任务**：
1. 加 `pytest` 覆盖核心函数
2. 参考 pricer 的 black + mypy + pytest + pandera 工具链

### P5.3 RD-Agent 自动因子挖掘
**任务**：
1. 参考 [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent)
2. 用 LLM 自动扩展因子库 200→1000+

**预期收益**：长期因子库自动迭代

### P5.4 Rust 性能优化
**任务**：
1. 参考 [WladHD/pyoe2-craftpath](https://github.com/WladHD/pyoe2-craftpath) 的 Rust+PyO3 架构
2. 用 Rust 重写因子计算热点 + PyO3 暴露给 Python

**预期收益**：性能提升 10-50×

---

## 长线计划总结表

| 阶段 | 方向 | 优先级 | 预期收益 | 关键工具 |
|------|------|--------|---------|---------|
| P0.1 | 验证 0.059 是否真实 | 🔴 最高 | 排除数据泄漏假象 | mlfinlab Purged K-Fold |
| P0.2 | IC 分析 + 因子筛选 | 🔴 最高 | 200→30-50 有效因子 | alphalens |
| P0.3 | TFT 自动选因子 | 🔴 最高 | 自动化特征选择 | neuralforecast |
| P1.1 | 武器箱 EV 表 | 🟠 高 | CS2 独有 alpha | GGanalysis |
| P1.2 | Trade Up EV 表 | 🟠 高 | CS2 独有 alpha | POE2_HTC Beam Search |
| P1.3 | 花色稀有度溢价 | 🟠 高 | CS2 独有 alpha | analyzing-nft-rarity |
| P1.4 | 事件因子 | 🟠 高 | 提升可解释性 | Kats |
| P2.1 | 回测严谨性 | 🟡 中 | Sharpe 真实化 | pyfolio + qtrade |
| P2.2 | 组合优化 | 🟡 中 | Sharpe +0.2-0.5 | Riskfolio-Lib |
| P2.3 | TimescaleDB | 🟡 中 | 回测速度 10-50× | BootyBayBroker 方案 |
| P2.4 | OpenBB 数据层 | 🟡 中 | 数据统一 | OpenBB |
| P3.1 | 规则引擎升级 | 🟠 高 | 条件自适应 | 自写 |
| P3.2 | Vibe-Trading 对比 | 🟠 高 | 量化 AI vs 规则 | Vibe-Trading |
| P3.3 | 网格交易 | 🟡 中 | 震荡市场收益 | binance-trading-bot |
| P3.4 | 强化学习 | 🟢 低 | 长期可能超越 | stable-baselines3 |
| P4.1 | 多模型对比 | 🟡 中 | 找最优模型 | LightGBM/CatBoost |
| P4.2 | LambdaRankIC | 🟡 中 | 目标对齐 | 自定义 objective |
| P4.3 | Optuna 超参 | 🟡 中 | 高效搜索 | Optuna GPSampler |
| P4.4 | 图神经网络 | 🟢 低 | 结构 alpha | HIST |
| P5.1 | YAML workflow | 🟢 低 | 可复现 | qlib |
| P5.2 | 测试覆盖 | 🟢 低 | 工程质量 | pytest |
| P5.3 | RD-Agent | 🟢 低 | 自动因子 | RD-Agent |
| P5.4 | Rust 优化 | 🟢 低 | 性能 10-50× | PyO3 |

---

## 关键洞察（防止忘记）

### 1. 最大风险：0.059 可能是假象
**mlfinlab 的 Purged K-Fold + DSR** 揭示：test spearman 0.059 可能是**数据泄漏**（时序重叠）或**多次试验过拟合**（9 组参数选最好）导致的假象。**必须先用 mlfinlab 验证**。

### 2. CS2 独有 alpha 的"金矿"
- **Trade Up EV**：POE2_HTC 的 Beam Search 直接套用
- **武器箱 EV**：GGanalysis 的抽卡层框架直接套用
- **花色稀有度**：analyzing-nft-rarity 的 4 种算法直接套用
- 这三个是**其他金融市场没有的 alpha 来源**

### 3. 数据基础设施瓶颈
BootyBayBroker 的 TimescaleDB 方案揭示：CS2 项目当前的扁平 JSON 存储在 2244×365 规模下已遇瓶颈，需要迁移到时序数据库。

### 4. AI 自动交易的完整路径
Vibe-Trading 的 LLM Agent + Shadow Account 架构，提供了从"规则交易"到"AI 自适应交易"的完整迁移路径。

### 5. 目标函数错配
本项目用 `rank:ndcg` 训练但用 Spearman Rank IC 评估，LambdaRankIC 论文提供了直接优化 Rank IC 的闭式解。

### 6. 中文社区资源
- QuantLab 的 anchor_date 机制直接解决"K 线未收盘"问题
- Frontiers AI 论文实证 LSTM+Neural HI 在 CS2 市场 20% 半年收益
- QuantDinger 已支持 MCP 协议，与 Trae/Cursor 契合

---

## 附录：术语对照表

| 术语 | 英文 | 含义 |
|------|------|------|
| 因子 | Factor / Alpha | 能预测未来收益的变量 |
| 信息系数 | IC | 因子值与未来收益的相关系数 |
| 秩信息系数 | Rank IC | 用排名算的 IC（Spearman），更稳健 |
| 信息比率 | ICIR | IC 均值 / IC 标准差 |
| 横截面 | Cross-Sectional | 同一时间点比较不同资产 |
| 时序 | Time-Series | 同一资产比较不同时间 |
| 排序学习 | LTR | 让模型学习排序而非数值预测 |
| 回测 | Backtest | 用历史数据模拟交易 |
| 最大回撤 | Max Drawdown | 历史最大亏损幅度 |
| 夏普比率 | Sharpe Ratio | 风险调整后收益 |
| 行业中性化 | Industry Neutralization | 剔除行业效应 |
| 未来函数 | Look-Ahead Bias | 用了未来才知道的数据 |
| 过拟合 | Overfitting | 训练集好测试集差 |
| 数据泄漏 | Data Leakage | train/test 时序重叠 |
| Purged K-Fold | - | 清除重叠样本的交叉验证 |
| Deflated Sharpe | DSR | 校正多次试验过拟合的 Sharpe |
| Walk-Forward | - | 滚动窗口训练 + 即时 OOS 测试 |
| Tear Sheet | - | 标准化绩效报告 |
| CVaR | Conditional VaR | 最差情况平均亏损 |
| 协变量 | Covariate | 时序模型的外部信息 |
| 抽卡层 | Gacha Layer | 概率抽卡的数学抽象 |
| Beam Search | - | 保留 top-K 候选的搜索算法 |

---

> 📝 **本文件为 CS2 排名预测项目的量化知识普及与开源项目调研文档（v2 完整版）。**
> 🗺️ **第五部分长线计划是核心**，防止忘记项目方向。
> 🔗 **配套文档**：[AGENTS.md](../AGENTS.md)（饰品知识库）/ [README.md](../README.md)（项目总览）/ [CHANGELOG.md](../CHANGELOG.md)（变更记录）
> 📅 **最后更新**：2026-06-17
