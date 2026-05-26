"""
log_setup.py — Single configure() call wires up the package logger.

Call once from __main__ before any module-level loggers are obtained.
Other modules just do `log = logging.getLogger(__name__)`.
"""

import logging
import sys

from .config import LOG_LEVEL


_FORMAT = "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"
_DATEFMT = "%H:%M:%S"

_configured = False


def configure() -> None:
    global _configured
    if _configured:
        return
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    root = logging.getLogger("friday")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    _configured = True
