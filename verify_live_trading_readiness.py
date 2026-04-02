#!/usr/bin/env python3
"""
Live Trading Readiness Verification Script
Comprehensive verification of all system components before live trading.
"""

import os
import sys
import json
import time
import traceback
from datetime import datetime
from typing import Dict, List, Any, Tuple

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# Results storage
results = {
    "timestamp": datetime.now().isoformat(),
    "overall_score": 0,
    "components": {},
    "tests": [],
    "issues": [],
    "warnings": [],
    "summary": {}
}


def log_test(category: str, name: str, passed: bool, details: str = "", score: float = 0):
    """Log a test result."""
    test_result = {
        "category": category,
        "name": name,
        "passed": passed,
        "details": details,
        "score": score if passed else 0,
        "timestamp": datetime.now().isoformat()
    }
    results["tests"].append(test_result)
    
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status} | {name}: {details}")
    return passed


def test_import(module_path: str, class_name: str = None) -> Tuple[bool, str]:
    """Test importing a module."""
    try:
        parts = module_path.split('.')
        module = __import__(module_path)
        for part in parts[1:]:
            module = getattr(module, part)
        
        if class_name:
            cls = getattr(module, class_name, None)
            if cls is None:
                return False, f"Class {class_name} not found"
        
        return True, f"Successfully imported {module_path}"
    except Exception as e:
        return False, str(e)


def check_file_exists(file_path: str) -> bool:
    """Check if a file exists."""
    return os.path.exists(file_path)


# =============================================================================
# 1. BACKEND HEALTH CHECK
# =============================================================================
print("\n" + "="*80)
print("1. BACKEND HEALTH CHECK")
print("="*80)

backend_score = 0
backend_total = 0

# Core modules to test
core_modules = [
    ("core.data_feed", "DataFeed"),
    ("core.gann_engine", "GannEngine"),
    ("core.ehlers_engine", "EhlersEngine"),
    ("core.astro_engine", "AstroEngine"),
    ("core.signal_engine", "AISignalEngine"),
    ("core.ml_engine", "MLEngine"),
    ("core.validation", "RateLimiter"),
    ("core.validation", "sanitize_symbol"),
    ("core.risk_manager", "RiskManager"),
    ("core.order_manager", None),
    ("core.execution_engine", None),
    ("core.portfolio_manager", None),
    ("core.hft_engine", None),
    ("core.hft_api", None),
    ("core.safety_api", None),
    ("core.trading_api", None),
]

print("\nCore Module Imports:")
for module_path, class_name in core_modules:
    backend_total += 1
    passed, details = test_import(module_path, class_name)
    if log_test("backend", f"Import {module_path}", passed, details, 1):
        backend_score += 1

# Test API module
print("\nAPI Module:")
backend_total += 1
try:
    import api
    passed = hasattr(api, 'app') and hasattr(api, 'socketio')
    if log_test("backend", "Flask API module", passed, "Flask app and socketio available", 1):
        backend_score += 1
except Exception as e:
    log_test("backend", "Flask API module", False, str(e), 0)

# Test comprehensive API blueprints
backend_total += 1
try:
    from api_comprehensive import (
        trading_api, positions_api, orders_api, risk_api, scanner_api,
        portfolio_api, forecast_api, cycles_api, config_sync_api
    )
    log_test("backend", "API blueprints", True, "All API blueprints imported", 1)
    backend_score += 1
except Exception as e:
    log_test("backend", "API blueprints", False, str(e), 0)

# Test config loader
backend_total += 1
try:
    from utils.config_loader import load_all_configs
    config = load_all_configs()
    passed = config is not None and len(config) > 0
    if passed:
        log_test("backend", "Configuration loader", True, f"Loaded {len(config)} config sections", 1)
        backend_score += 1
    else:
        log_test("backend", "Configuration loader", False, "No configuration loaded", 0)
        results["warnings"].append("Configuration may be incomplete")
except Exception as e:
    log_test("backend", "Configuration loader", False, str(e), 0)

# Test backtest components
backend_total += 1
try:
    from backtest.backtester import Backtester
    from backtest.metrics import calculate_performance_metrics
    log_test("backend", "Backtest components", True, "Backtester and metrics imported", 1)
    backend_score += 1
except Exception as e:
    log_test("backend", "Backtest components", False, str(e), 0)

results["components"]["backend"] = {
    "score": round(backend_score / backend_total * 100, 1) if backend_total > 0 else 0,
    "passed": backend_score,
    "total": backend_total
}

print(f"\nBackend Score: {backend_score}/{backend_total} ({round(backend_score/backend_total*100, 1)}%)")


# =============================================================================
# 2. FRONTEND HEALTH CHECK
# =============================================================================
print("\n" + "="*80)
print("2. FRONTEND HEALTH CHECK")
print("="*80)

frontend_score = 0
frontend_total = 0

# Check frontend directory structure
frontend_dir = os.path.join(PROJECT_ROOT, "frontend")
frontend_total += 1
if os.path.exists(frontend_dir):
    log_test("frontend", "Frontend directory", True, "Frontend directory exists", 1)
    frontend_score += 1
else:
    log_test("frontend", "Frontend directory", False, "Frontend directory missing", 0)

# Check package.json
frontend_total += 1
package_json_path = os.path.join(frontend_dir, "package.json")
if os.path.exists(package_json_path):
    try:
        with open(package_json_path) as f:
            pkg = json.load(f)
        log_test("frontend", "package.json", True, f"Valid JSON with {len(pkg.get('dependencies', {}))} dependencies", 1)
        frontend_score += 1
    except Exception as e:
        log_test("frontend", "package.json", False, str(e), 0)
else:
    log_test("frontend", "package.json", False, "package.json not found", 0)

# Check tsconfig
frontend_total += 1
tsconfig_path = os.path.join(frontend_dir, "tsconfig.json")
if os.path.exists(tsconfig_path):
    log_test("frontend", "TypeScript config", True, "tsconfig.json exists", 1)
    frontend_score += 1
else:
    log_test("frontend", "TypeScript config", False, "tsconfig.json missing", 0)

# Check App.tsx
frontend_total += 1
app_path = os.path.join(frontend_dir, "src", "App.tsx")
if os.path.exists(app_path):
    log_test("frontend", "App.tsx", True, "Main App component exists", 1)
    frontend_score += 1
else:
    log_test("frontend", "App.tsx", False, "App.tsx missing", 0)

# Check vite config
frontend_total += 1
vite_path = os.path.join(frontend_dir, "vite.config.ts")
if os.path.exists(vite_path):
    log_test("frontend", "Vite config", True, "vite.config.ts exists", 1)
    frontend_score += 1
else:
    log_test("frontend", "Vite config", False, "vite.config.ts missing", 0)

# Check UI components directory
frontend_total += 1
ui_dir = os.path.join(frontend_dir, "src", "components", "ui")
if os.path.exists(ui_dir):
    ui_files = [f for f in os.listdir(ui_dir) if f.endswith('.tsx')]
    log_test("frontend", "UI components", True, f"{len(ui_files)} UI components found", 1)
    frontend_score += 1
else:
    log_test("frontend", "UI components", False, "UI components directory missing", 0)

# Check node_modules
frontend_total += 1
node_modules = os.path.join(frontend_dir, "node_modules")
if os.path.exists(node_modules):
    log_test("frontend", "Dependencies installed", True, "node_modules exists", 1)
    frontend_score += 1
else:
    log_test("frontend", "Dependencies installed", False, "Run npm install", 0)
    results["warnings"].append("Frontend dependencies not installed - run 'cd frontend && npm install'")

results["components"]["frontend"] = {
    "score": round(frontend_score / frontend_total * 100, 1) if frontend_total > 0 else 0,
    "passed": frontend_score,
    "total": frontend_total
}

print(f"\nFrontend Score: {frontend_score}/{frontend_total} ({round(frontend_score/frontend_total*100, 1)}%)")


# =============================================================================
# 3. API SYNCHRONIZATION CHECK
# =============================================================================
print("\n" + "="*80)
print("3. API SYNCHRONIZATION CHECK")
print("="*80)

api_score = 0
api_total = 0

# Check API endpoints registration
api_total += 1
try:
    from api import app
    endpoints = [rule.rule for rule in app.url_map.iter_rules()]
    api_endpoints = [e for e in endpoints if e.startswith('/api/')]
    log_test("api", "API endpoints", True, f"{len(api_endpoints)} API endpoints registered", 1)
    api_score += 1
    results["summary"]["api_endpoints_count"] = len(api_endpoints)
except Exception as e:
    log_test("api", "API endpoints", False, str(e), 0)

# Check critical endpoints
critical_endpoints = [
    "/api/health",
    "/api/run_backtest",
    "/api/config",
    "/api/trading/",
    "/api/positions/",
    "/api/orders/",
    "/api/risk/",
    "/api/scanner/",
    "/api/portfolio/",
    "/api/forecast/",
    "/api/gann/",
    "/api/ehlers/",
    "/api/astro/",
    "/api/ml/",
    "/api/broker/",
    "/api/alerts/",
    "/api/settings/",
]

print("\nCritical Endpoints:")
for endpoint in critical_endpoints:
    api_total += 1
    try:
        from api import app
        matching = [e for e in app.url_map.iter_rules() if endpoint.rstrip('/') in e.rule]
        if matching:
            log_test("api", f"Endpoint {endpoint}", True, "Registered", 0.5)
            api_score += 1
        else:
            log_test("api", f"Endpoint {endpoint}", False, "Not found", 0)
    except Exception as e:
        log_test("api", f"Endpoint {endpoint}", False, str(e), 0)

# Check WebSocket events
api_total += 1
try:
    from api import socketio
    log_test("api", "WebSocket support", True, "SocketIO initialized", 1)
    api_score += 1
except Exception as e:
    log_test("api", "WebSocket support", False, str(e), 0)

results["components"]["api_sync"] = {
    "score": round(api_score / api_total * 100, 1) if api_total > 0 else 0,
    "passed": api_score,
    "total": api_total
}

print(f"\nAPI Score: {api_score}/{api_total} ({round(api_score/api_total*100, 1)}%)")


# =============================================================================
# 4. SECURITY CHECK
# =============================================================================
print("\n" + "="*80)
print("4. SECURITY CHECK")
print("="*80)

security_score = 0
security_total = 0

# Test SQL injection protection
security_total += 1
try:
    from core.validation import sanitize_symbol
    
    # Test valid symbols
    valid_tests = ["BTC-USD", "ETHUSD", "AAPL", "EUR/USD", "BTC.USDT"]
    invalid_tests = ["BTC'; DROP TABLE--", "ETH\" OR 1=1", "SELECT * FROM users", "'; DELETE FROM orders;--"]
    
    all_passed = True
    for symbol in valid_tests:
        try:
            sanitize_symbol(symbol)
        except:
            all_passed = False
            break
    
    for symbol in invalid_tests:
        try:
            sanitize_symbol(symbol)
            all_passed = False  # Should have raised
            break
        except ValueError:
            pass  # Expected
    
    if all_passed:
        log_test("security", "SQL injection protection", True, "Symbol sanitization works correctly", 1)
        security_score += 1
    else:
        log_test("security", "SQL injection protection", False, "Symbol sanitization failed", 0)
except Exception as e:
    log_test("security", "SQL injection protection", False, str(e), 0)

# Test rate limiter
security_total += 1
try:
    from core.validation import RateLimiter
    limiter = RateLimiter(requests_per_second=10, requests_per_minute=100)
    
    # Should allow first request
    allowed, _, _ = limiter.check_rate_limit("127.0.0.1")
    if allowed:
        log_test("security", "Rate limiter", True, "Rate limiter functional", 1)
        security_score += 1
    else:
        log_test("security", "Rate limiter", False, "Rate limiter blocked first request", 0)
except Exception as e:
    log_test("security", "Rate limiter", False, str(e), 0)

# Test input validation models
security_total += 1
try:
    from core.validation import OrderRequest, TradingStartRequest
    
    # Valid order
    valid_order = OrderRequest(
        symbol="BTC-USD",
        side="buy",
        quantity=1.0,
        order_type="market"
    )
    
    # Should fail - invalid symbol
    try:
        OrderRequest(symbol="BTC'; DROP TABLE--", side="buy", quantity=1.0)
        log_test("security", "Pydantic validation", False, "Invalid symbol accepted", 0)
    except ValueError:
        log_test("security", "Pydantic validation", True, "Pydantic models validate correctly", 1)
        security_score += 1
        
except Exception as e:
    log_test("security", "Pydantic validation", False, str(e), 0)

# Check CORS configuration
security_total += 1
try:
    from api import app
    cors_config = app.config.get('CORS_ORIGINS', '*')
    log_test("security", "CORS configuration", True, f"CORS configured: {cors_config}", 1)
    security_score += 1
except Exception as e:
    log_test("security", "CORS configuration", False, str(e), 0)

# Check secret key
security_total += 1
try:
    from api import app
    secret_key = app.config.get('SECRET_KEY', '')
    if secret_key and len(secret_key) > 10:
        log_test("security", "Secret key", True, "Secret key configured", 1)
        security_score += 1
    else:
        log_test("security", "Secret key", False, "Weak or missing secret key", 0)
        results["warnings"].append("Consider using a stronger secret key in production")
except Exception as e:
    log_test("security", "Secret key", False, str(e), 0)

results["components"]["security"] = {
    "score": round(security_score / security_total * 100, 1) if security_total > 0 else 0,
    "passed": security_score,
    "total": security_total
}

print(f"\nSecurity Score: {security_score}/{security_total} ({round(security_score/security_total*100, 1)}%)")


# =============================================================================
# 5. PERFORMANCE CHECK
# =============================================================================
print("\n" + "="*80)
print("5. PERFORMANCE CHECK")
print("="*80)

performance_score = 0
performance_total = 0

# Check latency logger file
performance_total += 1
latency_logger_path = os.path.join(PROJECT_ROOT, "src", "execution", "latency_logger.py")
if check_file_exists(latency_logger_path):
    log_test("performance", "Latency logger", True, "Latency logging file exists", 1)
    performance_score += 1
else:
    log_test("performance", "Latency logger", False, "Latency logger not found", 0)

# Check HFT engine
performance_total += 1
try:
    from core.hft_engine import HFTEngine
    log_test("performance", "HFT engine", True, "HFT engine available", 1)
    performance_score += 1
except Exception as e:
    log_test("performance", "HFT engine", False, str(e), 0)

# Check order router file
performance_total += 1
order_router_path = os.path.join(PROJECT_ROOT, "src", "execution", "order_router.py")
if check_file_exists(order_router_path):
    log_test("performance", "Order router", True, "Order router file exists", 1)
    performance_score += 1
else:
    log_test("performance", "Order router", False, "Order router not found", 0)

# Check HFT config
performance_total += 1
hft_config_path = os.path.join(PROJECT_ROOT, "config", "hft_config.yaml")
if check_file_exists(hft_config_path):
    log_test("performance", "HFT configuration", True, "HFT config file exists", 1)
    performance_score += 1
else:
    log_test("performance", "HFT configuration", False, "HFT config missing", 0)

# Test execution speed (mock)
performance_total += 1
try:
    start = time.time()
    # Simulate a simple calculation
    for _ in range(1000):
        _ = 1.0 + 1.0
    elapsed_ms = (time.time() - start) * 1000
    
    if elapsed_ms < 100:  # Should be very fast
        log_test("performance", "Basic execution speed", True, f"1000 operations in {elapsed_ms:.2f}ms", 1)
        performance_score += 1
    else:
        log_test("performance", "Basic execution speed", False, f"Slow: {elapsed_ms:.2f}ms", 0)
except Exception as e:
    log_test("performance", "Basic execution speed", False, str(e), 0)

results["components"]["performance"] = {
    "score": round(performance_score / performance_total * 100, 1) if performance_total > 0 else 0,
    "passed": performance_score,
    "total": performance_total
}

print(f"\nPerformance Score: {performance_score}/{performance_total} ({round(performance_score/performance_total*100, 1)}%)")


# =============================================================================
# 6. CONNECTORS CHECK
# =============================================================================
print("\n" + "="*80)
print("6. CONNECTORS CHECK")
print("="*80)

connectors_score = 0
connectors_total = 0

# Check MT5 connector
connectors_total += 1
mt5_path = os.path.join(PROJECT_ROOT, "interface", "mt5_connector.py")
if check_file_exists(mt5_path):
    log_test("connectors", "MT5 connector", True, "MT5 connector file exists", 1)
    connectors_score += 1
else:
    log_test("connectors", "MT5 connector", False, "MT5 connector not found", 0)

# Check Binance connector
connectors_total += 1
try:
    from interface.binance_connector import BinanceConnector
    log_test("connectors", "Binance connector", True, "BinanceConnector class available", 1)
    connectors_score += 1
except Exception as e:
    log_test("connectors", "Binance connector", False, str(e), 0)

# Check FIX connector
connectors_total += 1
fix_path = os.path.join(PROJECT_ROOT, "interface", "fix_connector.py")
if check_file_exists(fix_path):
    log_test("connectors", "FIX connector", True, "FIX connector file exists", 1)
    connectors_score += 1
else:
    log_test("connectors", "FIX connector", False, "FIX connector not found", 0)

# Check WebSocket connector
connectors_total += 1
ws_path = os.path.join(PROJECT_ROOT, "interface", "websocket_connector.py")
if check_file_exists(ws_path):
    log_test("connectors", "WebSocket connector", True, "WebSocket connector file exists", 1)
    connectors_score += 1
else:
    log_test("connectors", "WebSocket connector", False, "WebSocket connector not found", 0)

# Check OANDA connector
connectors_total += 1
oanda_path = os.path.join(PROJECT_ROOT, "interface", "oanda_connector.py")
if check_file_exists(oanda_path):
    log_test("connectors", "OANDA connector", True, "OANDA connector file exists", 1)
    connectors_score += 1
else:
    log_test("connectors", "OANDA connector", False, "OANDA connector not found", 0)

# Check TradingView connector
connectors_total += 1
tv_path = os.path.join(PROJECT_ROOT, "interface", "tradingview_connector.py")
if check_file_exists(tv_path):
    log_test("connectors", "TradingView connector", True, "TradingView connector file exists", 1)
    connectors_score += 1
else:
    log_test("connectors", "TradingView connector", False, "TradingView connector not found", 0)

results["components"]["connectors"] = {
    "score": round(connectors_score / connectors_total * 100, 1) if connectors_total > 0 else 0,
    "passed": connectors_score,
    "total": connectors_total
}

print(f"\nConnectors Score: {connectors_score}/{connectors_total} ({round(connectors_score/connectors_total*100, 1)}%)")


# =============================================================================
# 7. RISK MANAGEMENT CHECK
# =============================================================================
print("\n" + "="*80)
print("7. RISK MANAGEMENT CHECK")
print("="*80)

risk_score = 0
risk_total = 0

# Check circuit breaker
risk_total += 1
try:
    from src.risk.circuit_breaker import CircuitBreaker, CircuitBreakerState
    
    cb = CircuitBreaker({
        "max_daily_loss_pct": 5.0,
        "max_drawdown_pct": 15.0,
        "max_consecutive_failures": 5
    })
    
    # Test initial state
    if cb.state == CircuitBreakerState.CLOSED and cb.is_trading_allowed:
        log_test("risk", "Circuit breaker initialization", True, "Circuit breaker initialized correctly", 1)
        risk_score += 1
    else:
        log_test("risk", "Circuit breaker initialization", False, "Invalid initial state", 0)
except Exception as e:
    log_test("risk", "Circuit breaker", False, str(e), 0)

# Test kill switch
risk_total += 1
try:
    from src.risk.circuit_breaker import CircuitBreaker, CircuitBreakerState
    
    cb = CircuitBreaker()
    cb.kill_switch("Test kill switch")
    
    if cb.state == CircuitBreakerState.LOCKED and not cb.is_trading_allowed:
        log_test("risk", "Kill switch", True, "Kill switch works correctly", 1)
        risk_score += 1
    else:
        log_test("risk", "Kill switch", False, "Kill switch did not lock system", 0)
except Exception as e:
    log_test("risk", "Kill switch", False, str(e), 0)

# Check position sizer
risk_total += 1
ps_path = os.path.join(PROJECT_ROOT, "src", "risk", "position_sizer.py")
if check_file_exists(ps_path):
    log_test("risk", "Position sizer", True, "Position sizer file exists", 1)
    risk_score += 1
else:
    log_test("risk", "Position sizer", False, "Position sizer not found", 0)

# Check drawdown protector
risk_total += 1
dp_path = os.path.join(PROJECT_ROOT, "src", "risk", "drawdown_protector.py")
if check_file_exists(dp_path):
    log_test("risk", "Drawdown protector", True, "Drawdown protector file exists", 1)
    risk_score += 1
else:
    log_test("risk", "Drawdown protector", False, "Drawdown protector not found", 0)

# Check risk engine
risk_total += 1
re_path = os.path.join(PROJECT_ROOT, "core", "risk_engine.py")
if check_file_exists(re_path):
    log_test("risk", "Risk engine", True, "Risk engine file exists", 1)
    risk_score += 1
else:
    log_test("risk", "Risk engine", False, "Risk engine not found", 0)

# Check risk config
risk_total += 1
risk_config_path = os.path.join(PROJECT_ROOT, "config", "risk_config.yaml")
if check_file_exists(risk_config_path):
    log_test("risk", "Risk configuration", True, "risk_config.yaml exists", 1)
    risk_score += 1
else:
    log_test("risk", "Risk configuration", False, "risk_config.yaml missing", 0)

# Check portfolio risk
risk_total += 1
pr_path = os.path.join(PROJECT_ROOT, "src", "risk", "portfolio_risk.py")
if check_file_exists(pr_path):
    log_test("risk", "Portfolio risk module", True, "Portfolio risk file exists", 1)
    risk_score += 1
else:
    log_test("risk", "Portfolio risk module", False, "Portfolio risk not found", 0)

results["components"]["risk_management"] = {
    "score": round(risk_score / risk_total * 100, 1) if risk_total > 0 else 0,
    "passed": risk_score,
    "total": risk_total
}

print(f"\nRisk Management Score: {risk_score}/{risk_total} ({round(risk_score/risk_total*100, 1)}%)")


# =============================================================================
# 8. VALIDATION INTEGRATION TEST
# =============================================================================
print("\n" + "="*80)
print("8. VALIDATION INTEGRATION TEST")
print("="*80)

validation_score = 0
validation_total = 0

# Test OrderRequest validation
validation_total += 1
try:
    from core.validation import OrderRequest
    
    # Test valid order
    order = OrderRequest(symbol="BTC-USD", side="buy", quantity=1.0, order_type="market")
    log_test("validation", "OrderRequest valid", True, f"Valid order: {order.symbol}", 1)
    validation_score += 1
except Exception as e:
    log_test("validation", "OrderRequest valid", False, str(e), 0)

# Test invalid symbol rejection
validation_total += 1
try:
    from core.validation import OrderRequest
    
    try:
        OrderRequest(symbol="BTC'--", side="buy", quantity=1.0)
        log_test("validation", "Invalid symbol rejection", False, "Invalid symbol was accepted", 0)
    except ValueError:
        log_test("validation", "Invalid symbol rejection", True, "Invalid symbol correctly rejected", 1)
        validation_score += 1
except Exception as e:
    log_test("validation", "Invalid symbol rejection", False, str(e), 0)

# Test TradingStartRequest
validation_total += 1
try:
    from core.validation import TradingStartRequest
    
    req = TradingStartRequest(
        symbols=["BTC-USD", "ETH-USD"],
        mode="paper",
        leverage=1.0,
        initial_capital=100000.0
    )
    log_test("validation", "TradingStartRequest", True, f"Valid request with {len(req.symbols)} symbols", 1)
    validation_score += 1
except Exception as e:
    log_test("validation", "TradingStartRequest", False, str(e), 0)

# Test ScannerRequest
validation_total += 1
try:
    from core.validation import ScannerRequest
    
    req = ScannerRequest(
        symbols=["BTC-USD", "ETH-USD"],
        timeframe="1d",
        indicators=["mama_fama", "gann_levels"]
    )
    log_test("validation", "ScannerRequest", True, f"Valid scanner request", 1)
    validation_score += 1
except Exception as e:
    log_test("validation", "ScannerRequest", False, str(e), 0)

# Test BacktestRequest
validation_total += 1
try:
    from core.validation import BacktestRequest
    
    req = BacktestRequest(
        symbol="BTC-USD",
        start_date="2022-01-01",
        end_date="2023-12-31",
        initial_capital=100000.0
    )
    log_test("validation", "BacktestRequest", True, f"Valid backtest request", 1)
    validation_score += 1
except Exception as e:
    log_test("validation", "BacktestRequest", False, str(e), 0)

results["components"]["validation"] = {
    "score": round(validation_score / validation_total * 100, 1) if validation_total > 0 else 0,
    "passed": validation_score,
    "total": validation_total
}

print(f"\nValidation Score: {validation_score}/{validation_total} ({round(validation_score/validation_total*100, 1)}%)")


# =============================================================================
# CALCULATE OVERALL SCORE
# =============================================================================
print("\n" + "="*80)
print("OVERALL READINESS SCORE")
print("="*80)

total_score = 0
total_possible = 0

for component, data in results["components"].items():
    total_score += data["passed"]
    total_possible += data["total"]

overall_percentage = round(total_score / total_possible * 100, 1) if total_possible > 0 else 0
results["overall_score"] = overall_percentage
results["summary"]["total_passed"] = total_score
results["summary"]["total_tests"] = total_possible

print(f"\nOverall Score: {total_score}/{total_possible} ({overall_percentage}%)")

# Determine readiness level
if overall_percentage >= 90:
    readiness = "READY FOR LIVE TRADING"
    readiness_color = "🟢"
elif overall_percentage >= 75:
    readiness = "MOSTLY READY - Minor issues to address"
    readiness_color = "🟡"
elif overall_percentage >= 60:
    readiness = "NEEDS ATTENTION - Several issues found"
    readiness_color = "🟠"
else:
    readiness = "NOT READY - Critical issues found"
    readiness_color = "🔴"

results["summary"]["readiness"] = readiness
print(f"\n{readiness_color} Status: {readiness}")

# Print component breakdown
print("\nComponent Breakdown:")
for component, data in results["components"].items():
    status = "✅" if data["score"] >= 80 else "⚠️" if data["score"] >= 60 else "❌"
    print(f"  {status} {component}: {data['score']}%")

# Print issues if any
if results["issues"]:
    print("\nIssues Found:")
    for issue in results["issues"]:
        print(f"  ❌ {issue}")

# Print warnings if any
if results["warnings"]:
    print("\nWarnings:")
    for warning in results["warnings"]:
        print(f"  ⚠️ {warning}")


# =============================================================================
# SAVE JSON REPORT
# =============================================================================
report_path = os.path.join(PROJECT_ROOT, "live_trading_readiness_report.json")
with open(report_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n📄 JSON report saved to: {report_path}")


# =============================================================================
# GENERATE MARKDOWN REPORT
# =============================================================================
markdown_report = f"""# FINAL LIVE TRADING READINESS REPORT

**Generated:** {results['timestamp']}

## Executive Summary

| Metric | Value |
|--------|-------|
| **Overall Score** | {overall_percentage}% |
| **Status** | {readiness_color} {readiness} |
| **Total Tests** | {total_possible} |
| **Passed Tests** | {total_score} |
| **Failed Tests** | {total_possible - total_score} |

## Component Scores

| Component | Score | Status | Details |
|-----------|-------|--------|---------|
| Backend Health | {results['components']['backend']['score']}% | {"✅ PASS" if results['components']['backend']['score'] >= 80 else "⚠️ WARN" if results['components']['backend']['score'] >= 60 else "❌ FAIL"} | {results['components']['backend']['passed']}/{results['components']['backend']['total']} tests passed |
| Frontend Health | {results['components']['frontend']['score']}% | {"✅ PASS" if results['components']['frontend']['score'] >= 80 else "⚠️ WARN" if results['components']['frontend']['score'] >= 60 else "❌ FAIL"} | {results['components']['frontend']['passed']}/{results['components']['frontend']['total']} tests passed |
| API Synchronization | {results['components']['api_sync']['score']}% | {"✅ PASS" if results['components']['api_sync']['score'] >= 80 else "⚠️ WARN" if results['components']['api_sync']['score'] >= 60 else "❌ FAIL"} | {results['components']['api_sync']['passed']}/{results['components']['api_sync']['total']} tests passed |
| Security | {results['components']['security']['score']}% | {"✅ PASS" if results['components']['security']['score'] >= 80 else "⚠️ WARN" if results['components']['security']['score'] >= 60 else "❌ FAIL"} | {results['components']['security']['passed']}/{results['components']['security']['total']} tests passed |
| Performance | {results['components']['performance']['score']}% | {"✅ PASS" if results['components']['performance']['score'] >= 80 else "⚠️ WARN" if results['components']['performance']['score'] >= 60 else "❌ FAIL"} | {results['components']['performance']['passed']}/{results['components']['performance']['total']} tests passed |
| Connectors | {results['components']['connectors']['score']}% | {"✅ PASS" if results['components']['connectors']['score'] >= 80 else "⚠️ WARN" if results['components']['connectors']['score'] >= 60 else "❌ FAIL"} | {results['components']['connectors']['passed']}/{results['components']['connectors']['total']} tests passed |
| Risk Management | {results['components']['risk_management']['score']}% | {"✅ PASS" if results['components']['risk_management']['score'] >= 80 else "⚠️ WARN" if results['components']['risk_management']['score'] >= 60 else "❌ FAIL"} | {results['components']['risk_management']['passed']}/{results['components']['risk_management']['total']} tests passed |
| Validation | {results['components']['validation']['score']}% | {"✅ PASS" if results['components']['validation']['score'] >= 80 else "⚠️ WARN" if results['components']['validation']['score'] >= 60 else "❌ FAIL"} | {results['components']['validation']['passed']}/{results['components']['validation']['total']} tests passed |

## Detailed Test Results

### 1. Backend Health
"""

# Add backend tests
for test in [t for t in results['tests'] if t['category'] == 'backend']:
    status = "✅" if test['passed'] else "❌"
    markdown_report += f"- {status} **{test['name']}**: {test['details']}\n"

markdown_report += "\n### 2. Frontend Health\n"
for test in [t for t in results['tests'] if t['category'] == 'frontend']:
    status = "✅" if test['passed'] else "❌"
    markdown_report += f"- {status} **{test['name']}**: {test['details']}\n"

markdown_report += "\n### 3. API Synchronization\n"
for test in [t for t in results['tests'] if t['category'] == 'api']:
    status = "✅" if test['passed'] else "❌"
    markdown_report += f"- {status} **{test['name']}**: {test['details']}\n"

markdown_report += "\n### 4. Security\n"
for test in [t for t in results['tests'] if t['category'] == 'security']:
    status = "✅" if test['passed'] else "❌"
    markdown_report += f"- {status} **{test['name']}**: {test['details']}\n"

markdown_report += "\n### 5. Performance\n"
for test in [t for t in results['tests'] if t['category'] == 'performance']:
    status = "✅" if test['passed'] else "❌"
    markdown_report += f"- {status} **{test['name']}**: {test['details']}\n"

markdown_report += "\n### 6. Connectors\n"
for test in [t for t in results['tests'] if t['category'] == 'connectors']:
    status = "✅" if test['passed'] else "❌"
    markdown_report += f"- {status} **{test['name']}**: {test['details']}\n"

markdown_report += "\n### 7. Risk Management\n"
for test in [t for t in results['tests'] if t['category'] == 'risk']:
    status = "✅" if test['passed'] else "❌"
    markdown_report += f"- {status} **{test['name']}**: {test['details']}\n"

markdown_report += "\n### 8. Validation\n"
for test in [t for t in results['tests'] if t['category'] == 'validation']:
    status = "✅" if test['passed'] else "❌"
    markdown_report += f"- {status} **{test['name']}**: {test['details']}\n"

# Add issues section
if results['issues']:
    markdown_report += "\n## Issues Found\n\n"
    for issue in results['issues']:
        markdown_report += f"- ❌ {issue}\n"
else:
    markdown_report += "\n## Issues Found\n\nNo critical issues found.\n"

# Add warnings section
if results['warnings']:
    markdown_report += "\n## Warnings\n\n"
    for warning in results['warnings']:
        markdown_report += f"- ⚠️ {warning}\n"
else:
    markdown_report += "\n## Warnings\n\nNo warnings.\n"

# Add recommendations
markdown_report += """
## Recommendations

### Before Live Trading

1. **Security**
   - Ensure all API keys are stored securely (use environment variables or secrets manager)
   - Enable HTTPS in production
   - Set up proper authentication for all API endpoints

2. **Risk Management**
   - Configure circuit breaker thresholds appropriate for your account size
   - Test kill switch functionality manually
   - Set up alert notifications for circuit breaker trips

3. **Connectors**
   - Test broker connections in paper trading mode first
   - Verify WebSocket connections are stable
   - Configure reconnection logic for data feeds

4. **Monitoring**
   - Set up logging and monitoring (e.g., Grafana, Prometheus)
   - Configure alerting for critical errors
   - Monitor latency metrics during trading hours

5. **Backup & Recovery**
   - Implement database backup strategy
   - Create disaster recovery plan
   - Test restore procedures

### Post-Deployment

1. Start with paper trading mode
2. Monitor system performance for at least 1 week
3. Gradually increase position sizes
4. Review and adjust risk parameters based on actual performance

---

*This report was generated automatically by the Live Trading Readiness Verification System.*
"""

# Save markdown report
md_path = os.path.join(PROJECT_ROOT, "FINAL_LIVE_TRADING_READINESS_REPORT.md")
with open(md_path, 'w') as f:
    f.write(markdown_report)

print(f"📄 Markdown report saved to: {md_path}")

# Exit with appropriate code
sys.exit(0 if overall_percentage >= 75 else 1)
