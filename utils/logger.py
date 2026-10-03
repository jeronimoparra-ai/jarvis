#!/usr/bin/env python3
"""
Logger setup for Jarvis
"""

import logging
import sys
from pathlib import Path

def setup_logger(name: str = "jarvis", log_file: str = "jarvis.log") -> logging.Logger:
    """
    Set up and return a logger
    
    Args:
        name: Logger name
        log_file: Log file path
        
    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler
    try:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Could not set up file logging: {e}")
        
    return logger
