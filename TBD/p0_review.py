#!/usr/bin/env python3
# =============================================================================
# 模块：P0 审查与优化实验  [TBD]
# 文件：TBD/p0_review.py
# 用途：
#   1. 审查 P0.1 Purged K-Fold 的 val 集切分（验证无泄漏）
#   2. 优化实验：val 大小 + early_stopping_rounds 敏感性
#   3. 用 21 因子做 A/B/C 对比，找最优配置
# 使用：python TBD/p0_review.py
# =============================================================================

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

try:
    import xgboost as xgb
except ImportError as exc:
    raise SystemExit("xgboost not installed") from exc

from p0_validation import (
    purged_kfold_dates,
    map_date_idx_to_row_idx,
    build_dmatrix_from_rows,
    spearman_corr,
    TARGET_HORIZON_DAYS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path(__file__).resolve().parent / "factor_dataset.parquet"
DEFAULT_IC_REPORT = Path(__file__).resolve().parent / "p0_ic_report.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "p0_review_report.json"


def load_selected_factors(ic_report_path: Path) -> List[str]:
    with ic_report_path.open("r", encoding="utf-8") as f:
        return json.load(f).get("top_k_selected", [])


def run_config(
    df: pd.DataFrame,
    feature_cols: List[str],
    val_ratio: float,
    early_stopping_rounds: int,
    learning_rate: float,
    n_splits: int = 5,
) -> Dict:
    """跑一组配置，返回 5 折结果。"""
    unique_dates = np.sort(df["date"].unique())
    date_splits = purged_kfold_dates(
        unique_dates, n_splits=n_splits,
        label_horizon=TARGET_HORIZON_DAYS, embargo_days=2,
    )
    row_splits = map_date_idx_to_row_idx(df, date_splits)

    params = {
        "objective": "rank:ndcg",
        "eval_metric": "ndcg",
        "learning_rate": learning_rate,
        "max_depth": 5,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
        "tree_method": "hist",
        "random_state": 42,
        "n_jobs": -1,
    }

    fold_results: List[Dict] = []
    all_spearmans: List[float] = []
    all_best_iters: List[int] = []

    for split in row_splits:
        train_df = df.iloc[split.train_idx].sort_values(["date", "item_id"])
        train_dates = np.sort(train_df["date"].unique())
        val_cut = int(len(train_dates) * (1 - val_ratio))
        val_dates = train_dates[val_cut:]
        train_dates_final = train_dates[:val_cut]

        # 验证 val 无泄漏：检查 val 日期的标签窗口 [vd, vd+8] 是否与 test 标签窗口重叠
        # 重叠条件: vd <= test_label_end and vd+8 >= test_label_start
        test_label_start = split.test_start
        test_label_end = split.test_end + pd.Timedelta(days=TARGET_HORIZON_DAYS)
        leak = False
        for vd in val_dates:
            vd_label_end = vd + pd.Timedelta(days=TARGET_HORIZON_DAYS)
            if vd <= test_label_end and vd_label_end >= test_label_start:
                leak = True
                break
        leak_check = "LEAK" if leak else "OK"

        train_rows = train_df[train_df["date"].isin(train_dates_final)].index.to_numpy()
        val_rows = train_df[train_df["date"].isin(val_dates)].index.to_numpy()

        try:
            dtrain, _ = build_dmatrix_from_rows(df, train_rows, feature_cols)
            dval, truth_val = build_dmatrix_from_rows(df, val_rows, feature_cols)
            dtest, truth_test = build_dmatrix_from_rows(df, split.test_idx, feature_cols)
        except ValueError:
            continue

        model = xgb.train(
            params=params,
            dtrain=dtrain,
            num_boost_round=950,
            evals=[(dtrain, "train"), (dval, "val")],
            early_stopping_rounds=early_stopping_rounds,
            verbose_eval=False,
        )

        best_iter = int(model.best_iteration)
        preds_test = model.predict(dtest, iteration_range=(0, best_iter + 1))
        sp = spearman_corr(truth_test, preds_test)
        all_spearmans.append(sp)
        all_best_iters.append(best_iter)

        fold_results.append({
            "fold": split.fold_id + 1,
            "test_start": str(split.test_start.date()),
            "test_end": str(split.test_end.date()),
            "val_size_days": len(val_dates),
            "train_size_days": len(train_dates_final),
            "leak_check": leak_check,
            "best_iter": best_iter,
            "test_spearman": sp,
        })

    spearmans_arr = np.array([s for s in all_spearmans if np.isfinite(s)])
    iters_arr = np.array(all_best_iters)

    return {
        "val_ratio": val_ratio,
        "early_stopping_rounds": early_stopping_rounds,
        "learning_rate": learning_rate,
        "fold_results": fold_results,
        "mean_test_spearman": float(np.mean(spearmans_arr)),
        "std_test_spearman": float(np.std(spearmans_arr, ddof=1)),
        "mean_best_iter": float(np.mean(iters_arr)),
        "median_best_iter": float(np.median(iters_arr)),
        "best_iter_distribution": iters_arr.tolist(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--ic-report", type=Path, default=DEFAULT_IC_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print(f"加载数据集: {args.dataset}")
    df = pd.read_parquet(args.dataset)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "item_id"]).reset_index(drop=True)
    print(f"样本: {len(df):,} 行, 日期: {df['date'].nunique()}")

    selected = load_selected_factors(args.ic_report)
    selected = [f for f in selected if f in df.columns]
    print(f"使用 21 因子: {len(selected)}")

    # === 审查 1: val 集泄漏检查 ===
    print(f"\n{'='*70}")
    print("审查 1: val 集标签泄漏检查")
    print(f"{'='*70}")
    print("Purge 逻辑保证: train 中保留日期 t' 满足 t'+8 < test_start")
    print("val 是 train 子集 → val 最后日期 +8 < test_start → 无泄漏")
    print("(实验中将逐 fold 验证)")

    # === 优化实验: 3 种配置 ===
    configs = [
        {"name": "A_原配置", "val_ratio": 0.10, "es": 80, "lr": 0.018},
        {"name": "B_大val", "val_ratio": 0.20, "es": 80, "lr": 0.018},
        {"name": "C_大val_慢es", "val_ratio": 0.20, "es": 200, "lr": 0.018},
        {"name": "D_大val_慢es_慢lr", "val_ratio": 0.20, "es": 200, "lr": 0.010},
    ]

    results: List[Dict] = []
    for cfg in configs:
        print(f"\n{'='*70}")
        print(f"配置 {cfg['name']}: val={cfg['val_ratio']:.0%}, es={cfg['es']}, lr={cfg['lr']}")
        print(f"{'='*70}")
        r = run_config(
            df, selected,
            val_ratio=cfg["val_ratio"],
            early_stopping_rounds=cfg["es"],
            learning_rate=cfg["lr"],
        )
        r["config_name"] = cfg["name"]
        results.append(r)
        print(f"  spearman: {r['mean_test_spearman']:.4f} ± {r['std_test_spearman']:.4f}")
        print(f"  best_iter 均值: {r['mean_best_iter']:.1f}, 中位数: {r['median_best_iter']:.0f}")
        print(f"  best_iter 分布: {r['best_iter_distribution']}")

    # === 对比表 ===
    print(f"\n{'='*70}")
    print("优化对比表")
    print(f"{'='*70}")
    print(f"{'配置':<20} {'val':>5} {'es':>5} {'lr':>6} {'spearman':>10} {'std':>8} {'best_iter均值':>14} {'best_iter分布'}")
    for r in results:
        print(
            f"{r['config_name']:<20} "
            f"{r['val_ratio']:>5.0%} "
            f"{r['early_stopping_rounds']:>5} "
            f"{r['learning_rate']:>6.3f} "
            f"{r['mean_test_spearman']:>10.4f} "
            f"{r['std_test_spearman']:>8.4f} "
            f"{r['mean_best_iter']:>14.1f} "
            f"{r['best_iter_distribution']}"
        )

    # === 泄漏检查汇总 ===
    print(f"\n{'='*70}")
    print("val 集泄漏检查（配置 A 逐 fold）")
    print(f"{'='*70}")
    for fr in results[0]["fold_results"]:
        print(f"  Fold {fr['fold']}: val_max+8 vs test_start → {fr['leak_check']}")

    # === 找最优配置 ===
    best = max(results, key=lambda x: x["mean_test_spearman"])
    baseline = results[0]
    diff = best["mean_test_spearman"] - baseline["mean_test_spearman"]

    print(f"\n{'='*70}")
    print("结论")
    print(f"{'='*70}")
    print(f"  基线 (A): spearman={baseline['mean_test_spearman']:.4f}, best_iter均值={baseline['mean_best_iter']:.1f}")
    print(f"  最优 ({best['config_name']}): spearman={best['mean_test_spearman']:.4f}, best_iter均值={best['mean_best_iter']:.1f}")
    print(f"  提升: {diff:+.4f}")

    if diff > 0.005:
        verdict = f"✅ 优化有效: {best['config_name']} 提升 {diff:+.4f}"
    elif diff > -0.005:
        verdict = f"⚠️ 优化中性: val 大小不是瓶颈，best_iter=0 可能是数据信号弱"
    else:
        verdict = f"❌ 优化反而下降: {best['config_name']} 下降 {diff:+.4f}"

    print(f"  判定: {verdict}")

    # best_iter 改善评估
    iter_improved = best["mean_best_iter"] > baseline["mean_best_iter"] * 2
    print(f"  best_iter 改善: {'是' if iter_improved else '否'} (基线 {baseline['mean_best_iter']:.1f} → 最优 {best['mean_best_iter']:.1f})")

    # 保存
    report = {
        "configs": results,
        "baseline": baseline,
        "best": best,
        "diff": diff,
        "verdict": verdict,
        "best_iter_improved": iter_improved,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n报告: {args.output}")


if __name__ == "__main__":
    main()
