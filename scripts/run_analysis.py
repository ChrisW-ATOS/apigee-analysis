#!/usr/bin/env python3
"""Hourly anomaly detection scheduler."""
import logging
import time
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    from apigee_analysis.config import get_settings
    from apigee_analysis.detect import run_all

    settings = get_settings()
    log.info("Anomaly detection scheduler started")

    while True:
        now = datetime.now()
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        wait = (next_hour - now).total_seconds()
        log.info("Next run at %s — sleeping %.0fs", next_hour.strftime("%H:%M"), wait)
        time.sleep(wait)

        log.info("Running anomaly detection")
        try:
            run_all(settings)
        except Exception as exc:
            log.error("Detection failed: %s", exc)


if __name__ == "__main__":
    main()
