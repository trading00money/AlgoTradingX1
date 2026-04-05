import math

import numpy as np
import pandas as pd
from loguru import logger


def _detect_annualization_factor(equity_curve: pd.DataFrame) -> float:
    """
    Auto-detects bars_per_year from the equity curve's DatetimeIndex so that
    Sharpe and Calmar are annualized correctly regardless of bar frequency.

    Examples:
      - Daily data  → ~252 bars/year  → returns 252
      - 1H data     → ~6048 bars/year → returns 6048  (252 * 24)
      - 4H data     → ~1512 bars/year → returns 1512  (252 * 6)

    Falls back to 252 (daily assumption) if the index is not a DatetimeIndex
    or contains fewer than 10 rows.
    """
    if not isinstance(equity_curve.index, pd.DatetimeIndex) or len(equity_curve) < 10:
        logger.warning("Could not detect bar frequency — defaulting to 252 (daily).")
        return 252.0

    deltas = equity_curve.index.to_series().diff().dropna()
    median_delta = deltas.median()
    if pd.isnull(median_delta) or median_delta <= pd.Timedelta(0):
        logger.warning("Median bar gap is zero or null — defaulting to 252 (daily).")
        return 252.0

    bars_per_day = float(pd.Timedelta("1D") / median_delta)
    bars_per_year = max(1.0, bars_per_day) * 252.0
    logger.info(
        f"Bar frequency detected: {median_delta} → "
        f"{bars_per_day:.2f} bars/day → {bars_per_year:.0f} bars/year (annualization factor)"
    )
    return bars_per_year


def run_monte_carlo(
    trades: pd.DataFrame,
    initial_capital: float,
    n_simulations: int = 10_000,
    confidence_levels: tuple = (0.05, 0.50, 0.95),
) -> dict:
    """
    Monte Carlo simulation via bootstrapped trade sequences (sampling with
    replacement). Quantifies the range of outcomes that are statistically
    plausible given the observed trade distribution, independent of entry order.

    Args:
        trades: DataFrame with a 'pnl' column.
        initial_capital: Starting capital.
        n_simulations: Number of bootstrapped simulations to run.
        confidence_levels: Percentiles to report (default: 5th, 50th, 95th).

    Returns:
        dict with:
          - 'max_drawdown_pct': percentile stats for maximum drawdown (%)
          - 'final_equity':     percentile stats for final portfolio value ($)
          - 'n_simulations':    number of simulations run
          - 'worst_case_ruin_pct': % of simulations where equity fell below 50%
                                   of initial capital (catastrophic loss proxy)
    """
    if trades.empty or "pnl" not in trades.columns:
        logger.warning("Monte Carlo: no trades to simulate.")
        return {}

    pnl_values = trades["pnl"].values
    n_trades = len(pnl_values)
    rng = np.random.default_rng(seed=42)

    # Vectorised: draw all simulations at once (n_simulations × n_trades)
    shuffled = rng.choice(pnl_values, size=(n_simulations, n_trades), replace=True)
    equity_paths = np.cumsum(shuffled, axis=1) + initial_capital  # (sims × trades)

    # Max drawdown per simulation
    peaks = np.maximum.accumulate(equity_paths, axis=1)
    drawdowns = (equity_paths - peaks) / peaks
    max_drawdowns = np.abs(drawdowns.min(axis=1)) * 100  # %

    final_equities = equity_paths[:, -1]

    level_labels = [f"p{int(c * 100)}" for c in confidence_levels]
    dd_pcts = np.percentile(max_drawdowns, [c * 100 for c in confidence_levels])
    eq_pcts = np.percentile(final_equities, [c * 100 for c in confidence_levels])
    ruin_pct = float(np.mean(final_equities < initial_capital * 0.5) * 100)

    result = {
        "n_simulations": n_simulations,
        "max_drawdown_pct": dict(zip(level_labels, dd_pcts.tolist())),
        "final_equity": dict(zip(level_labels, eq_pcts.tolist())),
        "worst_case_ruin_pct": ruin_pct,
    }
    logger.info(
        f"Monte Carlo ({n_simulations:,} sims): "
        f"MaxDD p5={dd_pcts[0]:.1f}%  p50={dd_pcts[1]:.1f}%  p95={dd_pcts[2]:.1f}% | "
        f"Ruin (<50% capital): {ruin_pct:.1f}%"
    )
    return result


def calculate_performance_metrics(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    initial_capital: float,
    run_mc: bool = True,
    mc_simulations: int = 10_000,
) -> dict:
    """
    Calculates key performance metrics from backtest results.

    Args:
        equity_curve (pd.DataFrame): DataFrame of portfolio equity over time.
            Must have a DatetimeIndex for correct Sharpe/Calmar annualization.
        trades (pd.DataFrame): DataFrame of all executed trades.
        initial_capital (float): The starting capital.
        run_mc (bool): Whether to run Monte Carlo simulation (default True).
        mc_simulations (int): Number of Monte Carlo simulations (default 10,000).

    Returns:
        dict: A dictionary of calculated performance metrics.
    """
    logger.info("Calculating performance metrics...")

    if equity_curve.empty:
        logger.warning("Equity curve is empty, cannot calculate metrics.")
        return {}

    metrics = {}

    # --- Profitability Metrics ---
    final_equity = equity_curve["equity"].iloc[-1]
    metrics["Final Portfolio Value"] = final_equity
    metrics["Total Net Profit"] = final_equity - initial_capital
    metrics["Total Return (%)"] = ((final_equity / initial_capital) - 1) * 100

    # --- Trade Metrics ---
    if not trades.empty:
        metrics["Total Trades"] = len(trades)
        wins = trades[trades["pnl"] > 0]
        losses = trades[trades["pnl"] <= 0]
        metrics["Winning Trades"] = len(wins)
        metrics["Losing Trades"] = len(losses)
        metrics["Win Rate (%)"] = (len(wins) / len(trades) * 100) if len(trades) > 0 else 0
        metrics["Average Win ($)"] = wins["pnl"].mean() if len(wins) > 0 else 0.0
        metrics["Average Loss ($)"] = losses["pnl"].mean() if len(losses) > 0 else 0.0
        metrics["Profit Factor"] = (
            abs(wins["pnl"].sum() / losses["pnl"].sum())
            if len(losses) > 0 and losses["pnl"].sum() != 0
            else float("inf")
        )
        metrics["Avg Trade PnL ($)"] = trades["pnl"].mean()
        wr = metrics["Win Rate (%)"] / 100
        metrics["Expectancy ($)"] = (
            metrics["Average Win ($)"] * wr
            + metrics["Average Loss ($)"] * (1 - wr)
        )

        # Exit reason breakdown
        if "reason" in trades.columns:
            reason_counts = trades["reason"].value_counts().to_dict()
            reason_pnl = trades.groupby("reason")["pnl"].mean().to_dict()
            metrics["Exit Reasons"] = {
                r: f"{c} trades, avg ${reason_pnl.get(r, 0):,.0f}"
                for r, c in reason_counts.items()
            }

        # Per-direction breakdown (critical for diagnosing bull/bear asymmetry)
        if "side" in trades.columns:
            for side in ["long", "short"]:
                st = trades[trades["side"] == side]
                if len(st) == 0:
                    continue
                sw = st[st["pnl"] > 0]
                sl = st[st["pnl"] <= 0]
                side_wr = len(sw) / len(st) * 100
                side_pf = (
                    abs(sw["pnl"].sum() / sl["pnl"].sum())
                    if len(sl) > 0 and sl["pnl"].sum() != 0
                    else float("inf")
                )
                tag = side.title()
                metrics[f"{tag} Trades"] = len(st)
                metrics[f"{tag} WR (%)"] = round(side_wr, 1)
                metrics[f"{tag} PF"] = round(side_pf, 2)
                metrics[f"{tag} Avg Win ($)"] = round(sw["pnl"].mean(), 0) if len(sw) > 0 else 0
                metrics[f"{tag} Avg Loss ($)"] = round(sl["pnl"].mean(), 0) if len(sl) > 0 else 0

    # --- Risk & Return Metrics ---
    returns = equity_curve["equity"].pct_change().dropna()

    # Annualization factor: auto-detected from bar frequency (fixes 1H vs daily bug).
    # Previously hardcoded to sqrt(252) which understated Sharpe ~5× on 1H data.
    annualization = _detect_annualization_factor(equity_curve)

    # Sharpe Ratio (risk-free rate = 0)
    metrics["Sharpe Ratio"] = (
        float(returns.mean() / returns.std() * np.sqrt(annualization))
        if returns.std() != 0
        else 0.0
    )

    # Max Drawdown
    cumulative_max = equity_curve["equity"].cummax()
    drawdown = (equity_curve["equity"] - cumulative_max) / cumulative_max
    metrics["Max Drawdown (%)"] = abs(float(drawdown.min()) * 100)

    # Calmar Ratio: annualized return / max drawdown (both as decimals)
    annual_return = float(returns.mean()) * annualization
    metrics["Calmar Ratio"] = (
        annual_return / abs(float(drawdown.min()))
        if drawdown.min() != 0
        else float("inf")
    )

    logger.success(
        f"Metrics — Sharpe: {metrics['Sharpe Ratio']:.2f}  "
        f"Calmar: {metrics['Calmar Ratio']:.2f}  "
        f"MaxDD: {metrics['Max Drawdown (%)']:.1f}%  "
        f"(annualization={annualization:.0f})"
    )

    # --- Monte Carlo Simulation ---
    if run_mc and not trades.empty:
        mc_results = run_monte_carlo(trades, initial_capital, n_simulations=mc_simulations)
        if mc_results:
            metrics["Monte Carlo"] = mc_results

    # Sanitise: replace numpy inf/nan with JSON-safe Python equivalents.
    clean = {}
    for k, v in metrics.items():
        if isinstance(v, float) and math.isnan(v):
            clean[k] = 0.0
        elif isinstance(v, float) and math.isinf(v):
            clean[k] = 999.99
        else:
            clean[k] = v
    return clean


# Example Usage
if __name__ == "__main__":
    # Create mock 1H backtest results (hourly bars over ~1 year)
    dates = pd.date_range(start="2023-01-01", periods=8760, freq="1h")
    equity = 10000 * (1 + np.random.randn(8760).cumsum() * 0.0003)
    mock_equity_curve = pd.DataFrame({"equity": equity}, index=dates)

    mock_trades = pd.DataFrame(
        [
            {"pnl": 200, "side": "long"},
            {"pnl": -100, "side": "short"},
            {"pnl": 300, "side": "long"},
            {"pnl": -50, "side": "long"},
            {"pnl": 150, "side": "short"},
        ]
    )

    performance = calculate_performance_metrics(mock_equity_curve, mock_trades, 10000.0)

    print("--- Performance Metrics Test ---")
    import json

    print(json.dumps(performance, indent=2, default=str))
    print("--------------------------------")
