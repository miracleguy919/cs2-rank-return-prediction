#!/usr/bin/env python3
# =============================================================================
# 模块：P0.5 统计显著性检验（修复审查问题 3）  [TBD]
# 文件：TBD/p0_statistical_test.py
# 用途：
#   1. Paired t-test: 5 折 21 vs 199 因子的配对差异显著性
#   2. Wilcoxon 符号检验: 非参数版本（小样本更稳健）
#   3. 多随机种子实验: 验证 21 因子优势是否稳定（不依赖 random_state=42）
# 使用：python TBD/p0_statistical_test.py
# =============================================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Windows GBK 终端兼容：强制 stdout/stderr 用 utf-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import numpy as np
import pandas as pd
from scipy.stats import ttest_rel, wilcoxon

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
DEFAULT_PRIOR_REPORT = Path(__file__).resolve().parent / "p0_factor_selection_report.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "p0_statistical_test_report.json"

TARGET_LABEL_COL = "target_rank_label"

# 5 个随机种子（包含原 42）
RANDOM_SEEDS = [42, 0, 7, 13, 2024]

# 用 P0.4 推荐的最优配置（避免 best_iter=0 问题）
OPT_VAL_RATIO = 0.20
OPT_ES_ROUNDS = 200
OPT_LR = 0.010


def prepare_all_features(df: pd.DataFrame) -> List[str]:
    excluded = {"date", "item_id", "target_8d", "target_rank_pct", TARGET_LABEL_COL}
    return [c for c in df.columns if c not in excluded]


def load_selected_factors(ic_report_path: Path) -> List[str]:
    with ic_report_path.open("r", encoding="utf-8") as f:
        return json.load(f).get("top_k_selected", [])


# =============================================================================
# 1. Paired t-test (基于 P0.3 已有的 5 折结果，无需重训)
# =============================================================================

def paired_tests_on_prior_report(prior_report_path: Path) -> Dict:
    """从 P0.3 已有报告读取 5 折 spearman，做配对检验。"""
    print(f"\n{'='*70}")
    print("Part 1: 基于 P0.3 已有 5 折结果的配对统计检验")
    print(f"{'='*70}")

    with prior_report_path.open("r", encoding="utf-8") as f:
        report = json.load(f)

    sp_all = [fr["test_spearman"] for fr in report["experiment_all_features"]["fold_results"]]
    sp_sel = [fr["test_spearman"] for fr in report["experiment_selected_features"]["fold_results"]]
    diffs = [s - a for s, a in zip(sp_sel, sp_all)]

    print(f"\n  Fold-by-fold 对比 (21因子 - 199因子):")
    print(f"  {'Fold':<6} {'199因子':>12} {'21因子':>12} {'差异':>12}")
    for i, (a, s, d) in enumerate(zip(sp_all, sp_sel, diffs), 1):
        sign = "+" if d >= 0 else ""
        print(f"  {i:<6} {a:>12.4f} {s:>12.4f} {sign}{d:>11.4f}")

    mean_diff = float(np.mean(diffs))
    std_diff = float(np.std(diffs, ddof=1))
    n = len(diffs)

    # Paired t-test (H0: mean_diff = 0)
    t_stat, p_value_t = ttest_rel(sp_sel, sp_all)

    # Wilcoxon signed-rank (非参数版本，小样本更稳健)
    try:
        w_stat, p_value_w = wilcoxon(diffs)
        wilcoxon_ok = True
    except ValueError as e:
        # Wilcoxon 在所有差异同号时会报错
        w_stat, p_value_w = float("nan"), float("nan")
        wilcoxon_ok = False
        wilcoxon_err = str(e)

    # 效应量 (Cohen's d for paired)
    cohens_d = mean_diff / std_diff if std_diff > 1e-10 else float("nan")

    # 21 因子胜率
    win_rate = float(np.mean(np.array(diffs) > 0))

    print(f"\n  配对 t-test:")
    print(f"    mean_diff = {mean_diff:+.4f}, std_diff = {std_diff:.4f}")
    print(f"    t-statistic = {t_stat:.4f}, p-value = {p_value_t:.4f}")
    print(f"    Cohen's d (效应量) = {cohens_d:.4f}")
    print(f"\n  Wilcoxon signed-rank (非参数):")
    if wilcoxon_ok:
        print(f"    W = {w_stat:.4f}, p-value = {p_value_w:.4f}")
    else:
        print(f"    失败: {wilcoxon_err}")
    print(f"\n  21 因子胜率: {win_rate:.0%} ({int(sum(d > 0 for d in diffs))}/{n})")

    # 判定
    if p_value_t < 0.05 and win_rate >= 0.8:
        verdict = "✅ 21 因子显著优于 199 因子 (p<0.05 且胜率≥80%)"
    elif p_value_t < 0.10 or win_rate >= 0.6:
        verdict = "⚠️ 21 因子略优 (p<0.10 或胜率≥60%)，但样本小需谨慎"
    else:
        verdict = "❌ 21 因子优势不显著 (p≥0.10 且胜率<60%)"

    print(f"\n  判定: {verdict}")

    return {
        "n_folds": n,
        "sp_199": sp_all,
        "sp_21": sp_sel,
        "diffs": diffs,
        "mean_diff": mean_diff,
        "std_diff": std_diff,
        "paired_t": {"t_stat": float(t_stat), "p_value": float(p_value_t)},
        "wilcoxon": {"w_stat": float(w_stat), "p_value": float(p_value_w)} if wilcoxon_ok else {"error": wilcoxon_err},
        "cohens_d": cohens_d,
        "win_rate": win_rate,
        "verdict": verdict,
    }


# =============================================================================
# 2. 多随机种子实验 (重训 5 个种子)
# =============================================================================

def run_one_seed(
    df: pd.DataFrame,
    feature_cols: List[str],
    seed: int,
    n_splits: int = 5,
) -> Dict:
    """跑一个随机种子的 5 折 Purged K-Fold。"""
    unique_dates = np.sort(df["date"].unique())
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
        "random_state": seed,
        "n_jobs": -1,
    }

    fold_spearmans: List[float] = []
    for split in row_splits:
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

        preds = model.predict(dtest, iteration_range=(0, int(model.best_iteration) + 1))
        sp = spearman_corr(truth_test, preds)
        fold_spearmans.append(sp)

    arr = np.array([s for s in fold_spearmans if np.isfinite(s)])
    return {
        "seed": seed,
        "fold_spearmans": fold_spearmans,
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
    }


def multi_seed_experiment(df: pd.DataFrame, all_features: List[str], selected: List[str]) -> Dict:
    """5 个随机种子下对比 21 vs 199 因子。"""
    print(f"\n{'='*70}")
    print(f"Part 2: 多随机种子实验 ({len(RANDOM_SEEDS)} 种子, 配置: val={OPT_VAL_RATIO:.0%}, es={OPT_ES_ROUNDS}, lr={OPT_LR})")
    print(f"{'='*70}")

    seed_results: List[Dict] = []
    for seed in RANDOM_SEEDS:
        print(f"\n--- Seed = {seed} ---")
        print(f"  跑 199 因子...")
        r_all = run_one_seed(df, all_features, seed)
        print(f"  199 因子: mean={r_all['mean']:.4f} ± {r_all['std']:.4f}")

        print(f"  跑 21 因子...")
        r_sel = run_one_seed(df, selected, seed)
        print(f"  21 因子: mean={r_sel['mean']:.4f} ± {r_sel['std']:.4f}")

        diff = r_sel["mean"] - r_all["mean"]
        print(f"  差异: {diff:+.4f}")

        seed_results.append({
            "seed": seed,
            "sp_199": r_all,
            "sp_21": r_sel,
            "diff": diff,
            "21_wins": diff > 0,
        })

    # 跨种子汇总
    diffs = [r["diff"] for r in seed_results]
    sp_21_means = [r["sp_21"]["mean"] for r in seed_results]
    sp_199_means = [r["sp_199"]["mean"] for r in seed_results]

    mean_diff_across_seeds = float(np.mean(diffs))
    std_diff_across_seeds = float(np.std(diffs, ddof=1))
    win_rate_seeds = float(np.mean([d > 0 for d in diffs]))

    # 跨种子配对 t-test
    t_stat, p_value = ttest_rel(sp_21_means, sp_199_means)

    print(f"\n{'='*70}")
    print("跨种子汇总")
    print(f"{'='*70}")
    print(f"\n  {'Seed':<8} {'199因子':>12} {'21因子':>12} {'差异':>12} {'21胜?':>8}")
    for r in seed_results:
        sign = "+" if r["diff"] >= 0 else ""
        print(f"  {r['seed']:<8} {r['sp_199']['mean']:>12.4f} {r['sp_21']['mean']:>12.4f} {sign}{r['diff']:>11.4f} {'✓' if r['21_wins'] else '✗':>8}")

    print(f"\n  跨种子统计:")
    print(f"    21 因子 mean of means: {np.mean(sp_21_means):.4f} ± {np.std(sp_21_means, ddof=1):.4f}")
    print(f"    199 因子 mean of means: {np.mean(sp_199_means):.4f} ± {np.std(sp_199_means, ddof=1):.4f}")
    print(f"    差异 mean: {mean_diff_across_seeds:+.4f} ± {std_diff_across_seeds:.4f}")
    print(f"    21 因子胜率: {win_rate_seeds:.0%} ({int(sum(d > 0 for d in diffs))}/{len(diffs)})")
    print(f"    跨种子配对 t-test: t={t_stat:.4f}, p={p_value:.4f}")

    if p_value < 0.05 and win_rate_seeds >= 0.8:
        verdict = "✅ 21 因子优势在多随机种子下稳定 (p<0.05, 胜率≥80%)"
    elif win_rate_seeds >= 0.6:
        verdict = f"⚠️ 21 因子优势方向稳定 (胜率 {win_rate_seeds:.0%})，但 p={p_value:.4f} 不显著 (样本小)"
    else:
        verdict = "❌ 21 因子优势不稳定，依赖随机种子"

    print(f"\n  判定: {verdict}")

    return {
        "seeds": RANDOM_SEEDS,
        "config": {"val_ratio": OPT_VAL_RATIO, "es": OPT_ES_ROUNDS, "lr": OPT_LR},
        "seed_results": seed_results,
        "summary": {
            "mean_diff": mean_diff_across_seeds,
            "std_diff": std_diff_across_seeds,
            "win_rate": win_rate_seeds,
            "paired_t": {"t_stat": float(t_stat), "p_value": float(p_value)},
            "sp_21_mean_of_means": float(np.mean(sp_21_means)),
            "sp_21_std_of_means": float(np.std(sp_21_means, ddof=1)),
            "sp_199_mean_of_means": float(np.mean(sp_199_means)),
            "sp_199_std_of_means": float(np.std(sp_199_means, ddof=1)),
        },
        "verdict": verdict,
    }


# =============================================================================
# 主流程
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--ic-report", type=Path, default=DEFAULT_IC_REPORT)
    parser.add_argument("--prior-report", type=Path, default=DEFAULT_PRIOR_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-multi-seed", action="store_true",
                        help="跳过多随机种子实验（节省时间，只跑配对检验）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.prior_report.exists():
        raise FileNotFoundError(f"Prior report {args.prior_report} not found. Run p0_factor_selection.py first.")

    # Part 1: 配对检验（基于 P0.3 已有结果，秒级）
    paired_result = paired_tests_on_prior_report(args.prior_report)

    # Part 2: 多随机种子实验
    if args.skip_multi_seed:
        print("\n跳过多随机种子实验 (--skip-multi-seed)")
        multi_seed_result = {"skipped": True}
    else:
        if not args.dataset.exists():
            raise FileNotFoundError(f"Dataset {args.dataset} not found.")
        if not args.ic_report.exists():
            raise FileNotFoundError(f"IC report {args.ic_report} not found.")

        print(f"\n加载数据集: {args.dataset}")
        df = pd.read_parquet(args.dataset)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["date", "item_id"]).reset_index(drop=True)
        print(f"样本: {len(df):,} 行")

        all_features = prepare_all_features(df)
        selected = [f for f in load_selected_factors(args.ic_report) if f in df.columns]
        print(f"全量因子: {len(all_features)}, 筛选因子: {len(selected)}")

        multi_seed_result = multi_seed_experiment(df, all_features, selected)

    # 综合判定
    print(f"\n{'='*70}")
    print("P0.5 统计显著性检验 - 综合结论")
    print(f"{'='*70}")
    print(f"\n  Part 1 (配对检验, n=5 折):")
    print(f"    {paired_result['verdict']}")
    if not multi_seed_result.get("skipped"):
        print(f"\n  Part 2 (多随机种子, n={len(RANDOM_SEEDS)} 种子):")
        print(f"    {multi_seed_result['verdict']}")

    # 保存
    report = {
        "part1_paired_test": paired_result,
        "part2_multi_seed": multi_seed_result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n报告: {args.output}")


if __name__ == "__main__":
    main()
