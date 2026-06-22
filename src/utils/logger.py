"""
Logger — Structured logging setup using structlog.

Provides consistent, JSON-structured logging across all
pipeline components for easy debugging and monitoring.
"""

import sys
import io
import structlog
import logging


def _ensure_utf8_stdout():
    """
    Ensure sys.stdout can handle Unicode on Windows.

    Windows console defaults to cp1252, which crashes on characters
    like ₹ (Rupee sign). This wraps stdout in a UTF-8 writer with
    error replacement so structlog's PrintLoggerFactory never raises
    UnicodeEncodeError.
    """
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
        try:
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )
        except AttributeError:
            # Not a real file stream (e.g., in some test environments)
            pass
    if sys.stderr.encoding and sys.stderr.encoding.lower().replace("-", "") != "utf8":
        try:
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )
        except AttributeError:
            pass


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured logging for the application."""

    # Ensure UTF-8 output before structlog starts printing
    _ensure_utf8_stdout()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    """Get a named structured logger."""
    return structlog.get_logger(name)

