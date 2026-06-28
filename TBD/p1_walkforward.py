#!/usr/bin/env python3
# =============================================================================
# 模块：P1 Walk-Forward 验证  [TBD]
# 文件：TBD/p1_walkforward.py
# 用途：对 P1 的新标签数据集做 Walk-Forward 滚动验证，比较真实的滚动训练效果。
# 使用：python TBD/p1_walkforward.py --dataset TBD/factor_dataset_p1_5d.parquet
# =============================================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    import xgboost as xgb
except ImportError as exc:
    raise SystemExit("xgboost not installed") from exc


DEFAULT_DATASET = Path(__file__).resolve().parent / "factor_dataset_p1_5d.parquet"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "p1_walkforward_report.json"
OPT_VAL_RATIO = 0.20
OPT_ES_ROUNDS = 200
OPT_LR = 0.010
TRAIN_MIN_DATES = 120
TEST_WINDOW_DATES = 20
STEP_DATES = 20


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-min-dates", type=int, default=TRAIN_MIN_DATES)
    parser.add_argument("--test-window-dates", type=int, default=TEST_WINDOW_DATES)
    parser.add_argument("--step-dates", type=int, default=STEP_DATES)
    return parser.parse_args()


def spearman_corr(true_pct: np.ndarray, preds: np.ndarray) -> float:
    """Robust spearman corr that tolerates all-finite edge cases."""
    mask = np.isfinite(true_pct) & np.isfinite(preds)
    if mask.sum() < 2:
        return float("nan")
    truth = pd.Series(true_pct[mask])
    preds_series = pd.Series(preds[mask])
    return float(
        truth.rank(method="average").corr(preds_series.rank(method="average"), method="pearson")
    )


def prepare_features(df: pd.DataFrame) -> List[str]:
    excluded = {
        "date",
        "item_id",
        "target_3d",
        "target_5d",
        "target_8d",
        "target_rank_pct",
        "target_rank_label",
        "target_up_down_flat_label",
    }
    feature_cols = [c for c in df.columns if c not in excluded]
    if not feature_cols:
        raise ValueError("No feature columns detected.")
    return feature_cols


def build_dmatrix(frame: pd.DataFrame, feature_cols: List[str]) -> tuple:
    ordered = frame.sort_values(["date", "item_id"]).reset_index(drop=True)
    matrix = xgb.DMatrix(
        ordered[feature_cols],
        label=ordered["target_rank_label"],
        feature_names=feature_cols,
    )
    group_sizes = ordered.groupby("date", sort=False).size().tolist()
    if any(size < 2 for size in group_sizes):
        raise ValueError("Each date group must contain at least two items.")
    matrix.set_group(group_sizes)
    truth = ordered["target_rank_pct"].to_numpy()
    return matrix, truth


def make_windows(unique_dates: np.ndarray, train_min_dates: int, test_window_dates: int, step_dates: int) -> List[Dict]:
    windows: List[Dict] = []
    start = train_min_dates
    fold = 1
    while start + test_window_dates <= len(unique_dates):
        train_dates = unique_dates[:start]
        test_dates = unique_dates[start:start + test_window_dates]
        windows.append({
            "fold": fold,
            "train_dates": train_dates,
            "test_dates": test_dates,
        })
        fold += 1
        start += step_dates
    return windows


def run_walkforward(
    df: pd.DataFrame,
    feature_cols: List[str],
    train_min_dates: int,
    test_window_dates: int,
    step_dates: int,
) -> Dict:
    unique_dates = np.sort(df["date"].unique())
    windows = make_windows(unique_dates, train_min_dates, test_window_dates, step_dates)
    if not windows:
        raise RuntimeError("No valid walk-forward windows generated.")

    params = {
        "objective": "rank:ndcg",
        "eval_metric": "ndcg",
        "learning_rate": OPT_LR,
        "max_depth": 5,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
        "tree_method": "hist",
        "random_state": 42,
        "n_jobs": -1,
    }

    fold_results: List[Dict] = []
    all_spearmans: List[float] = []

    for window in windows:
        train_dates = window["train_dates"]
        test_dates = window["test_dates"]
        val_cut = int(len(train_dates) * (1 - OPT_VAL_RATIO))
        fit_dates = train_dates[:val_cut]
        val_dates = train_dates[val_cut:]

        train_df = df[df["date"].isin(fit_dates)].copy()
        val_df = df[df["date"].isin(val_dates)].copy()
        test_df = df[df["date"].isin(test_dates)].copy()

        dtrain, _ = build_dmatrix(train_df, feature_cols)
        dval, _ = build_dmatrix(val_df, feature_cols)
        dtest, truth_test = build_dmatrix(test_df, feature_cols)

        model = xgb.train(
            params=params,
            dtrain=dtrain,
            num_boost_round=950,
            evals=[(dtrain, "train"), (dval, "val")],
            early_stopping_rounds=OPT_ES_ROUNDS,
            verbose_eval=False,
        )

        best_iter = int(model.best_iteration)
        preds_test = model.predict(dtest, iteration_range=(0, best_iter + 1))
        sp = spearman_corr(truth_test, preds_test)
        all_spearmans.append(sp)

        fold_results.append({
            "fold": window["fold"],
            "train_start": str(pd.Timestamp(train_dates[0]).date()),
            "train_end": str(pd.Timestamp(train_dates[-1]).date()),
            "test_start": str(pd.Timestamp(test_dates[0]).date()),
            "test_end": str(pd.Timestamp(test_dates[-1]).date()),
            "best_iter": best_iter,
            "test_spearman": float(sp),
        })

        print(
            f"Fold {window['fold']}: "
            f"test {pd.Timestamp(test_dates[0]).date()} ~ {pd.Timestamp(test_dates[-1]).date()} "
            f"| best_iter={best_iter} | spearman={sp:.4f}"
        )

    sp_arr = np.array([s for s in all_spearmans if np.isfinite(s)])
    return {
        "config": {
            "train_min_dates": train_min_dates,
            "test_window_dates": test_window_dates,
            "step_dates": step_dates,
            "val_ratio": OPT_VAL_RATIO,
            "es": OPT_ES_ROUNDS,
            "lr": OPT_LR,
        },
        "fold_results": fold_results,
        "mean_test_spearman": float(np.mean(sp_arr)),
        "std_test_spearman": float(np.std(sp_arr, ddof=1)) if len(sp_arr) > 1 else 0.0,
        "n_folds": len(fold_results),
    }


def main() -> None:
    args = parse_args()
    if not args.dataset.exists():
        raise FileNotFoundError(f"Dataset not found: {args.dataset}")

    df = pd.read_parquet(args.dataset)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "item_id"]).reset_index(drop=True)
    feature_cols = prepare_features(df)

    print(f"加载数据: {args.dataset}")
    print(f"样本: {len(df):,}, 特征数: {len(feature_cols)}")

    report = run_walkforward(
        df,
        feature_cols,
        train_min_dates=args.train_min_dates,
        test_window_dates=args.test_window_dates,
        step_dates=args.step_dates,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("=" * 70)
    print(f"Walk-Forward mean spearman = {report['mean_test_spearman']:.4f} ± {report['std_test_spearman']:.4f}")
    print(f"报告: {args.output}")


if __name__ == "__main__":
    main()
