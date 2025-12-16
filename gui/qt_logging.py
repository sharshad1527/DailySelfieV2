# FILE: gui/qt_logging.py
import logging
import sys
from PySide6.QtCore import QObject, Signal, Qt, qInstallMessageHandler, QtMsgType

class LogSignalEmitter(QObject):
    """Worker to emit signals from the logging thread to the GUI thread."""
    new_log = Signal(dict) # Carries the log record dict

class QtSignalingHandler(logging.Handler):
    """
    A custom logging Handler that emits a Qt Signal for every log record.
    This allows the GUI to 'subscribe' to logs.
    """
    def __init__(self):
        super().__init__()
        self.emitter = LogSignalEmitter()

    def emit(self, record):
        try:
            msg = self.format(record)
            # Create a clean dict for the GUI to consume
            log_entry = {
                "level": record.levelname,
                "msg": record.getMessage(),
                "ts": record.created,
                "exc": self.formatException(record.exc_info) if record.exc_info else None
            }
            self.emitter.new_log.emit(log_entry)
        except Exception:
            self.handleError(record)

def qt_message_handler(mode, context, message):
    """
    Intercepts Qt internal messages (C++ side) and pipes them into Python logging.
    """
    logger = logging.getLogger("dailyselfie.qt_internal")
    
    if mode == QtMsgType.QtDebugMsg:
        logger.debug(message)
    elif mode == QtMsgType.QtInfoMsg:
        logger.info(message)
    elif mode == QtMsgType.QtWarningMsg:
        logger.warning(message)
    elif mode == QtMsgType.QtCriticalMsg:
        logger.error(message)
    elif mode == QtMsgType.QtFatalMsg:
        logger.critical(message)

def install_qt_logger():
    """Activate the Qt message interception."""
    qInstallMessageHandler(qt_message_handler)