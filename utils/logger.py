#!/usr/bin/env python3
"""
Logger setup for Jarvis.

- Handlers en el logger raíz (core/* y skills/* visibles).
- Filtro anti-secretos: api_key/token/password nunca salen en logs.
- INFO por defecto; DEBUG solo con JARVIS_DEBUG=1.
- Rotación simple: jarvis.log máx 1 MB x3.
"""

import logging
import logging.handlers
import os
import sys

from utils.secrets import RedactFilter


def setup_logger(name: str = "jarvis", log_file: str = "jarvis.log") -> logging.Logger:
    """
    Set up and return a logger

    Args:
        name: Logger name
        log_file: Log file path

    Returns:
        Configured logger
    """
    debug = os.getenv("JARVIS_DEBUG", "").strip().lower() in ("1", "true", "yes")
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(logging.DEBUG if debug else logging.INFO)
        return logging.getLogger(name)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    redact = RedactFilter()

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    console_handler.addFilter(redact)
    root.addHandler(console_handler)

    # File handler con rotación (3 x 1 MB)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=3)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'))
        file_handler.addFilter(redact)
        root.addHandler(file_handler)
    except Exception as e:
        print(f"Could not set up file logging: {e}")

    return logger
