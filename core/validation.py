"""
Input Validation Module for Gann Quant AI Trading System
Provides Pydantic models, validation decorators, SQL injection protection, and rate limiting.
"""

import re
import time
import threading
from functools import wraps
from typing import Optional, List, Dict, Any, Union, Literal
from datetime import datetime, date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from flask import request, jsonify

from loguru import logger


# ============================================================================
# SQL INJECTION PROTECTION
# ============================================================================

# Dangerous SQL patterns to detect
SQL_INJECTION_PATTERNS = [
    r"('|(\\'))",  # Single quotes
    r'("|(\\"))',  # Double quotes
    r';',  # Statement terminator
    r'--',  # SQL comment
    r'/\*',  # Block comment start
    r'\*/',  # Block comment end
    r'\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER|CREATE|TRUNCATE)\b',
    r'\b(EXEC|EXECUTE|EXECSP)\b',
    r'\b(WAITFOR\s+DELAY)\b',
    r'\b(BENCHMARK|SLEEP)\s*\(',
    r'\b(LOAD_FILE|INTO\s+OUTFILE|INTO\s+DUMPFILE)\b',
    r'\b(XP_|SP_)\w*',  # SQL Server extended procedures
    r'\b(DECLARE|CAST|CONVERT)\b',
    r'\\\\x[0-9a-fA-F]{2}',  # Hex encoded
    r'\\\\u[0-9a-fA-F]{4}',  # Unicode encoded
]

# Valid symbol pattern (alphanumeric, dash, underscore, slash, dot)
VALID_SYMBOL_PATTERN = re.compile(r'^[A-Za-z0-9_\-./]{1,20}$')


def sanitize_symbol(symbol: str) -> str:
    """
    Sanitize trading symbol to prevent SQL injection.
    
    Args:
        symbol: Raw symbol string
        
    Returns:
        Sanitized symbol string
        
    Raises:
        ValueError: If symbol contains dangerous patterns
    """
    if not symbol:
        raise ValueError("Symbol cannot be empty")
    
    # Check length
    if len(symbol) > 20:
        raise ValueError(f"Symbol too long: {len(symbol)} characters (max 20)")
    
    # Check for SQL injection patterns (case-insensitive)
    symbol_upper = symbol.upper()
    for pattern in SQL_INJECTION_PATTERNS:
        if re.search(pattern, symbol, re.IGNORECASE):
            logger.warning(f"Potential SQL injection detected in symbol: {symbol}")
            raise ValueError(f"Invalid symbol format: contains forbidden characters")
    
    # Validate against whitelist pattern
    if not VALID_SYMBOL_PATTERN.match(symbol):
        raise ValueError(f"Invalid symbol format: {symbol}. Use only alphanumeric, dash, underscore, slash, or dot.")
    
    return symbol.upper().strip()


def sanitize_symbols(symbols: List[str]) -> List[str]:
    """Sanitize a list of symbols"""
    return [sanitize_symbol(s) for s in symbols]


def sanitize_string(value: str, max_length: int = 500, field_name: str = "value") -> str:
    """
    Sanitize a general string input.
    
    Args:
        value: Raw string value
        max_length: Maximum allowed length
        field_name: Name of the field for error messages
        
    Returns:
        Sanitized string
    """
    if not value:
        return value
    
    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds maximum length of {max_length}")
    
    # Remove null bytes
    value = value.replace('\x00', '')
    
    # Strip whitespace
    value = value.strip()
    
    return value


def validate_positive_number(value: Union[int, float], field_name: str = "value") -> Union[int, float]:
    """Validate that a number is positive"""
    if value <= 0:
        raise ValueError(f"{field_name} must be positive, got: {value}")
    return value


def validate_non_negative_number(value: Union[int, float], field_name: str = "value") -> Union[int, float]:
    """Validate that a number is non-negative"""
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative, got: {value}")
    return value


# ============================================================================
# RATE LIMITING MIDDLEWARE
# ============================================================================

class RateLimiter:
    """
    Thread-safe rate limiter using sliding window algorithm.
    Provides per-IP and global rate limiting.
    """
    
    def __init__(
        self,
        requests_per_second: int = 100,
        requests_per_minute: int = 1000,
        burst_capacity: int = 50,
        per_ip_per_minute: int = 100
    ):
        self._lock = threading.Lock()
        self._requests_per_second = requests_per_second
        self._requests_per_minute = requests_per_minute
        self._burst_capacity = burst_capacity
        self._per_ip_per_minute = per_ip_per_minute
        
        # Global request timestamps
        self._global_requests: List[float] = []
        self._burst_tokens = burst_capacity
        self._last_burst_refill = time.time()
        
        # Per-IP request tracking
        self._ip_requests: Dict[str, List[float]] = {}
    
    def _cleanup_old_requests(self, requests: List[float], window_seconds: float) -> List[float]:
        """Remove requests older than the window"""
        cutoff = time.time() - window_seconds
        return [t for t in requests if t > cutoff]
    
    def _refill_burst_tokens(self):
        """Refill burst tokens at the rate of requests_per_second"""
        now = time.time()
        elapsed = now - self._last_burst_refill
        self._burst_tokens = min(
            self._burst_capacity,
            self._burst_tokens + elapsed * self._requests_per_second
        )
        self._last_burst_refill = now
    
    def check_rate_limit(self, client_ip: str = None) -> tuple:
        """
        Check if request is allowed under rate limits.
        
        Returns:
            Tuple of (allowed: bool, retry_after: float, error_message: str)
        """
        with self._lock:
            now = time.time()
            
            # Cleanup old global requests
            self._global_requests = self._cleanup_old_requests(self._global_requests, 60)
            
            # Check global requests per minute
            if len(self._global_requests) >= self._requests_per_minute:
                retry_after = 60 - (now - self._global_requests[0])
                return False, retry_after, "Global rate limit exceeded. Please retry later."
            
            # Check burst capacity
            self._refill_burst_tokens()
            if self._burst_tokens < 1:
                retry_after = 1.0 / self._requests_per_second
                return False, retry_after, "Burst rate limit exceeded. Please retry later."
            
            # Check per-IP rate limit
            if client_ip:
                if client_ip not in self._ip_requests:
                    self._ip_requests[client_ip] = []
                
                self._ip_requests[client_ip] = self._cleanup_old_requests(
                    self._ip_requests[client_ip], 60
                )
                
                if len(self._ip_requests[client_ip]) >= self._per_ip_per_minute:
                    retry_after = 60 - (now - self._ip_requests[client_ip][0])
                    return False, retry_after, f"Rate limit exceeded for IP {client_ip}. Please retry later."
                
                # Record IP request
                self._ip_requests[client_ip].append(now)
            
            # Consume burst token and record request
            self._burst_tokens -= 1
            self._global_requests.append(now)
            
            return True, 0, ""
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current rate limiter statistics"""
        with self._lock:
            now = time.time()
            self._global_requests = self._cleanup_old_requests(self._global_requests, 60)
            
            return {
                "global_requests_last_minute": len(self._global_requests),
                "burst_tokens_available": int(self._burst_tokens),
                "burst_capacity": self._burst_capacity,
                "tracked_ips": len(self._ip_requests),
                "limits": {
                    "requests_per_second": self._requests_per_second,
                    "requests_per_minute": self._requests_per_minute,
                    "per_ip_per_minute": self._per_ip_per_minute
                }
            }


# Global rate limiter instance
_rate_limiter = RateLimiter(
    requests_per_second=100,
    requests_per_minute=6000,
    burst_capacity=100,
    per_ip_per_minute=200
)


def rate_limit(f):
    """
    Decorator to apply rate limiting to Flask routes.
    Adds X-RateLimit headers to response.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get client IP
        client_ip = request.environ.get('HTTP_X_REAL_IP', request.remote_addr)
        
        # Check rate limit
        allowed, retry_after, error_message = _rate_limiter.check_rate_limit(client_ip)
        
        if not allowed:
            response = jsonify({
                "error": "Rate limit exceeded",
                "message": error_message,
                "retry_after": retry_after
            })
            response.status_code = 429
            response.headers['Retry-After'] = str(int(retry_after) + 1)
            response.headers['X-RateLimit-Limit'] = str(_rate_limiter._requests_per_minute)
            response.headers['X-RateLimit-Remaining'] = '0'
            return response
        
        # Execute the function
        result = f(*args, **kwargs)
        
        # Add rate limit headers to response
        if hasattr(result, 'headers'):
            stats = _rate_limiter.get_stats()
            result.headers['X-RateLimit-Limit'] = str(_rate_limiter._requests_per_minute)
            result.headers['X-RateLimit-Remaining'] = str(
                _rate_limiter._requests_per_minute - stats['global_requests_last_minute']
            )
        
        return result
    
    return decorated_function


# ============================================================================
# PYDANTIC VALIDATION MODELS
# ============================================================================

class TradingStartRequest(BaseModel):
    """Request model for starting trading"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    symbols: List[str] = Field(default_factory=list, max_length=50)
    mode: Literal['paper', 'live', 'backtest'] = Field(default='paper')
    leverage: float = Field(default=1.0, ge=1.0, le=100.0)
    initial_capital: float = Field(default=100000.0, ge=1000.0)
    max_positions: int = Field(default=5, ge=1, le=50)
    risk_per_trade: float = Field(default=1.0, ge=0.1, le=10.0)
    
    @field_validator('symbols')
    @classmethod
    def validate_symbols(cls, v):
        """Validate and sanitize all symbols"""
        if not v:
            return v
        return sanitize_symbols(v)
    
    @field_validator('leverage')
    @classmethod
    def validate_leverage(cls, v):
        """Validate leverage is reasonable"""
        if v > 50:
            logger.warning(f"High leverage requested: {v}x")
        return v


class OrderRequest(BaseModel):
    """Request model for creating an order"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    symbol: str = Field(..., min_length=1, max_length=20)
    side: Literal['buy', 'sell', 'BUY', 'SELL']
    quantity: float = Field(..., gt=0)
    price: Optional[float] = Field(default=None, ge=0)
    order_type: Literal['market', 'limit', 'stop', 'stop_limit'] = Field(default='market')
    stop_loss: Optional[float] = Field(default=None, ge=0)
    take_profit: Optional[float] = Field(default=None, ge=0)
    time_in_force: Literal['GTC', 'IOC', 'FOK', 'DAY'] = Field(default='GTC')
    reduce_only: bool = Field(default=False)
    post_only: bool = Field(default=False)
    
    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v):
        """Validate and sanitize symbol"""
        return sanitize_symbol(v)
    
    @field_validator('side')
    @classmethod
    def normalize_side(cls, v):
        """Normalize side to uppercase"""
        return v.upper()
    
    @model_validator(mode='after')
    def validate_order_constraints(self):
        """Validate order-specific constraints"""
        # Limit orders must have a price
        if self.order_type in ['limit', 'stop_limit'] and self.price is None:
            raise ValueError(f"{self.order_type} orders require a price")
        
        # Stop orders must have a trigger price (we use stop_loss field for this)
        if self.order_type in ['stop', 'stop_limit'] and self.stop_loss is None:
            raise ValueError(f"{self.order_type} orders require a stop price")
        
        # Validate stop_loss and take_profit logic for buy orders
        if self.side == 'BUY':
            if self.stop_loss is not None and self.price is not None and self.stop_loss >= self.price:
                raise ValueError("For buy orders, stop_loss must be below entry price")
            if self.take_profit is not None and self.price is not None and self.take_profit <= self.price:
                raise ValueError("For buy orders, take_profit must be above entry price")
        
        # Validate stop_loss and take_profit logic for sell orders
        if self.side == 'SELL':
            if self.stop_loss is not None and self.price is not None and self.stop_loss <= self.price:
                raise ValueError("For sell orders, stop_loss must be above entry price")
            if self.take_profit is not None and self.price is not None and self.take_profit >= self.price:
                raise ValueError("For sell orders, take_profit must be below entry price")
        
        return self


class PositionCloseRequest(BaseModel):
    """Request model for closing a position"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    position_id: Optional[str] = Field(default=None, max_length=50)
    symbol: str = Field(..., min_length=1, max_length=20)
    quantity: Optional[float] = Field(default=None, gt=0, description="Quantity to close, None for full position")
    reason: Optional[str] = Field(default=None, max_length=200)
    
    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v):
        """Validate and sanitize symbol"""
        return sanitize_symbol(v)
    
    @field_validator('position_id')
    @classmethod
    def validate_position_id(cls, v):
        """Validate position ID format"""
        if v is None:
            return v
        # Allow alphanumeric with dash and underscore
        if not re.match(r'^[A-Za-z0-9_\-]+$', v):
            raise ValueError("Invalid position_id format")
        return v


class RiskCalculateRequest(BaseModel):
    """Request model for calculating position size based on risk"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    account_balance: float = Field(..., gt=0, description="Total account balance")
    risk_percent: float = Field(..., gt=0, le=20, description="Risk percentage per trade")
    entry_price: float = Field(..., gt=0, description="Entry price")
    stop_loss: float = Field(..., gt=0, description="Stop loss price")
    max_risk_amount: Optional[float] = Field(default=None, gt=0, description="Maximum risk amount in currency")
    reward_ratio: float = Field(default=2.0, ge=1.0, le=10.0, description="Risk/reward ratio target")
    
    @model_validator(mode='after')
    def validate_prices(self):
        """Validate entry and stop loss prices"""
        if self.entry_price == self.stop_loss:
            raise ValueError("Entry price and stop loss cannot be the same")
        return self


class ScannerRequest(BaseModel):
    """Request model for market scanner"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    symbols: List[str] = Field(default_factory=lambda: ['BTC-USD', 'ETH-USD'], max_length=100)
    timeframe: Literal['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'] = Field(default='1d')
    indicators: List[str] = Field(
        default_factory=lambda: ['mama_fama', 'gann_levels', 'rsi'],
        max_length=20
    )
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    signal_type: Optional[Literal['buy', 'sell', 'both']] = Field(default='both')
    scan_mode: Literal['quick', 'standard', 'deep'] = Field(default='standard')
    
    @field_validator('symbols')
    @classmethod
    def validate_symbols(cls, v):
        """Validate and sanitize all symbols"""
        if not v:
            raise ValueError("At least one symbol is required")
        return sanitize_symbols(v)
    
    @field_validator('indicators')
    @classmethod
    def validate_indicators(cls, v):
        """Validate indicator names"""
        allowed_indicators = {
            'mama_fama', 'gann_levels', 'rsi', 'macd', 'bollinger',
            'ema_cross', 'fibonacci', 'pivot_points', 'volume_profile',
            'order_flow', 'vwap', 'atr', 'supertrend', 'ichimoku',
            'candlestick_patterns', 'harmonic_patterns', 'wave_analysis',
            'astro_cycles', 'ml_prediction', 'all'
        }
        for ind in v:
            if ind.lower() not in allowed_indicators:
                logger.warning(f"Unknown indicator: {ind}")
        return [ind.lower() for ind in v]


class ConfigUpdateRequest(BaseModel):
    """Request model for configuration updates"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    config_type: Literal[
        'gann', 'ehlers', 'astro', 'ml', 'risk', 'scanner',
        'strategy', 'broker', 'notifier', 'options', 'hft',
        'backtest', 'alerts', 'trading-modes', 'strategy-weights'
    ]
    config_data: Dict[str, Any] = Field(...)
    
    @field_validator('config_data')
    @classmethod
    def validate_config_data(cls, v):
        """Validate config data is not empty and has reasonable size"""
        if not v:
            raise ValueError("config_data cannot be empty")
        
        # Check for reasonable size (prevent memory exhaustion)
        import json
        try:
            data_str = json.dumps(v)
            if len(data_str) > 100000:  # 100KB max
                raise ValueError("Configuration data too large (max 100KB)")
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid configuration data: {e}")
        
        return v


class BacktestRequest(BaseModel):
    """Request model for running a backtest"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    symbol: str = Field(default='BTC-USD', min_length=1, max_length=20)
    start_date: str = Field(default='2022-01-01', pattern=r'^\d{4}-\d{2}-\d{2}$')
    end_date: str = Field(default='2023-12-31', pattern=r'^\d{4}-\d{2}-\d{2}$')
    initial_capital: float = Field(default=100000.0, ge=1000.0)
    timeframe: Literal['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'] = Field(default='1d')
    strategy: Optional[str] = Field(default=None, max_length=50)
    
    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v):
        """Validate and sanitize symbol"""
        return sanitize_symbol(v)
    
    @model_validator(mode='after')
    def validate_dates(self):
        """Validate date range"""
        try:
            start = datetime.strptime(self.start_date, '%Y-%m-%d')
            end = datetime.strptime(self.end_date, '%Y-%m-%d')
            
            if start >= end:
                raise ValueError("start_date must be before end_date")
            
            if end > datetime.now():
                raise ValueError("end_date cannot be in the future")
            
            # Limit backtest period to 5 years
            if (end - start).days > 365 * 5:
                raise ValueError("Backtest period cannot exceed 5 years")
            
        except ValueError as e:
            raise ValueError(f"Invalid date format: {e}")
        
        return self


class MarketDataRequest(BaseModel):
    """Request model for market data"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    timeframe: Literal['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w', '1M'] = Field(default='1d')
    start_date: Optional[str] = Field(default=None, pattern=r'^\d{4}-\d{2}-\d{2}$')
    end_date: Optional[str] = Field(default=None, pattern=r'^\d{4}-\d{2}-\d{2}$')
    limit: int = Field(default=500, ge=1, le=10000)
    include_indicators: bool = Field(default=False)


class SignalRequest(BaseModel):
    """Request model for signal generation"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    symbol: str = Field(..., min_length=1, max_length=20)
    timeframe: Literal['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'] = Field(default='1d')
    strategies: List[str] = Field(default_factory=lambda: ['gann', 'ehlers', 'astro'])
    
    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v):
        """Validate and sanitize symbol"""
        return sanitize_symbol(v)


class ForecastRequest(BaseModel):
    """Request model for forecasting"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    symbol: str = Field(default='BTC-USD', min_length=1, max_length=20)
    forecast_days: int = Field(default=7, ge=1, le=365)
    method: Literal['gann', 'ml', 'astro', 'ensemble'] = Field(default='ensemble')
    
    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v):
        """Validate and sanitize symbol"""
        return sanitize_symbol(v)


# ============================================================================
# VALIDATION DECORATORS
# ============================================================================

def validate_request(model_class: type[BaseModel], source: str = 'json'):
    """
    Decorator to validate Flask request using Pydantic model.
    
    Args:
        model_class: Pydantic model class to validate against
        source: Where to get data from ('json', 'args', 'form')
    
    Usage:
        @validate_request(OrderRequest)
        def create_order():
            data = request.validated_data  # Already validated
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                # Get data from specified source
                if source == 'json':
                    data = request.json or {}
                elif source == 'args':
                    data = request.args.to_dict()
                elif source == 'form':
                    data = request.form.to_dict()
                else:
                    data = {}
                
                # Validate using Pydantic model
                validated = model_class(**data)
                
                # Store validated data on request
                request.validated_data = validated
                
                return f(*args, **kwargs)
                
            except ValueError as e:
                logger.warning(f"Validation error in {f.__name__}: {e}")
                return jsonify({
                    "error": "Validation error",
                    "message": str(e),
                    "field": getattr(e, 'field', None)
                }), 400
            except Exception as e:
                # Handle Pydantic validation errors
                if hasattr(e, 'errors'):
                    errors = e.errors()
                    error_messages = [
                        f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
                        for err in errors
                    ]
                    logger.warning(f"Validation errors in {f.__name__}: {error_messages}")
                    return jsonify({
                        "error": "Validation error",
                        "messages": error_messages,
                        "details": errors
                    }), 400
                
                logger.error(f"Unexpected validation error in {f.__name__}: {e}")
                return jsonify({
                    "error": "Validation error",
                    "message": str(e)
                }), 400
        
        return decorated_function
    
    return decorator


def validate_symbol_param(f):
    """
    Decorator to validate symbol in URL path parameter.
    Expects 'symbol' as a keyword argument.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        symbol = kwargs.get('symbol')
        if symbol:
            try:
                kwargs['symbol'] = sanitize_symbol(symbol)
            except ValueError as e:
                return jsonify({
                    "error": "Invalid symbol",
                    "message": str(e)
                }), 400
        return f(*args, **kwargs)
    
    return decorated_function


def validate_json_fields(*required_fields: str):
    """
    Decorator to validate that specific JSON fields are present.
    
    Usage:
        @validate_json_fields('symbol', 'side', 'quantity')
        def create_order():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            data = request.json or {}
            missing = [field for field in required_fields if field not in data]
            
            if missing:
                return jsonify({
                    "error": "Missing required fields",
                    "missing_fields": missing
                }), 400
            
            return f(*args, **kwargs)
        
        return decorated_function
    
    return decorator


# ============================================================================
# FLASK MIDDLEWARE FOR RATE LIMITING
# ============================================================================

def init_rate_limiting(app):
    """
    Initialize rate limiting middleware for Flask app.
    
    Usage:
        from core.validation import init_rate_limiting
        init_rate_limiting(app)
    """
    @app.before_request
    def check_rate_limit():
        """Check rate limit before processing request"""
        # Skip rate limiting for health checks and static files
        if request.path in ['/api/health', '/health'] or request.path.startswith('/static'):
            return None
        
        # Get client IP
        client_ip = request.environ.get('HTTP_X_REAL_IP', request.remote_addr)
        
        # Check rate limit
        allowed, retry_after, error_message = _rate_limiter.check_rate_limit(client_ip)
        
        if not allowed:
            response = jsonify({
                "error": "Rate limit exceeded",
                "message": error_message,
                "retry_after": retry_after
            })
            response.status_code = 429
            response.headers['Retry-After'] = str(int(retry_after) + 1)
            return response
        
        return None
    
    @app.route('/api/rate-limit-stats')
    def rate_limit_stats():
        """Get rate limiter statistics"""
        return jsonify(_rate_limiter.get_stats())
    
    logger.info("Rate limiting middleware initialized")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_client_ip() -> str:
    """Get the client's real IP address from request"""
    return request.environ.get(
        'HTTP_X_REAL_IP',
        request.environ.get(
            'HTTP_X_FORWARDED_FOR',
            request.remote_addr
        )
    )


def format_validation_error(error: Exception) -> Dict[str, Any]:
    """Format a validation error for API response"""
    if hasattr(error, 'errors'):
        errors = error.errors()
        return {
            "error": "Validation failed",
            "details": [
                {
                    "field": ".".join(str(loc) for loc in err.get('loc', [])),
                    "message": err.get('msg', str(err)),
                    "type": err.get('type', 'value_error')
                }
                for err in errors
            ]
        }
    
    return {
        "error": "Validation failed",
        "message": str(error)
    }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Pydantic Models
    'TradingStartRequest',
    'OrderRequest',
    'PositionCloseRequest',
    'RiskCalculateRequest',
    'ScannerRequest',
    'ConfigUpdateRequest',
    'BacktestRequest',
    'MarketDataRequest',
    'SignalRequest',
    'ForecastRequest',
    
    # Validation Decorators
    'validate_request',
    'validate_symbol_param',
    'validate_json_fields',
    'rate_limit',
    
    # Sanitization Functions
    'sanitize_symbol',
    'sanitize_symbols',
    'sanitize_string',
    'validate_positive_number',
    'validate_non_negative_number',
    
    # Rate Limiting
    'RateLimiter',
    'init_rate_limiting',
    '_rate_limiter',
    
    # Utilities
    'get_client_ip',
    'format_validation_error',
]
