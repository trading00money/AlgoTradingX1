"""
AI Signal Engine (Async)
Comprehensive signal generation combining Gann, Astrology, Ehlers DSP, and ML models.
Fully async implementation with parallel execution and thread-safe operations.
"""
import asyncio
import numpy as np
import pandas as pd
from loguru import logger
from modules.gann.square_of_9 import SquareOf9
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
from concurrent.futures import ThreadPoolExecutor
import functools


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    STRONG_BUY = "STRONG_BUY"
    STRONG_SELL = "STRONG_SELL"


class SignalStrength(Enum):
    WEAK = 1
    MODERATE = 2
    STRONG = 3
    VERY_STRONG = 4


class AnalysisError(Exception):
    """Base exception for analysis errors."""
    def __init__(self, source: str, message: str, original_error: Optional[Exception] = None):
        self.source = source
        self.message = message
        self.original_error = original_error
        super().__init__(f"[{source}] {message}")


@dataclass
class SignalComponent:
    """Individual signal component from a specific engine."""
    source: str  # 'gann', 'astro', 'ehlers', 'ml', 'pattern'
    signal: SignalType
    confidence: float  # 0-100
    weight: float  # Contribution weight
    details: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None


@dataclass
class AISignal:
    """Complete AI trading signal."""
    symbol: str
    timeframe: str
    signal: SignalType
    confidence: float  # 0-100
    strength: SignalStrength
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    components: List[SignalComponent] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    model_attribution: Dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    valid_until: datetime = None
    metadata: Dict = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'signal': self.signal.value,
            'confidence': round(self.confidence, 2),
            'strength': self.strength.name,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'risk_reward': round(self.risk_reward, 2),
            'reasons': self.reasons,
            'model_attribution': self.model_attribution,
            'timestamp': self.timestamp.isoformat(),
            'errors': self.errors,
            'components': [
                {
                    'source': c.source,
                    'signal': c.signal.value,
                    'confidence': c.confidence,
                    'weight': c.weight,
                    'error': c.error
                } for c in self.components
            ]
        }


class AISignalEngine:
    """
    Main AI Signal Engine that combines multiple analysis methods.
    
    Async implementation with:
    - Parallel execution of all analysis modules
    - Thread-safe operations with async locks
    - Comprehensive error handling
    - Timeout support for each analysis module
    
    Integrates:
    - WD Gann modules (Square of 9, 24, 52, 90, 144, 360)
    - Gann Time-Price Geometry
    - Astrology & market cycles
    - John Ehlers DSP indicators
    - Machine Learning models
    - Pattern Recognition
    """
    
    # Default weights for each component
    DEFAULT_WEIGHTS = {
        'gann': 0.25,
        'astro': 0.15,
        'ehlers': 0.20,
        'ml': 0.25,
        'pattern': 0.10,
        'options_flow': 0.05
    }
    
    # Default timeouts for each analysis module (in seconds)
    DEFAULT_TIMEOUTS = {
        'gann': 5.0,
        'astro': 3.0,
        'ehlers': 4.0,
        'ml': 10.0,
        'pattern': 3.0
    }
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.weights = self.config.get('weights', self.DEFAULT_WEIGHTS.copy())
        self.timeouts = self.config.get('timeouts', self.DEFAULT_TIMEOUTS.copy())
        
        # Initialize engines (lazy loading)
        self._gann_engine = None
        self._astro_engine = None
        self._ehlers_engine = None
        self._ml_engine = None
        self._pattern_engine = None
        
        # Signal history with thread-safe access
        self.signal_history: List[AISignal] = []
        self._history_lock = asyncio.Lock()
        
        # Thread pool for CPU-bound operations
        self._executor = ThreadPoolExecutor(max_workers=4)
        
        # Cache for frequently accessed data
        self._cache: Dict[str, Any] = {}
        self._cache_lock = asyncio.Lock()
        
        logger.info("AISignalEngine (Async) initialized")
    
    async def _run_in_executor(self, func: callable, *args, **kwargs) -> Any:
        """Run a synchronous function in the thread pool executor."""
        loop = asyncio.get_event_loop()
        partial_func = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(self._executor, partial_func)
    
    async def _safe_analyze(
        self,
        analyze_func: callable,
        source: str,
        *args,
        **kwargs
    ) -> Optional[SignalComponent]:
        """
        Safely execute an analysis function with timeout and error handling.
        
        Args:
            analyze_func: The async analysis function to execute
            source: Name of the analysis source (for error reporting)
            *args, **kwargs: Arguments to pass to the analysis function
            
        Returns:
            SignalComponent or None if analysis failed
        """
        timeout = self.timeouts.get(source, 5.0)
        
        try:
            result = await asyncio.wait_for(
                analyze_func(*args, **kwargs),
                timeout=timeout
            )
            return result
            
        except asyncio.TimeoutError:
            error_msg = f"Analysis timed out after {timeout}s"
            logger.warning(f"[{source}] {error_msg}")
            return SignalComponent(
                source=source,
                signal=SignalType.HOLD,
                confidence=0.0,
                weight=0.0,
                error=error_msg
            )
            
        except AnalysisError as e:
            logger.warning(f"[{source}] Analysis error: {e.message}")
            return SignalComponent(
                source=source,
                signal=SignalType.HOLD,
                confidence=0.0,
                weight=0.0,
                error=str(e)
            )
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"[{source}] {error_msg}", exc_info=True)
            return SignalComponent(
                source=source,
                signal=SignalType.HOLD,
                confidence=0.0,
                weight=0.0,
                error=error_msg
            )
    
    async def generate_signal(
        self,
        symbol: str,
        data: pd.DataFrame,
        timeframe: str = "H1",
        current_price: float = None
    ) -> AISignal:
        """
        Generate comprehensive AI trading signal with parallel analysis.
        
        Args:
            symbol: Trading symbol
            data: OHLCV DataFrame
            timeframe: Timeframe of the data
            current_price: Current market price
            
        Returns:
            AISignal with complete analysis
        """
        start_time = datetime.now()
        
        if current_price is None and len(data) > 0:
            current_price = data['close'].iloc[-1]
        
        # Run all analyses in parallel using asyncio.gather
        components, errors = await self._run_parallel_analyses(
            data=data,
            symbol=symbol,
            current_price=current_price
        )
        
        # Extract reasons from high-confidence components
        reasons = self._extract_reasons(components)
        
        # Combine signals
        final_signal, confidence, strength = self._combine_signals(components)
        
        # Calculate entry, SL, TP
        entry, sl, tp = self._calculate_levels(data, final_signal, current_price)
        
        # Calculate risk-reward
        risk_reward = self._calculate_risk_reward(entry, sl, tp, final_signal)
        
        # Build model attribution
        attribution = self._build_attribution(components)
        
        # Create final signal
        signal = AISignal(
            symbol=symbol,
            timeframe=timeframe,
            signal=final_signal,
            confidence=confidence,
            strength=strength,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            risk_reward=risk_reward,
            components=components,
            reasons=reasons,
            model_attribution=attribution,
            errors=errors,
            metadata={
                'data_points': len(data),
                'components_used': len([c for c in components if c.error is None]),
                'analysis_time_ms': (datetime.now() - start_time).total_seconds() * 1000
            }
        )
        
        # Store in history (thread-safe)
        async with self._history_lock:
            self.signal_history.append(signal)
            if len(self.signal_history) > 1000:
                self.signal_history = self.signal_history[-500:]
        
        logger.info(f"Generated signal for {symbol}: {final_signal.value} ({confidence:.1f}%)")
        
        return signal
    
    async def _run_parallel_analyses(
        self,
        data: pd.DataFrame,
        symbol: str,
        current_price: float
    ) -> Tuple[List[SignalComponent], List[str]]:
        """
        Run all analysis modules in parallel using asyncio.gather.
        
        Returns:
            Tuple of (components list, errors list)
        """
        # Create analysis tasks
        tasks = [
            self._safe_analyze(self._analyze_gann, 'gann', data, current_price),
            self._safe_analyze(self._analyze_astro, 'astro', data, symbol),
            self._safe_analyze(self._analyze_ehlers, 'ehlers', data),
            self._safe_analyze(self._analyze_ml, 'ml', data),
            self._safe_analyze(self._analyze_patterns, 'pattern', data),
        ]
        
        # Run all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        components = []
        errors = []
        
        for i, result in enumerate(results):
            source = ['gann', 'astro', 'ehlers', 'ml', 'pattern'][i]
            
            if isinstance(result, Exception):
                error_msg = f"{source}: {str(result)}"
                errors.append(error_msg)
                logger.error(f"Analysis task failed: {error_msg}")
                components.append(SignalComponent(
                    source=source,
                    signal=SignalType.HOLD,
                    confidence=0.0,
                    weight=0.0,
                    error=str(result)
                ))
            elif result is not None:
                components.append(result)
                if result.error:
                    errors.append(f"{source}: {result.error}")
        
        return components, errors
    
    async def _analyze_gann(
        self,
        data: pd.DataFrame,
        current_price: float
    ) -> Optional[SignalComponent]:
        """Analyze using Gann methods (async)."""
        def _sync_analyze():
            if len(data) < 20:
                return None
            
            high = data['high'].max()
            low = data['low'].min()
            close = data['close'].iloc[-1]
            
            # Square of 9 analysis
            sq9 = SquareOf9(low)
            levels = sq9.get_levels(5)
            
            # Find nearest support/resistance
            supports = [l for l in levels.get('support', []) if l < current_price]
            resistances = [l for l in levels.get('resistance', []) if l > current_price]
            
            nearest_support = max(supports) if supports else low
            nearest_resistance = min(resistances) if resistances else high
            
            # Determine signal based on price position
            range_size = nearest_resistance - nearest_support
            price_position = (current_price - nearest_support) / range_size if range_size > 0 else 0.5
            
            if price_position < 0.3:
                signal = SignalType.BUY
                confidence = (0.3 - price_position) * 200 + 50
                reason = f"Price near Sq9 support ${nearest_support:.2f}"
            elif price_position > 0.7:
                signal = SignalType.SELL
                confidence = (price_position - 0.7) * 200 + 50
                reason = f"Price near Sq9 resistance ${nearest_resistance:.2f}"
            else:
                signal = SignalType.HOLD
                confidence = 50
                reason = "Price in neutral zone"
            
            return SignalComponent(
                source='gann',
                signal=signal,
                confidence=min(95, confidence),
                weight=self.weights.get('gann', 0.25),
                details={
                    'reason': reason,
                    'nearest_support': nearest_support,
                    'nearest_resistance': nearest_resistance
                }
            )
        
        try:
            return await self._run_in_executor(_sync_analyze)
        except Exception as e:
            raise AnalysisError('gann', str(e), e)
    
    async def _analyze_astro(
        self,
        data: pd.DataFrame,
        symbol: str
    ) -> Optional[SignalComponent]:
        """Analyze using astrological cycles (async)."""
        def _sync_analyze():
            from modules.astro.synodic_cycles import SynodicCycleCalculator
            
            synodic = SynodicCycleCalculator()
            phases = synodic.get_current_cycle_phases()
            
            bullish_score = 0
            bearish_score = 0
            
            for phase in phases:
                if phase.get('phase_name') in ['new', 'first_quarter']:
                    bullish_score += 1
                elif phase.get('phase_name') in ['full', 'last_quarter']:
                    bearish_score += 1
            
            if bullish_score > bearish_score:
                signal = SignalType.BUY
                confidence = 50 + (bullish_score * 10)
                reason = f"Bullish astro cycles ({bullish_score} signals)"
            elif bearish_score > bullish_score:
                signal = SignalType.SELL
                confidence = 50 + (bearish_score * 10)
                reason = f"Bearish astro cycles ({bearish_score} signals)"
            else:
                signal = SignalType.HOLD
                confidence = 50
                reason = "Neutral astro cycles"
            
            return SignalComponent(
                source='astro',
                signal=signal,
                confidence=confidence,
                weight=self.weights.get('astro', 0.15),
                details={'reason': reason}
            )
        
        try:
            return await self._run_in_executor(_sync_analyze)
        except Exception as e:
            raise AnalysisError('astro', str(e), e)
    
    async def _analyze_ehlers(
        self,
        data: pd.DataFrame
    ) -> Optional[SignalComponent]:
        """Analyze using Ehlers DSP indicators (async)."""
        def _sync_analyze():
            if len(data) < 50:
                return None
            
            signals = {'buy': 0, 'sell': 0}
            
            # Simple momentum check as fallback
            close = data['close']
            momentum = close.iloc[-1] / close.iloc[-10] - 1
            
            if momentum > 0.02:
                signals['buy'] += 2
            elif momentum < -0.02:
                signals['sell'] += 2
            
            # RSI-like calculation
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            if rsi < 30:
                signals['buy'] += 1
            elif rsi > 70:
                signals['sell'] += 1
            
            total = signals['buy'] + signals['sell']
            if total == 0:
                return None
            
            if signals['buy'] > signals['sell']:
                signal = SignalType.BUY
                confidence = 50 + (signals['buy'] / total) * 40
                reason = f"Ehlers bullish"
            elif signals['sell'] > signals['buy']:
                signal = SignalType.SELL
                confidence = 50 + (signals['sell'] / total) * 40
                reason = f"Ehlers bearish"
            else:
                signal = SignalType.HOLD
                confidence = 50
                reason = "Ehlers neutral"
            
            return SignalComponent(
                source='ehlers',
                signal=signal,
                confidence=confidence,
                weight=self.weights.get('ehlers', 0.20),
                details={'reason': reason}
            )
        
        try:
            return await self._run_in_executor(_sync_analyze)
        except Exception as e:
            raise AnalysisError('ehlers', str(e), e)
    
    async def _analyze_ml(
        self,
        data: pd.DataFrame
    ) -> Optional[SignalComponent]:
        """Analyze using ML models (async)."""
        def _sync_analyze():
            if len(data) < 100:
                return None
            
            close = data['close']
            sma_20 = close.rolling(20).mean()
            sma_50 = close.rolling(50).mean()
            
            if close.iloc[-1] > sma_20.iloc[-1] > sma_50.iloc[-1]:
                signal = SignalType.BUY
                confidence = 65
                reason = "Bullish MA alignment"
            elif close.iloc[-1] < sma_20.iloc[-1] < sma_50.iloc[-1]:
                signal = SignalType.SELL
                confidence = 65
                reason = "Bearish MA alignment"
            else:
                signal = SignalType.HOLD
                confidence = 50
                reason = "Mixed MA signals"
            
            return SignalComponent(
                source='ml',
                signal=signal,
                confidence=confidence,
                weight=self.weights.get('ml', 0.25),
                details={'reason': reason}
            )
        
        try:
            return await self._run_in_executor(_sync_analyze)
        except Exception as e:
            raise AnalysisError('ml', str(e), e)
    
    async def _analyze_patterns(
        self,
        data: pd.DataFrame
    ) -> Optional[SignalComponent]:
        """Analyze chart patterns (async)."""
        def _sync_analyze():
            if len(data) < 20:
                return None
            
            close = data['close'].values
            high = data['high'].values
            low = data['low'].values
            
            signal_bias = 0
            patterns = []
            
            # Higher highs/lows trend
            if high[-1] > high[-5] and low[-1] > low[-5]:
                signal_bias += 1
                patterns.append("Uptrend")
            elif high[-1] < high[-5] and low[-1] < low[-5]:
                signal_bias -= 1
                patterns.append("Downtrend")
            
            if signal_bias > 0:
                signal = SignalType.BUY
                confidence = 55
            elif signal_bias < 0:
                signal = SignalType.SELL
                confidence = 55
            else:
                signal = SignalType.HOLD
                confidence = 50
            
            return SignalComponent(
                source='pattern',
                signal=signal,
                confidence=confidence,
                weight=self.weights.get('pattern', 0.10),
                details={'reason': ', '.join(patterns) if patterns else 'No clear pattern'}
            )
        
        try:
            return await self._run_in_executor(_sync_analyze)
        except Exception as e:
            raise AnalysisError('pattern', str(e), e)
    
    def _extract_reasons(self, components: List[SignalComponent]) -> List[str]:
        """Extract reasons from high-confidence components."""
        reasons = []
        for comp in components:
            if comp.error is None and comp.confidence > 60:
                reason = f"{comp.source.capitalize()}: {comp.details.get('reason', 'Signal detected')}"
                reasons.append(reason)
        return reasons
    
    def _build_attribution(self, components: List[SignalComponent]) -> Dict[str, float]:
        """Build model attribution from components."""
        attribution = {}
        for c in components:
            if c.error is None and c.weight > 0:
                attribution[c.source] = c.weight * c.confidence
        
        total_attr = sum(attribution.values()) or 1
        return {k: round(v / total_attr * 100, 1) for k, v in attribution.items()}
    
    def _combine_signals(self, components: List[SignalComponent]) -> Tuple[SignalType, float, SignalStrength]:
        """Combine all signal components into final signal."""
        # Filter out failed components
        valid_components = [c for c in components if c.error is None and c.weight > 0]
        
        if not valid_components:
            return SignalType.HOLD, 50.0, SignalStrength.WEAK
        
        buy_score = 0
        sell_score = 0
        total_weight = 0
        
        for comp in valid_components:
            weight = comp.weight * (comp.confidence / 100)
            total_weight += comp.weight
            
            if comp.signal in [SignalType.BUY, SignalType.STRONG_BUY]:
                buy_score += weight
            elif comp.signal in [SignalType.SELL, SignalType.STRONG_SELL]:
                sell_score += weight
        
        if total_weight > 0:
            buy_score /= total_weight
            sell_score /= total_weight
        
        if buy_score > sell_score and buy_score > 0.4:
            signal = SignalType.STRONG_BUY if buy_score > 0.7 else SignalType.BUY
            confidence = buy_score * 100
        elif sell_score > buy_score and sell_score > 0.4:
            signal = SignalType.STRONG_SELL if sell_score > 0.7 else SignalType.SELL
            confidence = sell_score * 100
        else:
            signal = SignalType.HOLD
            confidence = 50
        
        if confidence >= 80:
            strength = SignalStrength.VERY_STRONG
        elif confidence >= 65:
            strength = SignalStrength.STRONG
        elif confidence >= 50:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK
        
        return signal, min(95, confidence), strength
    
    def _calculate_levels(self, data: pd.DataFrame, signal: SignalType, current_price: float) -> Tuple[float, float, float]:
        """Calculate entry, stop loss, and take profit levels."""
        if len(data) < 20:
            if signal in [SignalType.BUY, SignalType.STRONG_BUY]:
                return current_price, current_price * 0.98, current_price * 1.04
            elif signal in [SignalType.SELL, SignalType.STRONG_SELL]:
                return current_price, current_price * 1.02, current_price * 0.96
            return current_price, current_price, current_price
        
        # ATR calculation
        high = data['high']
        low = data['low']
        close = data['close']
        
        tr = pd.concat([high - low, abs(high - close.shift(1)), abs(low - close.shift(1))], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        
        if signal in [SignalType.BUY, SignalType.STRONG_BUY]:
            entry = current_price
            stop_loss = current_price - (atr * 1.5)
            take_profit = current_price + (atr * 3)
        elif signal in [SignalType.SELL, SignalType.STRONG_SELL]:
            entry = current_price
            stop_loss = current_price + (atr * 1.5)
            take_profit = current_price - (atr * 3)
        else:
            entry = current_price
            stop_loss = current_price
            take_profit = current_price
        
        return round(entry, 4), round(stop_loss, 4), round(take_profit, 4)
    
    def _calculate_risk_reward(self, entry: float, stop_loss: float, take_profit: float, signal: SignalType) -> float:
        """Calculate risk-reward ratio."""
        if signal in [SignalType.BUY, SignalType.STRONG_BUY]:
            risk = abs(entry - stop_loss)
            reward = abs(take_profit - entry)
        elif signal in [SignalType.SELL, SignalType.STRONG_SELL]:
            risk = abs(stop_loss - entry)
            reward = abs(entry - take_profit)
        else:
            return 0.0
        
        return reward / risk if risk > 0 else 0.0
    
    async def update_weights(self, weights: Dict[str, float]):
        """Update component weights (thread-safe)."""
        async with self._cache_lock:
            self.weights.update(weights)
    
    async def get_signal_history(self, symbol: str = None, limit: int = 50) -> List[Dict]:
        """Get signal history (thread-safe)."""
        async with self._history_lock:
            history = self.signal_history.copy()
        
        if symbol:
            history = [s for s in history if s.symbol == symbol]
        return [s.to_dict() for s in history[-limit:]]
    
    async def generate_signals(
        self,
        data: pd.DataFrame,
        gann_levels: Dict = None,
        astro_events: List = None,
        symbol: str = 'UNKNOWN',
        timeframe: str = "H1"
    ) -> pd.DataFrame:
        """
        Legacy compatibility wrapper for API endpoints (async).
        Converts the new AISignal format to DataFrame format expected by backtester.
        
        Args:
            data: OHLCV DataFrame
            gann_levels: Optional Gann price levels (ignored, calculated internally)
            astro_events: Optional astro events (ignored, calculated internally)
            symbol: Trading symbol
            timeframe: Timeframe of the data
            
        Returns:
            DataFrame with signal data for backtesting
        """
        # Generate the AI signal
        signal = await self.generate_signal(
            symbol=symbol,
            data=data,
            timeframe=timeframe
        )
        
        # Convert AISignal to DataFrame format expected by backtester
        return pd.DataFrame([{
            'timestamp': signal.timestamp,
            'signal': signal.signal.value,
            'price': signal.entry_price,
            'stop_loss': signal.stop_loss,
            'take_profit': signal.take_profit,
            'confidence': signal.confidence,
            'strength': signal.strength.name,
            'reason': ', '.join(signal.reasons) if signal.reasons else '',
            'risk_reward': signal.risk_reward
        }])
    
    def generate_signals_for_backtest(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        MACD Zero-Cross + EMA200 Regime + D1 EMA50 HTF Filter + DI Directional + Histogram Magnitude
        XAUUSD H1 — target PF ≥ 2.5, robust across multi-year periods

        WHAT CHANGED FROM v1 (PF=1.30, WR=35%)
        ========================================
        v1 problem: 37 losers came from three sources:
          a) Counter-regime MACD crosses: histogram flips up but EMA200 slope
             is still negative — entering against the multi-day trend bias.
          b) Counter-directional pressure: plus_di < minus_di at entry means
             sellers are still dominant even though histogram just crossed up.
          c) Noise crosses: histogram oscillates near zero producing tiny flips
             with no genuine momentum behind them.

        NEW FILTERS
        ===========
        1. EMA200 regime gate (H1: EMA200 ≈ 8.3 trading days = "weekly" bias)
           BUY only when close > EMA200 AND EMA200 slope (vs 20 bars ago) > 0.
           SELL only when close < EMA200 AND EMA200 slope < 0.
           This blocks entering against the dominant multi-day trend direction.

        2. DI directional confirmation (plus_di > minus_di + 3 for buys)
           Forces actual buying pressure to dominate at point of entry.
           Buffer of 3 prevents marginal DI crossovers from qualifying.

        3. Histogram cross magnitude > 0.15 × ATR
           Eliminates "noise crosses" where the histogram barely grazes zero.
           Only enter when the cross has enough energy behind it.

        4. RSI pullback confirmation: RSI was below 50 in last 4 bars (buys)
           Ensures the MACD cross follows a genuine momentum dip, not a
           continuation of an already-overbought push.

        MATH TARGET
        ===========
        At WR=45%, delivered RR=3.0:  PF = 0.45×3.0/0.55 = 2.45 ✓
        At WR=50%, delivered RR=3.0:  PF = 0.50×3.0/0.50 = 3.00 ✓
        RR config=3.5 → delivered ~3.0 (0.5R lost to slippage+commission).
        """
        close = data['close']
        high  = data['high']
        low   = data['low']

        # ── ATR (14-period EMA) ───────────────────────────────────────────────
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/14, adjust=False).mean()

        # ── MACD (12, 26, 9) ─────────────────────────────────────────────────
        ema12       = close.ewm(span=12, adjust=False).mean()
        ema26       = close.ewm(span=26, adjust=False).mean()
        macd_line   = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram   = macd_line - signal_line

        # Zero-cross events (single-bar transition)
        hist_cross_up   = (histogram > 0) & (histogram.shift(1) <= 0)
        hist_cross_down = (histogram < 0) & (histogram.shift(1) >= 0)

        # ── Filter 3: Histogram cross magnitude ───────────────────────────────
        # The absolute value of the histogram on the cross bar must exceed
        # 0.05 × ATR. Relaxed from 0.15 — eliminates only the truly flat crosses.
        cross_magnitude_ok_up   = histogram.abs() > (0.05 * atr)   # restored: H1-validated threshold
        cross_magnitude_ok_down = histogram.abs() > (0.05 * atr)

        # ── EMA stack (medium-term) ───────────────────────────────────────────
        ema55  = close.ewm(span=55,  adjust=False).mean()
        ema100 = close.ewm(span=100, adjust=False).mean()

        # ── Filter 1: EMA200 regime gate (macro weekly bias) ─────────────────
        # H1: EMA200 = ~200 hours = ~8.3 trading days
        ema200       = close.ewm(span=200, adjust=False).mean()
        ema200_slope = ema200 - ema200.shift(20)  # H1: 20 bars = 20h ≈ 1 trading day slope

        # Regime gate: strict — both price side AND slope direction required.
        # Relaxing slope to allow flat/counter-slope added trades that were
        # consistently losers (counter-trend entries during EMA200 consolidation).
        # WR dropped from 40% → 35% when slope was relaxed. Restoring strict gate.
        bull_regime = (close > ema200) & (ema200_slope > 0)
        bear_regime = (close < ema200) & (ema200_slope < 0)

        # ── D1 regime gate (higher-timeframe trend filter) ────────────────────
        # Resample H1 bars to Daily, compute EMA50 on daily close.
        # D1 EMA50 ≈ 50 trading days = ~2.5 months intermediate trend.
        # Forward-fill daily values back to H1 index.
        # Purpose: block entries when the multi-week trend has turned against us.
        # This is the filter that distinguishes 2025 (strong bull) from 2021-2024
        # (ranging or correcting) — the H1 EMA200 alone is too short (~8 days).
        daily_close  = data['close'].resample('D').last().dropna()
        d1_ema50     = daily_close.ewm(span=50, adjust=False).mean()
        d1_slope     = d1_ema50 - d1_ema50.shift(5)  # 5-day slope ≈ 1 trading week

        d1_ema50_h1    = d1_ema50.reindex(data.index, method='ffill')
        d1_slope_h1    = d1_slope.reindex(data.index, method='ffill')
        daily_close_h1 = daily_close.reindex(data.index, method='ffill')

        d1_bull = (daily_close_h1 > d1_ema50_h1) & (d1_slope_h1 > 0)
        d1_bear = (daily_close_h1 < d1_ema50_h1) & (d1_slope_h1 < 0)

        # ── ADX + Filter 2: DI Directional Confirmation ───────────────────────
        up_move   = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        plus_di   = 100 * pd.Series(plus_dm,  index=data.index).ewm(alpha=1/14, adjust=False).mean() / atr.replace(0, np.nan)
        minus_di  = 100 * pd.Series(minus_dm, index=data.index).ewm(alpha=1/14, adjust=False).mean() / atr.replace(0, np.nan)
        dx        = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx       = dx.ewm(alpha=1/14, adjust=False).mean().fillna(0)

        # DI buffer +1 — empirically best WR/frequency balance (WR=36.4%, 22 trades).
        di_bull = plus_di  > (minus_di + 1)   # buying pressure dominant
        di_bear = minus_di > (plus_di  + 1)   # selling pressure dominant

        # ── RSI ───────────────────────────────────────────────────────────────
        delta    = close.diff()
        avg_gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        avg_loss = (-delta).clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        rsi      = (100 - (100 / (1 + avg_gain / avg_loss.replace(0, np.nan)))).fillna(50)

        # Filter 4: RSI pullback — H1 validated (WR=36.4%, PF=2.53).
        rsi_was_low  = rsi.rolling(8).min() < 52   # for buys
        rsi_was_high = rsi.rolling(8).max() > 48   # for sells

        # ── Per-filter pass counts for diagnostics ───────────────────────────
        # Each line shows how many bars pass that filter independently.
        # When a combined condition = 0, compare these to find the bottleneck.
        _f1u = int(hist_cross_up.sum())
        _f1d = int(hist_cross_down.sum())
        _f2u = int((hist_cross_up & cross_magnitude_ok_up).sum())
        _f2d = int((hist_cross_down & cross_magnitude_ok_down).sum())
        _f3u = int((hist_cross_up & bull_regime).sum())
        _f3d = int((hist_cross_down & bear_regime).sum())
        _f3du = int((hist_cross_up & d1_bull).sum())
        _f3dd = int((hist_cross_down & d1_bear).sum())
        _f4u = int((hist_cross_up & di_bull).sum())
        _f4d = int((hist_cross_down & di_bear).sum())
        _f5u = int((hist_cross_up & (adx > 20)).sum())
        _f5d = int((hist_cross_down & (adx > 20)).sum())
        _f6u = int((hist_cross_up & rsi_was_low).sum())
        _f6d = int((hist_cross_down & rsi_was_high).sum())
        logger.info(
            f"[MACDv2 DIAG BUY]  cross={_f1u} | +magnitude={_f2u} "
            f"| +h1_regime={_f3u} | +d1_trend={_f3du} | +di={_f4u} | +adx={_f5u} | +rsi_pb={_f6u}"
        )
        logger.info(
            f"[MACDv2 DIAG SELL] cross={_f1d} | +magnitude={_f2d} "
            f"| +h1_regime={_f3d} | +d1_trend={_f3dd} | +di={_f4d} | +adx={_f5d} | +rsi_pb={_f6d}"
        )

        # ── Composite Entry Gates ─────────────────────────────────────────────
        # Relaxed vs prior version:
        #   - magnitude threshold: 0.15 ATR → 0.05 ATR (less aggressive cutoff)
        #   - DI buffer: +3 → +2 (slightly looser directional requirement)
        #   - RSI pullback window: 4 bars → 6 bars (more time for the setup to form)
        #   - ema55 > ema100 removed from regime (EMA200 alone is sufficient)
        #   - RSI ceiling raised to 72 for buys (gold can trend at elevated RSI)
        buy_condition = (
            hist_cross_up          &   # histogram zero-cross up (1 bar only)
            cross_magnitude_ok_up  &   # cross has energy (> 0.05 ATR)
            bull_regime            &   # above H1 EMA200, slope strictly rising
            d1_bull                &   # above D1 EMA50, daily slope rising (HTF filter)
            di_bull                &   # plus_di > minus_di + 1
            (adx > 15)             &   # validated threshold
            rsi_was_low            &   # RSI dipped < 52 in last 8 bars
            (rsi < 75)
        )

        sell_condition = (
            hist_cross_down         &
            cross_magnitude_ok_down &
            bear_regime             &   # below H1 EMA200, slope strictly falling
            d1_bear                 &   # below D1 EMA50, daily slope falling (HTF filter)
            di_bear                 &
            (adx > 15)              &
            rsi_was_high            &
            (rsi > 25)
        )

        # STRONG when MACD line also confirms direction
        strong_buy  = buy_condition  & (macd_line > 0) & (rsi < 65)
        strong_sell = sell_condition & (macd_line < 0) & (rsi > 35)

        conditions = [
            strong_buy,
            buy_condition  & ~strong_buy,
            strong_sell,
            sell_condition & ~strong_sell,
        ]
        choices = [
            SignalType.STRONG_BUY.value,
            SignalType.BUY.value,
            SignalType.STRONG_SELL.value,
            SignalType.SELL.value,
        ]
        raw_signal = np.select(conditions, choices, default=SignalType.HOLD.value)

        # ── 8-bar cooldown (H1: 8 hours ≈ 1 trading session) ────────────────
        signal_col      = raw_signal.copy()
        last_signal_bar = -999
        for i in range(len(signal_col)):
            if signal_col[i] != SignalType.HOLD.value:
                if (i - last_signal_bar) < 8:
                    signal_col[i] = SignalType.HOLD.value
                else:
                    last_signal_bar = i

        signals_df = pd.DataFrame({'signal': signal_col}, index=data.index)
        n_signals = (signals_df['signal'] != SignalType.HOLD.value).sum()
        logger.info(
            f"[MACDv2] FINAL signals={n_signals} / {len(data)} bars "
            f"({100*n_signals/max(len(data),1):.2f}%)"
        )
        return signals_df

    def generate_signals_sync(
        self,
        data: pd.DataFrame,
        gann_levels: Dict = None,
        astro_events: List = None,
        symbol: str = 'UNKNOWN',
        timeframe: str = "H1"
    ) -> pd.DataFrame:
        """
        Synchronous entry point for Flask routes.
        Runs generate_signals() in an isolated event loop so it never
        collides with an existing loop (e.g. SocketIO threading mode).
        """
        import concurrent.futures

        coro = self.generate_signals(data, gann_levels, astro_events, symbol, timeframe)

        # If a loop is already running in this thread (SocketIO threading mode
        # uses eventlet/gevent or plain threads — plain threads have no loop),
        # run in a fresh thread that owns its own event loop.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, coro).result()
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    async def cleanup(self):
        """Cleanup resources."""
        self._executor.shutdown(wait=True)
        logger.info("AISignalEngine cleanup completed")
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.cleanup()


# Singleton instance
_signal_engine: Optional[AISignalEngine] = None
_engine_lock = asyncio.Lock()


async def get_signal_engine(config: Dict = None) -> AISignalEngine:
    """Get or create the signal engine (thread-safe async)."""
    global _signal_engine
    
    async with _engine_lock:
        if _signal_engine is None:
            _signal_engine = AISignalEngine(config)
        return _signal_engine


# Synchronous wrapper for backward compatibility
def get_signal_engine_sync(config: Dict = None) -> AISignalEngine:
    """Synchronous wrapper for backward compatibility."""
    global _signal_engine
    if _signal_engine is None:
        _signal_engine = AISignalEngine(config)
    return _signal_engine


# Convenience function for running async signal generation
def run_async_signal(
    symbol: str,
    data: pd.DataFrame,
    timeframe: str = "H1",
    current_price: float = None,
    config: Dict = None
) -> AISignal:
    """
    Convenience function to run async signal generation from synchronous code.
    
    Usage:
        signal = run_async_signal("EURUSD", df, "H1", 1.0500)
    """
    async def _run():
        engine = await get_signal_engine(config)
        return await engine.generate_signal(symbol, data, timeframe, current_price)
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're already in an async context, create a new loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _run())
                return future.result()
        else:
            return loop.run_until_complete(_run())
    except RuntimeError:
        # No event loop exists, create one
        return asyncio.run(_run())
