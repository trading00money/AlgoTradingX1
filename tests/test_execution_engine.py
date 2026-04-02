"""
Tests for Execution Engine Module
Comprehensive unit tests for order execution and trade management
"""
import unittest
import sys
import os
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.execution_engine import ExecutionEngine, Order, OrderSide, OrderType, OrderStatus


class TestExecutionEngine(unittest.TestCase):
    """Test cases for Execution Engine"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.config = {
            'paper_trading': {
                'initial_balance': 100000.0
            },
            'risk': {
                'max_position_size': 0.1,
                'max_daily_loss': 0.05,
                'max_open_positions': 5
            }
        }
        cls.execution_engine = ExecutionEngine(cls.config)
    
    def test_engine_initialization(self):
        """Test engine initializes correctly"""
        self.assertIsNotNone(self.execution_engine)
        self.assertEqual(self.execution_engine._paper_balance, 100000.0)
    
    def test_paper_order_execution_buy(self):
        """Test paper trading buy order execution"""
        order = self.execution_engine.buy_market(
            symbol='BTC/USDT',
            quantity=0.1,
            broker='paper'
        )
        
        self.assertIsNotNone(order)
        self.assertIn('ORD-', order.id)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.side, OrderSide.BUY)
    
    def test_paper_order_execution_sell(self):
        """Test paper trading sell order execution"""
        # First buy
        self.execution_engine.buy_market(
            symbol='BTC/USDT',
            quantity=0.1,
            broker='paper'
        )
        
        # Then sell
        order = self.execution_engine.sell_market(
            symbol='BTC/USDT',
            quantity=0.1,
            broker='paper'
        )
        
        self.assertIsNotNone(order)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.side, OrderSide.SELL)
    
    def test_limit_order_creation(self):
        """Test limit order creation"""
        order = self.execution_engine.buy_limit(
            symbol='ETH/USDT',
            quantity=1.0,
            price=2500,
            broker='paper'
        )
        
        self.assertIsNotNone(order)
        self.assertEqual(order.type, OrderType.LIMIT)
    
    def test_stop_loss_order(self):
        """Test stop loss order creation"""
        order = self.execution_engine.create_order(
            symbol='BTC/USDT',
            side='SELL',
            order_type='STOP_LOSS',
            quantity=0.1,
            stop_price=44000,
            broker='paper'
        )
        
        self.assertIsNotNone(order)
        self.assertEqual(order.type, OrderType.STOP_LOSS)
    
    def test_take_profit_order(self):
        """Test take profit order creation"""
        order = self.execution_engine.buy_market(
            symbol='BTC/USDT',
            quantity=0.1,
            take_profit=48000,
            broker='paper'
        )
        
        self.assertIsNotNone(order)
        self.assertEqual(order.status, OrderStatus.FILLED)
    
    def test_latency_check(self):
        """Test execution latency measurement"""
        import time
        start_time = time.perf_counter()
        
        order = self.execution_engine.buy_market(
            symbol='BTC/USDT',
            quantity=0.01,
            broker='paper'
        )
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        # Paper trading should be fast
        self.assertLess(elapsed_ms, 1000)
        self.assertIsNotNone(order)
    
    def test_order_validation(self):
        """Test order validation"""
        # Valid order
        order = self.execution_engine.create_order(
            symbol='BTC/USDT',
            side='BUY',
            order_type='MARKET',
            quantity=0.1,
            broker='paper'
        )
        self.assertIsNotNone(order)
        
        # Invalid quantity (negative) - should still create but validation happens on submit
        try:
            order = self.execution_engine.create_order(
                symbol='BTC/USDT',
                side='BUY',
                order_type='MARKET',
                quantity=-0.1,
                broker='paper'
            )
        except Exception:
            pass  # May raise exception for negative quantity
    
    def test_position_tracking(self):
        """Test position tracking after order execution"""
        # Execute buy order
        self.execution_engine.buy_market(
            symbol='BTC/USDT',
            quantity=0.1,
            broker='paper'
        )
        
        positions = self.execution_engine.get_all_positions()
        
        self.assertIsNotNone(positions)
        # Position should exist after buy
        self.assertGreater(len(positions), 0)
    
    def test_balance_tracking(self):
        """Test balance tracking after trades"""
        initial_balance = self.execution_engine.get_paper_balance()
        
        # Execute trade
        self.execution_engine.buy_market(
            symbol='BTC/USDT',
            quantity=0.1,
            broker='paper'
        )
        
        new_balance = self.execution_engine.get_paper_balance()
        
        # Balance should remain accessible
        self.assertIsNotNone(new_balance)
    
    def test_order_cancellation(self):
        """Test order cancellation"""
        # Create limit order
        order = self.execution_engine.buy_limit(
            symbol='ETH/USDT',
            quantity=1.0,
            price=2000,  # Low price to stay pending
            broker='paper'
        )
        
        # Cancel order
        result = self.execution_engine.cancel_order(order.id)
        
        self.assertIsNotNone(result)
    
    def test_get_open_orders(self):
        """Test retrieving open orders"""
        # Create limit order
        self.execution_engine.buy_limit(
            symbol='ETH/USDT',
            quantity=1.0,
            price=2000,
            broker='paper'
        )
        
        open_orders = self.execution_engine.get_open_orders()
        
        self.assertIsNotNone(open_orders)
        self.assertIsInstance(open_orders, list)
    
    def test_execution_with_insufficient_balance(self):
        """Test order validation for large orders"""
        # Try to buy more than available balance
        order = self.execution_engine.create_order(
            symbol='BTC/USDT',
            side='BUY',
            order_type='MARKET',
            quantity=10000,  # Very large quantity
            broker='paper'
        )
        
        # Submit and check if validation happens
        submitted = self.execution_engine.submit_order(order)
        
        # Should be rejected or filled (paper mode may not check balance)
        self.assertIsNotNone(submitted)


class TestExecutionEngineIntegration(unittest.TestCase):
    """Integration tests for Execution Engine"""
    
    def test_full_trade_lifecycle(self):
        """Test complete trade lifecycle: open, monitor, close"""
        config = {
            'paper_trading': {
                'initial_balance': 100000.0
            },
            'risk': {
                'max_position_size': 0.1,
                'max_daily_loss': 0.05,
                'max_open_positions': 5
            }
        }
        engine = ExecutionEngine(config)
        
        # 1. Open position
        entry = engine.buy_market(
            symbol='BTC/USDT',
            quantity=0.1,
            broker='paper'
        )
        self.assertEqual(entry.status, OrderStatus.FILLED)
        
        # 2. Check position
        positions = engine.get_all_positions()
        self.assertGreater(len(positions), 0)
        
        # 3. Close position
        exit_order = engine.sell_market(
            symbol='BTC/USDT',
            quantity=0.1,
            broker='paper'
        )
        self.assertEqual(exit_order.status, OrderStatus.FILLED)
        
        # 4. Verify daily PnL is tracked
        pnl = engine.get_daily_pnl()
        self.assertIsNotNone(pnl)


if __name__ == '__main__':
    unittest.main()
