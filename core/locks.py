# core/locks.py
"""
File-based locking utility for DailySelfie.

Provides:
- file_lock(path: Path, timeout: float = 10.0, poll_interval: float = 0.1)
    Context manager that acquires an exclusive advisory lock on the given path.
    The lock is implemented using fcntl on POSIX and msvcrt on Windows.
    If neither is available, falls back to a process-local threading.Lock.

Usage:
    from core.locks import file_lock
    lockpath = Path("/tmp/dailyselfie.index.lock")    # or use paths.data_dir / "index.db.lock"
    with file_lock(lockpath, timeout=5.0):
        # safe critical section: append JSONL, write DB, write sidecar
        do_critical_work()
"""
from __future__ import annotations
import time
import errno
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional
import threading
import os

# Determine available backend
try:
    import fcntl  # POSIX advisory locks
    _HAS_FCNTL = True
except Exception:
    _HAS_FCNTL = False

try:
    import msvcrt  # Windows locking
    _HAS_MSVCRT = True
except Exception:
    _HAS_MSVCRT = False

# Fallback global reentrant lock (process-local) if OS locks aren't available
_GLOBAL_FALLBACK_LOCK = threading.RLock()


@contextmanager
def file_lock(lock_path: Path, timeout: float = 10.0, poll_interval: float = 0.1) -> Iterator[None]:
    """
    Acquire an exclusive lock on `lock_path`. Creates the lock file if missing.
    Releases lock when context exits.

    Parameters:
      lock_path: Path to the lock file. Use a file in the same directory as the DB (e.g. data/index.db.lock).
      timeout: maximum seconds to wait before raising TimeoutError.
      poll_interval: how frequently to retry acquiring the lock.

    Raises:
      TimeoutError if lock cannot be acquired within timeout.
      OSError / IOError on IO failures.
    """
    lock_path = Path(lock_path)
    # Ensure parent exists
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.time() + float(timeout) if timeout is not None and timeout > 0 else None

    if _HAS_FCNTL:
        # POSIX implementation using fcntl.flock
        fh = None
        try:
            # Open (or create) the lock file for read/write
            fh = open(str(lock_path), "a+b")
            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Got the lock
                    break
                except OSError as e:
                    if e.errno in (errno.EACCES, errno.EAGAIN):
                        # already locked by another process
                        if deadline and time.time() > deadline:
                            raise TimeoutError(f"Timeout acquiring file lock {lock_path}")
                        time.sleep(poll_interval)
                        continue
                    else:
                        raise
            # yield; lock held
            try:
                yield
            finally:
                try:
                    # flush + release
                    fh.flush()
                    os.fsync(fh.fileno())
                except Exception:
                    pass
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
                try:
                    fh.close()
                except Exception:
                    pass
        finally:
            # ensure file descriptor closed if something went wrong
            try:
                if fh and not fh.closed:
                    fh.close()
            except Exception:
                pass

    elif _HAS_MSVCRT:
        # Windows implementation using msvcrt.locking
        fh = None
        try:
            fh = open(str(lock_path), "a+b")
            while True:
                try:
                    # Lock the entire file (0 bytes from current pos, length 1<<31)
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as e:
                    # OSError is raised if lock cannot be acquired
                    if deadline and time.time() > deadline:
                        raise TimeoutError(f"Timeout acquiring file lock {lock_path}")
                    time.sleep(poll_interval)
                    continue
            try:
                yield
            finally:
                try:
                    fh.flush()
                    os.fsync(fh.fileno())
                except Exception:
                    pass
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
                try:
                    fh.close()
                except Exception:
                    pass
        finally:
            try:
                if fh and not fh.closed:
                    fh.close()
            except Exception:
                pass

    else:
        # Fallback: process-local lock (does not prevent other processes from entering)
        acquired = False
        try:
            acquired = _GLOBAL_FALLBACK_LOCK.acquire(timeout=timeout)
            if not acquired:
                raise TimeoutError(f"Timeout acquiring in-process fallback lock for {lock_path}")
            yield
        finally:
            if acquired:
                try:
                    _GLOBAL_FALLBACK_LOCK.release()
                except Exception:
                    pass


# Convenience helper to get a sane lock path next to a DB or index file
def lock_path_for(db_path: Path) -> Path:
    """
    Given a DB or file path, return a corresponding lock file path in the same folder.
    Example: lock_path_for(Path('/data/index.db')) -> Path('/data/index.db.lock')
    """
    p = Path(db_path)
    return p.with_suffix(p.suffix + ".lock") if p.suffix else p.with_name(p.name + ".lock")
