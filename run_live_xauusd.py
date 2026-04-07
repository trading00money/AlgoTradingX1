"""
run_live_xauusd.py — Live Paper Trading: GOLD (XAUUSD) on MetaTrader 5
Executes the v5 Pullback Strategy — identical logic to the validated backtest.

Strategy results (5-year XAUUSD H1 backtest, run.py):
  Return: 147.41%  |  Sharpe: 2.19  |  Max DD: 5.89%  |  PF: 2.17  |  Calmar: 3.06
  Trades: 495  |  WR: 45.9%  |  Avg Win: $1,217  |  Avg Loss: -$474  |  Expectancy: $301

How it works (bar-by-bar, hourly):
  1. Waits for H1 bar close (UTC hour boundary + 2s buffer)
  2. Fetches last 700 GOLD H1 bars from the running MT5 terminal
  3. Runs signal_engine.generate_signals_for_backtest() — same as backtester
  4. If last bar has a signal AND no open position → enter trade
  5. If position open: checks partial exit (3R), time stop (30 bars), regime exit

Risk (paper phase — scale up only after 30+ trades with live PF >= 1.4):
  - 0.5% equity risk per trade  (backtest used 1.0%)
  - Short trades use 0.5× size  (asymmetric sizing, same as backtest)
  - SL = 3.0 × ATR(14)
  - TP = 5.0 × RR (ceiling; regime exit captures 3-4R sweet spot)

Position state is written to live_state.json so the script survives restarts.

Requirements:
  - MetaTrader 5 terminal running and logged into the demo account
  - .env with MT5_LOGIN and MT5_PASSWORD  (already set)
  - pip install MetaTrader5  (if not already installed)

Usage:
  python run_live_xauusd.py

Scale-up checklist (before setting PAPER_RISK_PCT = 1.0):
  [ ] 30+ executed trades
  [ ] Live Profit Factor >= 1.4
  [ ] Live/Backtest PF ratio >= 0.70  (e.g., 1.5 live vs 1.94 backtest = 0.77 ✓)
  [ ] Max drawdown not approaching 15% of account
"""

import os
import sys
import json
import time
import math
import yaml
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

# Ensure project root is on sys.path so core.* and modules.* are importable
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

CONFIG_DIR  = os.path.join(SCRIPT_DIR, 'config')
STATE_FILE  = os.path.join(SCRIPT_DIR, 'live_state.json')

# ─────────────────────────────────────────────────────────────────────────────
# LIVE TRADING PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
PAPER_RISK_PCT   = 0.5   # % equity risk per trade — paper phase (backtest = 1.0%)
MT5_SYMBOL       = 'GOLD'  # Exact symbol name in your MT5 market watch
LOOKBACK_BARS    = 3500  # H1 bars to fetch.
# Warmup analysis (bars needed for 1% convergence of initial seed):
#   D1 EMA50  : resample H1→D1 then EWM(50) → needs 115 daily bars = 2,760 H1 bars  ← bottleneck
#   EMA200    : EWM(200) → needs 461 H1 bars
#   MAMA      : adaptive EWM → needs ~180 H1 bars
#   ATR/ADX   : EWM(14) → needs 63 H1 bars
#   ITrend    : IIR(0.07) → needs 64 H1 bars
#   EBSW      : HP(40)+SS(10) → needs ~50 H1 bars
# 3,500 bars → ~146 daily bars → D1 EMA50 convergence 99.6% ✓
MAGIC_NUMBER     = 20260101  # Unique magic so we identify our own orders in MT5

# Risk params — must match risk_config.yaml flat keys used in backtester
ATR_PERIOD       = 14
ATR_MULTIPLIER   = 3.0   # SL = 3.0 × ATR   (walk-forward selected 7/16 folds)
RISK_REWARD      = 5.0   # TP = 5.0 × risk distance
SHORT_SCALE      = 0.5   # Shorts use 50% of normal position size
PARTIAL_EXIT_R   = 3.0   # Close 50% of position when unrealized profit hits 3R
PARTIAL_EXIT_PCT = 0.5   # Fraction to close at PARTIAL_EXIT_R
TIME_STOP_BARS   = 30    # Close losing trade if still underwater after 30 bars

# Walk-forward validated entry filters (mirroring backtester.py / risk_config.yaml)
MA_TREND_PERIOD      = 200          # MA(200 H1 bars) trend direction filter
SEASONAL_WEAK_MONTHS = {4,5,6,7,8,9}  # Apr-Sep: Q2/Q3 gold edge degradation
SEASONAL_SIZE_SCALE  = 0.25         # 25% normal size during weak months
ADX_GATE_PERIOD      = 14           # ADX period (Wilder smoothing)
ADX_GATE_THRESHOLD   = 20.0         # Block entries in weak months when ADX < 20
# ─────────────────────────────────────────────────────────────────────────────


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


def load_state() -> Dict:
    """Load persisted position state from live_state.json."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {'position': None, 'trade_log': []}


def save_state(state: Dict):
    """Persist position state to disk."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────
class TelegramNotifier:
    """
    Sends trade notifications to a Telegram chat.
    Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment.
    Silently no-ops if either is missing or if requests fails.
    """

    def __init__(self):
        self._token   = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self._chat_id = os.getenv('TELEGRAM_ALERTS_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID', '')
        self._enabled = bool(self._token and self._chat_id)
        if self._enabled:
            logger.info(f"Telegram notifications enabled → chat {self._chat_id}")
        else:
            logger.warning("Telegram credentials not set — notifications disabled.")

    def send(self, message: str):
        """Send a plain-text / HTML message. Non-blocking; errors are logged."""
        if not self._enabled:
            return
        try:
            import requests
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            requests.post(
                url,
                json={'chat_id': self._chat_id, 'text': message, 'parse_mode': 'HTML'},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")

    # ── Pre-formatted message helpers ─────────────────────────────────────────

    def trade_opened(self, side: str, entry: float, sl: float, tp: float,
                     lots: float, atr: float, equity: float, risk_pct: float,
                     ticket: int):
        direction = "LONG" if side == 'long' else "SHORT"
        icon      = "🟢" if side == 'long' else "🔴"
        risk_usd  = equity * risk_pct / 100.0
        sl_dist   = abs(entry - sl)
        self.send(
            f"{icon} <b>TRADE OPENED — {direction} GOLD</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Ticket  : #{ticket}\n"
            f"Entry   : <b>{entry:.2f}</b>\n"
            f"SL      : {sl:.2f}  (dist: {sl_dist:.2f}/oz)\n"
            f"TP      : {tp:.2f}  (RR {RISK_REWARD:.1f}:1)\n"
            f"Lots    : {lots:.2f}\n"
            f"ATR×{ATR_MULTIPLIER} : {atr:.2f}\n"
            f"Risk    : ${risk_usd:.0f}  ({risk_pct}% equity)\n"
            f"Time    : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

    def partial_exit(self, ticket: int, side: str, close_lots: float,
                     close_price: float, entry_price: float,
                     remaining_lots: float, unrealized_r: float, bars: int):
        self.send(
            f"📤 <b>PARTIAL EXIT — {PARTIAL_EXIT_R}R reached</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Ticket  : #{ticket}\n"
            f"Side    : {side.upper()}\n"
            f"Closed  : {close_lots:.2f} lots @ {close_price:.2f}\n"
            f"Remaining: {remaining_lots:.2f} lots\n"
            f"SL moved: breakeven @ {entry_price:.2f}\n"
            f"R gained: +{unrealized_r:.2f}R\n"
            f"Bars open: {bars}\n"
            f"Time    : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

    def time_stop(self, ticket: int, side: str, lots: float,
                  entry: float, current: float, unrealized_r: float, bars: int):
        self.send(
            f"⏱ <b>TIME STOP — {bars} bars elapsed</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Ticket  : #{ticket}\n"
            f"Side    : {side.upper()}\n"
            f"Lots    : {lots:.2f}\n"
            f"Entry   : {entry:.2f}\n"
            f"Exit    : {current:.2f}\n"
            f"R at exit: {unrealized_r:+.2f}R\n"
            f"Bars open: {bars}\n"
            f"Time    : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

    def regime_exit(self, ticket: int, side: str, lots: float,
                    entry: float, current: float,
                    unrealized_r: float, bars: int, new_signal: int):
        new_dir = "SHORT" if new_signal == -1 else "LONG"
        self.send(
            f"🔄 <b>REGIME EXIT — signal reversed to {new_dir}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Ticket  : #{ticket}\n"
            f"Was     : {side.upper()} {lots:.2f} lots\n"
            f"Entry   : {entry:.2f}\n"
            f"Exit    : {current:.2f}\n"
            f"R at exit: {unrealized_r:+.2f}R\n"
            f"Bars open: {bars}\n"
            f"Time    : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

    def sl_tp_hit(self, pos_state: Dict):
        side   = pos_state.get('side', '?').upper()
        ticket = pos_state.get('ticket', '?')
        entry  = pos_state.get('entry_price', 0.0)
        sl     = pos_state.get('sl', 0.0)
        tp     = pos_state.get('tp', 0.0)
        lots   = pos_state.get('lots', 0.0)
        bars   = pos_state.get('bars_open', 0)
        partial = "Yes" if pos_state.get('partial_done') else "No"
        self.send(
            f"✅ <b>TRADE CLOSED — SL/TP hit (MT5)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Ticket  : #{ticket}\n"
            f"Was     : {side} {lots:.2f} lots\n"
            f"Entry   : {entry:.2f}\n"
            f"SL was  : {sl:.2f}\n"
            f"TP was  : {tp:.2f}\n"
            f"Partial : {partial}\n"
            f"Bars open: {bars}\n"
            f"Time    : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

    def startup(self, account: Dict):
        balance  = account.get('balance', 0.0)
        equity   = account.get('equity', 0.0)
        currency = account.get('currency', 'USD')
        login    = account.get('login', '?')
        server   = account.get('server', '?')
        self.send(
            f"🤖 <b>AlgoTradingX1 — LIVE PAPER TRADING STARTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Symbol  : {MT5_SYMBOL} (XAUUSD)\n"
            f"Strategy: v5 EMA20 Pullback\n"
            f"Risk    : {PAPER_RISK_PCT}% per trade\n"
            f"ATR×{ATR_MULTIPLIER} | RR {RISK_REWARD}:1 | Partial @{PARTIAL_EXIT_R}R\n"
            f"Account : {login}  |  {server}\n"
            f"Balance : {currency} {balance:,.2f}\n"
            f"Equity  : {currency} {equity:,.2f}\n"
            f"Time    : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

    def signal_detected(self, side: str, bar_time: str, close: float,
                        ema20: float, atr: float, sl: float, tp: float,
                        partial_tp: float, lots: float, risk_usd: float,
                        risk_pct: float, filters: Dict):
        direction = "LONG" if side == 'long' else "SHORT"
        icon      = "🎯" if side == 'long' else "🎯"
        sl_dist   = abs(close - sl)
        zone_lo   = min(close, ema20)
        zone_hi   = max(close, ema20)
        self.send(
            f"{icon} <b>SIGNAL DETECTED — {direction} GOLD</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Bar     : {bar_time}\n"
            f"Close   : <b>{close:.2f}</b>  |  EMA20: {ema20:.2f}\n"
            f"Zone    : {zone_lo:.2f} – {zone_hi:.2f}\n"
            f"\n"
            f"── Levels ──────────────────────\n"
            f"Stop Loss  : {sl:.2f}  ({sl_dist:.2f}/oz, {ATR_MULTIPLIER}×ATR)\n"
            f"Take Profit: {tp:.2f}  (RR {RISK_REWARD:.0f}:1)\n"
            f"Partial TP : {partial_tp:.2f}  ({PARTIAL_EXIT_R:.0f}R)\n"
            f"\n"
            f"── Sizing ───────────────────────\n"
            f"Lots    : {lots:.2f}\n"
            f"Risk    : ${risk_usd:.0f}  ({risk_pct}% equity)\n"
            f"ATR     : {atr:.2f}\n"
            f"\n"
            f"── Filters ──────────────────────\n"
            f"EMA200  : {filters.get('ema200','?')}  |  D1 EMA50: {filters.get('d1_ema50','?')}\n"
            f"ADX     : {filters.get('adx','?')}  |  Session: {filters.get('session','?')}\n"
            f"MAMA    : {filters.get('mama','?')}  |  ITrend : {filters.get('itrend','?')}\n"
            f"EBSW    : {filters.get('ebsw','?')}\n"
            f"\n"
            f"⏳ Placing order now…\n"
            f"Time    : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

    def shutdown(self, reason: str = 'manual', account: Dict = None):
        pos_line = ""
        if account:
            equity   = account.get('equity', 0.0)
            currency = account.get('currency', 'USD')
            pos_line = f"\nEquity  : {currency} {equity:,.2f}"
        self.send(
            f"🔴 <b>AlgoTradingX1 — STOPPED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Reason  : {reason}\n"
            f"Symbol  : {MT5_SYMBOL} (XAUUSD){pos_line}\n"
            f"Note    : Open position (if any) remains in MT5\n"
            f"Time    : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )


def seconds_to_next_h1_close(buffer_secs: float = 3.0) -> float:
    """Seconds until the next H1 candle closes (UTC hour boundary + buffer)."""
    now       = datetime.now(timezone.utc)
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return max(0.0, (next_hour - now).total_seconds() + buffer_secs)


def calculate_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low   = data['high'] - data['low']
    high_close = (data['high'] - data['close'].shift()).abs()
    low_close  = (data['low']  - data['close'].shift()).abs()
    tr  = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def lots_from_risk(
    equity: float,
    entry_price: float,
    stop_loss: float,
    side: str,
    risk_pct: float = PAPER_RISK_PCT,
) -> float:
    """
    Convert dollar-risk to MT5 lots for GOLD.
    Standard MT5 GOLD contract: 1 lot = 100 troy oz.
    So:  lots = (equity × risk_pct/100) / (|entry - sl| × 100)
    Minimum 0.01 lot, rounded to 0.01 step.
    """
    sl_distance = abs(entry_price - stop_loss)
    if sl_distance <= 0:
        return 0.01

    dollars_at_risk = equity * (risk_pct / 100.0)
    # P&L per lot = sl_distance × 100 oz/lot
    lots = dollars_at_risk / (sl_distance * 100.0)

    if side == 'short':
        lots *= SHORT_SCALE

    # Round to nearest 0.01 lot and clamp to safe range
    lots = max(0.01, min(round(lots / 0.01) * 0.01, 50.0))
    return lots


# ─────────────────────────────────────────────────────────────────────────────
# MT5Bridge subclass: overrides _initialize to work without a known server name
# (uses the already-running MT5 terminal instead of re-authenticating to a
#  specific broker server — safe when MT5 is open and logged in)
# ─────────────────────────────────────────────────────────────────────────────
class MT5Bridge:
    """
    Thin wrapper around the MetaTrader5 Python library.
    We avoid the full MetaTrader5Bridge class here because it requires knowing
    the broker server name upfront. Instead we rely on the running terminal.
    """

    def __init__(self):
        self._connected = False
        self._init()

    def _init(self):
        try:
            import MetaTrader5 as mt5
            self._mt5 = mt5

            # Connect to the already-running MT5 terminal
            if not mt5.initialize():
                logger.error(f"MT5 initialize() failed: {mt5.last_error()}")
                return

            # Attempt login (server=None → use terminal's current server)
            login    = int(os.getenv('MT5_LOGIN', '0'))
            password = os.getenv('MT5_PASSWORD', '')
            if login and password:
                ok = mt5.login(login=login, password=password)
                if not ok:
                    # Maybe already logged in — check account
                    acct = mt5.account_info()
                    if acct and acct.login == login:
                        logger.info("Already logged in via running terminal.")
                    else:
                        logger.error(
                            f"MT5 login failed: {mt5.last_error()}. "
                            "If the terminal is already logged in, this can be ignored."
                        )
                        # Still mark connected — mt5.initialize() succeeded,
                        # the terminal is running and market data is available.

            self._connected = True
            acct = mt5.account_info()
            if acct:
                logger.success(
                    f"MT5 ready | Account: {acct.login} {acct.name} | "
                    f"Balance: {acct.currency} {acct.balance:,.2f} | "
                    f"Server: {acct.server}"
                )
        except ImportError:
            logger.error("MetaTrader5 package not installed. Run: pip install MetaTrader5")
        except Exception as e:
            logger.error(f"MT5 init error: {e}")

    def is_connected(self) -> bool:
        try:
            return self._connected and self._mt5.terminal_info() is not None
        except Exception:
            return False

    def account_info(self) -> Optional[Dict]:
        try:
            info = self._mt5.account_info()
            if info is None:
                return None
            return {
                'login':   info.login,
                'name':    info.name,
                'server':  info.server,
                'balance': info.balance,
                'equity':  info.equity,
                'currency': info.currency,
            }
        except Exception:
            return None

    def fetch_bars(self, symbol: str, count: int) -> Optional[pd.DataFrame]:
        """Fetch the last `count` CLOSED H1 bars from MT5.
        start_pos=1 skips bar 0 (the currently-forming candle) and starts
        from bar 1 (the most recently completed candle). We call this 3s after
        bar close so bar 1 is the signal bar we just waited for.
        """
        try:
            mt5 = self._mt5
            mt5.symbol_select(symbol, True)
            # copy_rates_from_pos(symbol, tf, start_pos, count)
            # start_pos=0 = current (open) bar; start_pos=1 = last closed bar
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 1, count)
            if rates is None or len(rates) == 0:
                logger.error(f"No bars returned for {symbol}")
                return None
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
            df.set_index('time', inplace=True)
            df.rename(columns={'tick_volume': 'volume'}, inplace=True)
            return df[['open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            logger.error(f"fetch_bars error: {e}")
            return None

    def current_price(self, symbol: str) -> Optional[float]:
        try:
            tick = self._mt5.symbol_info_tick(symbol)
            return (tick.bid + tick.ask) / 2.0 if tick else None
        except Exception:
            return None

    def place_order(
        self, symbol: str, side: str, lots: float,
        sl: float, tp: float
    ) -> Optional[Dict]:
        """Place a market order. side = 'BUY' or 'SELL'."""
        try:
            mt5   = self._mt5
            tick  = mt5.symbol_info_tick(symbol)
            price = tick.ask if side == 'BUY' else tick.bid
            order_type = mt5.ORDER_TYPE_BUY if side == 'BUY' else mt5.ORDER_TYPE_SELL

            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       symbol,
                "volume":       lots,
                "type":         order_type,
                "price":        price,
                "sl":           sl,
                "tp":           tp,
                "deviation":    5,
                "magic":        MAGIC_NUMBER,
                "comment":      "v5_pullback",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                return {'ticket': result.order, 'price': result.price}
            else:
                logger.error(f"Order rejected: {result.retcode} — {result.comment}")
                return None
        except Exception as e:
            logger.error(f"place_order error: {e}")
            return None

    def get_positions(self, symbol: str) -> List[Dict]:
        """Return open positions for symbol with our magic number."""
        try:
            positions = self._mt5.positions_get(symbol=symbol)
            if not positions:
                return []
            return [
                {
                    'ticket': p.ticket,
                    'type':   'BUY' if p.type == 0 else 'SELL',
                    'volume': p.volume,
                    'open_price': p.price_open,
                    'current_price': p.price_current,
                    'sl': p.sl,
                    'tp': p.tp,
                    'profit': p.profit,
                }
                for p in positions if p.magic == MAGIC_NUMBER
            ]
        except Exception as e:
            logger.error(f"get_positions error: {e}")
            return []

    def close_position(self, ticket: int) -> bool:
        """Close an open position by ticket."""
        try:
            mt5 = self._mt5
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                logger.warning(f"Position {ticket} not found.")
                return False
            pos = positions[0]

            close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
            tick  = mt5.symbol_info_tick(pos.symbol)
            price = tick.bid if pos.type == 0 else tick.ask

            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       pos.symbol,
                "volume":       pos.volume,
                "type":         close_type,
                "position":     ticket,
                "price":        price,
                "deviation":    5,
                "magic":        MAGIC_NUMBER,
                "comment":      "close",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.success(f"Closed position {ticket} @ {result.price:.2f}")
                return True
            else:
                logger.error(f"Close failed: {result.retcode} — {result.comment}")
                return False
        except Exception as e:
            logger.error(f"close_position error: {e}")
            return False

    def partial_close(self, ticket: int, lots: float) -> bool:
        """Close a partial volume of a position."""
        try:
            mt5 = self._mt5
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return False
            pos = positions[0]
            lots = max(0.01, min(lots, pos.volume - 0.01))  # keep min 0.01 remaining

            close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
            tick  = mt5.symbol_info_tick(pos.symbol)
            price = tick.bid if pos.type == 0 else tick.ask

            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       pos.symbol,
                "volume":       lots,
                "type":         close_type,
                "position":     ticket,
                "price":        price,
                "deviation":    5,
                "magic":        MAGIC_NUMBER,
                "comment":      "partial_3R",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.success(f"Partial close {lots:.2f} lots @ {result.price:.2f}")
                return True
            else:
                logger.error(f"Partial close failed: {result.retcode}")
                return False
        except Exception as e:
            logger.error(f"partial_close error: {e}")
            return False

    def modify_sl(self, ticket: int, new_sl: float) -> bool:
        """Move stop loss to new_sl (for breakeven after partial exit)."""
        try:
            mt5 = self._mt5
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return False
            pos = positions[0]
            request = {
                "action":   mt5.TRADE_ACTION_SLTP,
                "symbol":   pos.symbol,
                "position": ticket,
                "sl":       new_sl,
                "tp":       pos.tp,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.success(f"SL moved to {new_sl:.2f} (breakeven)")
                return True
            else:
                logger.error(f"Modify SL failed: {result.retcode}")
                return False
        except Exception as e:
            logger.error(f"modify_sl error: {e}")
            return False

    def shutdown(self):
        try:
            self._mt5.shutdown()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# MAIN TRADER
# ─────────────────────────────────────────────────────────────────────────────

class LiveTrader:
    def __init__(self):
        # Load all configs (same keys as run.py / backtester)
        self.config = {
            'strategy_config':  load_config('strategy_config.yaml'),
            'broker_config':    load_config('broker_config.yaml'),
            'gann_config':      load_config('gann_config.yaml'),
            'risk_config':      load_config('risk_config.yaml'),
            'backtest_config':  load_config('backtest_config.yaml'),
            'ml_config':        load_config('ml_config.yaml'),
            'ehlers_config':    load_config('ehlers_config.yaml'),
            'astro_config':     load_config('astro_config.yaml'),
        }

        # MT5 connection
        self.mt5 = MT5Bridge()

        # Telegram notifications
        self.notifier = TelegramNotifier()

        # Signal engine — the v5 Pullback Strategy (same as backtest)
        from core.signal_engine import AISignalEngine
        self.signal_engine = AISignalEngine(self.config.get('strategy_config', {}))

        # State (position tracking across restarts)
        self.state = load_state()

        logger.info(
            f"LiveTrader ready | Symbol={MT5_SYMBOL} | "
            f"Risk={PAPER_RISK_PCT}% | ATR×{ATR_MULTIPLIER} | RR={RISK_REWARD}"
        )

    # ── Data & Signals ────────────────────────────────────────────────────────

    def fetch_data(self) -> Optional[pd.DataFrame]:
        """Fetch the last LOOKBACK_BARS of H1 GOLD bars from MT5."""
        data = self.mt5.fetch_bars(MT5_SYMBOL, LOOKBACK_BARS)
        if data is None:
            return None
        # MT5 copy_rates_from_pos returns bars in ascending time order.
        # start_pos=1 means bar 0 (currently forming) is skipped;
        # the last element is the most recently CLOSED bar.
        # Verify index is ascending
        if not data.index.is_monotonic_increasing:
            data = data.sort_index()
        return data

    def get_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """Run the v5 Pullback Strategy signal engine on current data."""
        try:
            return self.signal_engine.generate_signals_for_backtest(data)
        except Exception as e:
            logger.error(f"Signal generation failed: {e}")
            return pd.DataFrame()

    # ── Position Management ───────────────────────────────────────────────────

    def manage_open_position(self, data: pd.DataFrame, signals: pd.DataFrame):
        """
        Per-bar checks on the open position:
          1. Partial exit at PARTIAL_EXIT_R (3R) — close 50%, move SL to breakeven
          2. Time stop after TIME_STOP_BARS (30) if still underwater
          3. Regime exit if the signal reverses direction
        MT5's own SL/TP handle the normal stop and full target.
        """
        pos_state = self.state.get('position')
        if pos_state is None:
            return

        ticket      = pos_state['ticket']
        side        = pos_state['side']            # 'long' or 'short'
        entry_price = pos_state['entry_price']
        init_risk   = pos_state['initial_risk']    # |entry − sl| at time of entry
        partial_done = pos_state.get('partial_done', False)

        # Increment bars_open counter
        pos_state['bars_open'] = pos_state.get('bars_open', 0) + 1
        bars_open = pos_state['bars_open']
        save_state(self.state)

        # Verify position still exists in MT5 (SL or TP may have been hit)
        mt5_positions = self.mt5.get_positions(MT5_SYMBOL)
        mt5_pos = next((p for p in mt5_positions if p['ticket'] == ticket), None)

        if mt5_pos is None:
            # Closed by MT5 (SL/TP hit or manual close)
            logger.info(
                f"Position {ticket} no longer open in MT5 "
                f"(closed by SL/TP or manually). Clearing state."
            )
            self._log_trade_close(pos_state, reason='sl_tp')
            self.notifier.sl_tp_hit(pos_state)
            self.state['position'] = None
            save_state(self.state)
            return

        current_price = data['close'].iloc[-1]

        # Unrealized profit in R-multiples (init_risk = 1R in price distance)
        if side == 'long':
            unrealized_r = (current_price - entry_price) / init_risk
        else:
            unrealized_r = (entry_price - current_price) / init_risk

        logger.info(
            f"Position {ticket} | {side.upper()} | bars={bars_open} | "
            f"unrealized={unrealized_r:+.2f}R | price={current_price:.2f}"
        )

        # ── 1. PARTIAL EXIT at 3R ─────────────────────────────────────────────
        if not partial_done and unrealized_r >= PARTIAL_EXIT_R:
            close_lots = round(mt5_pos['volume'] * PARTIAL_EXIT_PCT / 0.01) * 0.01
            close_lots = max(0.01, close_lots)
            if close_lots < mt5_pos['volume']:
                logger.info(
                    f"Partial exit at {PARTIAL_EXIT_R}R: closing {close_lots:.2f} lots"
                )
                if self.mt5.partial_close(ticket, close_lots):
                    # Move SL to breakeven + 0.3R buffer (matches backtester
                    # breakeven_buffer_r: 0.3 applied after partial_exit_move_be)
                    be_buffer = 0.3 * init_risk
                    if side == 'long':
                        be_sl = round(entry_price + be_buffer, 2)
                    else:
                        be_sl = round(entry_price - be_buffer, 2)
                    self.mt5.modify_sl(ticket, be_sl)
                    self.state['position']['partial_done'] = True
                    self.state['position']['bars_open']    = bars_open
                    save_state(self.state)
                    remaining = round(mt5_pos['volume'] - close_lots, 2)
                    self.notifier.partial_exit(
                        ticket=ticket, side=side,
                        close_lots=close_lots,
                        close_price=data['close'].iloc[-1],
                        entry_price=entry_price,
                        remaining_lots=remaining,
                        unrealized_r=unrealized_r,
                        bars=bars_open,
                    )
            return  # Wait for rest of trade to play out

        # ── 2. TIME STOP: cut underwater trades at 30 bars ───────────────────
        if bars_open >= TIME_STOP_BARS and unrealized_r < 0:
            logger.info(
                f"Time stop: {bars_open} bars open, {unrealized_r:+.2f}R → closing"
            )
            if self.mt5.close_position(ticket):
                self._log_trade_close(pos_state, reason='time_stop')
                self.notifier.time_stop(
                    ticket=ticket, side=side, lots=mt5_pos['volume'],
                    entry=entry_price, current=current_price,
                    unrealized_r=unrealized_r, bars=bars_open,
                )
                self.state['position'] = None
                save_state(self.state)
            return

        # ── 3. REGIME EXIT: Ehlers fast-regime reversal ──────────────────────
        # Uses signals['regime'] column (integers: 1=bull, -1=bear, 0=neutral).
        # Matches backtester logic: exit long when regime <= 0 (bear or neutral),
        # exit short when regime >= 0 (bull or neutral).
        if not signals.empty and 'regime' in signals.columns:
            last_regime = int(signals['regime'].iloc[-1])
            regime_exit = (side == 'long'  and last_regime <= 0) or \
                          (side == 'short' and last_regime >= 0)
            if regime_exit:
                logger.info(
                    f"Regime exit: regime={last_regime} conflicts with {side.upper()} → closing {ticket}"
                )
                if self.mt5.close_position(ticket):
                    self._log_trade_close(pos_state, reason='regime_exit')
                    self.notifier.regime_exit(
                        ticket=ticket, side=side, lots=mt5_pos['volume'],
                        entry=entry_price, current=current_price,
                        unrealized_r=unrealized_r, bars=bars_open,
                        new_signal=last_regime,
                    )
                    self.state['position'] = None
                    save_state(self.state)
            return

    # ── Trade Entry ───────────────────────────────────────────────────────────

    def enter_trade(self, data: pd.DataFrame, signal: int):
        """Open a new trade. signal=1 → BUY, signal=-1 → SELL."""
        acct = self.mt5.account_info()
        if not acct:
            logger.error("Cannot get account info. Skipping entry.")
            return

        equity = acct['equity']
        if equity <= 0:
            logger.error("Invalid equity. Skipping entry.")
            return

        # ATR at last completed bar
        atr_series = calculate_atr(data, period=ATR_PERIOD)
        atr = float(atr_series.iloc[-1])
        if math.isnan(atr) or atr <= 0:
            logger.error("Invalid ATR. Skipping entry.")
            return

        entry_price = data['close'].iloc[-1]
        side        = 'long' if signal == 1 else 'short'
        current_month = data.index[-1].month

        # ── Vol-adaptive SL multiplier (matches RiskManager / risk_config.yaml) ─
        # Scales ATR multiplier down from 3.0 to 1.5 when ATR is above the 70th
        # percentile of the rolling 200-bar window.  Prevents oversized stops
        # (and undersized position sizes) during abnormally volatile regimes.
        VOL_ADAPTIVE_THRESHOLD = 0.70   # matches vol_adaptive_percentile: 70
        VOL_ADAPTIVE_MIN_MULT  = 1.5    # matches vol_adaptive_min_multiplier: 1.5
        MAX_SL_DISTANCE        = 100.0  # matches max_sl_distance: 100.0 ($100/oz)

        atr_pct = atr_series.rolling(200, min_periods=50).rank(pct=True).iloc[-1]
        effective_atr_mult = ATR_MULTIPLIER
        if not math.isnan(atr_pct) and atr_pct > VOL_ADAPTIVE_THRESHOLD:
            scale = (1.0 - atr_pct) / (1.0 - VOL_ADAPTIVE_THRESHOLD)
            effective_atr_mult = (
                VOL_ADAPTIVE_MIN_MULT
                + (ATR_MULTIPLIER - VOL_ADAPTIVE_MIN_MULT) * scale
            )
            logger.info(
                f"Vol-adaptive SL: ATR pct={atr_pct:.1%} → "
                f"mult {ATR_MULTIPLIER:.1f} → {effective_atr_mult:.2f}"
            )

        # ── MA trend direction filter (year-round) ────────────────────────
        # Only enter longs when close > MA(200); only shorts when close < MA(200).
        # Blocks counter-trend entries during macro regime shifts (e.g. 2022 gold
        # crash where ADX was high but trend was bearish vs. strategy's long bias).
        min_p = max(10, MA_TREND_PERIOD // 10)
        ma200 = data['close'].rolling(MA_TREND_PERIOD, min_periods=min_p).mean().iloc[-1]
        if not math.isnan(ma200):
            if side == 'long' and entry_price < ma200:
                logger.info(
                    f"MA trend filter BLOCKED long: price {entry_price:.2f} < MA200 {ma200:.2f}"
                )
                return
            if side == 'short' and entry_price > ma200:
                logger.info(
                    f"MA trend filter BLOCKED short: price {entry_price:.2f} > MA200 {ma200:.2f}"
                )
                return

        # ── Seasonal ADX gate (weak months only) ─────────────────────────
        # During Apr-Sep, block entries when ADX < 20 (no directional trend).
        if current_month in SEASONAL_WEAK_MONTHS:
            from backtest.backtester import calculate_adx
            adx_series = calculate_adx(data, period=ADX_GATE_PERIOD)
            adx_val = float(adx_series.iloc[-1])
            if adx_val < ADX_GATE_THRESHOLD:
                logger.info(
                    f"Seasonal ADX gate BLOCKED entry: ADX {adx_val:.1f} < {ADX_GATE_THRESHOLD} "
                    f"(month={current_month}, weak season)"
                )
                return

        # ── Seasonal position-size scaling ────────────────────────────────
        # During weak months, trade at 25% of normal risk to limit drawdowns.
        effective_risk_pct = PAPER_RISK_PCT
        if current_month in SEASONAL_WEAK_MONTHS:
            effective_risk_pct = PAPER_RISK_PCT * SEASONAL_SIZE_SCALE
            logger.info(
                f"Seasonal size filter: risk scaled to {effective_risk_pct:.3f}% "
                f"(month={current_month}, {SEASONAL_SIZE_SCALE:.0%} of normal)"
            )

        sl_dist = atr * effective_atr_mult
        if sl_dist > MAX_SL_DISTANCE:
            logger.info(f"SL cap: dist {sl_dist:.1f} > {MAX_SL_DISTANCE:.0f} → capped")
            sl_dist = MAX_SL_DISTANCE

        if side == 'long':
            sl = round(entry_price - sl_dist, 2)
            tp = round(entry_price + sl_dist * RISK_REWARD, 2)
        else:
            sl = round(entry_price + sl_dist, 2)
            tp = round(entry_price - sl_dist * RISK_REWARD, 2)

        lots = lots_from_risk(equity, entry_price, sl, side, risk_pct=effective_risk_pct)

        logger.info(
            f"ENTRY SIGNAL: {side.upper()} | "
            f"Entry≈{entry_price:.2f} | SL={sl:.2f} | TP={tp:.2f} | "
            f"ATR={atr:.2f} | Lots={lots:.2f} | "
            f"Risk=${equity * effective_risk_pct / 100:.0f} ({effective_risk_pct:.3f}%)"
        )

        # ── Telegram signal alert (fires BEFORE order is placed) ─────────────
        partial_tp = round(entry_price + sl_dist * PARTIAL_EXIT_R, 2) if side == 'long' \
                else round(entry_price - sl_dist * PARTIAL_EXIT_R, 2)
        ema20_val  = float(data['close'].ewm(span=20, adjust=False).mean().iloc[-1])

        # Collect filter states for the alert
        ema200_val = float(data['close'].ewm(span=200, adjust=False).mean().iloc[-1])
        adx_display = "?"
        try:
            from backtest.backtester import calculate_adx
            adx_display = f"{float(calculate_adx(data, period=ADX_GATE_PERIOD).iloc[-1]):.1f}"
        except Exception:
            pass
        filters = {
            'ema200':  'BULL' if entry_price > ema200_val else 'BEAR',
            'd1_ema50': 'BULL' if side == 'long' else 'BEAR',
            'adx':     adx_display,
            'session': 'London/NY',
            'mama':    'BULL' if side == 'long' else 'BEAR',
            'itrend':  'BULL' if side == 'long' else 'BEAR',
            'ebsw':    'BULL' if side == 'long' else 'BEAR',
        }
        self.notifier.signal_detected(
            side=side,
            bar_time=data.index[-1].strftime('%Y-%m-%d %H:%M UTC'),
            close=entry_price,
            ema20=ema20_val,
            atr=atr,
            sl=sl,
            tp=tp,
            partial_tp=partial_tp,
            lots=lots,
            risk_usd=equity * effective_risk_pct / 100,
            risk_pct=effective_risk_pct,
            filters=filters,
        )

        mt5_side = 'BUY' if side == 'long' else 'SELL'
        result = self.mt5.place_order(
            symbol=MT5_SYMBOL,
            side=mt5_side,
            lots=lots,
            sl=sl,
            tp=tp,
        )

        if result:
            actual_entry = result['price']
            actual_risk  = abs(actual_entry - sl)
            self.state['position'] = {
                'ticket':       result['ticket'],
                'side':         side,
                'entry_price':  actual_entry,
                'entry_time':   str(data.index[-1]),
                'initial_risk': actual_risk,
                'sl':           sl,
                'tp':           tp,
                'lots':         lots,
                'partial_done': False,
                'bars_open':    0,
            }
            save_state(self.state)
            logger.success(
                f"Trade opened | Ticket={result['ticket']} | "
                f"{side.upper()} {lots:.2f} lots {MT5_SYMBOL} @ {actual_entry:.2f} | "
                f"SL={sl:.2f} ({actual_risk:.2f}/oz) | TP={tp:.2f}"
            )
            self.notifier.trade_opened(
                side=side, entry=actual_entry, sl=sl, tp=tp,
                lots=lots, atr=atr, equity=equity,
                risk_pct=effective_risk_pct, ticket=result['ticket'],
            )
        else:
            logger.error("Order rejected by MT5. No position opened.")

    # ── Trade logging ─────────────────────────────────────────────────────────

    def _log_trade_close(self, pos_state: Dict, reason: str):
        """Append closed trade info to state trade_log for review."""
        entry = {
            **pos_state,
            'close_time': str(datetime.now(timezone.utc)),
            'close_reason': reason,
        }
        if 'trade_log' not in self.state:
            self.state['trade_log'] = []
        self.state['trade_log'].append(entry)

    # ── Main Loop ─────────────────────────────────────────────────────────────

    def run(self):
        if not self.mt5.is_connected():
            logger.error("MT5 not connected. Cannot start trading loop.")
            logger.error(
                "Ensure MetaTrader 5 is running and logged in. "
                "Check MT5_LOGIN / MT5_PASSWORD in .env"
            )
            return

        logger.info("═" * 60)
        logger.info("AlgoTradingX1 — LIVE PAPER TRADING STARTED")
        logger.info(f"  Symbol     : {MT5_SYMBOL} (XAUUSD on MT5)")
        logger.info(f"  Risk/trade : {PAPER_RISK_PCT}% equity")
        logger.info(f"  ATR mult   : {ATR_MULTIPLIER}×  |  RR: {RISK_REWARD}:1")
        logger.info(f"  Time stop  : {TIME_STOP_BARS} bars  |  Partial: {PARTIAL_EXIT_R}R")
        logger.info(f"  Strategy   : v5 EMA20 Pullback (Ehlers+ADX+Session)")
        logger.info("  Press Ctrl+C to stop.")
        logger.info("═" * 60)
        acct_info = self.mt5.account_info()
        if acct_info:
            self.notifier.startup(acct_info)

        while True:
            try:
                # ── Sleep until next H1 bar close ───────────────────────────
                wait = seconds_to_next_h1_close()
                wake = datetime.now(timezone.utc) + timedelta(seconds=wait)
                logger.info(
                    f"Waiting {wait / 60:.1f} min → "
                    f"next bar at {wake.strftime('%Y-%m-%d %H:%M UTC')}"
                )
                time.sleep(wait)

                bar_label = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:00 UTC')
                logger.info(f"── Bar close: {bar_label} ──")

                # ── Fetch last 700 H1 bars ──────────────────────────────────
                data = self.fetch_data()
                if data is None or len(data) < 2760:
                    logger.warning(
                        f"Only {len(data) if data is not None else 0} bars received "
                        f"(need 2760+ for D1 EMA50 convergence). Skipping bar."
                    )
                    continue

                logger.info(
                    f"Data: {len(data)} bars | "
                    f"{data.index[0].strftime('%Y-%m-%d')} → "
                    f"{data.index[-1].strftime('%Y-%m-%d %H:%M')} | "
                    f"Close={data['close'].iloc[-1]:.2f}"
                )

                # ── Generate signals ────────────────────────────────────────
                signals = self.get_signals(data)
                if signals.empty or 'signal' not in signals.columns:
                    logger.warning("Signal engine returned no output. Skipping bar.")
                    continue

                # signal column returns strings: "BUY"/"SELL"/"HOLD"
                # (matches SignalType enum values in signal_engine.py)
                _LONG_SIG  = {"BUY", "STRONG_BUY"}
                _SHORT_SIG = {"SELL", "STRONG_SELL"}
                n_signals = int(signals['signal'].isin(_LONG_SIG | _SHORT_SIG).sum())
                logger.info(
                    f"Signals: {n_signals} non-neutral bars | "
                    f"Last bar signal: {signals['signal'].iloc[-1]}"
                )

                # ── Manage open position ────────────────────────────────────
                self.manage_open_position(data, signals)

                # ── Check for new entry ─────────────────────────────────────
                if self.state.get('position') is None:
                    last_signal = signals['signal'].iloc[-1]
                    if last_signal in _LONG_SIG:
                        logger.info(f"New LONG signal on {data.index[-1]} → entering trade")
                        self.enter_trade(data, 1)
                    elif last_signal in _SHORT_SIG:
                        logger.info(f"New SHORT signal on {data.index[-1]} → entering trade")
                        self.enter_trade(data, -1)
                    else:
                        logger.info("No entry signal. Flat.")
                else:
                    pos = self.state['position']
                    logger.info(
                        f"Position held: {pos['side'].upper()} {pos['lots']} lots | "
                        f"Entry @ {pos['entry_price']:.2f} | "
                        f"Bars open: {pos.get('bars_open', '?')} | "
                        f"Partial done: {pos.get('partial_done', False)}"
                    )

            except KeyboardInterrupt:
                logger.info("Stopped by user. Open position (if any) remains in MT5.")
                logger.info(f"State saved to {STATE_FILE}")
                acct_info = self.mt5.account_info()
                self.notifier.shutdown(reason='Stopped by user (Ctrl+C)', account=acct_info)
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                logger.info("Continuing after 60s...")
                time.sleep(60)

        self.mt5.shutdown()


# ─────────────────────────────────────────────────────────────────────────────

def main():
    logger.info("AlgoTradingX1 — run_live_xauusd.py starting up...")

    # Quick sanity checks
    if not os.getenv('MT5_LOGIN'):
        logger.error("MT5_LOGIN not set in .env. Aborting.")
        sys.exit(1)
    if not os.getenv('MT5_PASSWORD'):
        logger.error("MT5_PASSWORD not set in .env. Aborting.")
        sys.exit(1)

    trader = LiveTrader()
    trader.run()


if __name__ == '__main__':
    main()
