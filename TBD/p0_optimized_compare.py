#!/usr/bin/env python3
# =============================================================================
# 模块：P0 优化后双盲对照  [TBD]
# 文件：TBD/p0_optimized_compare.py
# 用途：用最优配置（val=20%, es=200, lr=0.01）重跑 21 vs 199 因子对比
#       验证 P0.3 结论在优化后是否仍然成立
# 使用：python TBD/p0_optimized_compare.py
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
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "p0_optimized_compare_report.json"

# 最优配置（来自 p0_review.py）
OPT_VAL_RATIO = 0.20
OPT_ES_ROUNDS = 200
OPT_LR = 0.010


def prepare_all_features(df: pd.DataFrame) -> List[str]:
    excluded = {"date", "item_id", "target_8d", "target_rank_pct", "target_rank_label"}
    return [c for c in df.columns if c not in excluded]


def load_selected_factors(ic_report_path: Path) -> List[str]:
    with ic_report_path.open("r", encoding="utf-8") as f:
        return json.load(f).get("top_k_selected", [])


def run_optimized_purged_cv(
    df: pd.DataFrame,
    feature_cols: List[str],
    n_splits: int = 5,
) -> Dict:
    """用最优配置跑 Purged K-Fold。"""
    unique_dates = np.sort(df["date"].unique())
    print(f"\n{'='*70}")
    print(f"最优配置 Purged K-Fold (因子数={len(feature_cols)}, val={OPT_VAL_RATIO:.0%}, es={OPT_ES_ROUNDS}, lr={OPT_LR})")
    print(f"{'='*70}")

    date_splits = purged_kfold_dates(
        unique_dates, n_splits=n_splits,
        label_horizon=TARGET_HORIZON_DAYS, embargo_days=2,
    )
    row_splits = map_date_idx_to_row_idx(df, date_splits)

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
    importance_sum = pd.Series(0.0, index=feature_cols)

    for split in row_splits:
        print(f"\n--- Fold {split.fold_id + 1}/{n_splits} ---")
        print(f"  Test: {split.test_start.date()} ~ {split.test_end.date()}")

        train_df = df.iloc[split.train_idx].sort_values(["date", "item_id"])
        train_dates = np.sort(train_df["date"].unique())
        val_cut = int(len(train_dates) * (1 - OPT_VAL_RATIO))
        val_dates = train_dates[val_cut:]
        train_dates_final = train_dates[:val_cut]

        train_rows = train_df[train_df["date"].isin(train_dates_final)].index.to_numpy()
        val_rows = train_df[train_df["date"].isin(val_dates)].index.to_numpy()

        try:
            dtrain, _ = build_dmatrix_from_rows(df, train_rows, feature_cols)
            dval, _ = build_dmatrix_from_rows(df, val_rows, feature_cols)
            dtest, truth_test = build_dmatrix_from_rows(df, split.test_idx, feature_cols)
        except ValueError:
            continue

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

        scores = model.get_score(importance_type="gain")
        for f in feature_cols:
            importance_sum[f] += scores.get(f, 0.0)

        result = {
            "fold": split.fold_id + 1,
            "test_start": str(split.test_start.date()),
            "test_end": str(split.test_end.date()),
            "val_days": len(val_dates),
            "best_iter": best_iter,
            "test_spearman": sp,
        }
        fold_results.append(result)
        print(f"  best_iter: {best_iter}, spearman: {sp:.4f}")

    spearmans_arr = np.array([s for s in all_spearmans if np.isfinite(s)])
    importance_avg = (importance_sum / max(len(all_spearmans), 1)).sort_values(ascending=False)

    return {
        "n_features": len(feature_cols),
        "val_ratio": OPT_VAL_RATIO,
        "early_stopping_rounds": OPT_ES_ROUNDS,
        "learning_rate": OPT_LR,
        "fold_results": fold_results,
        "mean_test_spearman": float(np.mean(spearmans_arr)),
        "std_test_spearman": float(np.std(spearmans_arr, ddof=1)),
        "feature_importance_gain": importance_avg.to_dict(),
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
    print(f"样本: {len(df):,} 行")

    all_features = prepare_all_features(df)
    selected = [f for f in load_selected_factors(args.ic_report) if f in df.columns]
    print(f"\n全量因子: {len(all_features)}, 筛选因子: {len(selected)}")

    # === 实验 1: 199 因子 + 最优配置 ===
    print(f"\n{'#'*70}")
    print(f"# 实验 1: 199 因子 + 最优配置")
    print(f"{'#'*70}")
    result_all = run_optimized_purged_cv(df, all_features)

    # === 实验 2: 21 因子 + 最优配置 ===
    print(f"\n{'#'*70}")
    print(f"# 实验 2: 21 因子 + 最优配置")
    print(f"{'#'*70}")
    result_sel = run_optimized_purged_cv(df, selected)

    # === 对比 ===
    sp_all = result_all["mean_test_spearman"]
    sp_sel = result_sel["mean_test_spearman"]
    diff = sp_sel - sp_all

    print(f"\n{'='*70}")
    print("优化后对比结论")
    print(f"{'='*70}")
    print(f"\n  199 因子: spearman = {sp_all:.4f} ± {result_all['std_test_spearman']:.4f}")
    print(f"  21 因子:  spearman = {sp_sel:.4f} ± {result_sel['std_test_spearman']:.4f}")
    print(f"  差异: {diff:+.4f}")

    # 与原配置对比
    print(f"\n  与 P0.3 原配置对比:")
    print(f"    原配置 (val10% es80):     199因子=0.0104, 21因子=0.0313, 差异=+0.0209")
    print(f"    最优配置 (val20% es200 lr0.01): 199因子={sp_all:.4f}, 21因子={sp_sel:.4f}, 差异={diff:+.4f}")

    if diff > 0.005:
        verdict = f"✅ 优化后 21 因子仍优于 199 因子 (+{diff:.4f})"
    elif diff > -0.005:
        verdict = f"⚠️ 优化后两者持平，21 因子简化模型仍合理"
    else:
        verdict = f"❌ 优化后 21 因子反而下降 ({diff:+.4f})，可能丢失了非线性信号"

    print(f"\n  判定: {verdict}")

    # Feature importance
    fi = pd.Series(result_sel["feature_importance_gain"]).sort_values(ascending=False)
    print(f"\n  优化后 21 因子模型 Feature Importance Top 5 (gain):")
    for i, (f, s) in enumerate(fi.head(5).items(), 1):
        print(f"    {i}. {f:<35} gain={s:.2f}")

    # 保存
    report = {
        "config": {"val_ratio": OPT_VAL_RATIO, "es": OPT_ES_ROUNDS, "lr": OPT_LR},
        "result_all_199": result_all,
        "result_selected_21": result_sel,
        "comparison": {
            "spearman_199": sp_all,
            "spearman_21": sp_sel,
            "diff": diff,
            "verdict": verdict,
            "vs_original": {
                "original_199": 0.0104, "original_21": 0.0313, "original_diff": 0.0209,
                "optimized_199": sp_all, "optimized_21": sp_sel, "optimized_diff": diff,
            },
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n报告: {args.output}")


if __name__ == "__main__":
    main()
