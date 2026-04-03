import pandas as pd
import numpy as np
from loguru import logger
from typing import Dict, List

from core.risk_manager import RiskManager
from core.portfolio_manager import PortfolioManager
from core.signal_engine import SignalType

# Canonical sets — single source of truth for directional signal mapping
_LONG_SIGNALS = frozenset({SignalType.BUY.value, SignalType.STRONG_BUY.value})
_SHORT_SIGNALS = frozenset({SignalType.SELL.value, SignalType.STRONG_SELL.value})

class Backtester:
    """
    Runs a vector-based backtest using modular Risk and Portfolio Managers.
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
        logger.info(f"Backtester initialized with initial capital: ${self.initial_capital:,.2f}")

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

        for i, row in data.iterrows():
            timestamp = row.name

            # 1. Check for exit conditions on the open position
            if self.position:
                exit_price = None
                exit_reason = None

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

                size = portfolio_manager.calculate_position_size(self.capital, entry_price, stop_loss)
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
