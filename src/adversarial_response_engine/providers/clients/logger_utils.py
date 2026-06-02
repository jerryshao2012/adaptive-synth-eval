"""Centralized logging configuration utility."""
# Sibling copy exists at adaptive_synth_eval/clients/logger_utils.py — keep in sync manually.

from __future__ import annotations

import logging
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def setup_logger(
        name: Optional[str] = None,
        level: Optional[str] = None,
        format_string: Optional[str] = None,
) -> logging.Logger:
    log_level = level or os.getenv("LOG_LEVEL", "INFO").upper()
    if format_string is None:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format=format_string,
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    return logging.getLogger(name)
