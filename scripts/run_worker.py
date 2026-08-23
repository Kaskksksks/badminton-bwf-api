#!/usr/bin/env python3
"""Run the persistent adaptive BWF polling worker."""
from __future__ import annotations

import signal
import threading

from app.core.logging import configure_logging
from app.core.config import get_settings
from app.polling.scheduler import build_scheduler


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    scheduler = build_scheduler()
    stop = threading.Event()

    def request_stop(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    scheduler.start()
    try:
        stop.wait()
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
