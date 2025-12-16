"""
logging.py

Centralized logging utilities for DailySelfie.

Provides:
- JsonLineFormatter: compact JSONL formatter for structured logs
- init_logger: initialise a root "dailyselfie" logger with RotatingFileHandler
- get_logger: convenience to fetch child loggers
- read_jsonl_tail: helper to read the last N JSON objects from a JSONL log file

Design notes:
- Logs are written in UTF-8 JSON lines. Each record contains: ts (ISO UTC), level, logger,
  msg, and optional meta and uuid fields.
- The module intentionally keeps behavior simple and testable. Consumer code
  should pass the logs_dir Path resolved by paths.get_app_paths().

Example
-------
    from logging import init_logger, get_logger, read_jsonl_tail
    logger = init_logger(Path("/some/app/data/logs"))
    logger.info("started", extra={"meta": {"os": "linux"}})

"""
from __future__ import annotations
import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any


DEFAULT_LOG_FILENAME = "dailyselfie.jsonl"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        entry: Dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "meta") and record.meta:
            entry["meta"] = record.meta
        
        # Handle Exception Info
        if record.exc_info:
            # Format the full traceback
            entry["exc"] = self.formatException(record.exc_info)
        
        return json.dumps(entry, ensure_ascii=False)


def _make_rotating_handler(log_file: Path, max_bytes: int, backup_count: int) -> logging.Handler:
    handler = logging.handlers.RotatingFileHandler(
        filename=str(log_file), maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setFormatter(JsonLineFormatter())
    return handler


def init_logger(logs_dir: Path, console: bool = True) -> logging.Logger:
    """Initialize the root logger. Idempotent."""
    logger = logging.getLogger("dailyselfie")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # Don't double-print to root

    # 1. File Handler (JSONL)
    log_file = logs_dir / DEFAULT_LOG_FILENAME
    file_h = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=DEFAULT_MAX_BYTES, backupCount=DEFAULT_BACKUP_COUNT, encoding="utf-8"
    )
    file_h.setFormatter(JsonLineFormatter())
    file_h.setLevel(logging.DEBUG) # Log EVERYTHING to file
    logger.addHandler(file_h)

    # 2. Console Handler (Human Readable)
    if console:
        console_h = logging.StreamHandler()
        console_h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        console_h.setLevel(logging.INFO) # Only INFO+ to terminal
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


# Convenience CLI for quick debugging when executing directly
if __name__ == "__main__":
    from pathlib import Path
    import sys

    logs = Path.cwd() / "logs_test"
    logs.mkdir(parents=True, exist_ok=True)
    logger = init_logger(logs, console=True)
    logger.info("logging_test_start", extra={"meta": {"mode": "direct_run"}})
    print("Wrote a test log to:", logs / DEFAULT_LOG_FILENAME)
    tail = read_jsonl_tail(logs / DEFAULT_LOG_FILENAME, max_lines=10)
    print("Last lines:")
    for r in tail:
        print(r)
