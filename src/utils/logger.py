"""
Logger — Structured logging setup using structlog.

Provides consistent, JSON-structured logging across all
pipeline components for easy debugging and monitoring.
"""

import structlog
import logging


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured logging for the application."""

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
