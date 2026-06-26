"""Seasonality-aware baseline using STL decomposition.

Replaces the flat rolling mean with Seasonal-Trend decomposition (STL),
which removes daily seasonal patterns before computing Z-scores on residuals.
Falls back to flat Z-score for proxies with insufficient data.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Minimum hourly data points required to attempt STL decomposition.
# 72 = 3 days of hourly data (2 full daily cycles minimum for STL).
STL_MIN_POINTS = 72

# Daily seasonality period for hourly data.
STL_PERIOD = 24


def _flat_zscore(series: pd.Series) -> tuple[float, None]:
    """Simple (value - mean) / std on the full series. Fallback for sparse data."""
    if len(series) < 2:
        return 0.0, None
    mean = series.mean()
    std  = series.std()
    if std == 0:
        return 0.0, None
    return float((series.iloc[-1] - mean) / std), None


def zscore_and_forecast(series: pd.Series, forecast_hours: int = 2) -> tuple[float, float | None]:
    """Compute a seasonality-aware Z-score and optional forward forecast.

    Args:
        series: Hourly time series (7-day window recommended).
        forecast_hours: How many hours ahead to project for predictive alerting.

    Returns:
        (z_score, forecast_z_score)
        - z_score: Z-score of the latest residual after removing trend+seasonality.
        - forecast_z_score: Z-score of the forecasted value `forecast_hours` ahead,
          or None if forecasting is not possible.
    """
    if len(series) < STL_MIN_POINTS:
        log.debug("insufficient data (%d points) — falling back to flat Z-score", len(series))
        return _flat_zscore(series)

    try:
        from statsmodels.tsa.seasonal import STL
        stl = STL(series, period=STL_PERIOD, robust=True)
        result = stl.fit()

        residuals = result.resid
        std = residuals.std()
        if std == 0:
            return 0.0, None

        # Current Z-score on residual
        z_current = float(residuals.iloc[-1] / std)

        # Forecast: project seasonal + trend components forward
        forecast_z: float | None = None
        try:
            trend    = result.trend
            seasonal = result.seasonal

            # Linear extrapolation of trend
            trend_slope  = (trend.iloc[-1] - trend.iloc[-24]) / 24
            trend_fcast  = trend.iloc[-1] + trend_slope * forecast_hours

            # Seasonal component is periodic — reuse the value from same hour
            seasonal_fcast = seasonal.iloc[-(STL_PERIOD - forecast_hours) % STL_PERIOD]

            predicted = trend_fcast + seasonal_fcast
            residual_mean = residuals.mean()
            forecast_z = float((predicted - series.mean()) / std + residual_mean / std)
        except Exception:
            pass

        return z_current, forecast_z

    except Exception as exc:
        log.debug("STL failed (%s) — falling back to flat Z-score", exc)
        return _flat_zscore(series)
