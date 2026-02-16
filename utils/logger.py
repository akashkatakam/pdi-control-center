import logging
import sys
from pathlib import Path
from datetime import datetime
import os

# Create logs directory
Path("logs").mkdir(exist_ok=True)


def setup_logger(name: str, level: str = None) -> logging.Logger:
    """
    Setup logger with both file and console handlers
    """
    # Get log level from environment or default to DEBUG for development
    log_level = getattr(logging, (level or os.getenv("LOG_LEVEL", "DEBUG")).upper())

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # Always set logger to DEBUG

    # Prevent duplicate handlers
    if logger.handlers:
        return logger

    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # File handler - detailed logs (always DEBUG)
    log_file = f"logs/pdi_app_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)  # File always captures DEBUG
    file_handler.setFormatter(detailed_formatter)

    # Console handler - respects LOG_LEVEL
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)  # Can be controlled via env
    console_handler.setFormatter(simple_formatter)

    # Error file handler - separate file for errors
    error_file = f"logs/pdi_errors_{datetime.now().strftime('%Y%m%d')}.log"
    error_handler = logging.FileHandler(error_file, encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)

    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.addHandler(error_handler)

    return logger


# Export a default logger instance
logger = setup_logger("pdi_control_center")
