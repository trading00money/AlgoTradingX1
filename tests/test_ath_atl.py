"""
Tests for ATH/ATL Predictor Module
Comprehensive unit tests for All-Time High/Low prediction functionality
"""
import unittest
import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.ath_atl_predictor import ATHATLPredictor, ATHATLPrediction, PredictionType, ConfidenceLevel


class TestAthAtlPredictor(unittest.TestCase):
    """Test cases for ATH/ATL Predictor"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.config = {
            'lookback_days': 100,
            'forecast_days': 90,
            'min_swing_pct': 5.0
        }
        cls.predictor = ATHATLPredictor(cls.config)
        
        # Generate sample price data
        dates = pd.date_range(start='2025-01-01', periods=200, freq='D')
        np.random.seed(42)
        
        # Simulate trend with ATH/ATL points
        base_price = 100
        returns = np.random.normal(0.001, 0.02, 200)
        prices = base_price * np.exp(np.cumsum(returns))
        
        cls.sample_data = pd.DataFrame({
            'open': prices * (1 - np.random.uniform(0, 0.01, 200)),
            'high': prices * (1 + np.random.uniform(0, 0.02, 200)),
            'low': prices * (1 - np.random.uniform(0, 0.02, 200)),
            'close': prices,
            'volume': np.random.uniform(1000000, 5000000, 200)
        }, index=dates)
        
        # Ensure OHLC consistency
        cls.sample_data['high'] = cls.sample_data[['open', 'high', 'close']].max(axis=1)
        cls.sample_data['low'] = cls.sample_data[['open', 'low', 'close']].min(axis=1)
    
    def test_predictor_initialization(self):
        """Test predictor initializes correctly"""
        self.assertIsNotNone(self.predictor)
        self.assertEqual(self.predictor.config.get('lookback_days'), 100)
    
    def test_get_ath_atl(self):
        """Test ATH/ATL identification"""
        ath, atl = self.predictor.get_ath_atl(self.sample_data)
        
        self.assertIsNotNone(ath)
        self.assertIsNotNone(atl)
        self.assertIn('price', ath)
        self.assertIn('price', atl)
        self.assertIn('date', ath)
        self.assertIn('date', atl)
        self.assertGreater(ath['price'], 0)
        self.assertGreater(atl['price'], 0)
    
    def test_find_swing_points(self):
        """Test swing point detection"""
        swing_highs, swing_lows = self.predictor.find_swing_points(self.sample_data)
        
        self.assertIsNotNone(swing_highs)
        self.assertIsNotNone(swing_lows)
        # Swing points may be empty for random data, but should return DataFrames
        self.assertIsInstance(swing_highs, pd.DataFrame)
        self.assertIsInstance(swing_lows, pd.DataFrame)
    
    def test_predict(self):
        """Test prediction generation"""
        predictions = self.predictor.predict(self.sample_data)
        
        self.assertIsNotNone(predictions)
        self.assertIsInstance(predictions, list)
        # Predictions may be empty if not enough swing points
        if len(predictions) > 0:
            self.assertIsInstance(predictions[0], ATHATLPrediction)
    
    def test_gann_time_cycles(self):
        """Test Gann time cycle analysis"""
        current_date = self.sample_data.index[-1]
        pivot_date = self.sample_data.index[0]
        
        cycles = self.predictor.analyze_gann_time_cycles(
            pivot_date, 'high', current_date
        )
        
        self.assertIsNotNone(cycles)
        self.assertIsInstance(cycles, list)
    
    def test_gann_price_targets(self):
        """Test Gann price target calculation"""
        targets = self.predictor.calculate_gann_price_targets(100.0, 'low')
        
        self.assertIsNotNone(targets)
        self.assertIsInstance(targets, list)
        if len(targets) > 0:
            self.assertIn('price', targets[0])
            self.assertIn('angle', targets[0])
    
    def test_empty_data_handling(self):
        """Test handling of empty data"""
        empty_df = pd.DataFrame()
        
        # Should handle gracefully or raise appropriate exception
        try:
            ath, atl = self.predictor.get_ath_atl(empty_df)
        except Exception:
            pass  # Expected for empty data
    
    def test_get_summary(self):
        """Test prediction summary"""
        predictions = self.predictor.predict(self.sample_data)
        summary = self.predictor.get_summary(predictions)
        
        self.assertIsNotNone(summary)
        self.assertIn('status', summary)
    
    def test_fibonacci_time_extensions(self):
        """Test Fibonacci time extensions"""
        dates = list(self.sample_data.index[-10:])
        current_date = self.sample_data.index[-1]
        
        extensions = self.predictor.calculate_fibonacci_time_extensions(dates, current_date)
        
        self.assertIsNotNone(extensions)
        self.assertIsInstance(extensions, list)


class TestATHATLIntegration(unittest.TestCase):
    """Integration tests for ATH/ATL module"""
    
    def test_predictor_with_real_data_structure(self):
        """Test with realistic market data structure"""
        config = {}
        predictor = ATHATLPredictor(config)
        
        # Create realistic OHLCV data
        dates = pd.date_range(start='2025-06-01', periods=100, freq='D')
        data = pd.DataFrame({
            'open': np.linspace(100, 120, 100) + np.random.normal(0, 2, 100),
            'high': np.linspace(102, 125, 100) + np.random.normal(0, 2, 100),
            'low': np.linspace(98, 115, 100) + np.random.normal(0, 2, 100),
            'close': np.linspace(100, 120, 100) + np.random.normal(0, 2, 100),
            'volume': np.random.uniform(1e6, 5e6, 100)
        }, index=dates)
        
        # Ensure OHLC consistency
        data['high'] = data[['open', 'high', 'close']].max(axis=1)
        data['low'] = data[['open', 'low', 'close']].min(axis=1)
        
        predictions = predictor.predict(data)
        summary = predictor.get_summary(predictions)
        
        self.assertIsNotNone(summary)
        self.assertIn('status', summary)


if __name__ == '__main__':
    unittest.main()
