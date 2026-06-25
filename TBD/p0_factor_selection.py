#!/usr/bin/env python3
# =============================================================================
# 模块：P0.3 因子选择验证 + Feature Importance  [TBD]
# 文件：TBD/p0_factor_selection.py
# 用途：
#   1. 用 P0.2 选出的 21 个因子训练 XGBoost
#   2. 在 Purged K-Fold 下对比 199 因子 vs 21 因子的 spearman
#   3. 输出 XGBoost feature_importance 排名（替代 neuralforecast TFT）
#   4. 综合给出最终因子推荐清单
# 使用：python TBD/p0_factor_selection.py
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
    raise SystemExit("xgboost not installed. Run: pip install xgboost") from exc

# 复用 P0.1 的 Purged K-Fold 实现
from p0_validation import (
    PurgedSplit,
    purged_kfold_dates,
    map_date_idx_to_row_idx,
    build_dmatrix_from_rows,
    spearman_corr,
    TARGET_HORIZON_DAYS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path(__file__).resolve().parent / "factor_dataset.parquet"
DEFAULT_IC_REPORT = Path(__file__).resolve().parent / "p0_ic_report.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "p0_factor_selection_report.json"

TARGET_LABEL_COL = "target_rank_label"


def prepare_all_features(df: pd.DataFrame) -> List[str]:
    excluded = {"date", "item_id", "target_8d", "target_rank_pct", TARGET_LABEL_COL}
    return [c for c in df.columns if c not in excluded]


def load_selected_factors(ic_report_path: Path) -> List[str]:
    """从 P0.2 报告加载筛选后的因子列表。"""
    with ic_report_path.open("r", encoding="utf-8") as f:
        report = json.load(f)
    return report.get("top_k_selected", [])


# =============================================================================
# Purged K-Fold 训练 + Feature Importance
# =============================================================================

def run_purged_cv_with_importance(
    df: pd.DataFrame,
    feature_cols: List[str],
    n_splits: int = 5,
    label_horizon: int = TARGET_HORIZON_DAYS,
    embargo_days: int = 2,
    params: Dict | None = None,
) -> Dict:
    """Purged K-Fold 训练，同时收集 feature importance。"""
    unique_dates = np.sort(df["date"].unique())
    print(f"\n{'='*70}")
    print(f"Purged K-Fold (因子数={len(feature_cols)}, n_splits={n_splits})")
    print(f"{'='*70}")

    date_splits = purged_kfold_dates(
        unique_dates, n_splits=n_splits,
        label_horizon=label_horizon, embargo_days=embargo_days,
    )
    row_splits = map_date_idx_to_row_idx(df, date_splits)

    if params is None:
        params = {
            "objective": "rank:ndcg",
            "eval_metric": "ndcg",
            "learning_rate": 0.018,
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
        val_cut = int(len(train_dates) * 0.9)
        val_dates = train_dates[val_cut:]
        train_dates_final = train_dates[:val_cut]

        train_rows = train_df[train_df["date"].isin(train_dates_final)].index.to_numpy()
        val_rows = train_df[train_df["date"].isin(val_dates)].index.to_numpy()

        try:
            dtrain, truth_train = build_dmatrix_from_rows(df, train_rows, feature_cols)
            dval, truth_val = build_dmatrix_from_rows(df, val_rows, feature_cols)
            dtest, truth_test = build_dmatrix_from_rows(df, split.test_idx, feature_cols)
        except ValueError as e:
            print(f"  ⚠️ 跳过: {e}")
            continue

        model = xgb.train(
            params=params,
            dtrain=dtrain,
            num_boost_round=950,
            evals=[(dtrain, "train"), (dval, "val")],
            early_stopping_rounds=80,
            verbose_eval=False,
        )

        best_iter = int(model.best_iteration)
        preds_test = model.predict(dtest, iteration_range=(0, best_iter + 1))
        sp = spearman_corr(truth_test, preds_test)
        all_spearmans.append(sp)

        # 累加 feature importance
        scores = model.get_score(importance_type="gain")
        for f in feature_cols:
            importance_sum[f] += scores.get(f, 0.0)

        result = {
            "fold": split.fold_id + 1,
            "test_start": str(split.test_start.date()),
            "test_end": str(split.test_end.date()),
            "test_rows": len(split.test_idx),
            "test_spearman": sp,
            "best_iteration": best_iter,
        }
        fold_results.append(result)
        print(f"  Test spearman: {sp:.4f}  (best_iter: {best_iter})")

    if not all_spearmans:
        return {"error": "No valid folds"}

    spearmans_arr = np.array([s for s in all_spearmans if np.isfinite(s)])
    importance_avg = (importance_sum / len(all_spearmans)).sort_values(ascending=False)

    return {
        "n_splits": n_splits,
        "n_features": len(feature_cols),
        "fold_results": fold_results,
        "mean_test_spearman": float(np.mean(spearmans_arr)),
        "std_test_spearman": float(np.std(spearmans_arr, ddof=1)) if len(spearmans_arr) > 1 else 0.0,
        "min_test_spearman": float(np.min(spearmans_arr)),
        "max_test_spearman": float(np.max(spearmans_arr)),
        "feature_importance_gain": importance_avg.to_dict(),
    }


# =============================================================================
# 主流程
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--ic-report", type=Path, default=DEFAULT_IC_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--n-splits", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.dataset.exists():
        raise FileNotFoundError(f"Dataset {args.dataset} not found.")
    if not args.ic_report.exists():
        raise FileNotFoundError(f"IC report {args.ic_report} not found. Run p0_ic_analysis.py first.")

    print(f"加载数据集: {args.dataset}")
    df = pd.read_parquet(args.dataset)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "item_id"]).reset_index(drop=True)
    print(f"样本: {len(df):,} 行")

    all_features = prepare_all_features(df)
    selected_features = load_selected_factors(args.ic_report)

    # 防御：过滤掉不在 df 中的因子
    selected_features = [f for f in selected_features if f in df.columns]
    print(f"\n全量因子数: {len(all_features)}")
    print(f"P0.2 筛选因子数: {len(selected_features)}")

    # === 实验 1: 全量 199 因子 ===
    print(f"\n{'#'*70}")
    print(f"# 实验 1: 全量 {len(all_features)} 因子 (baseline)")
    print(f"{'#'*70}")
    result_all = run_purged_cv_with_importance(df, all_features, n_splits=args.n_splits)

    # === 实验 2: P0.2 筛选 21 因子 ===
    print(f"\n{'#'*70}")
    print(f"# 实验 2: P0.2 筛选 {len(selected_features)} 因子")
    print(f"{'#'*70}")
    result_selected = run_purged_cv_with_importance(df, selected_features, n_splits=args.n_splits)

    # === 对比与结论 ===
    print(f"\n{'='*70}")
    print("P0.3 对比结论")
    print(f"{'='*70}")

    if "error" in result_all or "error" in result_selected:
        print("  ❌ 实验失败")
        return

    sp_all = result_all["mean_test_spearman"]
    sp_sel = result_selected["mean_test_spearman"]
    diff = sp_sel - sp_all

    print(f"\n  全量 {len(all_features)} 因子: spearman = {sp_all:.4f} ± {result_all['std_test_spearman']:.4f}")
    print(f"  筛选 {len(selected_features)} 因子: spearman = {sp_sel:.4f} ± {result_selected['std_test_spearman']:.4f}")
    print(f"  差异: {diff:+.4f}")

    if diff > 0.005:
        verdict = f"✅ 筛选有效：21 因子比 199 因子提升 {diff:+.4f}，因子选择成功"
    elif diff > -0.005:
        verdict = f"⚠️ 筛选中性：21 因子与 199 因子持平，因子选择未带来明显提升但简化了模型"
    else:
        verdict = f"❌ 筛选反而下降 {diff:+.4f}：可能丢失了 XGBoost 能利用的非线性组合信号"

    print(f"\n  判定: {verdict}")

    # Feature importance Top 10
    fi = result_selected["feature_importance_gain"]
    fi_series = pd.Series(fi).sort_values(ascending=False)
    print(f"\n  XGBoost Feature Importance Top 10 (gain, 21因子模型):")
    for i, (factor, score) in enumerate(fi_series.head(10).items(), 1):
        print(f"    {i:>2}. {factor:<35} gain={score:.2f}")

    # 保存报告
    report = {
        "experiment_all_features": result_all,
        "experiment_selected_features": result_selected,
        "comparison": {
            "spearman_all": sp_all,
            "spearman_selected": sp_sel,
            "diff": diff,
            "verdict": verdict,
        },
        "top_10_importance_in_selected": fi_series.head(10).to_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n报告已保存: {args.output}")

    # 最终结论
    print(f"\n{'='*70}")
    print("P0 阶段总结 (P0.1 + P0.2 + P0.3)")
    print(f"{'='*70}")
    print(f"""
  P0.1 Purged K-Fold 验证:
    - 原 0.059 是数据泄漏假象，真实 spearman ≈ 0.01
    - DSR 通过（9 组间方差真实），但绝对值虚高

  P0.2 IC 分析:
    - 199 因子 → 21 因子（去冗余后）
    - Top 因子: alpha040_lag15, mfi_14_lag15, adx_14_lag0
    - 176/199 p<0.05 暗示多重共线性严重

  P0.3 因子选择验证:
    - 全量 199 因子 spearman: {sp_all:.4f}
    - 筛选 21 因子 spearman: {sp_sel:.4f}
    - {verdict}

  下一步建议:
    1. 无论 21 vs 199 哪个更好，spearman 都很低（~0.01-0.05）
    2. 真正问题在数据/标签设计，不在因子数:
       - target_8d 可能信号噪比太低
       - 试试 target_3d / target_5d（短期更可预测）
       - 试试分类标签（涨/跌/平）替代回归
    3. 进入 P1: 重新设计标签 + 走 Walk-Forward 验证""")


if __name__ == "__main__":
    main()
