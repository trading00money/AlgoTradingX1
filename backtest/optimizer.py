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
) -> List[Dict]:
    """
    Convenience function that wires the Backtester and metrics into
    walk_forward_optimize, handling signal slicing automatically.

    Each walk-forward fold:
      1. Trains (grid-searches param_grid) on an in-sample window.
      2. Tests the best params on the immediately following OOS window.
      3. Reports efficiency = test_score / train_score for each fold.

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

    def _backtest_slice(data_slice: pd.DataFrame, params: Dict) -> float:
        """Run one backtest fold and return the chosen score metric."""
        config = {
            **base_config,
            'risk_config': {**base_config.get('risk_config', {}), **params},
        }
        bt = Backtester(config)
        # Signals are reindexed to the exact date range of this fold's data.
        signals_slice = signals.reindex(data_slice.index)
        results = bt.run(data_slice, signals_slice)

        if results['trades'].empty:
            return 0.0

        metrics = calculate_performance_metrics(
            results['equity_curve'],
            results['trades'],
            results['initial_capital'],
            run_mc=False,   # skip MC inside each fold — too slow
        )
        score = float(metrics.get(metric_key, 0.0))
        # Guard against inf/nan from folds with very few trades
        return score if np.isfinite(score) else 0.0

    optimizer = StrategyOptimizer(
        {'optimizer_config': {'method': 'grid_search', 'optimization_metric': score_metric}}
    )
    raw_results = optimizer.walk_forward_optimize(
        price_data=price_data,
        param_grid=param_grid,
        backtest_func=_backtest_slice,
        train_period=train_period,
        test_period=test_period,
    )

    # Attach efficiency ratio to each result for convenience
    for r in raw_results:
        r['efficiency'] = (
            r['test_score'] / r['train_score']
            if r['train_score'] > 0
            else float('nan')
        )
    return raw_results


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
