/**
 * Shared Timeframe Constants
 * 
 * This file provides a single source of truth for all timeframe definitions.
 * Import from this file instead of defining timeframes locally.
 */

export interface TimeframeOption {
  value: string;
  label: string;
  minutes?: number;
}

/**
 * Standard timeframes with labels for UI display
 */
export const TIMEFRAMES: TimeframeOption[] = [
  { value: "M1", label: "1 Minute", minutes: 1 },
  { value: "M2", label: "2 Minutes", minutes: 2 },
  { value: "M3", label: "3 Minutes", minutes: 3 },
  { value: "M5", label: "5 Minutes", minutes: 5 },
  { value: "M10", label: "10 Minutes", minutes: 10 },
  { value: "M15", label: "15 Minutes", minutes: 15 },
  { value: "M30", label: "30 Minutes", minutes: 30 },
  { value: "H1", label: "1 Hour", minutes: 60 },
  { value: "H2", label: "2 Hours", minutes: 120 },
  { value: "H4", label: "4 Hours", minutes: 240 },
  { value: "H6", label: "6 Hours", minutes: 360 },
  { value: "H8", label: "8 Hours", minutes: 480 },
  { value: "H12", label: "12 Hours", minutes: 720 },
  { value: "D1", label: "1 Day", minutes: 1440 },
  { value: "D3", label: "3 Days", minutes: 4320 },
  { value: "W1", label: "1 Week", minutes: 10080 },
  { value: "MN", label: "1 Month", minutes: 43200 },
];

/**
 * Array of timeframe values only (for backward compatibility)
 */
export const TIMEFRAME_VALUES = TIMEFRAMES.map(tf => tf.value);

/**
 * Map of timeframe value to label
 */
export const TIMEFRAME_LABELS = Object.fromEntries(
  TIMEFRAMES.map(tf => [tf.value, tf.label])
) as Record<string, string>;

/**
 * Map of timeframe value to minutes
 */
export const TIMEFRAME_MINUTES = Object.fromEntries(
  TIMEFRAMES.filter(tf => tf.minutes !== undefined).map(tf => [tf.value, tf.minutes])
) as Record<string, number>;

/**
 * Common timeframes for quick access
 */
export const COMMON_TIMEFRAMES = {
  ONE_MINUTE: "M1",
  FIVE_MINUTES: "M5",
  FIFTEEN_MINUTES: "M15",
  ONE_HOUR: "H1",
  FOUR_HOURS: "H4",
  ONE_DAY: "D1",
  ONE_WEEK: "W1",
} as const;

/**
 * Short timeframe list for simple selectors
 */
export const SHORT_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1", "W1"];

/**
 * Intraday timeframes only
 */
export const INTRADAY_TIMEFRAMES = TIMEFRAMES.filter(tf => 
  tf.minutes !== undefined && tf.minutes < 1440
);

/**
 * Swing trading timeframes
 */
export const SWING_TIMEFRAMES = TIMEFRAMES.filter(tf => 
  tf.minutes !== undefined && tf.minutes >= 1440 && tf.minutes < 10080
);

export default TIMEFRAMES;
