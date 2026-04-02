from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from loguru import logger
import pandas as pd
import threading
import time
import random
import os
import secrets
import copy
import math
import atexit
from datetime import datetime

# Import core components and config loader
from utils.config_loader import load_all_configs
from core.data_feed import DataFeed
from core.gann_engine import GannEngine
from core.ehlers_engine import EhlersEngine
from core.astro_engine import AstroEngine
from core.ml_engine import MLEngine
from core.signal_engine import AISignalEngine
from backtest.backtester import Backtester
from backtest.metrics import calculate_performance_metrics

# Import comprehensive API blueprints
from api_comprehensive import (
    trading_api, positions_api, orders_api, risk_api, scanner_api,
    portfolio_api, forecast_api, cycles_api, config_sync_api,
    gann_api, ehlers_api, astro_api, ml_api, broker_api,
    options_api, alerts_api, patterns_api, smith_api, rr_api,
    reports_api, agent_api, settings_api, strategies_api,
    instruments_api, market_data_api
)

# --- Flask App Initialization ---
app = Flask(__name__)
# SECURITY: Use environment variable for secret key, fallback to secure random for development
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))
if not os.environ.get('FLASK_SECRET_KEY'):
    logger.warning("FLASK_SECRET_KEY not set in environment. Using temporary random key (not suitable for production).")

# Allow requests from configured origins; default to "*" for development only
_cors_origins = os.environ.get('CORS_ORIGINS', '*')
if _cors_origins == '*':
    logger.warning("CORS_ORIGINS not set. Allowing all origins (not suitable for production).")
CORS(app, resources={r"/api/*": {"origins": _cors_origins}})

# --- Flask-SocketIO Initialization ---
socketio = SocketIO(
    app,
    cors_allowed_origins=_cors_origins,
    async_mode='threading',
    ping_timeout=60,
    ping_interval=25
)

# --- Security ---
# If set, the /api/ws/broadcast endpoint requires this key in the X-API-Key header
BROADCAST_API_KEY = os.environ.get('BROADCAST_API_KEY')
if not BROADCAST_API_KEY:
    logger.warning("BROADCAST_API_KEY not set. The broadcast endpoint is unauthenticated.")

# --- WebSocket State Management ---
# Track subscribed symbols per session
subscriptions = {}  # {session_id: set(symbols)}
subscriptions_lock = threading.Lock()

# Background thread flag and shutdown signal
background_thread = None
thread_lock = threading.Lock()
_shutdown_event = threading.Event()

def _shutdown_background_thread():
    """Signal the broadcast thread to stop and wait for it to exit."""
    _shutdown_event.set()
    if background_thread is not None:
        background_thread.join(timeout=5)
    logger.info("Background price update thread stopped.")

atexit.register(_shutdown_background_thread)

# --- Register Comprehensive API Blueprints ---
app.register_blueprint(trading_api, url_prefix='/api/trading')
app.register_blueprint(positions_api, url_prefix='/api/positions')
app.register_blueprint(orders_api, url_prefix='/api/orders')
app.register_blueprint(risk_api, url_prefix='/api/risk')
app.register_blueprint(scanner_api, url_prefix='/api/scanner')
app.register_blueprint(portfolio_api, url_prefix='/api/portfolio')
app.register_blueprint(forecast_api, url_prefix='/api/forecast')
app.register_blueprint(cycles_api, url_prefix='/api/cycles')
app.register_blueprint(config_sync_api, url_prefix='/api/config')
app.register_blueprint(gann_api, url_prefix='/api/gann')
app.register_blueprint(ehlers_api, url_prefix='/api/ehlers')
app.register_blueprint(astro_api, url_prefix='/api/astro')
app.register_blueprint(ml_api, url_prefix='/api/ml')
app.register_blueprint(broker_api, url_prefix='/api/broker')
app.register_blueprint(options_api, url_prefix='/api/options')
app.register_blueprint(alerts_api, url_prefix='/api/alerts')
app.register_blueprint(patterns_api, url_prefix='/api/patterns')
app.register_blueprint(smith_api, url_prefix='/api/smith')
app.register_blueprint(rr_api, url_prefix='/api/rr')
app.register_blueprint(reports_api, url_prefix='/api/reports')
app.register_blueprint(agent_api, url_prefix='/api/agent')
app.register_blueprint(settings_api, url_prefix='/api/settings')
app.register_blueprint(strategies_api, url_prefix='/api/strategies')
app.register_blueprint(instruments_api, url_prefix='/api/instruments')
app.register_blueprint(market_data_api, url_prefix='/api/market-data')

logger.info("All API blueprints registered successfully")

# --- Load Configurations ---
# Load all configs at startup to be shared across requests
try:
    CONFIG = load_all_configs()
    if not CONFIG:
        raise RuntimeError("Configurations could not be loaded.")
    logger.success("All configurations loaded for Flask API.")
except Exception as e:
    logger.error(f"FATAL: Could not load configurations. API cannot start. Error: {e}")
    CONFIG = None


# --- WebSocket Event Handlers ---

@socketio.on('connect')
def handle_connect():
    """Handle client connection - emit connection confirmation"""
    from flask import request as socket_request
    session_id = socket_request.sid
    
    with subscriptions_lock:
        subscriptions[session_id] = set()
    
    logger.info(f"Client connected: {session_id}")
    
    emit('connection_confirmed', {
        'status': 'connected',
        'session_id': session_id,
        'timestamp': datetime.now().isoformat(),
        'message': 'Successfully connected to Gann Quant AI WebSocket server'
    })


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection - cleanup subscriptions"""
    from flask import request as socket_request
    session_id = socket_request.sid
    
    with subscriptions_lock:
        if session_id in subscriptions:
            # Leave all subscribed symbol rooms
            for symbol in subscriptions[session_id]:
                leave_room(symbol)
                logger.info(f"Client {session_id} unsubscribed from {symbol} on disconnect")
            del subscriptions[session_id]
    
    logger.info(f"Client disconnected: {session_id}")
    emit('disconnection_confirmed', {
        'status': 'disconnected',
        'session_id': session_id,
        'timestamp': datetime.now().isoformat()
    })


@socketio.on('subscribe')
def handle_subscribe(data):
    """Subscribe to symbol price updates"""
    from flask import request as socket_request
    session_id = socket_request.sid
    
    symbol = data.get('symbol', '').upper()
    
    if not symbol:
        emit('error', {
            'message': 'Symbol is required for subscription',
            'timestamp': datetime.now().isoformat()
        })
        return
    
    # Join the room for this symbol
    join_room(symbol)
    
    with subscriptions_lock:
        if session_id not in subscriptions:
            subscriptions[session_id] = set()
        subscriptions[session_id].add(symbol)
    
    logger.info(f"Client {session_id} subscribed to {symbol}")
    
    emit('subscription_confirmed', {
        'status': 'subscribed',
        'symbol': symbol,
        'timestamp': datetime.now().isoformat(),
        'message': f'Successfully subscribed to {symbol} price updates'
    })
    
    # Start background thread if not running
    start_background_thread()


@socketio.on('unsubscribe')
def handle_unsubscribe(data):
    """Unsubscribe from symbol price updates"""
    from flask import request as socket_request
    session_id = socket_request.sid
    
    symbol = data.get('symbol', '').upper()
    
    if not symbol:
        emit('error', {
            'message': 'Symbol is required for unsubscription',
            'timestamp': datetime.now().isoformat()
        })
        return
    
    # Leave the room for this symbol
    leave_room(symbol)
    
    with subscriptions_lock:
        if session_id in subscriptions:
            subscriptions[session_id].discard(symbol)
    
    logger.info(f"Client {session_id} unsubscribed from {symbol}")
    
    emit('unsubscription_confirmed', {
        'status': 'unsubscribed',
        'symbol': symbol,
        'timestamp': datetime.now().isoformat(),
        'message': f'Successfully unsubscribed from {symbol} price updates'
    })


# --- Background Thread for Price Updates ---

def get_subscribed_symbols():
    """Get all currently subscribed symbols"""
    with subscriptions_lock:
        all_symbols = set()
        for session_symbols in subscriptions.values():
            all_symbols.update(session_symbols)
        return list(all_symbols)


def generate_mock_price_update(symbol):
    """Generate mock price update for a symbol"""
    # In production, this would fetch real-time data from broker/exchange
    base_prices = {
        'BTC-USD': 45000.0,
        'ETH-USD': 3000.0,
        'AAPL': 180.0,
        'GOOGL': 140.0,
        'MSFT': 380.0,
        'TSLA': 250.0,
        'EURUSD': 1.08,
        'GBPUSD': 1.25,
        'USDJPY': 150.0,
        'XAUUSD': 2000.0,
    }
    
    base_price = base_prices.get(symbol, 100.0)
    # Simulate small price movement
    price_change = random.uniform(-0.002, 0.002) * base_price
    current_price = base_price + price_change
    
    return {
        'symbol': symbol,
        'price': round(current_price, 2),
        'bid': round(current_price - 0.01, 2),
        'ask': round(current_price + 0.01, 2),
        'volume': random.randint(100, 10000),
        'timestamp': datetime.now().isoformat(),
        'change': round(price_change, 4),
        'changePercent': round((price_change / base_price) * 100, 4),  # Fixed: camelCase to match frontend
        'open': round(base_price, 2),  # Added: missing field
        'high': round(current_price + 0.5, 2),  # Added: missing field
        'low': round(current_price - 0.5, 2),  # Added: missing field
        'high24h': round(base_price * 1.02, 2),  # Added: missing field
        'low24h': round(base_price * 0.98, 2)  # Added: missing field
    }


def fetch_real_price_update():
    """Fetch real price update from data feed if available.
    TODO: implement live feed; returns None to fall back to mock data for now.
    """
    return None


def broadcast_price_updates():
    """Background thread to broadcast price updates to subscribed clients"""
    logger.info("Price update broadcast thread started")
    
    while not _shutdown_event.is_set():
        try:
            symbols = get_subscribed_symbols()
            if symbols:
                for symbol in symbols:
                    price_data = fetch_real_price_update()
                    if price_data is None:
                        price_data = generate_mock_price_update(symbol)
                    socketio.emit('price_update', price_data, room=symbol)
            socketio.sleep(1)
        except Exception as e:
            logger.error(f"Error in price update broadcast: {e}")
            socketio.sleep(5)
    logger.info("Broadcast loop exited cleanly.")


def start_background_thread():
    """Start the background thread if not already running"""
    global background_thread
    
    with thread_lock:
        if background_thread is None or not background_thread.is_alive():
            background_thread = socketio.start_background_task(broadcast_price_updates)
            logger.info("Background price update thread started")


# --- API Endpoints ---

@app.route("/api/run_backtest", methods=['POST'])
def run_backtest_endpoint():
    """
    Endpoint to run a backtest with specified parameters.
    """
    if not CONFIG:
        return jsonify({"error": "Server configuration is missing."}), 500

    params = request.json
    logger.info(f"Received backtest request with params: {params}")

    # Extract parameters from request
    start_date = params.get("startDate", "2022-01-01")
    end_date = params.get("endDate", "2023-12-31")
    initial_capital = float(params.get("initialCapital", 100000.0))
    symbol = params.get("symbol", "BTC-USD") # Allow symbol to be passed in future

    try:
        # This logic is adapted from the integration_test script
        data_feed = DataFeed(broker_config=CONFIG.get('broker_config', {}))
        price_data = data_feed.get_historical_data(symbol, "1d", start_date, end_date)
        if price_data is None:
            return jsonify({"error": f"Failed to fetch price data for {symbol}."}), 400

        gann_engine = GannEngine(gann_config=CONFIG.get('gann_config', {}))
        ehlers_engine = EhlersEngine(ehlers_config=CONFIG.get('ehlers_config', {}))
        signal_engine = AISignalEngine(CONFIG.get('strategy_config', {}))

        gann_levels = gann_engine.calculate_sq9_levels(price_data)
        data_with_indicators = ehlers_engine.calculate_all_indicators(price_data)

        # AstroEngine raises FileNotFoundError if the ephemeris file is missing.
        try:
            astro_engine = AstroEngine(astro_config=CONFIG.get('astro_config', {}))
            astro_events = astro_engine.analyze_dates(price_data.index)
        except FileNotFoundError as e:
            logger.warning(f"Astro engine unavailable — skipping: {e}")
            astro_events = None

        # MLEngine raises ValueError for unsupported model types.
        try:
            ml_engine = MLEngine(CONFIG)
            ml_predictions = ml_engine.get_predictions(data_with_indicators, gann_levels, astro_events)
            if ml_predictions is not None:
                data_with_indicators = data_with_indicators.join(ml_predictions)
        except ValueError as e:
            logger.warning(f"ML engine unavailable — skipping: {e}")

        # generate_signals_sync() is the synchronous entry point; never returns a coroutine.
        signals = signal_engine.generate_signals_sync(data_with_indicators, gann_levels, astro_events)

        # Use a deep copy so concurrent requests don't corrupt shared CONFIG
        backtest_cfg = copy.deepcopy(CONFIG)
        backtest_cfg['backtest_config']['initial_capital'] = initial_capital
        backtester = Backtester(backtest_cfg)
        results = backtester.run(data_with_indicators, signals)

        performance = {}
        if not results['trades'].empty:
            raw_metrics = calculate_performance_metrics(
                results['equity_curve'], results['trades'], results['initial_capital']
            )
            # Transform to frontend-expected format (camelCase, numeric values)
            performance = {
                "totalReturn": float(raw_metrics.get('Total Return (%)', 0)) / 100,  # Convert % to decimal
                "sharpeRatio": float(raw_metrics.get('Sharpe Ratio', 0)),
                "maxDrawdown": float(raw_metrics.get('Max Drawdown (%)', 0)) / 100,  # Convert % to decimal
                "winRate": float(raw_metrics.get('Win Rate (%)', 0)) / 100,  # Convert % to decimal
                "profitFactor": (
                    999.99 if math.isinf(raw_metrics.get('Profit Factor', 0))
                    else float(raw_metrics.get('Profit Factor', 0))
                ),
                "totalTrades": int(float(raw_metrics.get('Total Trades', 0))),
            }

        # Convert DataFrames to JSON-serializable format
        results['trades']['entry_date'] = results['trades']['entry_date'].dt.strftime('%Y-%m-%d')
        results['trades']['exit_date'] = results['trades']['exit_date'].dt.strftime('%Y-%m-%d')

        # Transform equity curve to match frontend expected format
        equity_curve_formatted = []
        for date_val, row in results['equity_curve'].iterrows():
            if hasattr(date_val, 'strftime'):
                date_str = date_val.strftime('%Y-%m-%d')
            else:
                date_str = str(date_val)
            equity_curve_formatted.append({
                "date": date_str,
                "equity": float(row.get('equity', row.get('balance', 0)))
            })

        response_data = {
            "performanceMetrics": performance,
            "equityCurve": equity_curve_formatted,
            "trades": results['trades'].to_dict(orient='records'),
        }

        logger.success("Backtest completed successfully and results returned.")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"An error occurred during backtest: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/health", methods=['GET'])
def health_check():
    """Health check endpoint for frontend monitoring"""
    try:
        if CONFIG:
            return jsonify({
                "status": "healthy",
                "message": "Backend API is running",
                "timestamp": pd.Timestamp.now().isoformat(),
                "config_loaded": bool(CONFIG),
                "websocket": "enabled",
                "active_subscriptions": len(get_subscribed_symbols())
            })
        else:
            return jsonify({
                "status": "unhealthy",
                "message": "Configuration not loaded",
                "timestamp": pd.Timestamp.now().isoformat()
            }), 500
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "message": f"Health check failed: {str(e)}",
            "timestamp": pd.Timestamp.now().isoformat()
        }), 500


@app.route("/api/config", methods=['GET'])
def get_config():
    """Get current configuration for frontend"""
    try:
        if not CONFIG:
            return jsonify({"error": "Configuration not loaded"}), 500
        
        # Return safe config (exclude sensitive data)
        safe_config = {}
        for key, value in CONFIG.items():
            if key in ['broker_config', 'risk_config']:
                # Only show non-sensitive config
                safe_config[key] = {
                    k: v for k, v in value.items() 
                    if k not in ['api_key', 'secret', 'password']
                }
            else:
                safe_config[key] = value
        
        return jsonify(safe_config)
    except Exception as e:
        logger.error(f"Failed to get config: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/market-data/<symbol>", methods=['POST'])
def get_market_data(symbol):
    """Get market data for a symbol"""
    try:
        if not CONFIG:
            return jsonify({"error": "Configuration not loaded"}), 500
        
        data = request.json
        timeframe = data.get('timeframe', '1d')
        start_date = data.get('startDate', '2022-01-01')
        end_date = data.get('endDate', '2023-12-31')
        
        data_feed = DataFeed(broker_config=CONFIG.get('broker_config', {}))
        price_data = data_feed.get_historical_data(symbol, timeframe, start_date, end_date)
        
        if price_data is None:
            return jsonify({"error": f"Failed to fetch price data for {symbol}"}), 400
        
        # Convert to the format expected by frontend
        market_data = []
        for index, row in price_data.iterrows():
            # Handle both datetime index and string index
            if hasattr(index, 'strftime'):
                time_str = index.strftime('%Y-%m-%d %H:%M:%S')
            else:
                time_str = str(index)
            
            # Handle both capitalized and lowercase column names (use `is not None`
            # so a legitimate 0 value is not skipped by a falsy `or` check)
            open_price = float(row.get('Open') if row.get('Open') is not None else row.get('open'))
            high_price = float(row.get('High') if row.get('High') is not None else row.get('high'))
            low_price = float(row.get('Low') if row.get('Low') is not None else row.get('low'))
            close_price = float(row.get('Close') if row.get('Close') is not None else row.get('close'))
            volume = float(row.get('Volume') if row.get('Volume') is not None else row.get('volume', 0))
            
            market_data.append({
                'time': time_str,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': volume
            })
        
        return jsonify(market_data)
    except Exception as e:
        logger.error(f"Failed to get market data: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gann-levels/<symbol>", methods=['POST'])
def get_gann_levels(symbol):
    """Get Gann Square of 9 levels for a symbol at a specific price"""
    try:
        if not CONFIG:
            return jsonify({"error": "Configuration not loaded"}), 500
        
        data = request.json
        current_price = data.get('price', 0)
        
        if current_price <= 0:
            return jsonify({"error": "Invalid price provided"}), 400
        
        gann_engine = GannEngine(gann_config=CONFIG.get('gann_config', {}))

        # Create mock price data for calculation
        mock_data = pd.DataFrame({
            'open': [current_price],
            'high': [current_price * 1.01],
            'low': [current_price * 0.99],
            'close': [current_price]
        })
        
        sq9_levels = gann_engine.calculate_sq9_levels(mock_data)
        
        if not sq9_levels:
            return jsonify({"error": "Failed to calculate Gann levels"}), 400
        
        # Transform to frontend expected format
        gann_levels = []
        
        # Add support levels
        for i, level in enumerate(sq9_levels.get('support', [])):
            gann_levels.append({
                "angle": (i + 1) * 45,  # Approximate angle representation
                "price": float(level),
                "type": "support" if i % 2 == 0 else "minor"
            })
        
        # Add resistance levels
        for i, level in enumerate(sq9_levels.get('resistance', [])):
            gann_levels.append({
                "angle": 180 + (i + 1) * 45,  # Approximate angle representation
                "price": float(level),
                "type": "resistance" if i % 2 == 0 else "major"
            })
        
        return jsonify(gann_levels)
    except Exception as e:
        logger.error(f"Failed to get Gann levels: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/signals/<symbol>", methods=['GET'])
def get_signals(symbol):
    """Get trading signals for a symbol"""
    try:
        if not CONFIG:
            return jsonify({"error": "Configuration not loaded"}), 500
        
        data_feed = DataFeed(broker_config=CONFIG.get('broker_config', {}))
        
        # Get recent data for signal generation
        from datetime import timedelta
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        price_data = data_feed.get_historical_data(symbol, '1d', start_date, end_date)
        
        if price_data is None:
            return jsonify({"error": f"Failed to fetch price data for {symbol}"}), 400
        
        # Generate signals using the signal engine
        gann_engine = GannEngine(gann_config=CONFIG.get('gann_config', {}))
        ehlers_engine = EhlersEngine(ehlers_config=CONFIG.get('ehlers_config', {}))
        signal_engine = AISignalEngine(CONFIG.get('strategy_config', {}))

        gann_levels = gann_engine.calculate_sq9_levels(price_data)
        data_with_indicators = ehlers_engine.calculate_all_indicators(price_data)

        try:
            astro_engine = AstroEngine(astro_config=CONFIG.get('astro_config', {}))
            astro_events = astro_engine.analyze_dates(price_data.index)
        except FileNotFoundError as e:
            logger.warning(f"Astro engine unavailable — skipping: {e}")
            astro_events = None

        # generate_signals_sync() is the synchronous entry point; never returns a coroutine.
        signals_df = signal_engine.generate_signals_sync(data_with_indicators, gann_levels, astro_events)
        
        # Transform to frontend expected format
        signals = []
        if not signals_df.empty:
            for timestamp, row in signals_df.iterrows():
                # Handle datetime conversion
                if hasattr(timestamp, 'strftime'):
                    timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    timestamp_str = str(timestamp)
                
                # Handle missing price field - use close price as fallback
                price_val = float(row.get('price') or row.get('close', 0))
                
                signals.append({
                    "timestamp": timestamp_str,
                    "symbol": symbol,
                    "signal": row.get('signal', 'hold'),
                    "strength": float(row.get('strength', 0.75)),  # Get strength if available
                    "price": price_val,
                    "message": row.get('reason', f"{row.get('signal', 'hold')} signal generated")
                })
        
        return jsonify(signals)
    except Exception as e:
        logger.error(f"Failed to get signals: {e}")
        return jsonify({"error": str(e)}), 500


# --- WebSocket REST API Endpoints ---

@app.route("/api/ws/status", methods=['GET'])
def websocket_status():
    """Get WebSocket server status"""
    try:
        with subscriptions_lock:
            active_sessions = len(subscriptions)
            all_symbols = get_subscribed_symbols()
        
        return jsonify({
            "status": "running",
            "websocket_enabled": True,
            "active_sessions": active_sessions,
            "subscribed_symbols": all_symbols,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Failed to get WebSocket status: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ws/broadcast", methods=['POST'])
def broadcast_message():
    """Broadcast a message to all clients subscribed to a symbol"""
    if BROADCAST_API_KEY:
        if request.headers.get('X-API-Key', '') != BROADCAST_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.json
        symbol = data.get('symbol', '').upper()
        message = data.get('message', {})
        
        if not symbol:
            return jsonify({"error": "Symbol is required"}), 400
        
        # Add timestamp if not present
        if 'timestamp' not in message:
            message['timestamp'] = datetime.now().isoformat()
        
        # Emit to the room for this symbol
        socketio.emit('broadcast', message, room=symbol)
        
        return jsonify({
            "status": "success",
            "symbol": symbol,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Failed to broadcast message: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'

    logger.info(f"Starting Gann Quant AI API server on {host}:{port}...")
    logger.info(f"Registered routes: {len(app.url_map._rules)} endpoints")

    if debug_mode:
        logger.warning("Running in DEBUG mode (development only)")
        socketio.run(app, host=host, port=port, debug=True, allow_unsafe_werkzeug=True)
    else:
        from waitress import serve
        logger.info("Running in PRODUCTION mode via Waitress")
        serve(app, host=host, port=port, threads=8)
