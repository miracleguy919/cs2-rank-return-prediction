#!/usr/bin/env python3
# =============================================================================
# 模块：P0.1 数据泄漏验证  [TBD]
# 文件：TBD/p0_validation.py
# 用途：验证当前 test spearman 0.059 是否为数据泄漏假象。
#       实现 Purged K-Fold（清除式交叉验证）+ DSR（衰减夏普比率）。
#       参考：Marcos López de Prado《Advances in Financial Machine Learning》
# 使用：python TBD/p0_validation.py
# =============================================================================

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

try:
    import xgboost as xgb
except ImportError as exc:
    raise SystemExit("xgboost not installed. Run: pip install xgboost") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path(__file__).resolve().parent / "factor_dataset.parquet"
DEFAULT_METRICS = Path(__file__).resolve().parent / "xgb_rank_metrics.json"
TARGET_LABEL_COL = "target_rank_label"
TARGET_HORIZON_DAYS = 8  # target_8d = 未来 8 天收益


# =============================================================================
# 1. Purged K-Fold（清除式交叉验证）
# =============================================================================

@dataclass
class PurgedSplit:
    """单个 fold 的训练/测试索引。"""
    train_idx: np.ndarray
    test_idx: np.ndarray
    fold_id: int
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    purged_count: int  # 被清除的训练样本数


def purged_kfold_dates(
    dates: np.ndarray,
    n_splits: int = 5,
    label_horizon: int = TARGET_HORIZON_DAYS,
    embargo_days: int = 2,
) -> List[PurgedSplit]:
    """按日期生成清除式 K-Fold 切分。

    核心思想：
    1. 把日期轴按时间顺序分成 K 个不重叠的 fold
    2. 对每个 fold 作为 test：
       - 从 train 中清除"标签窗口与 test 标签窗口重叠"的样本
       - 标签是未来 label_horizon 天收益，test 的第 t 天标签覆盖 [t, t+H]
       - train 中第 t' 天标签覆盖 [t', t'+H]，若与 [t_test, t_test+H] 重叠则清除
    3. 额外加 embargo（禁运期）：test 后再留 embargo_days 天不用于训练

    参数：
        dates: 排序后的唯一日期数组
        n_splits: fold 数
        label_horizon: 标签窗口天数（target_8d = 8）
        embargo_days: 禁运期天数
    """
    dates = pd.to_datetime(dates)
    n = len(dates)
    if n < n_splits * 3:
        raise ValueError(f"Need at least {n_splits*3} dates, got {n}")

    # 按 时间顺序均分 fold（每个 fold 是连续的日期段）
    fold_bounds = np.array_split(np.arange(n), n_splits)

    splits: List[PurgedSplit] = []

    for fold_id, test_indices in enumerate(fold_bounds):
        test_start = dates[test_indices.min()]
        test_end = dates[test_indices.max()]

        # 标签窗口扩展：test 样本的标签覆盖 [test_start, test_end + H]
        test_label_start = test_start
        test_label_end = test_end + pd.Timedelta(days=label_horizon)

        # embargo：test 后加禁运期
        embargo_end = test_label_end + pd.Timedelta(days=embargo_days)

        # 训练集 = 所有不在 test 段，且标签窗口不与 test 标签窗口重叠的样本
        train_mask = np.ones(n, dtype=bool)
        train_mask[test_indices] = False  # 排除 test 本身

        # 清除：train 样本 t'，若 [t', t'+H] 与 [test_label_start, embargo_end] 重叠
        purged_count = 0
        for i in range(n):
            if not train_mask[i]:
                continue
            t_prime = dates[i]
            t_prime_label_end = t_prime + pd.Timedelta(days=label_horizon)
            # 重叠判断：[t', t'+H] vs [test_label_start, embargo_end]
            if t_prime_label_end >= test_label_start and t_prime <= embargo_end:
                train_mask[i] = False
                purged_count += 1

        train_idx = np.where(train_mask)[0]
        # 转换日期索引为实际行索引在下面 main 中处理

        splits.append(PurgedSplit(
            train_idx=train_idx,  # 这里是日期级别的索引
            test_idx=test_indices,
            fold_id=fold_id,
            test_start=test_start,
            test_end=test_end,
            purged_count=purged_count,
        ))

    return splits


def map_date_idx_to_row_idx(
    df: pd.DataFrame, date_splits: List[PurgedSplit]
) -> List[PurgedSplit]:
    """把日期级别的索引映射为 DataFrame 行级别的索引。"""
    date_to_rows: Dict[pd.Timestamp, np.ndarray] = {}
    for ts, group in df.groupby("date"):
        date_to_rows[ts] = group.index.to_numpy()

    unique_dates = np.sort(df["date"].unique())
    row_splits: List[PurgedSplit] = []

    for split in date_splits:
        train_rows: List[int] = []
        for date_idx in split.train_idx:
            ts = unique_dates[date_idx]
            if ts in date_to_rows:
                train_rows.extend(date_to_rows[ts].tolist())

        test_rows: List[int] = []
        for date_idx in split.test_idx:
            ts = unique_dates[date_idx]
            if ts in date_to_rows:
                test_rows.extend(date_to_rows[ts].tolist())

        row_splits.append(PurgedSplit(
            train_idx=np.array(train_rows),
            test_idx=np.array(test_rows),
            fold_id=split.fold_id,
            test_start=split.test_start,
            test_end=split.test_end,
            purged_count=split.purged_count,
        ))

    return row_splits


# =============================================================================
# 2. DSR（Deflated Sharpe Ratio，衰减夏普比率）
# =============================================================================

def deflated_sharpe_ratio(
    sharpe_results: List[float],
    observed_sharpe: float,
    n_trials: int | None = None,
) -> Dict[str, float]:
    """计算衰减夏普比率（López de Prado 2014）。

    核心思想：当你做 N 次试验选最好的，最好的那个 Sharpe 有"运气成分"。
    DSR 把这个运气因素扣掉，看真实水平。

    公式：
        E[max(SR_n)] ≈ σ_SR * ((1-γ)*Φ^{-1}(1-1/N) + γ*Φ^{-1}(1-1/(N*e)))
        DSR = (SR_observed - E[max]) / σ_SR

    其中：
        γ = 欧拉常数 ≈ 0.5772
        σ_SR = Sharpe 的标准差
        N = 试验次数

    参数：
        sharpe_results: 所有试验的 Sharpe（或 spearman）列表
        observed_sharpe: 选中的最优 Sharpe
        n_trials: 试验次数（默认用 len(sharpe_results)）
    """
    from scipy.stats import norm

    if n_trials is None:
        n_trials = len(sharpe_results)

    sharpe_arr = np.array([s for s in sharpe_results if np.isfinite(s)])
    if len(sharpe_arr) < 2:
        return {
            "dsr": float("nan"),
            "e_max": float("nan"),
            "sigma_sr": float("nan"),
            "n_trials": n_trials,
            "verdict": "insufficient_data",
        }

    sigma_sr = float(np.std(sharpe_arr, ddof=1))
    gamma = 0.5772156649015329  # 欧拉常数
    e = np.e

    # 期望最大 Sharpe（Bailey & López de Prado 2014）
    # E[max] ≈ σ * ((1-γ)*Φ^{-1}(1-1/N) + γ*Φ^{-1}(1-1/(N*e)))
    if n_trials <= 1:
        e_max = 0.0
    else:
        term1 = (1 - gamma) * norm.ppf(1 - 1.0 / n_trials)
        term2 = gamma * norm.ppf(1 - 1.0 / (n_trials * e))
        e_max = sigma_sr * (term1 + term2)

    if sigma_sr < 1e-10:
        dsr = float("nan")
        verdict = "zero_variance"
    else:
        dsr = (observed_sharpe - e_max) / sigma_sr
        if dsr < 0:
            verdict = "LIKELY_ARTIFACT"  # 假象：观测值低于运气线
        elif dsr < 0.5:
            verdict = "MARGINAL"  # 边缘：略高于运气线
        else:
            verdict = "LIKELY_REAL"  # 真实：显著高于运气线

    return {
        "dsr": float(dsr),
        "e_max": float(e_max),
        "sigma_sr": sigma_sr,
        "n_trials": n_trials,
        "observed": float(observed_sharpe),
        "verdict": verdict,
    }


# =============================================================================
# 3. Purged K-Fold 训练评估
# =============================================================================

def prepare_features(df: pd.DataFrame) -> List[str]:
    excluded = {"date", "item_id", "target_8d", "target_rank_pct", TARGET_LABEL_COL}
    return [col for col in df.columns if col not in excluded]


def build_dmatrix_from_rows(
    df: pd.DataFrame, row_idx: np.ndarray, feature_cols: List[str]
) -> Tuple[xgb.DMatrix, np.ndarray]:
    """从行索引构建 DMatrix（带 group）。"""
    frame = df.iloc[row_idx].sort_values(["date", "item_id"]).reset_index(drop=True)
    if len(frame) == 0:
        raise ValueError("Empty frame passed to build_dmatrix_from_rows")

    matrix = xgb.DMatrix(
        frame[feature_cols],
        label=frame[TARGET_LABEL_COL],
        feature_names=feature_cols,
    )
    group_sizes = frame.groupby("date", sort=False).size().tolist()
    matrix.set_group(group_sizes)
    truth = frame["target_rank_pct"].to_numpy()
    return matrix, truth


def spearman_corr(true_pct: np.ndarray, preds: np.ndarray) -> float:
    mask = np.isfinite(true_pct) & np.isfinite(preds)
    if mask.sum() < 2:
        return float("nan")
    truth = pd.Series(true_pct[mask])
    preds_series = pd.Series(preds[mask])
    return float(truth.rank(method="average").corr(
        preds_series.rank(method="average"), method="pearson"
    ))


def run_purged_cv(
    df: pd.DataFrame,
    feature_cols: List[str],
    n_splits: int = 5,
    label_horizon: int = TARGET_HORIZON_DAYS,
    embargo_days: int = 2,
    params: Dict | None = None,
) -> Dict:
    """运行 Purged K-Fold 交叉验证。"""
    unique_dates = np.sort(df["date"].unique())
    print(f"\n{'='*70}")
    print(f"Purged K-Fold 交叉验证 (n_splits={n_splits}, horizon={label_horizon}d, embargo={embargo_days}d)")
    print(f"{'='*70}")
    print(f"总日期数: {len(unique_dates)}")
    print(f"日期范围: {unique_dates[0]} ~ {unique_dates[-1]}")
    print(f"总样本数: {len(df):,}")
    print(f"特征数: {len(feature_cols)}")

    # 生成日期级切分
    date_splits = purged_kfold_dates(
        unique_dates, n_splits=n_splits,
        label_horizon=label_horizon, embargo_days=embargo_days,
    )

    # 映射为行级切分
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

    for split in row_splits:
        print(f"\n--- Fold {split.fold_id + 1}/{n_splits} ---")
        print(f"  Test 区间: {split.test_start.date()} ~ {split.test_end.date()}")
        print(f"  Train 行数: {len(split.train_idx):,}")
        print(f"  Test 行数: {len(split.test_idx):,}")
        print(f"  清除样本数: {split.purged_count} 日期")

        # 从 train 切出 10% 作为 val（用于 early stopping）
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

        preds_test = model.predict(dtest, iteration_range=(0, model.best_iteration + 1))
        sp = spearman_corr(truth_test, preds_test)
        all_spearmans.append(sp)

        # 同时算 train spearman 看过拟合
        preds_train = model.predict(dtrain, iteration_range=(0, model.best_iteration + 1))
        sp_train = spearman_corr(truth_train, preds_train)

        result = {
            "fold": split.fold_id + 1,
            "test_start": str(split.test_start.date()),
            "test_end": str(split.test_end.date()),
            "train_rows": len(train_rows),
            "test_rows": len(split.test_idx),
            "purged_dates": split.purged_count,
            "test_spearman": sp,
            "train_spearman": sp_train,
            "best_iteration": int(model.best_iteration),
        }
        fold_results.append(result)
        print(f"  Test spearman: {sp:.4f}  (train: {sp_train:.4f}, best_iter: {model.best_iteration})")

    if not all_spearmans:
        return {"error": "No valid folds completed"}

    spearmans_arr = np.array([s for s in all_spearmans if np.isfinite(s)])
    summary = {
        "n_splits": n_splits,
        "label_horizon_days": label_horizon,
        "embargo_days": embargo_days,
        "fold_results": fold_results,
        "mean_test_spearman": float(np.mean(spearmans_arr)),
        "std_test_spearman": float(np.std(spearmans_arr, ddof=1)) if len(spearmans_arr) > 1 else 0.0,
        "min_test_spearman": float(np.min(spearmans_arr)),
        "max_test_spearman": float(np.max(spearmans_arr)),
        "current_reported_spearman": 0.059,  # 当前 train_xgb.py 报告的值
    }
    summary["abs_bias"] = abs(summary["mean_test_spearman"] - 0.059)
    return summary


# =============================================================================
# 4. DSR 检验（基于 grid search 历史）
# =============================================================================

def run_dsr_test(metrics_path: Path) -> Dict:
    """从 xgb_rank_metrics.json 读取 9 组 grid 结果，算 DSR。"""
    print(f"\n{'='*70}")
    print("DSR 检验（衰减夏普比率）")
    print(f"{'='*70}")

    with metrics_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    grid_results = data.get("grid_results", [])
    if not grid_results:
        return {"error": "No grid_results in metrics file"}

    # 收集 9 组的 test spearman
    test_spearmans = [r["metrics"]["test"]["spearman"] for r in grid_results]
    val_spearmans = [r["metrics"]["val"]["spearman"] for r in grid_results]

    print(f"9 组 grid test spearman:")
    for i, sp in enumerate(test_spearmans):
        print(f"  组{i}: {sp:.4f}")
    print(f"  均值: {np.mean(test_spearmans):.4f}")
    print(f"  标准差: {np.std(test_spearmans, ddof=1):.4f}")

    # 当前选中的是组2（val accuracy 最高），test spearman = 0.059
    observed = data["metrics"]["test"]["spearman"]
    print(f"\n当前选中（按 val accuracy）: test spearman = {observed:.4f}")

    # 用 test spearman 做 DSR
    dsr_result = deflated_sharpe_ratio(test_spearmans, observed, n_trials=len(test_spearmans))
    print(f"\nDSR 结果:")
    print(f"  期望最大 spearman（运气线）: {dsr_result['e_max']:.4f}")
    print(f"  观测 spearman: {dsr_result['observed']:.4f}")
    print(f"  DSR: {dsr_result['dsr']:.4f}")
    print(f"  判定: {dsr_result['verdict']}")

    # 补充：用 val spearman 也算一次（因为实际选择标准是 val）
    val_observed = data["metrics"]["val"]["spearman"]
    dsr_val = deflated_sharpe_ratio(val_spearmans, val_observed, n_trials=len(val_spearmans))

    return {
        "test_spearmans": test_spearmans,
        "val_spearmans": val_spearmans,
        "observed_test_spearman": observed,
        "dsr_test": dsr_result,
        "dsr_val": dsr_val,
    }


# =============================================================================
# 5. 主流程
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--label-horizon", type=int, default=TARGET_HORIZON_DAYS)
    parser.add_argument("--embargo-days", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "p0_validation_report.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.dataset.exists():
        raise FileNotFoundError(f"Dataset {args.dataset} not found. Run preprocess_xgb.py first.")

    print(f"加载数据集: {args.dataset}")
    df = pd.read_parquet(args.dataset)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "item_id"]).reset_index(drop=True)
    print(f"样本数: {len(df):,}, 日期数: {df['date'].nunique()}, 物品数: {df['item_id'].nunique()}")

    feature_cols = prepare_features(df)

    # Part 1: Purged K-Fold
    cv_summary = run_purged_cv(
        df, feature_cols,
        n_splits=args.n_splits,
        label_horizon=args.label_horizon,
        embargo_days=args.embargo_days,
    )

    # Part 2: DSR
    dsr_summary = run_dsr_test(args.metrics)

    # 汇总结论
    print(f"\n{'='*70}")
    print("P0.1 验证结论")
    print(f"{'='*70}")

    if "error" not in cv_summary:
        mean_sp = cv_summary["mean_test_spearman"]
        bias = cv_summary["abs_bias"]
        print(f"\n1. Purged K-Fold 验证:")
        print(f"   当前报告 spearman: 0.059")
        print(f"   Purged K-Fold 均值: {mean_sp:.4f}")
        print(f"   偏差: {bias:.4f}")
        if bias < 0.02:
            verdict_cv = "✅ 0.059 大概率真实（偏差 < 0.02）"
        elif bias < 0.04:
            verdict_cv = "⚠️ 0.059 部分真实（偏差 0.02-0.04，有轻微泄漏）"
        else:
            verdict_cv = "❌ 0.059 大概率是假象（偏差 > 0.04，有严重泄漏）"
        print(f"   判定: {verdict_cv}")

    if "error" not in dsr_summary:
        dsr_verdict = dsr_summary["dsr_test"]["verdict"]
        print(f"\n2. DSR 检验:")
        print(f"   判定: {dsr_verdict}")
        if "ARTIFACT" in dsr_verdict:
            verdict_dsr = "❌ 0.059 低于运气线，9 组选最好纯属运气"
        elif "MARGINAL" in dsr_verdict:
            verdict_dsr = "⚠️ 0.059 略高于运气线，但有运气成分"
        else:
            verdict_dsr = "✅ 0.059 显著高于运气线，真实有效"
        print(f"   说明: {verdict_dsr}")

    # 综合结论
    print(f"\n3. 综合结论:")
    if "error" not in cv_summary and "error" not in dsr_summary:
        if "ARTIFACT" in dsr_verdict or bias > 0.04:
            final = "❌ 0.059 大概率是假象，需重新设计实验"
        elif "MARGINAL" in dsr_verdict or bias > 0.02:
            final = "⚠️ 0.059 部分真实部分运气，谨慎继续"
        else:
            final = "✅ 0.059 大概率真实，可继续优化"
        print(f"   {final}")

    # 保存报告
    report = {
        "purged_cv": cv_summary,
        "dsr_test": dsr_summary,
        "verdict_cv": verdict_cv if "error" not in cv_summary else "ERROR",
        "verdict_dsr": verdict_dsr if "error" not in dsr_summary else "ERROR",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n报告已保存: {args.output}")


if __name__ == "__main__":
    main()
