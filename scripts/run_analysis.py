#!/usr/bin/env python3
"""Hourly anomaly detection scheduler.

Runs at HH:10 each hour — 10 minutes after the fetch cron starts (HH:00).
The fetch typically completes in 2-3 minutes; the 10-minute offset ensures
the latest Apigee data is fully committed to InfluxDB before analysis reads it.

With LAG_HOURS=2 the analysis reads data from two hours ago, so this offset
is a belt-and-braces measure rather than a strict requirement.
"""
import logging
import time
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

OFFSET_MINUTES = 10   # run this many minutes after the top of each hour


def main() -> None:
    from apigee_analysis.config import get_settings
    from apigee_analysis.detect import run_all

    settings = get_settings()
    log.info("Anomaly detection scheduler started (offset: %d min past the hour)", OFFSET_MINUTES)

    while True:
        now      = datetime.now()
        next_run = (now + timedelta(hours=1)).replace(
            minute=OFFSET_MINUTES, second=0, microsecond=0
        )
        # If we just started and HH:10 is still in the future this hour, use it
        this_run = now.replace(minute=OFFSET_MINUTES, second=0, microsecond=0)
        if this_run > now:
            next_run = this_run

        wait = (next_run - now).total_seconds()
        log.info("Next run at %s — sleeping %.0fs", next_run.strftime("%H:%M"), wait)
        time.sleep(wait)

        log.info("Running anomaly detection")
        try:
            run_all(settings)
        except Exception as exc:
            log.error("Detection failed: %s", exc)


if __name__ == "__main__":
    main()
