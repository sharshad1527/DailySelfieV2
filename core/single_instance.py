# core/single_instance.py
"""
Single-instance enforcement for the DailySelfie dashboard GUI (Qt local IPC).

POLICY
------
Single-instance enforcement applies ONLY to the default dashboard GUI launch
(`python DailySelfie.py` with no sub-command). It is deliberately scoped that
way because:

- The `--start-up` capture popup MUST remain launchable while a dashboard is
  already running: the tray "Capture now" action spawns exactly that popup as
  a detached subprocess, and blocking it would break tray capture.
- Headless CLI modes (--capture, --list-cameras, theme toggles, install/
  uninstall, ...) are entirely unaffected.

MECHANISM
---------
QLocalServer / QLocalSocket (Qt networking) on a per-user key:

    "DailySelfie-" + sha256("<username>:<uid>")[:10]

so multiple Linux users on one machine each get their own instance namespace.

try_become_primary():
1. Attempts to connect to an existing server (~300 ms timeout).
   - Connected -> this process is SECONDARY: it forwards argv[1:] as a
     newline-delimited UTF-8 message to the running instance and returns
     None (the caller should exit quietly).
   - Not connected -> removeServer(key) clears any stale socket left behind
     by a crashed previous instance, then listens.
2. As primary, newConnection handling reads forwarded args (buffered until
   the secondary disconnects, with a 2 s safety finalize so a misbehaving
   peer can never wedge a connection) and invokes
   on_secondary_launch(args: list[str]).

FAIL-OPEN CONTRACT
------------------
Any exception in this machinery is logged as a warning and a truthy no-op
sentinel (_FailOpenPrimary) is returned instead of raising. Callers treat
None strictly as "you are secondary, exit"; anything truthy means "continue
as primary" — startup must NEVER be blocked by single-instance plumbing.
The worst case under fail-open is a duplicated GUI, which beats blocking.
If PySide6.QtNetwork itself is unavailable (split-package installs ship it
separately), the import degrades to None sentinels and try_become_primary()
logs "single_instance_qtnetwork_missing" once and returns _FailOpenPrimary()
— enforcement is silently disabled rather than erroring every launch.
"""
from __future__ import annotations

import hashlib
import getpass
import os
import sys
from typing import Callable, List, Optional

from PySide6.QtCore import QTimer

try:  # QtNetwork is optional in split-package PySide6 installs.
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
except ImportError:
    QLocalServer = None
    QLocalSocket = None

from core.logging import get_logger

logger = get_logger("single_instance")

_CONNECT_TIMEOUT_MS = 300
_FINALIZE_TIMEOUT_MS = 2000


class _FailOpenPrimary:
    """Truthy no-op stand-in for a QLocalServer (fail-open path).

    Lets callers uniformly call close()/deleteLater() on shutdown even when
    the machinery failed and we chose to continue as primary.
    """

    def close(self) -> None:
        pass

    def deleteLater(self) -> None:
        pass


def _default_key() -> str:
    """Per-user key: 'DailySelfie-' + short hash of username/uid."""
    uid = os.getuid() if hasattr(os, "getuid") else 0
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    digest = hashlib.sha256(f"{user}:{uid}".encode("utf-8")).hexdigest()[:10]
    return f"DailySelfie-{digest}"


def try_become_primary(
    key_suffix: Optional[str] = None,
    on_secondary_launch: Optional[Callable[[List[str]], None]] = None,
    argv: Optional[List[str]] = None,
) -> Optional[QLocalServer]:
    """Become the single-instance primary, or forward args to the existing one.

    Returns:
        QLocalServer  : this process is now the primary; keep a reference and
                        close() it on application quit.
        _FailOpenPrimary : machinery failed but we continue as primary
                        (fail-open; never blocks startup).
        None          : an instance was already running; argv has been
                        forwarded to it and this process should exit quietly.
    """
    try:
        if QLocalServer is None or QLocalSocket is None:
            logger.warning("single_instance_qtnetwork_missing")
            return _FailOpenPrimary()

        key = _default_key()
        if key_suffix:
            key = f"{key}-{key_suffix}"

        # 1. Probe for an already-running instance.
        probe = QLocalSocket()
        probe.connectToServer(key)
        if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
            payload = "\n".join(argv if argv is not None else sys.argv[1:])
            if payload:
                probe.write(payload.encode("utf-8"))
                probe.flush()
                probe.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
            probe.disconnectFromServer()
            logger.info(
                "secondary_forwarded_args",
                extra={"meta": {"key": key, "args": payload.split("\n") if payload else []}},
            )
            return None

        # 2. Nobody answered: clean up any stale socket from a crashed run,
        #    then listen. removeServer() is safe when nothing exists.
        QLocalServer.removeServer(key)
        server = QLocalServer()
        if not server.listen(key):
            logger.warning(
                "single_instance_listen_failed",
                extra={"meta": {"error": server.errorString()}},
            )
            return _FailOpenPrimary()

        def _finalize(sock: QLocalSocket, buf: bytearray, state: dict) -> None:
            if state.get("done"):
                return
            state["done"] = True
            buf.extend(bytes(sock.readAll()))
            try:
                text = bytes(buf).decode("utf-8", "replace")
                fwd_args = [part for part in text.split("\n") if part]
                if callable(on_secondary_launch):
                    on_secondary_launch(fwd_args)
            except Exception:
                logger.exception("single_instance_callback_failed")
            finally:
                try:
                    sock.deleteLater()
                except RuntimeError:
                    pass

        def _on_new_connection() -> None:
            while server.hasPendingConnections():
                sock = server.nextPendingConnection()
                buf = bytearray()
                state = {"done": False}
                timer = QTimer(sock)
                timer.setSingleShot(True)

                timer.timeout.connect(lambda: _finalize(sock, buf, state))
                sock.disconnected.connect(lambda: _finalize(sock, buf, state))
                sock.readyRead.connect(lambda: buf.extend(bytes(sock.readAll())))
                # Safety net: finalize 2 s after connect even if the peer
                # never disconnects cleanly.
                timer.start(_FINALIZE_TIMEOUT_MS)

        server.newConnection.connect(_on_new_connection)
        logger.info("primary_listening", extra={"meta": {"key": key}})
        return server

    except Exception as exc:
        logger.warning("single_instance_fail_open", extra={"meta": {"error": str(exc)}})
        return _FailOpenPrimary()
