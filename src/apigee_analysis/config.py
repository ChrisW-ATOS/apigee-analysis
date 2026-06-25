"""Configuration loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    influx_url: str
    influx_token: str
    influx_org: str
    source_bucket: str
    anomaly_bucket: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    def _req(key: str) -> str:
        val = os.getenv(key, "").strip()
        if not val:
            raise RuntimeError(f"Required env var not set: {key}")
        return val

    return Settings(
        influx_url=_req("INFLUX_URL"),
        influx_token=_req("INFLUX_TOKEN"),
        influx_org=_req("INFLUX_ORG"),
        source_bucket=os.getenv("INFLUX_SOURCE_BUCKET", "Apigee Reports"),
        anomaly_bucket=os.getenv("INFLUX_ANOMALY_BUCKET", "Anomalies"),
    )
