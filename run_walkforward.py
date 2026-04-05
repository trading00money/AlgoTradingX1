"""
Walk-Forward Optimization Runner
Runs walk-forward validation using the same data pipeline as run.py backtest.

Usage:
    python run_walkforward.py

Output:
    Prints a fold-by-fold efficiency table and avg efficiency score.
    Target: avg efficiency >= 0.6 before going live.
"""
import os
import sys
import yaml
import json
from loguru import logger
from typing import Dict

from dotenv import load_dotenv
load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_DIR = os.path.join(SCRIPT_DIR, 'config')


def load_config(file_name: str) -> Dict:
    path = os.path.join(CONFIG_DIR, file_name)
    try:
        with open(path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Config not found: {path}")
        return {}
    except Exception as e:
        logger.error(f"Error loading {path}: {e}")
        return {}


def main():
    logger.info("=== Walk-Forward Optimization ===")

    # 1. Load configs (same as run.py)
    config = {
        'strategy_config':  load_config('strategy_config.yaml'),
        'broker_config':    load_config('broker_config.yaml'),
        'gann_config':      load_config('gann_config.yaml'),
        'risk_config':      load_config('risk_config.yaml'),
        'backtest_config':  load_config('backtest_config.yaml'),
        'ml_config':        load_config('ml_config.yaml'),
        'ehlers_config':    load_config('ehlers_config.yaml'),
        'astro_config':     load_config('astro_config.yaml'),
    }

    # 2. Load data and generate signals (same pipeline as run.py)
    from core.data_feed import DataFeed
    from core.gann_engine import GannEngine
    from core.ehlers_engine import EhlersEngine
    from core.astro_engine import AstroEngine
    from core.ml_engine import MLEngine
    from core.signal_engine import AISignalEngine

    data_feed     = DataFeed(broker_config=config.get('broker_config', {}))
    gann_engine   = GannEngine(gann_config=config.get('gann_config', {}))
    ehlers_engine = EhlersEngine(ehlers_config=config.get('ehlers_config', {}))
    astro_engine  = AstroEngine(astro_config=config.get('astro_config', {}))
    ml_engine     = MLEngine(config)
    signal_engine = AISignalEngine(config.get('strategy_config', {}))

    backtest_cfg = config.get('backtest_config', {})
    symbol    = backtest_cfg.get('symbol', 'XAUUSD')
    timeframe = backtest_cfg.get('timeframe', '1h')
    start_date = backtest_cfg.get('start_date', '2021-01-01')
    end_date   = backtest_cfg.get('end_date', '2026-04-01')

    logger.info(f"Fetching {symbol} {timeframe} data from {start_date} to {end_date}...")
    price_data = data_feed.get_historical_data(
        symbol=symbol, timeframe=timeframe,
        start_date=start_date, end_date=end_date
    )

    if price_data is None or price_data.empty:
        logger.error("Failed to fetch historical data. Aborting.")
        return

    logger.info(f"Data loaded: {len(price_data)} bars  ({price_data.index[0]} → {price_data.index[-1]})")

    # Generate indicators and signals
    gann_levels          = gann_engine.calculate_sq9_levels(price_data)
    data_with_indicators = ehlers_engine.calculate_all_indicators(price_data)
    astro_events         = astro_engine.analyze_dates(price_data.index)
    ml_predictions       = ml_engine.get_predictions(data_with_indicators, gann_levels, astro_events)

    if ml_predictions is not None:
        data_with_indicators = data_with_indicators.join(ml_predictions)

    signals = signal_engine.generate_signals_for_backtest(data_with_indicators)

    if signals.empty or signals['signal'].isna().all():
        logger.error("No signals generated. Aborting.")
        return

    logger.info(f"Signals generated: {signals['signal'].notna().sum()} non-null signal bars")

    # 3. Define the parameter grid to test
    #    These are the risk_config keys to optimize each fold.
    #    Add or remove values to expand/narrow the search space.
    param_grid = {
        'atr_multiplier':    [2.0, 2.5, 3.0],
        'risk_reward_ratio': [4.0, 5.0],
    }

    total_combinations = 1
    for v in param_grid.values():
        total_combinations *= len(v)
    logger.info(
        f"Param grid: {param_grid}  ({total_combinations} combinations per fold)"
    )

    # 4. Run walk-forward
    #    train_period = 6048 bars = 1 year of 1H (252 days × 24 bars)
    #    test_period  = 1512 bars = 3 months of 1H (63 days × 24 bars)
    from backtest.optimizer import walk_forward_backtest

    results = walk_forward_backtest(
        price_data=price_data,
        signals=signals,
        base_config=config,
        param_grid=param_grid,
        train_period=6048,
        test_period=1512,
        score_metric='sharpe',
    )

    if not results:
        logger.error("Walk-forward returned no results. Not enough data for even one fold.")
        return

    # 5. Print fold-by-fold summary table
    print("\n" + "=" * 80)
    print("WALK-FORWARD RESULTS")
    print("=" * 80)
    print(
        f"{'Fold':<6} {'Test Period':<14} {'Best ATR':<10} {'Best RR':<10} "
        f"{'Train Sharpe':<14} {'Test Sharpe':<13} {'Efficiency':<12} {'Status'}"
    )
    print("-" * 80)

    for i, r in enumerate(results):
        eff   = r['efficiency']
        atr   = r['best_params'].get('atr_multiplier', '-')
        rr    = r['best_params'].get('risk_reward_ratio', '-')
        ts    = r['test_start'].strftime('%Y-%m') if hasattr(r['test_start'], 'strftime') else str(r['test_start'])[:7]
        te    = r['test_end'].strftime('%Y-%m')   if hasattr(r['test_end'],   'strftime') else str(r['test_end'])[:7]

        if eff >= 0.6:
            status = "PASS"
        elif eff >= 0.4:
            status = "MARGINAL"
        else:
            status = "FAIL (overfit?)"

        print(
            f"{i+1:<6} {ts+' → '+te:<14} {str(atr):<10} {str(rr):<10} "
            f"{r['train_score']:<14.3f} {r['test_score']:<13.3f} {eff:<12.2f} {status}"
        )

    print("-" * 80)

    valid_effs = [r['efficiency'] for r in results if r['train_score'] > 0]
    avg_eff    = sum(valid_effs) / len(valid_effs) if valid_effs else float('nan')
    pass_count = sum(1 for e in valid_effs if e >= 0.6)
    fail_count = sum(1 for e in valid_effs if e < 0.4)

    print(f"\nFolds total   : {len(results)}")
    print(f"PASS  (≥0.6)  : {pass_count}")
    print(f"FAIL  (<0.4)  : {fail_count}")
    print(f"Avg efficiency: {avg_eff:.2f}", end="  ")

    if avg_eff >= 0.6:
        print("✓ ROBUST — strategy passes walk-forward validation")
    elif avg_eff >= 0.4:
        print("⚠ MARGINAL — review failing folds before going live")
    else:
        print("✗ OVERFIT — do not go live. Review parameters.")

    # 6. Best parameter vote count
    from collections import Counter
    atr_votes = Counter(r['best_params'].get('atr_multiplier') for r in results)
    rr_votes  = Counter(r['best_params'].get('risk_reward_ratio') for r in results)

    print("\n--- Parameter Stability (most selected per fold) ---")
    print(f"atr_multiplier    votes: {dict(atr_votes)}")
    print(f"risk_reward_ratio votes: {dict(rr_votes)}")

    recommended_atr = atr_votes.most_common(1)[0][0]
    recommended_rr  = rr_votes.most_common(1)[0][0]
    print(f"\nRecommended params for live trading:")
    print(f"  atr_multiplier:    {recommended_atr}  (selected {atr_votes[recommended_atr]}/{len(results)} folds)")
    print(f"  risk_reward_ratio: {recommended_rr}  (selected {rr_votes[recommended_rr]}/{len(results)} folds)")
    print("=" * 80)

    # 7. Save results to JSON
    output_path = os.path.join(SCRIPT_DIR, 'walkforward_results.json')
    with open(output_path, 'w') as f:
        json.dump(
            [{
                'fold': i + 1,
                'train_start': str(r['train_start']),
                'train_end':   str(r['train_end']),
                'test_start':  str(r['test_start']),
                'test_end':    str(r['test_end']),
                'best_params': r['best_params'],
                'train_score': r['train_score'],
                'test_score':  r['test_score'],
                'efficiency':  r['efficiency'],
            } for i, r in enumerate(results)],
            f, indent=2
        )
    logger.info(f"Full results saved to {output_path}")


if __name__ == '__main__':
    main()
