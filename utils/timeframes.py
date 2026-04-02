"""
Shared Timeframe Constants for Backend

This module provides a single source of truth for all timeframe definitions.
Import from this module instead of defining timeframes locally.
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class TimeframeUnit(Enum):
    """Timeframe unit types"""
    MINUTE = "M"
    HOUR = "H"
    DAY = "D"
    WEEK = "W"
    MONTH = "MN"


@dataclass
class TimeframeOption:
    """Timeframe option with metadata"""
    value: str
    label: str
    minutes: int
    unit: TimeframeUnit


# Standard timeframes with full metadata
TIMEFRAMES: List[TimeframeOption] = [
    TimeframeOption("M1", "1 Minute", 1, TimeframeUnit.MINUTE),
    TimeframeOption("M2", "2 Minutes", 2, TimeframeUnit.MINUTE),
    TimeframeOption("M3", "3 Minutes", 3, TimeframeUnit.MINUTE),
    TimeframeOption("M5", "5 Minutes", 5, TimeframeUnit.MINUTE),
    TimeframeOption("M10", "10 Minutes", 10, TimeframeUnit.MINUTE),
    TimeframeOption("M15", "15 Minutes", 15, TimeframeUnit.MINUTE),
    TimeframeOption("M30", "30 Minutes", 30, TimeframeUnit.MINUTE),
    TimeframeOption("H1", "1 Hour", 60, TimeframeUnit.HOUR),
    TimeframeOption("H2", "2 Hours", 120, TimeframeUnit.HOUR),
    TimeframeOption("H4", "4 Hours", 240, TimeframeUnit.HOUR),
    TimeframeOption("H6", "6 Hours", 360, TimeframeUnit.HOUR),
    TimeframeOption("H8", "8 Hours", 480, TimeframeUnit.HOUR),
    TimeframeOption("H12", "12 Hours", 720, TimeframeUnit.HOUR),
    TimeframeOption("D1", "1 Day", 1440, TimeframeUnit.DAY),
    TimeframeOption("D3", "3 Days", 4320, TimeframeUnit.DAY),
    TimeframeOption("W1", "1 Week", 10080, TimeframeUnit.WEEK),
    TimeframeOption("MN", "1 Month", 43200, TimeframeUnit.MONTH),
]

# Array of timeframe values only
TIMEFRAME_VALUES: List[str] = [tf.value for tf in TIMEFRAMES]

# Dictionary mapping value to label
TIMEFRAME_LABELS: Dict[str, str] = {tf.value: tf.label for tf in TIMEFRAMES}

# Dictionary mapping value to minutes
TIMEFRAME_MINUTES: Dict[str, int] = {tf.value: tf.minutes for tf in TIMEFRAMES}

# Common timeframes for quick access
class CommonTimeframes:
    ONE_MINUTE = "M1"
    FIVE_MINUTES = "M5"
    FIFTEEN_MINUTES = "M15"
    ONE_HOUR = "H1"
    FOUR_HOURS = "H4"
    ONE_DAY = "D1"
    ONE_WEEK = "W1"

# Short timeframe list for simple selectors
SHORT_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1", "W1"]

# Intraday timeframes only
INTRADAY_TIMEFRAMES = [tf for tf in TIMEFRAMES if tf.minutes < 1440]

# Swing trading timeframes
SWING_TIMEFRAMES = [tf for tf in TIMEFRAMES if 1440 <= tf.minutes < 10080]


def get_timeframe_by_value(value: str) -> Optional[TimeframeOption]:
    """Get timeframe option by value"""
    for tf in TIMEFRAMES:
        if tf.value == value:
            return tf
    return None


def get_timeframe_minutes(value: str) -> int:
    """Get minutes for a timeframe value, defaults to 60 (H1) if not found"""
    return TIMEFRAME_MINUTES.get(value, 60)


def validate_timeframe(value: str) -> bool:
    """Validate if a timeframe value is valid"""
    return value in TIMEFRAME_VALUES
