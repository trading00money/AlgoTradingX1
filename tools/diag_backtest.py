import sys

from loguru import logger

# Configure loguru ASAP (before importing the app) so we only print DIAG lines.
logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    filter=lambda record: "DIAG trade#" in record["message"],
)

import run


def main() -> int:
    config = {
        "strategy_config": run.load_config("strategy_config.yaml"),
        "broker_config": run.load_config("broker_config.yaml"),
        "gann_config": run.load_config("gann_config.yaml"),
        "risk_config": run.load_config("risk_config.yaml"),
        "backtest_config": run.load_config("backtest_config.yaml"),
        "ml_config": run.load_config("ml_config.yaml"),
        "ehlers_config": run.load_config("ehlers_config.yaml"),
        "astro_config": run.load_config("astro_config.yaml"),
    }

    run.run_backtest(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

