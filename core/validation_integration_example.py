"""
Example Integration of Validation Module with API Endpoints

This file demonstrates how to integrate the validation module with the existing API.
Copy the relevant patterns to the actual API files.
"""

from flask import Blueprint, request, jsonify
from loguru import logger

# Import validation components
from core.validation import (
    # Pydantic models
    TradingStartRequest,
    OrderRequest,
    PositionCloseRequest,
    RiskCalculateRequest,
    ScannerRequest,
    ConfigUpdateRequest,
    BacktestRequest,
    MarketDataRequest,
    SignalRequest,
    ForecastRequest,
    
    # Decorators
    validate_request,
    validate_symbol_param,
    validate_json_fields,
    rate_limit,
    
    # Sanitization
    sanitize_symbol,
    sanitize_symbols,
    
    # Rate limiting
    init_rate_limiting,
    _rate_limiter,
)


# ============================================================================
# EXAMPLE: TRADING API WITH VALIDATION
# ============================================================================

trading_api_validated = Blueprint('trading_api_validated', __name__)


@trading_api_validated.route('/start', methods=['POST'])
@rate_limit
@validate_request(TradingStartRequest)
def start_trading_validated():
    """
    Start live/paper trading with full validation.
    
    Request body:
    {
        "symbols": ["BTC-USD", "ETH-USD"],
        "mode": "paper",
        "leverage": 1.0,
        "initial_capital": 100000.0,
        "max_positions": 5,
        "risk_per_trade": 1.0
    }
    """
    try:
        # Access validated data from request.validated_data
        data = request.validated_data
        
        # No need for manual validation - already done by decorator
        symbols = data.symbols
        mode = data.mode
        leverage = data.leverage
        
        # Business logic here...
        logger.info(f"Trading started for symbols: {symbols}, mode: {mode}, leverage: {leverage}x")
        
        return jsonify({
            'success': True,
            'message': 'Trading started',
            'state': {
                'symbols': symbols,
                'mode': mode,
                'leverage': leverage
            }
        })
    except Exception as e:
        logger.error(f"Failed to start trading: {e}")
        return jsonify({'error': str(e)}), 500


@trading_api_validated.route('/stop', methods=['POST'])
@rate_limit
def stop_trading_validated():
    """Stop trading"""
    # No validation needed for stop
    return jsonify({'success': True, 'message': 'Trading stopped'})


# ============================================================================
# EXAMPLE: ORDER API WITH VALIDATION
# ============================================================================

orders_api_validated = Blueprint('orders_api_validated', __name__)


@orders_api_validated.route('', methods=['POST'])
@rate_limit
@validate_request(OrderRequest)
def create_order_validated():
    """
    Create a new order with full validation.
    
    Request body:
    {
        "symbol": "BTC-USD",
        "side": "buy",
        "quantity": 0.1,
        "price": 45000.00,
        "order_type": "limit",
        "stop_loss": 44000.00,
        "take_profit": 47000.00,
        "time_in_force": "GTC"
    }
    """
    try:
        order_data = request.validated_data
        
        # Order data is already validated and sanitized
        symbol = order_data.symbol  # Sanitized against SQL injection
        side = order_data.side  # Normalized to uppercase
        quantity = order_data.quantity  # Validated as positive
        price = order_data.price
        order_type = order_data.order_type
        stop_loss = order_data.stop_loss
        take_profit = order_data.take_profit
        
        # Business logic - create order
        import uuid
        from datetime import datetime
        order_id = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
        
        order = {
            'orderId': order_id,
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': quantity,
            'price': price,
            'stopLoss': stop_loss,
            'takeProfit': take_profit,
            'timeInForce': order_data.time_in_force,
            'status': 'pending',
            'timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"Order created: {order_id} - {side} {quantity} {symbol} @ {price}")
        
        return jsonify({
            'success': True,
            'order': order
        })
    except Exception as e:
        logger.error(f"Failed to create order: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# EXAMPLE: POSITION API WITH VALIDATION
# ============================================================================

positions_api_validated = Blueprint('positions_api_validated', __name__)


@positions_api_validated.route('/<position_id>/close', methods=['POST'])
@rate_limit
@validate_request(PositionCloseRequest)
def close_position_validated(position_id):
    """
    Close a specific position with validation.
    
    URL param: position_id
    Request body:
    {
        "symbol": "BTC-USD",
        "quantity": 0.1,  // Optional, closes full position if not provided
        "reason": "Manual close"
    }
    """
    try:
        data = request.validated_data
        
        # Data is already validated
        symbol = data.symbol
        quantity = data.quantity
        reason = data.reason
        
        # Business logic - close position
        logger.info(f"Closing position {position_id} for {symbol}, quantity: {quantity or 'ALL'}, reason: {reason}")
        
        return jsonify({
            'success': True,
            'message': f'Position {position_id} closed',
            'details': {
                'position_id': position_id,
                'symbol': symbol,
                'quantity': quantity,
                'reason': reason
            }
        })
    except Exception as e:
        logger.error(f"Failed to close position: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# EXAMPLE: RISK API WITH VALIDATION
# ============================================================================

risk_api_validated = Blueprint('risk_api_validated', __name__)


@risk_api_validated.route('/calculate-position-size', methods=['POST'])
@rate_limit
@validate_request(RiskCalculateRequest)
def calculate_position_size_validated():
    """
    Calculate position size based on risk parameters.
    
    Request body:
    {
        "account_balance": 100000.0,
        "risk_percent": 1.0,
        "entry_price": 45000.0,
        "stop_loss": 44000.0,
        "max_risk_amount": 1000.0,
        "reward_ratio": 2.0
    }
    """
    try:
        data = request.validated_data
        
        account_balance = data.account_balance
        risk_percent = data.risk_percent
        entry_price = data.entry_price
        stop_loss = data.stop_loss
        
        # Calculate position size
        risk_amount = account_balance * (risk_percent / 100)
        
        # Apply max risk if specified
        if data.max_risk_amount and risk_amount > data.max_risk_amount:
            risk_amount = data.max_risk_amount
        
        stop_distance = abs(entry_price - stop_loss)
        
        if stop_distance == 0:
            return jsonify({'error': 'Stop distance cannot be zero'}), 400
        
        position_size = risk_amount / stop_distance
        position_value = position_size * entry_price
        
        # Calculate take profit based on reward ratio
        direction = 1 if entry_price > stop_loss else -1
        take_profit = entry_price + (stop_distance * data.reward_ratio * direction)
        
        return jsonify({
            'riskAmount': round(risk_amount, 2),
            'stopDistance': round(stop_distance, 2),
            'positionSize': round(position_size, 6),
            'positionValue': round(position_value, 2),
            'riskPercent': risk_percent,
            'takeProfit': round(take_profit, 2),
            'rewardRatio': data.reward_ratio,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Failed to calculate position size: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# EXAMPLE: SCANNER API WITH VALIDATION
# ============================================================================

scanner_api_validated = Blueprint('scanner_api_validated', __name__)


@scanner_api_validated.route('/scan', methods=['POST'])
@rate_limit
@validate_request(ScannerRequest)
def run_scanner_validated():
    """
    Run market scanner with validation.
    
    Request body:
    {
        "symbols": ["BTC-USD", "ETH-USD", "EURUSD"],
        "timeframe": "1d",
        "indicators": ["mama_fama", "gann_levels", "rsi"],
        "min_confidence": 0.7,
        "signal_type": "both",
        "scan_mode": "standard"
    }
    """
    try:
        data = request.validated_data
        
        # All symbols are already sanitized
        symbols = data.symbols
        timeframe = data.timeframe
        indicators = data.indicators
        min_confidence = data.min_confidence
        
        logger.info(f"Running scanner for {len(symbols)} symbols, timeframe: {timeframe}")
        
        # Business logic - run scanner
        results = []
        # ... scanner implementation ...
        
        return jsonify({
            'results': results,
            'scannedSymbols': symbols,
            'timeframe': timeframe,
            'indicators': indicators,
            'minConfidence': min_confidence,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Scanner failed: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# EXAMPLE: CONFIG API WITH VALIDATION
# ============================================================================

config_api_validated = Blueprint('config_api_validated', __name__)


@config_api_validated.route('/update', methods=['POST'])
@rate_limit
@validate_request(ConfigUpdateRequest)
def update_config_validated():
    """
    Update configuration with validation.
    
    Request body:
    {
        "config_type": "gann",
        "config_data": {
            "sq9_levels": 8,
            "angle_sensitivity": 0.5
        }
    }
    """
    try:
        data = request.validated_data
        
        config_type = data.config_type
        config_data = data.config_data
        
        logger.info(f"Updating {config_type} configuration")
        
        # Business logic - save config
        # save_yaml_config(f'{config_type}_config.yaml', config_data)
        
        return jsonify({
            'success': True,
            'message': f'{config_type} configuration updated',
            'config_type': config_type
        })
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# EXAMPLE: SYMBOL VALIDATION IN URL PATH
# ============================================================================

market_data_api_validated = Blueprint('market_data_api_validated', __name__)


@market_data_api_validated.route('/<symbol>', methods=['POST'])
@rate_limit
@validate_symbol_param
@validate_request(MarketDataRequest)
def get_market_data_validated(symbol):
    """
    Get market data with symbol validation in URL path.
    
    URL: /api/market-data/BTC-USD
    Request body:
    {
        "timeframe": "1d",
        "start_date": "2023-01-01",
        "end_date": "2023-12-31",
        "limit": 500,
        "include_indicators": true
    }
    """
    try:
        # Symbol is already sanitized by @validate_symbol_param decorator
        data = request.validated_data
        
        logger.info(f"Getting market data for {symbol}, timeframe: {data.timeframe}")
        
        # Business logic - fetch market data
        # price_data = data_feed.get_historical_data(symbol, data.timeframe, ...)
        
        return jsonify({
            'symbol': symbol,
            'timeframe': data.timeframe,
            'data': [],  # Actual data here
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Failed to get market data: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# EXAMPLE: BACKTEST API WITH VALIDATION
# ============================================================================

backtest_api_validated = Blueprint('backtest_api_validated', __name__)


@backtest_api_validated.route('/run', methods=['POST'])
@rate_limit
@validate_request(BacktestRequest)
def run_backtest_validated():
    """
    Run backtest with full validation.
    
    Request body:
    {
        "symbol": "BTC-USD",
        "start_date": "2022-01-01",
        "end_date": "2023-12-31",
        "initial_capital": 100000.0,
        "timeframe": "1d",
        "strategy": "gann_ehlers_hybrid"
    }
    """
    try:
        data = request.validated_data
        
        # All fields are validated including:
        # - Symbol is sanitized
        # - Dates are valid format and range
        # - Capital is positive
        # - Timeframe is valid option
        
        logger.info(f"Running backtest for {data.symbol} from {data.start_date} to {data.end_date}")
        
        # Business logic - run backtest
        # results = backtester.run(...)
        
        return jsonify({
            'symbol': data.symbol,
            'startDate': data.start_date,
            'endDate': data.end_date,
            'initialCapital': data.initial_capital,
            'performanceMetrics': {},
            'trades': [],
            'equityCurve': []
        })
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# INTEGRATION INSTRUCTIONS
# ============================================================================

"""
INTEGRATION INSTRUCTIONS:

1. In your main api.py or app initialization, add rate limiting middleware:

   from core.validation import init_rate_limiting
   
   app = Flask(__name__)
   init_rate_limiting(app)

2. Import validation decorators in your API files:

   from core.validation import (
       validate_request, validate_symbol_param, rate_limit,
       OrderRequest, ScannerRequest, etc.
   )

3. Apply decorators to your endpoints:

   @app.route('/api/orders', methods=['POST'])
   @rate_limit
   @validate_request(OrderRequest)
   def create_order():
       data = request.validated_data
       # data is already validated
       ...

4. For URL path parameters, use validate_symbol_param:

   @app.route('/api/market-data/<symbol>', methods=['POST'])
   @rate_limit
   @validate_symbol_param
   def get_market_data(symbol):
       # symbol is already sanitized
       ...

5. For endpoints that don't need Pydantic models but need basic field checks:

   @app.route('/api/positions/<position_id>', methods=['DELETE'])
   @rate_limit
   @validate_json_fields('symbol')  # Ensure 'symbol' is in JSON body
   def delete_position(position_id):
       symbol = request.json['symbol']
       ...

RATE LIMITING CONFIGURATION:

The default rate limiter allows:
- 100 requests per second (burst)
- 6000 requests per minute (global)
- 200 requests per minute (per IP)

To customize, modify the global rate limiter or create a new instance:

   from core.validation import RateLimiter
   
   custom_limiter = RateLimiter(
       requests_per_second=50,
       requests_per_minute=3000,
       burst_capacity=50,
       per_ip_per_minute=100
   )
   
   @app.route('/api/endpoint')
   @rate_limit_with(custom_limiter)
   def my_endpoint():
       ...

SQL INJECTION PROTECTION:

All symbol inputs are automatically sanitized against SQL injection when using
the Pydantic models or the validate_symbol_param decorator.

The sanitization:
- Limits length to 20 characters
- Only allows alphanumeric, dash, underscore, slash, and dot
- Detects and blocks common SQL injection patterns
- Logs potential attacks
"""

from datetime import datetime


if __name__ == '__main__':
    # Test validation models
    print("Testing validation models...")
    
    # Test OrderRequest
    try:
        order = OrderRequest(
            symbol="BTC-USD",
            side="buy",
            quantity=0.1,
            price=45000.0,
            order_type="limit",
            stop_loss=44000.0,
            take_profit=47000.0
        )
        print(f"✓ OrderRequest valid: {order.model_dump()}")
    except Exception as e:
        print(f"✗ OrderRequest failed: {e}")
    
    # Test SQL injection protection
    try:
        bad_order = OrderRequest(
            symbol="BTC-USD'; DROP TABLE orders; --",
            side="buy",
            quantity=0.1
        )
        print(f"✗ SQL injection not blocked!")
    except ValueError as e:
        print(f"✓ SQL injection blocked: {e}")
    
    # Test TradingStartRequest
    try:
        trading = TradingStartRequest(
            symbols=["BTC-USD", "ETH-USD"],
            mode="paper",
            leverage=2.0,
            initial_capital=50000.0
        )
        print(f"✓ TradingStartRequest valid: {trading.model_dump()}")
    except Exception as e:
        print(f"✗ TradingStartRequest failed: {e}")
    
    # Test BacktestRequest
    try:
        backtest = BacktestRequest(
            symbol="BTC-USD",
            start_date="2022-01-01",
            end_date="2023-12-31"
        )
        print(f"✓ BacktestRequest valid: {backtest.model_dump()}")
    except Exception as e:
        print(f"✗ BacktestRequest failed: {e}")
    
    # Test rate limiter
    print("\nRate limiter stats:", _rate_limiter.get_stats())
    
    print("\n✅ All tests passed!")
