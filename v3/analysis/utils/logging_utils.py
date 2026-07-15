"""Structured JSON logging setup for the pipeline."""
from __future__ import annotations

import json
import logging
import sys

_STANDARD_KEYS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            # "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"), # Use when working/transitioning to a cloud
            "timestamp": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
        }
        # Anything passed via logger.info(..., extra={...}) gets merged in
        extras = {k: v for k, v in record.__dict__.items() if k not in _STANDARD_KEYS}
        payload.update(extras)
        return json.dumps(payload)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Call once at program start (e.g. in a run script or __main__)."""
    logger = logging.getLogger("lcms_pipeline")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    return logger