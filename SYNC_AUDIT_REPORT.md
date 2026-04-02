# Frontend-Backend Synchronization Audit Report
## Generated: 2026-02-14

---

## 🟢 AUDIT STATUS: COMPLETE — ALL ROUTES SYNCHRONIZED

---

## 1. Architecture Overview

The backend uses **5 route sources** that collectively serve the frontend:

| Source | Blueprint Prefix | File |
|--------|-----------------|------|
| `api_v2.py` (inline) | `/api` (direct) | Main Flask app - core trading endpoints |
| `api_sync.py` | `/api` | Extended sync routes (smith, options, RR, patterns, gann advanced, broker, ML, settings) |
| `config_sync_api.py` | `/api/config` | YAML config CRUD (gann, ehlers, astro, ml, strategy, broker, notifier, options) |
| `missing_endpoints_api.py` | `/api` | ML training/ensemble, alerts, broker balance/positions, strategies |
| Other modules | Various | ai_api, settings_api, market_data_api, execution_api, trading_api, hft_api, safety_api |

---

## 2. Issues Found & Fixed

### 🔴 CRITICAL — Missing Endpoint
| Frontend Call | Backend Route | Fix |
|---|---|---|
| `optimizeStrategyWeights()` → `POST /strategies/optimize` | **DID NOT EXIST** | ✅ Added `optimize_strategy_weights()` in `api_v2.py` |

### 🔴 CRITICAL — Payload Shape Mismatches  
| Frontend Call | Was Sending | Backend Expected | Fix |
|---|---|---|---|
| `saveTradingModes(modes)` | `JSON.stringify(modes)` (raw array) | `{ modes: [...] }` | ✅ Fixed to `JSON.stringify({ modes })` |
| `saveLeverageConfig(leverages)` | `JSON.stringify(leverages)` (raw array) | `{ manualLeverages: [...] }` | ✅ Fixed to `JSON.stringify({ manualLeverages: leverages })` |

### ⚠️ WARNING — Duplicate Route Conflicts (Flask first-registered wins)
| Route Path | Source 1 | Source 2 | Fix |
|---|---|---|---|
| `/api/config/gann` | `api_v2.py` inline | `config_sync_api.py` | ✅ Removed from `api_v2.py` (config_sync_api has YAML persistence) |
| `/api/config/ehlers` | `api_v2.py` inline | `config_sync_api.py` | ✅ Removed from `api_v2.py` |
| `/api/config/astro` | `api_v2.py` inline | `config_sync_api.py` | ✅ Removed from `api_v2.py` |
| `/api/config/trading-modes` | `api_sync.py` | `config_sync_api.py` | ✅ Removed from `config_sync_api.py` |
| `/api/config/leverage` | `api_sync.py` | `config_sync_api.py` | ✅ Removed from `config_sync_api.py` |
| `/api/config/risk` | `api_sync.py` | `config_sync_api.py` | ✅ Removed from `config_sync_api.py` |
| `/api/config/scanner` | `api_sync.py` | `config_sync_api.py` | ✅ Removed from `config_sync_api.py` |
| `/api/config/settings/load` | `config_sync_api.py` | `missing_endpoints_api.py` | ✅ Removed from `missing_endpoints_api.py` |
| `/api/config/settings/save` | `config_sync_api.py` | `missing_endpoints_api.py` | ✅ Removed from `missing_endpoints_api.py` |
| `/api/config/strategy-weights` | `config_sync_api.py` | `missing_endpoints_api.py` | ✅ Removed from `missing_endpoints_api.py` |
| `/api/config/instruments` | `config_sync_api.py` | `missing_endpoints_api.py` | ✅ Removed from `missing_endpoints_api.py` |
| `/api/settings/load-all` | `api_sync.py` | `missing_endpoints_api.py` | ✅ Removed from `missing_endpoints_api.py` |

---

## 3. Complete Route Map (Final — Post-Fix)

### Core Trading (api_v2.py inline)
| Frontend Method | HTTP | Path | Status |
|---|---|---|---|
| `healthCheck()` | GET | `/api/health` | ✅ |
| `getConfig()` | GET | `/api/config` | ✅ |
| `runBacktest()` | POST | `/api/run_backtest` | ✅ |
| `getMarketData()` | POST | `/api/market-data/<symbol>` | ✅ |
| `getLatestPrice()` | GET | `/api/market-data/<symbol>/latest` | ✅ |
| `getGannLevels()` | POST | `/api/gann-levels/<symbol>` | ✅ |
| `getGannFullAnalysis()` | POST | `/api/gann/full-analysis` | ✅ |
| `getEhlersAnalysis()` | POST | `/api/ehlers/analyze` | ✅ |
| `getAstroAnalysis()` | POST | `/api/astro/analyze` | ✅ |
| `getMLPrediction()` | POST | `/api/ml/predict` | ✅ |
| `getSignals()` | GET | `/api/signals/<symbol>` | ✅ |
| `startTrading()` | POST | `/api/trading/start` | ✅ |
| `stopTrading()` | POST | `/api/trading/stop` | ✅ |
| `pauseTrading()` | POST | `/api/trading/pause` | ✅ |
| `resumeTrading()` | POST | `/api/trading/resume` | ✅ |
| `getTradingStatus()` | GET | `/api/trading/status` | ✅ |
| `getPositions()` | GET | `/api/positions` | ✅ |
| `getPosition()` | GET | `/api/positions/<symbol>` | ✅ |
| `closePosition()` | POST | `/api/positions/<id>/close` | ✅ |
| `createOrder()` | POST | `/api/orders` | ✅ |
| `getOrders()` | GET | `/api/orders` | ✅ |
| `cancelOrder()` | DELETE | `/api/orders/<id>` | ✅ |
| `getRiskMetrics()` | GET | `/api/risk/metrics` | ✅ |
| `calculatePositionSize()` | POST | `/api/risk/calculate-position-size` | ✅ |
| `runScanner()` | POST | `/api/scanner/scan` | ✅ |
| `getPortfolioSummary()` | GET | `/api/portfolio/summary` | ✅ |
| `getDailyForecast()` | POST | `/api/forecast/daily` | ✅ |
| `getWaveForecast()` | POST | `/api/forecast/waves` | ✅ |
| `getAstroForecast()` | POST | `/api/forecast/astro` | ✅ |
| `getMLForecast()` | POST | `/api/forecast/ml` | ✅ |
| `analyzeCycles()` | POST | `/api/cycles/analyze` | ✅ |
| `syncConfig()` | POST | `/api/config/sync` | ✅ |
| `generateReport()` | POST | `/api/reports/generate` | ✅ |
| `optimizeStrategyWeights()` | POST | `/api/strategies/optimize` | ✅ **NEW** |

### Extended Analysis (api_sync.py)
| Frontend Method | HTTP | Path | Status |
|---|---|---|---|
| `getSmithChartAnalysis()` | POST | `/api/smith/analyze` | ✅ |
| `getOptionsAnalysis()` | POST | `/api/options/analyze` | ✅ |
| `calculateOptionsGreeks()` | POST | `/api/options/greeks` | ✅ |
| `calculateRiskReward()` | POST | `/api/rr/calculate` | ✅ |
| `scanPatterns()` | POST | `/api/patterns/scan` | ✅ |
| `getGannVibrationMatrix()` | POST | `/api/gann/vibration-matrix` | ✅ |
| `getGannSupplyDemand()` | POST | `/api/gann/supply-demand` | ✅ |
| `testBrokerConnection()` | POST | `/api/broker/test-connection` | ✅ |
| `getInstruments()` / `saveInstruments()` | GET/POST | `/api/instruments` | ✅ |
| `getStrategyWeights()` / `saveStrategyWeights()` | GET/POST | `/api/config/strategies` | ✅ |
| `getTradingModes()` / `saveTradingModes()` | GET/POST | `/api/config/trading-modes` | ✅ |
| `getRiskConfig()` / `updateRiskConfig()` | GET/POST | `/api/config/risk` | ✅ |
| `getScannerConfig()` / `updateScannerConfig()` | GET/POST | `/api/config/scanner` | ✅ |
| `getLeverageConfig()` / `saveLeverageConfig()` | GET/POST | `/api/config/leverage` | ✅ |
| `syncAllSettings()` | POST | `/api/settings/sync-all` | ✅ |
| `loadAllSettings()` | GET | `/api/settings/load-all` | ✅ |

### Config YAML CRUD (config_sync_api.py)
| Frontend Method | HTTP | Path | Status |
|---|---|---|---|
| `getAllConfigs()` | GET | `/api/config/all` | ✅ |
| `syncAllConfigsToBackend()` | POST | `/api/config/sync-all` | ✅ |
| `getGannConfig/FromYaml()` | GET/POST | `/api/config/gann` | ✅ |
| `getEhlersConfig/FromYaml()` | GET/POST | `/api/config/ehlers` | ✅ |
| `getAstroConfig/FromYaml()` | GET/POST | `/api/config/astro` | ✅ |
| `getMLConfigFromYaml()` | GET/POST | `/api/config/ml` | ✅ |
| `getStrategyConfigFromYaml()` | GET/POST | `/api/config/strategy` | ✅ |
| `getBrokerConfigFromYaml()` | GET/POST | `/api/config/broker` | ✅ |
| `getNotifierConfigFromYaml()` | GET/POST | `/api/config/notifier` | ✅ |
| `getOptionsConfigFromYaml()` | GET/POST | `/api/config/options` | ✅ |
| `getStrategyWeightsFromYaml()` | GET/POST | `/api/config/strategy-weights` | ✅ |
| `getInstrumentsFromYaml()` | GET/POST | `/api/config/instruments` | ✅ |
| `loadSettingsFromBackend()` | GET | `/api/config/settings/load` | ✅ |
| `saveSettingsToBackend()` | POST | `/api/config/settings/save` | ✅ |

### ML & Alerts (missing_endpoints_api.py)
| Frontend Method | HTTP | Path | Status |
|---|---|---|---|
| `getBinanceBalance()` | GET | `/api/broker/binance/balance` | ✅ |
| `getMT5Positions()` | GET | `/api/broker/mt5/positions` | ✅ |
| `getTrainingStatus()` | GET | `/api/ml/training-status/<id>` | ✅ |
| `startAutoTuning()` | POST | `/api/ml/auto-tune` | ✅ |
| `getEnsembleConfig()` / `saveEnsembleConfig()` | GET/POST | `/api/ml/ensemble` | ✅ |
| `exportMLModel()` | POST | `/api/ml/export` | ✅ |
| `getAlertConfig()` / `saveAlertConfig()` | GET/POST | `/api/alerts/config` | ✅ |
| `testAlertChannel()` | POST | `/api/alerts/test/<channel>` | ✅ |
| `sendAlert()` | POST | `/api/alerts/send` | ✅ |

### ML Train & Config (api_sync.py)
| Frontend Method | HTTP | Path | Status |
|---|---|---|---|
| `getMLConfig()` / `saveMLConfig()` | GET/POST | `/api/ml/config` | ✅ |
| `startMLTraining()` | POST | `/api/ml/train` | ✅ |

---

## 4. Files Modified

| File | Changes |
|------|---------|
| `api_v2.py` | Removed 3 duplicate config routes (gann/ehlers/astro). Added `/strategies/optimize` endpoint. |
| `apiService.ts` | Fixed `saveTradingModes` payload shape. Fixed `saveLeverageConfig` payload shape. |
| `config_sync_api.py` | Removed 8 duplicate routes (trading-modes, leverage, risk, scanner) that clashed with api_sync.py. |
| `missing_endpoints_api.py` | Removed 10 duplicate routes (settings load/save, strategy-weights, instruments, settings/load-all) that clashed with config_sync_api.py. |

---

## 5. Bookmap & Open Terminal Backend Audit (2026-02-14)

### 🔴 CRITICAL — WebSocket Namespace Mismatch (FIXED)
| Issue | Detail | Fix |
|---|---|---|
| Frontend connects to default `/` namespace | `io(WS_BASE_URL, { path: '/socket.io' })` | ✅ Added default namespace handlers |
| Backend only registered `/ws` namespace handlers | `@socketio.on('connect', namespace='/ws')` | ✅ Kept `/ws` AND added default namespace handlers |
| `price_stream_worker` only emitted on `/ws` | `socketio.emit('price_update', data, namespace='/ws')` | ✅ Now emits on BOTH namespaces |

### 🔴 CRITICAL — Missing Backend Endpoints for Bookmap/Terminal (FIXED)
| Endpoint | Method | Purpose | Status |
|---|---|---|---|
| `/api/bookmap/depth/<symbol>` | GET | Order book / DOM depth | ✅ Created |
| `/api/bookmap/tape/<symbol>` | GET | Time & Sales data | ✅ Created |
| `/api/bookmap/heatmap/<symbol>` | GET | Heatmap historical snapshots | ✅ Created |
| `/api/bookmap/footprint/<symbol>` | GET | Footprint/cluster chart data | ✅ Created |
| `/api/bookmap/detection/<symbol>` | GET | Iceberg/spoofing/stop-run detection | ✅ Created |
| `/api/bookmap/cvd/<symbol>` | GET | Cumulative Volume Delta | ✅ Created |
| `/api/terminal/command` | POST | Execute terminal commands | ✅ Created |
| `/api/terminal/history` | GET | Command history | ✅ Created |
| `/api/terminal/watchlist` | GET/POST/DELETE | Watchlist management | ✅ Created |
| `/api/terminal/fundamental/<symbol>` | GET | Fundamental analysis data | ✅ Created |
| `/api/terminal/news` | GET | Market news feed | ✅ Created |
| `/api/terminal/options/<symbol>` | GET | Options chain overview | ✅ Created |

### 🔴 WebSocket Events Added for Real-time Bookmap/Terminal
| Event | Direction | Purpose |
|---|---|---|
| `subscribe_depth` | Client → Server | Subscribe to real-time depth updates |
| `depth_update` | Server → Client | Real-time order book depth data |
| `subscribe_tape` | Client → Server | Subscribe to time & sales |
| `tape_update` | Server → Client | Real-time trade tape data |
| `terminal_command` | Client → Server | Execute terminal command via WS |
| `terminal_result` | Server → Client | Terminal command result |

### ⚠️ YAML Config Fixes
| File | Issue | Fix |
|---|---|---|
| `options_config.yaml` line 24 | Corrupted value `7-the-money)` | ✅ Fixed to `7` |
| `options_config.yaml` line 41 | Duplicate `greeks` key (overrides first greeks block) | ✅ Renamed to `greeks_calculation` |
| `config_sync_api.py` line 67-78 | `hft_config.yaml` missing from config sync list | ✅ Added |

### Files Created/Modified
| File | Changes |
|------|---------|
| `core/bookmap_terminal_api.py` | **NEW** — Full API Blueprint for Bookmap & Terminal features |
| `api_v2.py` | Added default namespace WS handlers, bookmap WS events, blueprint registration |
| `config_sync_api.py` | Added `hft_config.yaml` to sync list |
| `config/options_config.yaml` | Fixed corrupted value and duplicate key |

---

## 6. Verification

- ✅ TypeScript compilation: **0 errors**
- ✅ All 80+ frontend API calls have matching backend routes
- ✅ No duplicate route conflicts remain
- ✅ Payload shapes match between frontend and backend
- ✅ Data source exclusively uses broker connectors (MetaTrader, Exchange/CCXT, FIX)
- ✅ Frontend default data source set to `'broker'`
- ✅ Flask debug mode defaults to `False` in production
- ✅ All 11 YAML config files parse correctly
- ✅ Bookmap & Terminal backend endpoints operational
- ✅ WebSocket namespace mismatch resolved
- ✅ `bookmap_terminal_api.py` syntax validated

