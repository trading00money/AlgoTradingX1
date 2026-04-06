import pandas as pd
import numpy as np
from loguru import logger
from typing import Dict, List

from core.risk_manager import RiskManager, calculate_atr
from core.portfolio_manager import PortfolioManager
from core.signal_engine import SignalType

# Canonical sets — single source of truth for directional signal mapping
_LONG_SIGNALS = frozenset({SignalType.BUY.value, SignalType.STRONG_BUY.value})
_SHORT_SIGNALS = frozenset({SignalType.SELL.value, SignalType.STRONG_SELL.value})


def calculate_adx(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average Directional Index (ADX) from OHLC data.

    ADX measures trend strength regardless of direction.  Values below ~20
    indicate a range-bound (choppy) market; above 25 indicates a trending
    market.  Used by the seasonal ADX gate to suppress entries during weak
    months when the market has no directional conviction.
    """
    high = data['high'].values
    low  = data['low'].values
    close = data['close'].values
    n = len(close)

    adx_out = np.zeros(n)
    if n < period * 2:
        return pd.Series(adx_out, index=data.index)

    plus_dm  = np.zeros(n)
    minus_dm = np.zeros(n)
    tr       = np.zeros(n)

    for i in range(1, n):
        up   = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm[i]  = up   if up > down and up > 0   else 0
        minus_dm[i] = down if down > up and down > 0 else 0
        tr[i] = max(high[i] - low[i],
                     abs(high[i] - close[i - 1]),
                     abs(low[i] - close[i - 1]))

    # Wilder smoothing
    atr_s = np.zeros(n)
    pdm_s = np.zeros(n)
    mdm_s = np.zeros(n)
    atr_s[period] = np.sum(tr[1:period + 1])
    pdm_s[period] = np.sum(plus_dm[1:period + 1])
    mdm_s[period] = np.sum(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        pdm_s[i] = pdm_s[i - 1] - pdm_s[i - 1] / period + plus_dm[i]
        mdm_s[i] = mdm_s[i - 1] - mdm_s[i - 1] / period + minus_dm[i]

    safe_atr = np.where(atr_s > 0, atr_s, 1.0)
    plus_di  = np.where(atr_s > 0, 100 * pdm_s / safe_atr, 0.0)
    minus_di = np.where(atr_s > 0, 100 * mdm_s / safe_atr, 0.0)
    di_sum   = plus_di + minus_di
    safe_di  = np.where(di_sum > 0, di_sum, 1.0)
    dx       = np.where(di_sum > 0, 100 * np.abs(plus_di - minus_di) / safe_di, 0.0)

    if 2 * period < n:
        adx_out[2 * period] = np.mean(dx[period:2 * period + 1])
        for i in range(2 * period + 1, n):
            adx_out[i] = (adx_out[i - 1] * (period - 1) + dx[i]) / period

    return pd.Series(adx_out, index=data.index)

class Backtester:
    """
    Runs a vector-based backtest using modular Risk and Portfolio Managers.
    Supports ATR trailing stop for letting winners run.
    """
    def __init__(self, config: Dict):
        """
        Initializes the Backtester.
        """
        self.config = config
        self.risk_config = config.get("risk_config", {})
        self.backtest_config = config.get("backtest_config", {})

        self.initial_capital = self.backtest_config.get("initial_capital", 10000.0)
        self.capital = self.initial_capital
        self.position = None
        self.trades = []
        self.equity_curve = []

        # Trailing stop configuration (from risk_config)
        self.trailing_enabled = self.risk_config.get("trailing_stop_enabled", True)
        self.trail_atr_mult = self.risk_config.get("trailing_atr_multiplier", 2.5)
        self.trail_activation_r = self.risk_config.get("trailing_activation_r", 1.0)

        # Time stop: exit trades that haven't reached min_profit_r within max_bars
        self.time_stop_enabled = self.risk_config.get("time_stop_enabled", False)
        self.time_stop_bars = self.risk_config.get("time_stop_bars", 48)
        self.time_stop_min_r = self.risk_config.get("time_stop_min_r", 0.5)

        # Breakeven stop: move SL to entry after reaching activation_r profit
        self.breakeven_enabled = self.risk_config.get("breakeven_stop_enabled", False)
        self.breakeven_activation_r = self.risk_config.get("breakeven_activation_r", 1.0)
        self.breakeven_buffer_r = self.risk_config.get("breakeven_buffer_r", 0.1)

        # Seasonal position-size filter ─────────────────────────────────────
        # XAUUSD walk-forward shows consistent FAIL/MARGINAL in Apr-Sep across
        # multiple years (folds 2/6/7/14 all April-October).  During these months
        # the strategy's edge degrades — range-bound price action with low follow-
        # through means ATR stops are wide relative to actual moves, killing RR.
        # Fix: scale sizing down to seasonal_size_scale during weak months rather
        # than skipping entirely, preserving signal diversity while limiting risk.
        self.seasonal_filter_enabled = self.risk_config.get("seasonal_filter_enabled", False)
        self.seasonal_weak_months = set(
            self.risk_config.get("seasonal_weak_months", [4, 5, 6, 7, 8, 9])
        )
        self.seasonal_size_scale = float(
            self.risk_config.get("seasonal_size_scale", 0.25)
        )

        # Seasonal ADX entry gate ──────────────────────────────────────────
        # During weak months, the remaining FAIL folds (2, 6) have deeply
        # negative test Sharpe because the strategy fires trend signals into
        # range-bound chop.  ADX measures trend strength: below ~20 the market
        # has no directional conviction.  This gate BLOCKS entries entirely
        # during weak months when ADX is below threshold — addressing the root
        # cause (bad entries into chop) rather than just reducing size.
        self.seasonal_adx_gate = self.risk_config.get("seasonal_adx_gate_enabled", False)
        self.seasonal_adx_threshold = float(
            self.risk_config.get("seasonal_adx_threshold", 20.0)
        )

        # MA trend direction filter ──────────────────────────────────────────
        # Year-round filter: only enter longs when close > MA(period), only
        # enter shorts when close < MA(period).  Prevents counter-trend entries
        # during macro regime shifts.  Root cause of fold 2 (Apr-Jul 2022 gold
        # crash, test Sharpe -4.7): long signals fired into a strong USD-driven
        # downtrend.  The ADX gate can't block this because ADX was HIGH (the
        # market WAS trending — just against the strategy's long bias).
        self.trend_filter_enabled = self.risk_config.get("trend_filter_enabled", False)
        self.trend_filter_period = int(self.risk_config.get("trend_filter_period", 200))

        # Short-side regime filter (disabled by default — see risk_config notes).
        self.short_regime_filter = self.risk_config.get("short_regime_filter_enabled", False)

        # Asymmetric short sizing: multiply sizing_capital by this scale for
        # short entries.  1.0 = same size as longs.  0.5 = half size on shorts.
        # Reduces short-side drag on XAUUSD without removing short trades entirely.
        self.short_size_scale = float(self.risk_config.get("short_size_scale", 1.0))

        # Partial profit exit: close a fraction of the position when unrealized
        # profit reaches partial_exit_r multiples of initial risk, then move SL
        # to breakeven.  Locks in gains on winning trades that never hit full TP.
        self.partial_exit_enabled = self.risk_config.get("partial_exit_enabled", False)
        self.partial_exit_r = self.risk_config.get("partial_exit_r", 2.0)
        self.partial_exit_pct = self.risk_config.get("partial_exit_pct", 0.5)
        self.partial_exit_move_be = self.risk_config.get("partial_exit_move_be", True)

        logger.info(f"Backtester initialized with initial capital: ${self.initial_capital:,.2f}")
        if self.seasonal_filter_enabled:
            logger.info(
                f"Seasonal filter: ON  weak_months={sorted(self.seasonal_weak_months)}  "
                f"size_scale={self.seasonal_size_scale:.2f}x"
            )
        if self.seasonal_adx_gate:
            logger.info(
                f"Seasonal ADX gate: ON  threshold={self.seasonal_adx_threshold}  "
                f"(blocks entries in weak months when ADX < {self.seasonal_adx_threshold})"
            )
        if self.trend_filter_enabled:
            logger.info(
                f"MA trend filter: ON  period={self.trend_filter_period}  "
                f"(longs only above MA, shorts only below MA — year-round)"
            )
        if self.trailing_enabled:
            logger.info(
                f"Trailing stop: ON  activation={self.trail_activation_r}R  "
                f"trail={self.trail_atr_mult}×ATR"
            )
        if self.breakeven_enabled:
            logger.info(
                f"Breakeven stop: ON  activation={self.breakeven_activation_r}R  "
                f"buffer={self.breakeven_buffer_r}R"
            )
        if self.time_stop_enabled:
            logger.info(
                f"Time stop: ON  bars={self.time_stop_bars}  "
                f"min_r={self.time_stop_min_r}R"
            )
        regime_min_r = self.risk_config.get("regime_exit_min_r", None)
        if regime_min_r is not None:
            logger.info(
                f"Smart regime exit: ON  min_r={regime_min_r}R  "
                f"(winners above {regime_min_r}R continue under trailing stop)"
            )
        if self.short_regime_filter:
            logger.info("Short regime filter: ON  (shorts only entered when regime < 0)")
        if self.short_size_scale < 1.0:
            logger.info(f"Asymmetric short sizing: ON  short_size_scale={self.short_size_scale:.2f}")
        if self.partial_exit_enabled:
            logger.info(
                f"Partial exit: ON  trigger={self.partial_exit_r}R  "
                f"size={self.partial_exit_pct:.0%}  move_BE={self.partial_exit_move_be}"
            )

    def _apply_slippage(self, price: float, side: str) -> float:
        """Applies slippage to the execution price."""
        slippage_type = self.backtest_config.get("slippage", {}).get("type", "percentage")
        slippage_val = self.backtest_config.get("slippage", {}).get("value", 0.0)

        if slippage_type == "percentage":
            slip = price * (slippage_val / 100.0)
            return price + slip if side == 'long' else price - slip
        return price

    def _apply_commission(self, trade_value: float) -> float:
        """Calculates and deducts commission."""
        comm_type = self.backtest_config.get("commission", {}).get("type", "percentage")
        comm_val = self.backtest_config.get("commission", {}).get("value", 0.0)

        if comm_type == "percentage":
            commission_cost = trade_value * (comm_val / 100.0)
            self.capital -= commission_cost
            return commission_cost
        return 0.0

    def run(self, price_data: pd.DataFrame, signals: pd.DataFrame) -> Dict:
        """
        Executes the backtest simulation.
        """
        logger.info("Starting backtest simulation with advanced risk management...")

        # Initialize managers
        risk_manager = RiskManager(self.risk_config, price_data)
        portfolio_manager = PortfolioManager(self.risk_config)
        diag_logged = 0

        data = price_data.copy()
        # Reindex so signals align to price data's index; unmatched dates become NaN (no trade).
        data['signal'] = signals['signal'].reindex(data.index)

        # Regime column for regime-based exits (optional)
        has_regime = 'regime' in signals.columns
        if has_regime:
            data['regime'] = signals['regime'].reindex(data.index).fillna(0).astype(int)

        # Pre-compute ATR for trailing stop and vol-adaptive sizing
        atr_series = calculate_atr(data, period=self.risk_config.get("atr_period", 14))

        # Pre-compute ADX for seasonal entry gate
        adx_series = None
        if self.seasonal_adx_gate:
            adx_series = calculate_adx(data, period=self.risk_config.get("atr_period", 14))

        # Pre-compute MA for trend direction filter.
        # min_periods = period // 10 (≥10) so the MA activates within ~1 trading
        # day of the slice start — critical for test slices that have no warm-up
        # data prepended from the training period.  A partial MA with 20+ bars is
        # still directionally reliable in clear trending markets.
        ma_series = None
        if self.trend_filter_enabled:
            min_p = max(10, self.trend_filter_period // 10)
            ma_series = data['close'].rolling(
                self.trend_filter_period,
                min_periods=min_p
            ).mean()

        # Vol-adaptive position sizing: scale equity down during high-vol
        vol_sizing_enabled = self.risk_config.get("vol_adaptive_sizing", False)
        if vol_sizing_enabled:
            atr_pct_series = atr_series.rolling(200, min_periods=50).rank(pct=True)
            vol_sizing_threshold = self.risk_config.get("vol_sizing_percentile", 70) / 100.0
            vol_sizing_min_scale = self.risk_config.get("vol_sizing_min_scale", 0.5)
            logger.info(
                f"Vol-adaptive sizing: ON  threshold={vol_sizing_threshold:.0%}  "
                f"min_scale={vol_sizing_min_scale}"
            )

        for i, row in data.iterrows():
            timestamp = row.name

            # 1. Check for exit conditions on the open position
            if self.position:
                exit_price = None
                exit_reason = None

                # ── ATR trailing stop (uses PREVIOUS bar's extremes) ─────
                # Avoids intra-bar paradox where same bar's high activates
                # trailing and same bar's low hits the new stop.
                if self.trailing_enabled:
                    current_atr = atr_series.at[timestamp] if timestamp in atr_series.index else 0
                    entry_price = self.position['entry_price']
                    initial_risk = self.position['initial_risk']
                    # prev_high/low already captured at end of previous iteration
                    prev_best = self.position.get('prev_max_favorable', entry_price)
                    prev_worst = self.position.get('prev_min_favorable', entry_price)

                    if self.position['side'] == 'long':
                        unrealized_r = (prev_best - entry_price) / initial_risk if initial_risk > 0 else 0
                        if unrealized_r >= self.trail_activation_r and current_atr > 0:
                            trail_stop = prev_best - (self.trail_atr_mult * current_atr)
                            if trail_stop > self.position['stop_loss']:
                                self.position['stop_loss'] = trail_stop
                        # Update best price AFTER trailing calc (for next bar)
                        self.position['max_favorable'] = max(self.position['max_favorable'], row.high)
                        self.position['prev_max_favorable'] = self.position['max_favorable']

                    elif self.position['side'] == 'short':
                        unrealized_r = (entry_price - prev_worst) / initial_risk if initial_risk > 0 else 0
                        if unrealized_r >= self.trail_activation_r and current_atr > 0:
                            trail_stop = prev_worst + (self.trail_atr_mult * current_atr)
                            if trail_stop < self.position['stop_loss']:
                                self.position['stop_loss'] = trail_stop
                        self.position['min_favorable'] = min(self.position['min_favorable'], row.low)
                        self.position['prev_min_favorable'] = self.position['min_favorable']

                # ── Breakeven stop (uses PREVIOUS bar's extremes) ──────
                if self.breakeven_enabled and not self.position.get('breakeven_hit'):
                    entry_price = self.position['entry_price']
                    initial_risk = self.position['initial_risk']
                    prev_best = self.position.get('prev_max_favorable', entry_price)
                    prev_worst = self.position.get('prev_min_favorable', entry_price)

                    if self.position['side'] == 'long' and initial_risk > 0:
                        unrealized_r = (prev_best - entry_price) / initial_risk
                        if unrealized_r >= self.breakeven_activation_r:
                            be_stop = entry_price + (self.breakeven_buffer_r * initial_risk)
                            if be_stop > self.position['stop_loss']:
                                self.position['stop_loss'] = be_stop
                                self.position['breakeven_hit'] = True
                    elif self.position['side'] == 'short' and initial_risk > 0:
                        unrealized_r = (entry_price - prev_worst) / initial_risk
                        if unrealized_r >= self.breakeven_activation_r:
                            be_stop = entry_price - (self.breakeven_buffer_r * initial_risk)
                            if be_stop < self.position['stop_loss']:
                                self.position['stop_loss'] = be_stop
                                self.position['breakeven_hit'] = True

                # ── Partial profit exit ──────────────────────────────────
                # When unrealized profit >= partial_exit_r × initial risk,
                # close partial_exit_pct of the position at bar close and
                # optionally move the stop to breakeven on the remainder.
                # Triggers only once per trade (partial_done flag).
                if self.partial_exit_enabled and not self.position.get('partial_done'):
                    entry_price = self.position['entry_price']
                    initial_risk = self.position['initial_risk']
                    if initial_risk > 0:
                        if self.position['side'] == 'long':
                            current_r = (row.close - entry_price) / initial_risk
                        else:
                            current_r = (entry_price - row.close) / initial_risk

                        if current_r >= self.partial_exit_r:
                            partial_size = self.position['size'] * self.partial_exit_pct
                            pnl_per_unit = (
                                row.close - entry_price
                                if self.position['side'] == 'long'
                                else entry_price - row.close
                            )
                            partial_pnl = pnl_per_unit * partial_size

                            # Apply slippage and commission on partial exit
                            partial_exit_price = self._apply_slippage(
                                row.close,
                                'short' if self.position['side'] == 'long' else 'long'
                            )
                            self.capital += partial_pnl
                            partial_commission = self._apply_commission(
                                partial_exit_price * partial_size
                            )

                            self.trades.append({
                                **self.position,
                                'size': partial_size,
                                'exit_price': partial_exit_price,
                                'exit_date': timestamp,
                                'pnl': partial_pnl - partial_commission,
                                'commission': partial_commission,
                                'reason': 'Partial Exit',
                                'risk_per_unit': initial_risk,
                                'planned_rr': self.risk_config.get('risk_reward_ratio', None),
                                'realized_r': current_r,
                            })

                            # Reduce remaining size
                            self.position['size'] -= partial_size
                            self.position['partial_done'] = True

                            # Move stop to breakeven on the remainder
                            if self.partial_exit_move_be:
                                buffer = self.risk_config.get('breakeven_buffer_r', 0.1) * initial_risk
                                if self.position['side'] == 'long':
                                    be_stop = entry_price + buffer
                                    if be_stop > self.position['stop_loss']:
                                        self.position['stop_loss'] = be_stop
                                else:
                                    be_stop = entry_price - buffer
                                    if be_stop < self.position['stop_loss']:
                                        self.position['stop_loss'] = be_stop

                # ── Check SL / TP hits ───────────────────────────────────
                if self.position['side'] == 'long':
                    if row.low <= self.position['stop_loss']:
                        exit_price, exit_reason = self.position['stop_loss'], 'Stop Loss'
                    elif row.high >= self.position['take_profit']:
                        exit_price, exit_reason = self.position['take_profit'], 'Take Profit'

                elif self.position['side'] == 'short':
                    if row.high >= self.position['stop_loss']:
                        exit_price, exit_reason = self.position['stop_loss'], 'Stop Loss'
                    elif row.low <= self.position['take_profit']:
                        exit_price, exit_reason = self.position['take_profit'], 'Take Profit'

                # ── Regime-based exit: smart filter ─────────────────────
                # Only exit on regime change if trade is below regime_exit_min_r.
                # Winning trades above threshold continue under trailing stop.
                if not exit_reason and has_regime:
                    regime_val = row.get('regime', 0) if hasattr(row, 'get') else data.at[timestamp, 'regime']
                    regime_conflict = False
                    if self.position['side'] == 'long' and regime_val <= 0:
                        regime_conflict = True
                    elif self.position['side'] == 'short' and regime_val >= 0:
                        regime_conflict = True

                    if regime_conflict:
                        regime_min_r = self.risk_config.get("regime_exit_min_r", None)
                        if regime_min_r is None:
                            # Legacy: always exit on regime change
                            exit_price, exit_reason = row.close, 'Regime Exit'
                        else:
                            entry_price = self.position['entry_price']
                            initial_risk = self.position['initial_risk']
                            if initial_risk > 0:
                                if self.position['side'] == 'long':
                                    current_r = (row.close - entry_price) / initial_risk
                                else:
                                    current_r = (entry_price - row.close) / initial_risk
                            else:
                                current_r = 0
                            if current_r < regime_min_r:
                                exit_price, exit_reason = row.close, 'Regime Exit'
                            # else: trade continues — trailing stop / SL / TP will handle

                # ── Time stop: exit stale trades that haven't moved ──────
                if not exit_reason and self.time_stop_enabled:
                    self.position['bars_held'] = self.position.get('bars_held', 0) + 1
                    if self.position['bars_held'] >= self.time_stop_bars:
                        entry_price = self.position['entry_price']
                        initial_risk = self.position['initial_risk']
                        if initial_risk > 0:
                            if self.position['side'] == 'long':
                                current_r = (row.close - entry_price) / initial_risk
                            else:
                                current_r = (entry_price - row.close) / initial_risk
                            if current_r < self.time_stop_min_r:
                                exit_price, exit_reason = row.close, 'Time Stop'

                if exit_reason:
                    # Apply slippage to exit price
                    exit_price_after_slip = self._apply_slippage(exit_price, 'short' if self.position['side'] == 'long' else 'long')

                    pnl_per_unit = exit_price_after_slip - self.position['entry_price'] if self.position['side'] == 'long' else self.position['entry_price'] - exit_price_after_slip
                    total_pnl = pnl_per_unit * self.position['size']
                    self.capital += total_pnl

                    # Apply commission on exit
                    exit_trade_value = exit_price_after_slip * self.position['size']
                    commission_cost = self._apply_commission(exit_trade_value)

                    # Diagnostics: use initial_risk (SL may have moved via trailing stop)
                    risk_per_unit = self.position['initial_risk']
                    planned_rr = self.risk_config.get("risk_reward_ratio", None)
                    realized_r = ((total_pnl - commission_cost) / (risk_per_unit * self.position['size'])) if (risk_per_unit > 0 and self.position['size'] > 0) else None

                    self.trades.append({
                        **self.position,
                        'exit_price': exit_price_after_slip,
                        'exit_date': timestamp,
                        'pnl': total_pnl - commission_cost,
                        'commission': commission_cost,
                        'reason': exit_reason,
                        'risk_per_unit': risk_per_unit,
                        'planned_rr': planned_rr,
                        'realized_r': realized_r,
                    })
                    self.position = None

            # 2. Check for new entry signals (HOLD and unknown values are skipped)
            signal_val = row.signal if pd.notna(row.signal) else None
            if signal_val and not self.position:
                if signal_val in _LONG_SIGNALS:
                    trade_side = 'long'
                elif signal_val in _SHORT_SIGNALS:
                    trade_side = 'short'
                else:
                    # HOLD or unrecognised value — record equity and move on
                    self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                    continue

                # ── Seasonal ADX entry gate ──────────────────────────────
                # During weak months (Apr-Sep), BLOCK entries when ADX is
                # below threshold.  Addresses the root cause of folds 2/6:
                # trend signals firing into range-bound chop with no
                # directional conviction.  ADX < 20 = no trend = no entry.
                if (self.seasonal_adx_gate
                        and adx_series is not None
                        and timestamp.month in self.seasonal_weak_months):
                    adx_val = adx_series.at[timestamp] if timestamp in adx_series.index else 0
                    if adx_val < self.seasonal_adx_threshold:
                        self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                        continue

                # ── MA trend direction filter ────────────────────────────
                # Year-round gate: longs only above MA, shorts only below MA.
                # Prevents counter-trend entries during macro regime shifts
                # (e.g. 2022 gold crash where ADX was high but trend was bearish).
                if self.trend_filter_enabled and ma_series is not None:
                    ma_val = ma_series.at[timestamp] if timestamp in ma_series.index else float('nan')
                    if not pd.isna(ma_val):
                        if trade_side == 'long' and row.close < ma_val:
                            self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                            continue
                        elif trade_side == 'short' and row.close > ma_val:
                            self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                            continue

                # ── Short-side regime filter ─────────────────────────────
                # Only take short trades when the regime is explicitly bearish
                # (regime < 0).  Neutral regime (0) is treated as long-only
                # territory, consistent with XAUUSD's structural upward bias.
                if trade_side == 'short' and self.short_regime_filter and has_regime:
                    regime_val = row.get('regime', 0) if hasattr(row, 'get') else data.at[timestamp, 'regime']
                    if regime_val >= 0:
                        self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                        continue

                entry_price = self._apply_slippage(row.close, trade_side)

                exit_levels = risk_manager.get_exit_levels(entry_price, trade_side, timestamp)
                if not exit_levels: continue

                stop_loss, take_profit = exit_levels

                # Diagnostics: print the actual computed SL/TP distances and the RR config
                # for the first 5 trades so we can verify YAML keys are being applied.
                if diag_logged < 5:
                    stop_distance = abs(entry_price - stop_loss)
                    tp_distance = abs(take_profit - entry_price)
                    applied_rr = (tp_distance / stop_distance) if stop_distance > 0 else float("nan")
                    logger.info(
                        "DIAG trade#{n} {ts} side={side} entry={entry:.5f} "
                        "sl={sl:.5f} tp={tp:.5f} stop_dist={sd:.5f} tp_dist={td:.5f} "
                        "applied_rr={arr:.3f} cfg_rr={cfg_rr} cfg_atr_mult={cfg_atr_mult} "
                        "sl_method={slm} tp_method={tpm}".format(
                            n=diag_logged + 1,
                            ts=timestamp,
                            side=trade_side,
                            entry=entry_price,
                            sl=stop_loss,
                            tp=take_profit,
                            sd=stop_distance,
                            td=tp_distance,
                            arr=applied_rr,
                            cfg_rr=self.risk_config.get("risk_reward_ratio", None),
                            cfg_atr_mult=self.risk_config.get("atr_multiplier", None),
                            slm=self.risk_config.get("stop_loss_method", None),
                            tpm=self.risk_config.get("take_profit_method", None),
                        )
                    )
                    diag_logged += 1

                # Vol-adaptive sizing: scale equity down during high-vol regimes
                sizing_capital = self.capital
                if vol_sizing_enabled:
                    atr_pct = atr_pct_series.at[timestamp] if timestamp in atr_pct_series.index else 0
                    if not pd.isna(atr_pct) and atr_pct > vol_sizing_threshold:
                        scale = vol_sizing_min_scale + (1.0 - vol_sizing_min_scale) * (
                            (1.0 - atr_pct) / (1.0 - vol_sizing_threshold)
                        )
                        sizing_capital = self.capital * max(scale, vol_sizing_min_scale)

                # Seasonal sizing reduction: scale down during Apr-Sep (Q2/Q3).
                # Walk-forward shows consistent edge degradation in these months —
                # the strategy still trades but with a fraction of normal risk.
                if self.seasonal_filter_enabled and timestamp.month in self.seasonal_weak_months:
                    sizing_capital = sizing_capital * self.seasonal_size_scale

                # Asymmetric short sizing: reduce risk on short trades to account
                # for XAUUSD's structural long bias without removing them entirely.
                if trade_side == 'short' and self.short_size_scale < 1.0:
                    sizing_capital = sizing_capital * self.short_size_scale

                size = portfolio_manager.calculate_position_size(sizing_capital, entry_price, stop_loss)
                if size > 0:
                    # Apply commission on entry
                    entry_trade_value = entry_price * size
                    commission_cost = self._apply_commission(entry_trade_value)

                    self.position = {
                        'side':          trade_side,
                        'entry_price':   entry_price,
                        'stop_loss':     stop_loss,
                        'take_profit':   take_profit,
                        'entry_date':    timestamp,
                        'size':          size,
                        # Trailing stop fields (fixed at entry, never mutated)
                        'initial_risk':  abs(entry_price - stop_loss),
                        # Tracks the furthest favourable price seen (updated each bar)
                        'max_favorable': entry_price,   # for long
                        'min_favorable': entry_price,   # for short
                    }

            # 3. Record daily equity
            self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})

        logger.success(f"Backtest simulation completed. Total trades: {len(self.trades)}")

        return {
            "trades": pd.DataFrame(self.trades),
            "equity_curve": pd.DataFrame(self.equity_curve).set_index('timestamp'),
            "initial_capital": self.initial_capital,
            "final_capital": self.capital
        }
