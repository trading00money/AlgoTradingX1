"""
Utility Decorators for API Error Handling

This module provides decorators for consistent error handling
across API endpoints, reducing boilerplate code and improving
maintainability.
"""

import functools
from typing import Callable, Dict, Any, Optional, Tuple
from flask import jsonify, Response
from loguru import logger
from datetime import datetime


import traceback


def api_error_handler(f: Callable) -> Callable:
    """
    Decorator for consistent API error handling.
    
    Usage:
        @api_error_handler
        def my_endpoint():
            # Your endpoint logic
            return {"data": result}
    
    This will automatically:
    - Catch exceptions and log them
    - Return consistent error responses
    - Add timestamp to responses
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs) -> Response:
        try:
            result = f(*args, **kwargs)
            
            # If result is already a Response, return as-is
            if isinstance(result, Response):
                return result
            
            
            # If result is a tuple (data, status_code)
            if isinstance(result, tuple):
                data, status_code = result
                return jsonify({
                    "success": True,
                    "data": data,
                    "timestamp": datetime.now().isoformat()
                }), status_code
            
            
            # Default: return as JSON response
            return jsonify({
                "success": True,
                "data": result,
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            error_message = str(e)
            error_type = type(e).__name__
            
            # Log the full error with traceback for debugging
            logger.error(f"API Error in {f.__name__}: {error_message}\\n{traceback.format_exc()}")
            
            # Return consistent error response
            return jsonify({
                "success": False,
                "error": error_message,
                "error_type": error_type,
                "timestamp": datetime.now().isoformat()
            }), 500
            
    return decorated_function


