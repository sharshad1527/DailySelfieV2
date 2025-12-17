"""
logging.py

Centralized logging utilities for DailySelfie.

Provides:
- JsonLineFormatter: compact JSONL formatter for structured logs
- init_logger: initialise a root "dailyselfie" logger with RotatingFileHandler
- get_logger: convenience to fetch child loggers
- read_jsonl_tail: helper to read the last N JSON objects from a JSONL log file
- LogContext: Context manager for injecting context into logs (e.g. session_id)

Design notes:
- Logs are written in UTF-8 JSON lines. Each record contains: ts (ISO UTC), level, logger,
  msg, and optional meta and uuid fields.
- Includes a separate 'dailyselfie.error.jsonl' for ERROR+ logs.
"""
from __future__ import annotations
import json
import logging
import logging.handlers
import os
import contextvars
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

DEFAULT_LOG_FILENAME = "dailyselfie.jsonl"
ERROR_LOG_FILENAME = "dailyselfie.error.jsonl"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3

# Global context variable for logging context
_log_context = contextvars.ContextVar("log_context", default={})


class LogContext:
    """
    Context manager to inject key-value pairs into all logs within the block.

    Usage:
        with LogContext(session_id="1234"):
            logger.info("Doing something") # will have session_id=1234
    """
    def __init__(self, **kwargs):
        self.new_ctx = kwargs
        self.token = None

    def __enter__(self):
        ctx = _log_context.get().copy()
        ctx.update(self.new_ctx)
        self.token = _log_context.set(ctx)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            _log_context.reset(self.token)


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

        entry: Dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "pid": os.getpid(),
            "thread": record.threadName,
        }

        # Add context from LogContext
        ctx = _log_context.get()
        if ctx:
            entry.update(ctx)

        # Add debug info if debug level
        if record.levelno == logging.DEBUG:
            entry["func"] = record.funcName
            entry["line"] = record.lineno

        if hasattr(record, "meta") and record.meta:
            entry["meta"] = record.meta
        
        # Handle Exception Info
        if record.exc_info:
            # Format the full traceback
            entry["exc"] = self.formatException(record.exc_info)
        
        return json.dumps(entry, ensure_ascii=False)


def _make_rotating_handler(log_file: Path, level: int) -> logging.Handler:
    handler = logging.handlers.RotatingFileHandler(
        filename=str(log_file),
        maxBytes=DEFAULT_MAX_BYTES,
        backupCount=DEFAULT_BACKUP_COUNT,
        encoding="utf-8"
    )
    handler.setFormatter(JsonLineFormatter())
    handler.setLevel(level)
    return handler


def init_logger(logs_dir: Path, console: bool = True) -> logging.Logger:
    """Initialize the root logger. Idempotent."""
    logger = logging.getLogger("dailyselfie")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # Don't double-print to root

    # 1. Main File Handler (All logs DEBUG+)
    main_log = logs_dir / DEFAULT_LOG_FILENAME
    logger.addHandler(_make_rotating_handler(main_log, logging.DEBUG))

    # 2. Error File Handler (Only ERROR+)
    error_log = logs_dir / ERROR_LOG_FILENAME
    logger.addHandler(_make_rotating_handler(error_log, logging.ERROR))

    # 3. Console Handler (Human Readable)
    if console:
        console_h = logging.StreamHandler()
        # Simple formatter for console
        console_h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        console_h.setLevel(logging.INFO)
        logger.addHandler(console_h)

    return logger


def get_logger(child: Optional[str] = None) -> logging.Logger:
    """Get the 'dailyselfie' logger or a child (e.g., 'dailyselfie.camera')."""
    base = "dailyselfie"
    name = f"{base}.{child}" if child else base
    return logging.getLogger(name)


def read_jsonl_tail(log_file: Path, max_lines: int = 200) -> List[Dict[str, Any]]:
    """Read up to `max_lines` JSON objects from the end of a JSONL file.

    This is implemented in a memory-friendly manner by seeking from the end.
    It gracefully ignores malformed lines.
    """
    if not log_file.exists():
        return []

    lines: List[str] = []
    # Read in blocks from the end
    block_size = 4096
    with log_file.open("rb") as f:
        f.seek(0, 2)
        file_size = f.tell()
        if file_size == 0:
            return []
        remaining = file_size
        buffer = b""
        while remaining > 0 and len(lines) < max_lines + 1:
            read_size = min(block_size, remaining)
            f.seek(remaining - read_size)
            chunk = f.read(read_size)
            remaining -= read_size
            buffer = chunk + buffer
            # split into lines
            parts = buffer.split(b"\n")
            # keep the first (possibly partial) piece in buffer
            buffer = parts[0]
            new_lines = [p.decode("utf-8", errors="replace") for p in parts[1:]]
            # prepend because we read backwards
            lines = new_lines + lines
            if remaining == 0 and buffer:
                # left-over first line
                try:
                    lines = [buffer.decode("utf-8", errors="replace")] + lines
                except Exception:
                    pass
            # trim to max_lines to avoid growing too large
            if len(lines) > max_lines:
                lines = lines[-max_lines:]
                break

    # Parse JSON, ignore malformed
    results: List[Dict[str, Any]] = []
    for ln in (lines[-max_lines:] if lines else []):
        ln = ln.strip()
        if not ln:
            continue
        try:
            results.append(json.loads(ln))
        except Exception:
            # skip malformed line
            continue
    return results


def global_exception_hook(exctype, value, tb):
    """
    Catch any unhandled exception (bug) and log it before crashing.
    """
    import sys
    import traceback

    # Ignore KeyboardInterrupt (Ctrl+C)
    if issubclass(exctype, KeyboardInterrupt):
        sys.__excepthook__(exctype, value, tb)
        return

    logger = get_logger("crash_handler")
    logger.critical("Uncaught Exception", exc_info=(exctype, value, tb))

    # We rely on the log file being written.
    # Since the GUI might be dead, we print to stderr as a backup.
    sys.stderr.write("!!! CRITICAL CRASH LOGGED !!!\n")
    traceback.print_exception(exctype, value, tb)

    # Safe exit
    sys.exit(1)
