#!/usr/bin/env python3
# =============================================================================
# 模块：P0.2 因子 IC 分析与筛选  [TBD]
# 文件：TBD/p0_ic_analysis.py
# 用途：对 factor_dataset.parquet 中的 200 个因子做 IC 分析，
#       筛选出有效因子（ICIR 高、IC 稳定、分位收益单调）。
#       参考：alphalens 核心指标（IC / ICIR / quantile returns）。
# 使用：python TBD/p0_ic_analysis.py
# =============================================================================

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, ttest_1samp


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path(__file__).resolve().parent / "factor_dataset.parquet"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "p0_ic_report.json"
DEFAULT_CSV = Path(__file__).resolve().parent / "p0_ic_factor_ranking.csv"

TARGET_COL = "target_8d"
DATE_COL = "date"
ITEM_COL = "item_id"
MIN_CROSS_SECTION = 20  # 截面最小样本数
TOP_K_DEFAULT = 50  # 筛选 Top-K 因子


def prepare_features(df: pd.DataFrame) -> List[str]:
    excluded = {DATE_COL, ITEM_COL, TARGET_COL, "target_rank_pct", "target_rank_label"}
    return [c for c in df.columns if c not in excluded]


# =============================================================================
# 1. 单因子 IC 时间序列
# =============================================================================

def compute_ic_series(df: pd.DataFrame, factor_col: str, target_col: str) -> pd.Series:
    """对每个日期计算因子与目标的 Spearman 秩相关，返回 IC 时间序列。"""
    ic_list: List[Tuple[pd.Timestamp, float]] = []

    for date, sub in df.groupby(DATE_COL):
        factor_vals = sub[factor_col].dropna()
        target_vals = sub[target_col]
        mask = factor_vals.notna() & target_vals.notna()
        if mask.sum() < MIN_CROSS_SECTION:
            continue
        f = sub.loc[mask, factor_col].to_numpy()
        t = sub.loc[mask, target_col].to_numpy()
        if np.std(f) < 1e-10 or np.std(t) < 1e-10:
            continue
        corr, _ = spearmanr(f, t)
        if np.isfinite(corr):
            ic_list.append((date, corr))

    if not ic_list:
        return pd.Series(dtype=float)

    return pd.Series(dict(ic_list), name=factor_col)


# =============================================================================
# 2. IC 统计量（IC / ICIR / t / 正 IC 比例）
# =============================================================================

def ic_statistics(ic_series: pd.Series) -> Dict[str, float]:
    """计算 IC 序列的统计量。"""
    if len(ic_series) < 5:
        return {
            "ic_mean": float("nan"),
            "ic_std": float("nan"),
            "icir": float("nan"),
            "ic_t": float("nan"),
            "ic_pvalue": float("nan"),
            "positive_ratio": float("nan"),
            "n_dates": int(len(ic_series)),
        }

    mean = float(ic_series.mean())
    std = float(ic_series.std(ddof=1))
    icir = mean / std if std > 1e-10 else float("nan")
    n = len(ic_series)
    ic_t = mean * np.sqrt(n) / std if std > 1e-10 else float("nan")
    _, pvalue = ttest_1samp(ic_series, 0)
    positive_ratio = float((ic_series > 0).mean())

    return {
        "ic_mean": mean,
        "ic_std": std,
        "icir": icir,
        "ic_t": float(ic_t),
        "ic_pvalue": float(pvalue),
        "positive_ratio": positive_ratio,
        "n_dates": n,
    }


# =============================================================================
# 3. 分位数收益分析（5 档）
# =============================================================================

def quantile_returns(df: pd.DataFrame, factor_col: str, target_col: str, n_quantiles: int = 5) -> Dict:
    """把每日因子分 5 档，计算每档的平均未来收益，及 Top-Bottom 价差。"""
    records: List[Dict] = []

    for date, sub in df.groupby(DATE_COL):
        factor_vals = sub[factor_col]
        target_vals = sub[target_col]
        mask = factor_vals.notna() & target_vals.notna()
        if mask.sum() < n_quantiles * 2:
            continue
        valid = sub.loc[mask, [factor_col, target_col]].copy()
        try:
            valid["q"] = pd.qcut(valid[factor_col], n_quantiles, labels=False, duplicates="drop")
        except ValueError:
            continue
        if valid["q"].nunique() < 2:
            continue
        for q, g in valid.groupby("q"):
            records.append({
                "date": date,
                "quantile": int(q),
                "return": float(g[target_col].mean()),
                "n": len(g),
            })

    if not records:
        return {"top_minus_bottom": float("nan"), "monotonic_score": 0.0, "quantile_avg_returns": []}

    qr = pd.DataFrame(records)
    avg_by_q = qr.groupby("quantile")["return"].mean()
    top_minus_bottom = float(avg_by_q.iloc[-1] - avg_by_q.iloc[0]) if len(avg_by_q) >= 2 else float("nan")

    # 单调性评分：分位收益是否单调递增/递减（-1 到 1）
    if len(avg_by_q) >= 2:
        diffs = avg_by_q.diff().dropna()
        monotonic_score = float((diffs > 0).sum() - (diffs < 0).sum()) / len(diffs)
    else:
        monotonic_score = 0.0

    return {
        "top_minus_bottom": top_minus_bottom,
        "monotonic_score": monotonic_score,  # 1=完全单调递增, -1=完全单调递减
        "quantile_avg_returns": avg_by_q.round(5).to_dict(),
    }


# =============================================================================
# 4. 因子自相关（信号衰减速度）
# =============================================================================

def factor_autocorr(df: pd.DataFrame, factor_col: str, max_lag: int = 10) -> float:
    """计算因子值的 1 阶自相关（按 item_id 分组），衡量信号衰减速度。
    高自相关 = 信号持久（好），低自相关 = 信号噪声大（坏）。"""
    autocorrs: List[float] = []
    for _, g in df.groupby(ITEM_COL):
        s = g[factor_col].dropna()
        if len(s) < max_lag + 5:
            continue
        try:
            ac = s.autocorr(lag=1)
            if np.isfinite(ac):
                autocorrs.append(ac)
        except Exception:
            continue
    return float(np.mean(autocorrs)) if autocorrs else float("nan")


# =============================================================================
# 5. 主流程：批量分析所有因子
# =============================================================================

def analyze_all_factors(df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    """对所有因子做完整 IC 分析，返回 DataFrame。"""
    rows: List[Dict] = []
    total = len(feature_cols)

    for i, factor in enumerate(feature_cols):
        if (i + 1) % 20 == 0:
            print(f"  进度: {i+1}/{total}")

        ic_series = compute_ic_series(df, factor, TARGET_COL)
        stats = ic_statistics(ic_series)
        qr = quantile_returns(df, factor, TARGET_COL)
        ac = factor_autocorr(df, factor)

        rows.append({
            "factor": factor,
            **stats,
            "top_minus_bottom": qr["top_minus_bottom"],
            "monotonic_score": qr["monotonic_score"],
            "autocorr_lag1": ac,
        })

    result = pd.DataFrame(rows)

    # 综合评分：|ICIR| + 0.5 * |monotonic_score| + 0.3 * (autocorr > 0.3)
    result["abs_icir"] = result["icir"].abs()
    result["abs_monotonic"] = result["monotonic_score"].abs()
    result["has_persistence"] = (result["autocorr_lag1"] > 0.3).astype(float)
    result["score"] = (
        result["abs_icir"].fillna(0)
        + 0.5 * result["abs_monotonic"].fillna(0)
        + 0.3 * result["has_persistence"]
    )

    # 按 score 降序
    result = result.sort_values("score", ascending=False).reset_index(drop=True)
    return result


# =============================================================================
# 6. 因子相关性筛选（去冗余）
# =============================================================================

def filter_redundant(top_df: pd.DataFrame, df: pd.DataFrame, corr_threshold: float = 0.7) -> List[str]:
    """从 top_df 中筛选，去除与已选因子相关性 > 0.7 的因子。"""
    selected: List[str] = []
    selected_corr: pd.DataFrame = pd.DataFrame()

    for _, row in top_df.iterrows():
        factor = row["factor"]
        if factor not in df.columns:
            continue

        if selected_corr.empty:
            selected.append(factor)
            selected_corr = df[[factor]].copy()
            continue

        # 计算与已选因子的最大相关性
        max_corr = 0.0
        for sel in selected:
            mask = df[factor].notna() & df[sel].notna()
            if mask.sum() < 100:
                continue
            c = df.loc[mask, factor].corr(df.loc[mask, sel])
            if np.isfinite(c) and abs(c) > max_corr:
                max_corr = abs(c)

        if max_corr < corr_threshold:
            selected.append(factor)
            if len(selected) % 5 == 0:
                print(f"    已选 {len(selected)} 个因子 (当前: {factor}, max_corr={max_corr:.3f})")

    return selected


# =============================================================================
# 7. 主入口
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--top-k", type=int, default=TOP_K_DEFAULT)
    parser.add_argument("--corr-threshold", type=float, default=0.7)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.dataset.exists():
        raise FileNotFoundError(f"Dataset {args.dataset} not found. Run preprocess_xgb.py first.")

    print(f"加载数据集: {args.dataset}")
    df = pd.read_parquet(args.dataset)
    df[DATE_COL] = pd.to_datetime(df[DATE_COL])
    df = df.sort_values([DATE_COL, ITEM_COL]).reset_index(drop=True)
    print(f"样本: {len(df):,} 行, 日期: {df[DATE_COL].nunique()}, 物品: {df[ITEM_COL].nunique()}")

    feature_cols = prepare_features(df)
    print(f"因子数: {len(feature_cols)}")

    print(f"\n{'='*70}")
    print("Step 1: 对每个因子计算 IC / ICIR / 分位收益 / 自相关")
    print(f"{'='*70}")
    ranking = analyze_all_factors(df, feature_cols)

    print(f"\n{'='*70}")
    print(f"Step 2: Top-K={args.top_k} 因子（按综合评分）")
    print(f"{'='*70}")
    top_k = ranking.head(args.top_k)
    print(f"{'因子':<35} {'IC':>8} {'ICIR':>8} {'t':>8} {'T-B':>10} {'Mono':>6} {'AC1':>6}")
    for _, row in top_k.iterrows():
        print(
            f"{row['factor']:<35} "
            f"{row['ic_mean']:>8.4f} "
            f"{row['icir']:>8.3f} "
            f"{row['ic_t']:>8.2f} "
            f"{row['top_minus_bottom']:>10.5f} "
            f"{row['monotonic_score']:>6.2f} "
            f"{row['autocorr_lag1']:>6.2f}"
        )

    print(f"\n{'='*70}")
    print(f"Step 3: 相关性去冗余 (threshold={args.corr_threshold})")
    print(f"{'='*70}")
    selected = filter_redundant(top_k, df, corr_threshold=args.corr_threshold)
    print(f"\n去冗余后保留: {len(selected)} 个因子")

    # 汇总统计
    all_icir = ranking["icir"].dropna()
    summary = {
        "total_factors": len(feature_cols),
        "factors_with_positive_icir": int((ranking["icir"] > 0).sum()),
        "factors_with_negative_icir": int((ranking["icir"] < 0).sum()),
        "factors_significant_p05": int((ranking["ic_pvalue"] < 0.05).sum()),
        "factors_high_persistence": int((ranking["autocorr_lag1"] > 0.5).sum()),
        "factors_monotonic": int((ranking["monotonic_score"].abs() > 0.5).sum()),
        "top_k_selected": selected,
        "icir_distribution": {
            "mean": float(all_icir.mean()),
            "std": float(all_icir.std()),
            "min": float(all_icir.min()),
            "max": float(all_icir.max()),
            "median": float(all_icir.median()),
        },
        "top_10_by_icir": ranking.head(10)[["factor", "ic_mean", "icir", "ic_t", "ic_pvalue"]].to_dict("records"),
    }

    # 保存
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str, ensure_ascii=False)

    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    ranking.to_csv(args.csv_output, index=False)

    print(f"\n报告已保存: {args.output}")
    print(f"完整排名: {args.csv_output}")

    print(f"\n{'='*70}")
    print("P0.2 结论")
    print(f"{'='*70}")
    print(f"  总因子数: {len(feature_cols)}")
    print(f"  ICIR > 0 的因子: {summary['factors_with_positive_icir']}")
    print(f"  p<0.05 显著因子: {summary['factors_significant_p05']}")
    print(f"  ICIR 中位数: {summary['icir_distribution']['median']:.3f}")
    print(f"  去冗余后保留: {len(selected)} 个因子")
    print(f"\n  下一步: 用这 {len(selected)} 个因子重新训练 XGBoost，看 Purged K-Fold 是否提升")


if __name__ == "__main__":
    main()
