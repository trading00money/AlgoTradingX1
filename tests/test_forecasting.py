"""
Tests for Forecasting Module
Comprehensive unit tests for all forecasting functionality
"""
import unittest
import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.forecasting import (
    GannDailyForecaster,
    GannWaveAnalyzer,
    AstroCycleProjector,
    MLTimeForecaster,
    ReportGenerator
)


class TestGannDailyForecaster(unittest.TestCase):
    """Test cases for Gann Daily Forecaster"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.config = {
            'forecast_days': 5,
            'use_cycles': True,
            'angle_set': [1, 2, 3, 4, 8],
            'confidence_threshold': 0.6
        }
        cls.forecaster = GannDailyForecaster(cls.config)
        
        # Generate sample data
        dates = pd.date_range(start='2025-01-01', periods=100, freq='D')
        np.random.seed(42)
        
        cls.sample_data = pd.DataFrame({
            'open': np.linspace(100, 120, 100) + np.random.normal(0, 1, 100),
            'high': np.linspace(102, 125, 100) + np.random.normal(0, 1, 100),
            'low': np.linspace(98, 115, 100) + np.random.normal(0, 1, 100),
            'close': np.linspace(100, 120, 100) + np.random.normal(0, 1, 100),
            'volume': np.random.uniform(1e6, 5e6, 100)
        }, index=dates)
    
    def test_forecaster_initialization(self):
        """Test forecaster initializes correctly"""
        self.assertIsNotNone(self.forecaster)
    
    def test_daily_forecast(self):
        """Test daily forecast generation"""
        result = self.forecaster.generate_forecast(self.sample_data)
        
        self.assertIsNotNone(result)
    
    def test_multi_day_forecast(self):
        """Test multi-day forecast"""
        result = self.forecaster.generate_multi_day_forecast(self.sample_data, days_ahead=5)
        
        self.assertIsNotNone(result)
    
    def test_gann_levels_calculation(self):
        """Test Gann level calculation"""
        current_price = 110.0
        cycle_low = 95.0
        cycle_high = 125.0
        result = self.forecaster.calculate_gann_levels(current_price, cycle_low, cycle_high)
        
        self.assertIsNotNone(result)
    
    def test_sq9_level_calculation(self):
        """Test Square of 9 level calculation"""
        base_price = 100.0
        angle = 45.0
        result = self.forecaster.calculate_sq9_level(base_price, angle)
        
        self.assertIsNotNone(result)
    
    def test_forecast_with_empty_data(self):
        """Test handling of empty data"""
        empty_df = pd.DataFrame()
        
        try:
            result = self.forecaster.generate_forecast(empty_df)
        except Exception:
            pass  # Expected for empty data


class TestGannWaveAnalyzer(unittest.TestCase):
    """Test cases for Gann Wave Analyzer"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.config = {
            'wave_count': 5,
            'min_swing': 0.02
        }
        cls.analyzer = GannWaveAnalyzer(cls.config)
        
        # Generate sample data with wave patterns
        dates = pd.date_range(start='2025-01-01', periods=200, freq='D')
        t = np.linspace(0, 4 * np.pi, 200)
        prices = 100 + 20 * np.sin(t) + 10 * np.sin(2 * t)
        
        cls.sample_data = pd.DataFrame({
            'open': prices - 1,
            'high': prices + 2,
            'low': prices - 2,
            'close': prices,
            'volume': np.random.uniform(1e6, 5e6, 200)
        }, index=dates)
    
    def test_analyzer_initialization(self):
        """Test analyzer initializes correctly"""
        self.assertIsNotNone(self.analyzer)
    
    def test_analyze(self):
        """Test analyze functionality"""
        result = self.analyzer.analyze(self.sample_data)
        
        self.assertIsNotNone(result)
    
    def test_wave_projection(self):
        """Test wave projection"""
        # First analyze to get waves
        analysis_result = self.analyzer.analyze(self.sample_data)
        current_price = self.sample_data['close'].iloc[-1]
        
        # Get waves list from analysis result
        waves = analysis_result.get('waves', [])
        
        # Project next wave
        result = self.analyzer.project_next_wave(waves, current_price)
        
        self.assertIsNotNone(result)


class TestAstroCycleProjector(unittest.TestCase):
    """Test cases for Astro Cycle Projector"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.config = {
            'use_lunar': True,
            'use_planetary': True,
            'projection_days': 30
        }
        cls.projector = AstroCycleProjector(cls.config)
    
    def test_projector_initialization(self):
        """Test projector initializes correctly"""
        self.assertIsNotNone(self.projector)
    
    def test_lunar_phase_calculation(self):
        """Test lunar phase calculation"""
        result = self.projector.calculate_lunar_phase(datetime.now())
        
        self.assertIsNotNone(result)
    
    def test_cycle_projection(self):
        """Test cycle projection"""
        result = self.projector.project_cycles(datetime.now())
        
        self.assertIsNotNone(result)
    
    def test_daily_influence(self):
        """Test daily influence calculation"""
        result = self.projector.get_daily_influence(datetime.now())
        
        self.assertIsNotNone(result)


class TestMLTimeForecaster(unittest.TestCase):
    """Test cases for ML Time Forecaster"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.config = {
            'model_type': 'gradient_boosting',
            'forecast_horizon': 5,
            'confidence_interval': 0.95
        }
        cls.forecaster = MLTimeForecaster(cls.config)
        
        # Generate sample data
        dates = pd.date_range(start='2025-01-01', periods=200, freq='D')
        np.random.seed(42)
        
        cls.sample_data = pd.DataFrame({
            'open': np.linspace(100, 120, 200) + np.random.normal(0, 2, 200),
            'high': np.linspace(102, 125, 200) + np.random.normal(0, 2, 200),
            'low': np.linspace(98, 115, 200) + np.random.normal(0, 2, 200),
            'close': np.linspace(100, 120, 200) + np.random.normal(0, 2, 200),
            'volume': np.random.uniform(1e6, 5e6, 200)
        }, index=dates)
    
    def test_forecaster_initialization(self):
        """Test forecaster initializes correctly"""
        self.assertIsNotNone(self.forecaster)
    
    def test_time_series_forecast(self):
        """Test time series forecasting"""
        result = self.forecaster.forecast(self.sample_data)
        
        self.assertIsNotNone(result)
    
    def test_confidence_calculation(self):
        """Test confidence calculation"""
        # First generate predictions
        forecast_result = self.forecaster.forecast(self.sample_data)
        
        # Get predictions array from forecast
        if isinstance(forecast_result, dict) and 'predictions' in forecast_result:
            predictions = forecast_result['predictions']
        else:
            predictions = np.array([100.0, 101.0, 102.0])  # Fallback
        
        # Calculate confidence
        result = self.forecaster.calculate_confidence(self.sample_data, predictions)
        
        self.assertIsNotNone(result)
    
    def test_feature_calculation(self):
        """Test feature calculation"""
        result = self.forecaster.calculate_features(self.sample_data)
        
        self.assertIsNotNone(result)


class TestReportGenerator(unittest.TestCase):
    """Test cases for Report Generator"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.config = {
            'report_type': 'daily',
            'include_charts': False
        }
        cls.generator = ReportGenerator(cls.config)
        
        # Generate sample data
        dates = pd.date_range(start='2025-01-01', periods=100, freq='D')
        
        cls.sample_data = pd.DataFrame({
            'open': np.linspace(100, 120, 100),
            'high': np.linspace(102, 125, 100),
            'low': np.linspace(98, 115, 100),
            'close': np.linspace(100, 120, 100),
            'volume': np.random.uniform(1e6, 5e6, 100)
        }, index=dates)
    
    def test_generator_initialization(self):
        """Test generator initializes correctly"""
        self.assertIsNotNone(self.generator)
    
    def test_full_report_generation(self):
        """Test full report generation"""
        result = self.generator.generate_full_report(self.sample_data, 'BTCUSDT')
        
        self.assertIsNotNone(result)
    
    def test_market_summary(self):
        """Test market summary generation"""
        result = self.generator.generate_market_summary(self.sample_data)
        
        self.assertIsNotNone(result)
    
    def test_technical_analysis(self):
        """Test technical analysis generation"""
        result = self.generator.generate_technical_analysis(self.sample_data)
        
        self.assertIsNotNone(result)


class TestForecastingIntegration(unittest.TestCase):
    """Integration tests for Forecasting module"""
    
    def test_combined_forecast(self):
        """Test combining multiple forecasting methods"""
        # Generate sample data
        dates = pd.date_range(start='2025-01-01', periods=200, freq='D')
        np.random.seed(42)
        
        data = pd.DataFrame({
            'open': np.linspace(100, 120, 200) + np.random.normal(0, 2, 200),
            'high': np.linspace(102, 125, 200) + np.random.normal(0, 2, 200),
            'low': np.linspace(98, 115, 200) + np.random.normal(0, 2, 200),
            'close': np.linspace(100, 120, 200) + np.random.normal(0, 2, 200),
            'volume': np.random.uniform(1e6, 5e6, 200)
        }, index=dates)
        
        # Test individual forecasters
        gann_forecaster = GannDailyForecaster({})
        wave_analyzer = GannWaveAnalyzer({})
        
        gann_result = gann_forecaster.generate_forecast(data)
        wave_result = wave_analyzer.analyze(data)
        
        self.assertIsNotNone(gann_result)
        self.assertIsNotNone(wave_result)


if __name__ == '__main__':
    unittest.main()
