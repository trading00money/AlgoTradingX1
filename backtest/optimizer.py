"""
Backtest Optimizer Module
Strategy parameter optimization using grid search and genetic algorithms
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Callable
from loguru import logger
from itertools import product
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from datetime import datetime


class StrategyOptimizer:
    """
    Optimizer for trading strategy parameters.
    Supports grid search, random search, and genetic algorithm optimization.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize the optimizer.
        
        Args:
            config: Optimizer configuration dictionary
        """
        self.config = config
        self.optimizer_config = config.get('optimizer_config', {})
        self.method = self.optimizer_config.get('method', 'grid_search')
        self.metric = self.optimizer_config.get('optimization_metric', 'sharpe_ratio')
        self.max_workers = self.optimizer_config.get('max_workers', 4)
        
        self.results_history = []
        logger.info(f"StrategyOptimizer initialized with method: {self.method}")
    
    def grid_search(
        self,
        param_grid: Dict[str, List],
        objective_func: Callable,
        **kwargs
    ) -> Tuple[Dict, float]:
        """
        Perform grid search optimization.
        
        Args:
            param_grid: Dictionary of parameters and their possible values
            objective_func: Function to optimize (higher is better)
            **kwargs: Additional arguments passed to objective_func
            
        Returns:
            Tuple of (best_params, best_score)
        """
        logger.info(f"Starting grid search with {self._count_combinations(param_grid)} combinations")
        
        # Generate all combinations
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combinations = list(product(*param_values))
        
        best_params = None
        best_score = float('-inf')
        
        for combo in combinations:
            params = dict(zip(param_names, combo))
            
            try:
                score = objective_func(params, **kwargs)
                
                self.results_history.append({
                    'params': params.copy(),
                    'score': score,
                    'timestamp': datetime.now().isoformat()
                })
                
                if score > best_score:
                    best_score = score
                    best_params = params.copy()
                    logger.info(f"New best: {best_score:.4f} with params: {best_params}")
                    
            except Exception as e:
                logger.warning(f"Error evaluating params {params}: {e}")
                continue
        
        logger.success(f"Grid search complete. Best score: {best_score:.4f}")
        return best_params, best_score
    
    def random_search(
        self,
        param_distributions: Dict[str, Tuple],
        objective_func: Callable,
        n_iter: int = 100,
        **kwargs
    ) -> Tuple[Dict, float]:
        """
        Perform random search optimization.
        
        Args:
            param_distributions: Dictionary of parameters and their (min, max) ranges
            objective_func: Function to optimize (higher is better)
            n_iter: Number of random iterations
            **kwargs: Additional arguments passed to objective_func
            
        Returns:
            Tuple of (best_params, best_score)
        """
        logger.info(f"Starting random search with {n_iter} iterations")
        
        best_params = None
        best_score = float('-inf')
        
        for i in range(n_iter):
            # Generate random params
            params = {}
            for name, (min_val, max_val) in param_distributions.items():
                if isinstance(min_val, int) and isinstance(max_val, int):
                    params[name] = np.random.randint(min_val, max_val + 1)
                else:
                    params[name] = np.random.uniform(min_val, max_val)
            
            try:
                score = objective_func(params, **kwargs)
                
                self.results_history.append({
                    'params': params.copy(),
                    'score': score,
                    'iteration': i,
                    'timestamp': datetime.now().isoformat()
                })
                
                if score > best_score:
                    best_score = score
                    best_params = params.copy()
                    logger.info(f"Iteration {i}: New best: {best_score:.4f}")
                    
            except Exception as e:
                logger.warning(f"Error at iteration {i}: {e}")
                continue
        
        logger.success(f"Random search complete. Best score: {best_score:.4f}")
        return best_params, best_score
    
    def walk_forward_optimize(
        self,
        price_data: pd.DataFrame,
        param_grid: Dict[str, List],
        backtest_func: Callable,
        train_period: int = 6048,  # 1 year of 1H bars (252 days × 24 bars)
        test_period: int = 1512,   # 3 months of 1H bars (63 days × 24 bars)
        **kwargs
    ) -> List[Dict]:
        """
        Walk-forward optimization for out-of-sample testing.

        Args:
            price_data: Full price history.
            param_grid: Parameters to optimize.
            backtest_func: Backtesting function.
            train_period: Training window in bars. Default 6048 = 1 year of 1H bars
                (252 trading days × 24 bars/day). For daily data use 252.
            test_period: Out-of-sample test window in bars. Default 1512 = 3 months
                of 1H bars (63 trading days × 24 bars/day). For daily data use 63.

        Returns:
            List of optimization results for each walk-forward period, each
            containing train_start, train_end, test_start, test_end,
            best_params, train_score, and test_score.

        Note:
            The ratio of train_score / test_score across all periods is a key
            robustness indicator. A healthy strategy shows test_score / train_score
            >= 0.6 consistently. Ratios below 0.4 indicate overfitting.
        """
        logger.info("Starting walk-forward optimization")
        
        results = []
        total_bars = len(price_data)
        current_start = 0
        
        while current_start + train_period + test_period <= total_bars:
            train_end = current_start + train_period
            test_end = train_end + test_period
            
            # Split data
            train_data = price_data.iloc[current_start:train_end]
            test_data = price_data.iloc[train_end:test_end]
            
            # Optimize on training data
            def train_objective(params):
                return backtest_func(train_data, params, **kwargs)
            
            best_params, train_score = self.grid_search(param_grid, train_objective)
            
            # Test on out-of-sample data
            test_score = backtest_func(test_data, best_params, **kwargs)
            
            results.append({
                'train_start': train_data.index[0],
                'train_end': train_data.index[-1],
                'test_start': test_data.index[0],
                'test_end': test_data.index[-1],
                'best_params': best_params,
                'train_score': train_score,
                'test_score': test_score
            })
            
            efficiency = test_score / train_score if train_score > 0 else float('nan')
            logger.info(
                f"Period {len(results)}: Train={train_score:.4f}  "
                f"Test={test_score:.4f}  Efficiency={efficiency:.2f}"
                + (" ⚠ possible overfit" if efficiency < 0.4 else "")
            )

            # Move forward
            current_start += test_period

        if results:
            efficiencies = [
                r['test_score'] / r['train_score']
                for r in results
                if r['train_score'] > 0
            ]
            avg_eff = float(np.mean(efficiencies)) if efficiencies else float('nan')
            logger.success(
                f"Walk-forward complete: {len(results)} periods  "
                f"avg efficiency={avg_eff:.2f}  "
                f"({'robust' if avg_eff >= 0.6 else 'possible overfit — review params'})"
            )
        return results
    
    def _count_combinations(self, param_grid: Dict) -> int:
        """Count total parameter combinations"""
        count = 1
        for values in param_grid.values():
            count *= len(values)
        return count
    
    def get_optimization_report(self) -> Dict:
        """Get summary report of optimization results"""
        if not self.results_history:
            return {"error": "No optimization results available"}
        
        scores = [r['score'] for r in self.results_history]
        
        return {
            'total_evaluations': len(self.results_history),
            'best_score': max(scores),
            'worst_score': min(scores),
            'mean_score': np.mean(scores),
            'std_score': np.std(scores),
            'best_params': max(self.results_history, key=lambda x: x['score'])['params']
        }
    
    def save_results(self, filepath: str):
        """Save optimization results to JSON file"""
        with open(filepath, 'w') as f:
            json.dump({
                'config': self.optimizer_config,
                'results': self.results_history,
                'summary': self.get_optimization_report()
            }, f, indent=2, default=str)
        logger.info(f"Results saved to {filepath}")


def walk_forward_backtest(
    price_data: pd.DataFrame,
    signals: pd.DataFrame,
    base_config: Dict,
    param_grid: Dict[str, List],
    train_period: int = 6048,
    test_period: int = 1512,
    score_metric: str = 'sharpe',
    inner_cv_folds: int = 3,
    inner_cv_consistency_penalty: float = 1.0,
) -> List[Dict]:
    """
    Convenience function that wires the Backtester and metrics into a
    walk-forward loop with inner cross-validation for robust param selection.

    Each walk-forward fold:
      1. Splits the training window into `inner_cv_folds` sequential sub-periods.
      2. Scores each param combo as:
             mean(sub-period scores) − consistency_penalty × std(sub-period scores)
         This selects params that are consistently good across sub-periods,
         not just best in one lucky window (the primary overfitting mechanism).
      3. Re-evaluates best params on the FULL training window → train_score.
      4. Tests on the immediately following OOS window → test_score.
      5. Reports efficiency = test_score / train_score.

    Args:
        price_data:   Full OHLCV DataFrame with a DatetimeIndex.
        signals:      Signals DataFrame aligned to price_data's index,
                      containing at minimum a 'signal' column and optionally
                      a 'regime' column.
        base_config:  Full config dict (keys: 'risk_config', 'backtest_config').
                      param_grid values override 'risk_config' keys each fold.
        param_grid:   Dict of risk_config keys to test, e.g.:
                        {'atr_multiplier': [2.0, 2.5, 3.0],
                         'risk_reward_ratio': [4.0, 5.0]}
        train_period: IS window in bars. Default 6048 = 1 year × 1H bars.
        test_period:  OOS window in bars. Default 1512 = 3 months × 1H bars.
        score_metric: Metric to optimise. One of 'sharpe' | 'calmar' |
                      'profit_factor'. Default 'sharpe'.
        inner_cv_folds: Number of sequential sub-folds within each training
                      window for param selection. Default 3. Set to 1 to
                      revert to the old full-window behaviour.
        inner_cv_consistency_penalty: Weight applied to std(sub-fold scores)
                      when computing the adjusted score. Default 1.0 means
                      one std dev of inconsistency costs a full Sharpe point.
                      Higher values favour more consistent (lower-variance) params.

    Returns:
        List of dicts, one per fold:
          train_start, train_end, test_start, test_end,
          best_params, train_score, test_score, efficiency.

    Usage:
        results = walk_forward_backtest(
            price_data=df,
            signals=signals_df,
            base_config=config,
            param_grid={
                'atr_multiplier':    [2.0, 2.5, 3.0],
                'risk_reward_ratio': [4.0, 5.0],
            },
        )
        # Healthy strategy: avg efficiency >= 0.6 across all folds.
    """
    # Deferred imports to avoid circular dependency at module level.
    from backtest.backtester import Backtester
    from backtest.metrics import calculate_performance_metrics

    _SCORE_KEY = {
        'sharpe':        'Sharpe Ratio',
        'calmar':        'Calmar Ratio',
        'profit_factor': 'Profit Factor',
    }
    metric_key = _SCORE_KEY.get(score_metric, 'Sharpe Ratio')

    def _backtest_slice(
        data_slice: pd.DataFrame,
        params: Dict,
        warmup_slice: pd.DataFrame = None,
    ) -> float:
        """Run one backtest slice and return the chosen score metric.

        Args:
            data_slice:   The slice to score (train sub-fold or test window).
            params:       Parameter overrides (atr_multiplier, risk_reward_ratio, …).
            warmup_slice: Optional prepend data for indicator warm-up.  Signals
                          are forced NaN here so no trades fire, but indicators
                          (MA, ADX) build up their history before the actual
                          slice begins.  This prevents the first N bars of a
                          test slice from being unfiltered due to NaN indicators.
        """
        config = {
            **base_config,
            'risk_config': {**base_config.get('risk_config', {}), **params},
        }
        bt = Backtester(config)

        if warmup_slice is not None and not warmup_slice.empty:
            # Combine warmup + actual slice.  No signals in warmup period.
            combined_data    = pd.concat([warmup_slice, data_slice])
            combined_signals = signals.reindex(combined_data.index).copy()
            combined_signals.loc[warmup_slice.index, 'signal'] = float('nan')
            raw = bt.run(combined_data, combined_signals)

            # Restrict evaluation to the actual data_slice only.
            test_start = data_slice.index[0]
            trades_df  = raw['trades']
            if not trades_df.empty and 'entry_date' in trades_df.columns:
                trades_df = trades_df[trades_df['entry_date'] >= test_start].copy()
            eq = raw['equity_curve']
            eq = eq[eq.index >= test_start]

            if trades_df.empty:
                return 0.0

            metrics = calculate_performance_metrics(
                eq, trades_df, raw['initial_capital'], run_mc=False
            )
        else:
            # Signals are reindexed to the exact date range of this slice.
            signals_slice = signals.reindex(data_slice.index)
            raw = bt.run(data_slice, signals_slice)

            if raw['trades'].empty:
                return 0.0

            metrics = calculate_performance_metrics(
                raw['equity_curve'], raw['trades'],
                raw['initial_capital'], run_mc=False,
            )

        score = float(metrics.get(metric_key, 0.0))
        # Guard against inf/nan from folds with very few trades
        return score if np.isfinite(score) else 0.0

    def _inner_cv_score(train_slice: pd.DataFrame, params: Dict) -> float:
        """Score params using sequential K-fold CV within the training window.

        Splits `train_slice` into `inner_cv_folds` consecutive sub-periods
        and runs the strategy on each.  Returns:
            mean(scores) − consistency_penalty × std(scores)

        This penalises params that only work in one sub-period of the training
        window — the main cause of large train/test Sharpe gaps (overfit).
        Falls back to the full-window score when sub-periods are too short
        (< 300 bars) to produce reliable metrics.
        """
        n = len(train_slice)
        min_inner_bars = 300  # need enough trades per sub-period
        fold_size = n // inner_cv_folds

        if inner_cv_folds <= 1 or fold_size < min_inner_bars:
            # Sub-periods too small for reliable metrics — full window fallback.
            return _backtest_slice(train_slice, params)

        sub_scores = []
        for k in range(inner_cv_folds):
            start = k * fold_size
            # Last fold absorbs any remainder so no bars are orphaned.
            end = start + fold_size if k < inner_cv_folds - 1 else n
            sub_slice = train_slice.iloc[start:end]
            if len(sub_slice) < min_inner_bars:
                continue
            sub_scores.append(_backtest_slice(sub_slice, params))

        if not sub_scores:
            return _backtest_slice(train_slice, params)

        arr = np.array(sub_scores, dtype=float)
        mean_s = float(np.mean(arr))
        std_s  = float(np.std(arr))
        # Consistency-adjusted score: penalise high cross-period variance.
        # A param set that averages Sharpe 1.5 with std 0.1 scores higher
        # than one averaging 1.8 with std 1.4 (the typical overfit pattern).
        return mean_s - inner_cv_consistency_penalty * std_s

    # ── Main walk-forward loop ────────────────────────────────────────────────
    total_bars = len(price_data)
    current_start = 0
    results = []
    param_names  = list(param_grid.keys())
    param_values = list(param_grid.values())
    all_combos   = list(product(*param_values))

    while current_start + train_period + test_period <= total_bars:
        train_end = current_start + train_period
        test_end  = train_end + test_period

        train_slice = price_data.iloc[current_start:train_end]
        test_slice  = price_data.iloc[train_end:test_end]

        # ── Step 1: select params via inner CV (robust to sub-period variance) ─
        best_params = None
        best_cv_score = float('-inf')
        for combo in all_combos:
            params = dict(zip(param_names, combo))
            cv_score = _inner_cv_score(train_slice, params)
            if cv_score > best_cv_score:
                best_cv_score = cv_score
                best_params = params.copy()

        if best_params is None:
            current_start += test_period
            continue

        # ── Step 2: measure train_score on full window (for the table / debug) ─
        train_score = _backtest_slice(train_slice, best_params)

        # ── Step 3: OOS test (with warm-up from tail of training window) ────
        # Prepend the last indicator_warmup bars of the training slice so that
        # indicators (MA trend filter, ADX) are already initialised at the
        # first bar of the test period.  Without this, the MA is NaN for the
        # first min_periods bars, leaving those trades unfiltered.
        indicator_warmup = base_config.get('risk_config', {}).get(
            'trend_filter_period', 200
        )
        warmup_data = train_slice.iloc[-indicator_warmup:] if indicator_warmup > 0 else None
        test_score = _backtest_slice(test_slice, best_params, warmup_slice=warmup_data)

        efficiency = (
            test_score / train_score if train_score > 0 else float('nan')
        )
        logger.info(
            f"Fold {len(results)+1}: "
            f"Train={train_score:.4f}  Test={test_score:.4f}  "
            f"Efficiency={efficiency:.2f}  Params={best_params}"
            + (" ⚠ possible overfit" if np.isfinite(efficiency) and efficiency < 0.4 else "")
        )

        results.append({
            'train_start': train_slice.index[0],
            'train_end':   train_slice.index[-1],
            'test_start':  test_slice.index[0],
            'test_end':    test_slice.index[-1],
            'best_params': best_params,
            'train_score': train_score,
            'test_score':  test_score,
            'efficiency':  efficiency,
        })

        current_start += test_period

    if results:
        valid_effs = [r['efficiency'] for r in results if np.isfinite(r['efficiency'])]
        avg_eff = float(np.mean(valid_effs)) if valid_effs else float('nan')
        logger.success(
            f"Walk-forward complete: {len(results)} folds  "
            f"avg efficiency={avg_eff:.2f}  "
            f"({'robust' if avg_eff >= 0.6 else 'possible overfit — review params'})"
        )

    return results


# Example usage
if __name__ == '__main__':
    # Test grid search
    config = {
        'optimizer_config': {
            'method': 'grid_search',
            'optimization_metric': 'sharpe_ratio'
        }
    }
    
    optimizer = StrategyOptimizer(config)
    
    # Example objective function
    def dummy_objective(params):
        return -(params['a'] - 3)**2 - (params['b'] - 5)**2 + 10
    
    param_grid = {
        'a': [1, 2, 3, 4, 5],
        'b': [3, 4, 5, 6, 7]
    }
    
    best_params, best_score = optimizer.grid_search(param_grid, dummy_objective)
    print(f"Best params: {best_params}, Score: {best_score}")
