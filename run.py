import argparse
import yaml
from loguru import logger
from typing import Dict
from dotenv import load_dotenv
import os
load_dotenv()

# Import core components
from core.data_feed import DataFeed
from core.gann_engine import GannEngine
from core.ehlers_engine import EhlersEngine
from core.astro_engine import AstroEngine
from core.ml_engine import MLEngine
from core.signal_engine import AISignalEngine
from backtest.backtester import Backtester
from backtest.metrics import calculate_performance_metrics
import json


# Get the absolute path of the directory containing run.py
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_DIR = os.path.join(SCRIPT_DIR, 'config')

def load_config(file_name: str) -> Dict:
    """Loads a YAML configuration file from the config directory."""
    path = os.path.join(CONFIG_DIR, file_name)
    try:
        with open(path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Configuration file not found at: {path}")
        return {}
    except Exception as e:
        logger.error(f"Error loading configuration from {path}: {e}")
        return {}

def run_backtest(config: Dict):
    """
    Orchestrates the backtesting process.
    """
    logger.info("Starting backtest run...")

    # 1. Initialize components
    data_feed = DataFeed(broker_config=config.get('broker_config', {}))
    gann_engine = GannEngine(gann_config=config.get('gann_config', {}))
    ehlers_engine = EhlersEngine(ehlers_config=config.get('ehlers_config', {}))
    astro_engine = AstroEngine(astro_config=config.get('astro_config', {}))
    ml_engine = MLEngine(config) # Pass the full config
    signal_engine = AISignalEngine(config.get('strategy_config', {}))

    # 2. Get historical data
    # For now, we'll hardcode a symbol and date range for testing.
    # In a real scenario, this would be driven by the backtest config.
    symbol = "BTC/USDT"
    start_date = "2024-01-01"
    end_date = "2025-01-01"

    price_data = data_feed.get_historical_data(
        symbol=symbol,
        timeframe="1h",
        start_date=start_date,
        end_date=end_date
    )

    if price_data is None or price_data.empty:
        logger.error("Failed to fetch historical data. Aborting backtest.")
        return

    # 3. Perform analysis
    gann_levels = gann_engine.calculate_sq9_levels(price_data)
    data_with_indicators = ehlers_engine.calculate_all_indicators(price_data)
    astro_events = astro_engine.analyze_dates(price_data.index)
    ml_predictions = ml_engine.get_predictions(data_with_indicators, gann_levels, astro_events)

    # Merge predictions into the main data frame
    if ml_predictions is not None:
        data_with_indicators = data_with_indicators.join(ml_predictions)

    # 4. Generate signals
    signals = signal_engine.generate_signals_sync(data_with_indicators, gann_levels, astro_events)

    if signals.empty:
        logger.warning("No signals were generated. Backtest cannot proceed.")
        return

    # 5. Run the backtester
    logger.info("Signals generated. Handing off to the backtester...")
    backtester = Backtester(config)
    results = backtester.run(price_data, signals)

    # 6. Calculate and display performance metrics
    if results and not results['trades'].empty:
        performance = calculate_performance_metrics(
            equity_curve=results['equity_curve'],
            trades=results['trades'],
            initial_capital=results['initial_capital']
        )
        print("\n--- Backtest Performance Metrics ---")
        print(json.dumps(performance, indent=2))
        print("------------------------------------")

        # In a real GUI, you would plot results['equity_curve']

    logger.success("Backtest run finished.")


def run_live(config: Dict):
    """Orchestrates the live trading process via TradingOrchestrator."""
    import asyncio
    import signal as _signal
    from core.trading_orchestrator import TradingOrchestrator

    logger.info("--- Starting Live Trading Mode ---")

    # Build orchestrator config from loaded configs
    broker_cfg = config.get('broker_config', {})
    strategy_cfg = config.get('strategy_config', {})

    # Collect symbols from enabled trading modes.
    # Each mode uses 'selectedInstrument' (single symbol) or 'symbols' (list).
    symbols = []
    for mode in broker_cfg.get('trading_modes', []):
        if not mode.get('enabled', True):
            continue
        for sym in mode.get('symbols', []):
            if sym and sym not in symbols:
                symbols.append(sym)
        instrument = mode.get('selectedInstrument', '')
        if instrument and instrument not in symbols:
            symbols.append(instrument)
    if not symbols:
        symbols = ["BTC/USDT"]
        logger.warning("No symbols found in broker_config. Defaulting to BTC/USDT.")

    # Timeframes from strategy config or default
    timeframes = strategy_cfg.get('timeframes', ['1h'])
    scan_interval = strategy_cfg.get('scan_interval_seconds', 60)

    # Inject exchange connectors into the data feed singleton before the
    # orchestrator starts, so subscribe_ticks() has something to talk to.
    try:
        from core.realtime_data_feed import get_data_feed
        from core.Binance_connector import BinanceConnector
        data_feed = get_data_feed()
        for mode in broker_cfg.get('trading_modes', []):
            if mode.get('exchange', '').lower() == 'binance' and mode.get('enabled', True):
                connector = BinanceConnector({
                    'api_key': os.environ.get('BINANCE_API_KEY', mode.get('apiKey', '')),
                    'api_secret': os.environ.get('BINANCE_API_SECRET', mode.get('apiSecret', '')),
                    'testnet': mode.get('testnet', False),
                })
                data_feed.add_exchange_connector('binance', connector)
                logger.info("Binance connector injected into data feed.")
                break
    except Exception as e:
        logger.warning(f"Could not initialize Binance connector for data feed: {e}")

    # Pre-initialise the execution gate singleton with the configured mode
    # before the orchestrator calls get_execution_gate() with no args.
    execution_cfg = strategy_cfg.get('execution', {})
    try:
        from core.execution_gate import get_execution_gate
        get_execution_gate(config=execution_cfg)
        logger.info(
            f"Execution gate: mode={execution_cfg.get('trading_mode', 'manual')}, "
            f"paper={execution_cfg.get('paper_trading', True)}"
        )
    except Exception as e:
        logger.warning(f"Could not pre-configure execution gate: {e}")

    orchestrator_cfg = {
        'symbols': symbols,
        'timeframes': timeframes,
        'scan_interval': scan_interval,
        **config,  # pass all configs through for sub-components
    }

    orchestrator = TradingOrchestrator(orchestrator_cfg)

    async def _run():
        started = await orchestrator.start()
        if not started:
            logger.error("Orchestrator failed to start. Aborting live trading.")
            return

        logger.success(f"Live trading running — symbols: {symbols}, timeframes: {timeframes}")
        logger.info("Press Ctrl+C to stop.")

        # Block until a shutdown signal is received
        stop_event = asyncio.Event()

        def _handle_sigint():
            logger.warning("Shutdown signal received. Stopping...")
            stop_event.set()

        loop = asyncio.get_event_loop()
        try:
            loop.add_signal_handler(_signal.SIGINT, _handle_sigint)
            loop.add_signal_handler(_signal.SIGTERM, _handle_sigint)
        except NotImplementedError:
            # Windows does not support add_signal_handler; fall back to KeyboardInterrupt
            pass

        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            logger.warning("KeyboardInterrupt received. Stopping...")
        finally:
            await orchestrator.stop()
            logger.success("Live trading stopped cleanly.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.warning("Interrupted before event loop started.")

def main():
    """
    Main entry point for the application.
    Parses command-line arguments and launches the appropriate mode.
    """
    parser = argparse.ArgumentParser(description="Gann Quant AI Trading Bot")
    parser.add_argument(
        "mode",
        choices=["live", "backtest", "scanner", "trainer", "optimize"],
        help="The mode to run the application in."
    )
    args = parser.parse_args()

    # Load all configurations
    logger.info("Loading all configurations...")
    config = {
        'strategy_config': load_config('strategy_config.yaml'),
        'broker_config': load_config('broker_config.yaml'),
        'gann_config': load_config('gann_config.yaml'),
        'risk_config': load_config('risk_config.yaml'),
        'backtest_config': load_config('backtest_config.yaml'),
        'ml_config': load_config('ml_config.yaml'),
        'ehlers_config': load_config('ehlers_config.yaml'),
        'astro_config': load_config('astro_config.yaml'),
    }

    # Non-critical configs (missing is OK — engines handle absence gracefully)
    _optional_keys = {'ehlers_config', 'astro_config'}
    if not all(v for k, v in config.items() if k not in _optional_keys):
        logger.error("One or more configuration files failed to load. Exiting.")
        return

    if args.mode == "backtest":
        run_backtest(config)
    elif args.mode == "scanner":
        from scanner.market_scanner import MarketScanner
        scanner = MarketScanner(config)
        scanner.run_scan()
    elif args.mode == "trainer":
        run_trainer(config)
    elif args.mode == "live":
        run_live(config)
    else:
        logger.warning(f"Mode '{args.mode}' is not yet implemented.")


def run_trainer(config: Dict):
    """
    Orchestrates the ML model training process.
    """
    logger.info("--- Starting ML Trainer Mode ---")

    # 1. Initialize components
    data_feed = DataFeed(broker_config=config.get('broker_config', {}))
    gann_engine = GannEngine(gann_config=config.get('gann_config', {}))
    ehlers_engine = EhlersEngine(ehlers_config=config.get('ehlers_config', {}))
    astro_engine = AstroEngine(astro_config=config.get('astro_config', {}))
    ml_engine = MLEngine(config)

    # 2. Fetch a large dataset for training
    price_data = data_feed.get_historical_data(
        symbol="BTC/USDT",
        timeframe="1d",
        start_date="2018-01-01",
        end_date="2023-12-31"
    )
    if price_data is None:
        logger.error("Could not fetch data for training. Aborting.")
        return

    # 3. Perform analysis to generate features
    gann_levels = gann_engine.calculate_sq9_levels(price_data)
    data_with_indicators = ehlers_engine.calculate_all_indicators(price_data)
    astro_events = astro_engine.analyze_dates(price_data.index)

    # 4. Train the model
    ml_engine.train_model(data_with_indicators, gann_levels, astro_events)

if __name__ == "__main__":
    main()
