"""Logging configuration for file processor.

Provides centralized logging setup with:
- Console and file handlers
- Configurable log levels
- Log rotation
- Structured log format
"""

import logging
import sys
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime

from config import settings


def setup_logger(
    name: str = __name__,
    log_dir: str = None,
    console_level: int = None,
    file_level: int = None
) -> logging.Logger:
    """Set up logger with console and file handlers.
    
    Args:
        name: Logger name (typically __name__)
        log_dir: Directory for log files (default from config)
        console_level: Logging level for console (default from config)
        file_level: Logging level for file (default from config)
    
    Returns:
        Configured logger instance
    """
    # Use config defaults if not specified
    if log_dir is None:
        log_dir = settings.LOG_DIR
    if console_level is None:
        console_level = getattr(logging, settings.LOG_LEVEL_CONSOLE)
    if file_level is None:
        file_level = getattr(logging, settings.LOG_LEVEL_FILE)
    
    logger = logging.getLogger(name)
    
    # Prevent duplicate handlers on repeated calls
    if logger.handlers:
        return logger
    
    # Logger accepts all messages; handlers filter by level
    logger.setLevel(logging.DEBUG)
    
    # Formatter with detailed information
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler with rotation
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    if settings.LOG_USE_SINGLE_FILE:
        # Use single log file for all application runs
        log_file = log_path / "app.log"
    else:
        # Use timestamped log file (old behavior)
        current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        log_file = log_path / f"log_{current_time}.log"
    
    file_handler = RotatingFileHandler(
        log_file,
        encoding='utf-8',
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


# Shared file handler for all loggers to write to the same file
_shared_file_handler = None

def get_shared_file_handler():
    """Get or create a shared file handler for unified logging."""
    global _shared_file_handler
    
    if _shared_file_handler is not None:
        return _shared_file_handler
    
    log_path = Path(settings.LOG_DIR)
    log_path.mkdir(parents=True, exist_ok=True)
    
    if settings.LOG_USE_SINGLE_FILE:
        log_file = log_path / "app.log"
    else:
        current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        log_file = log_path / f"log_{current_time}.log"
    
    _shared_file_handler = RotatingFileHandler(
        log_file,
        encoding='utf-8',
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    _shared_file_handler.setLevel(getattr(logging, settings.LOG_LEVEL_FILE))
    _shared_file_handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    
    return _shared_file_handler


# Create default logger for the project
default_logger = setup_logger(settings.PROJECT_NAME)
