"""Seasonality-aware baseline using STL decomposition + AR(1) on residuals.

Z-score is computed on STL residuals (daily seasonality removed).
Forecasting fits AR(1) on those same residuals — no second STL fit,
no decomposition mismatch.

The function returns a third value — the predicted quantity in the
original series units — so callers can store a meaningful predicted
error rate or traffic value in InfluxDB rather than just a z-score.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

STL_MIN_POINTS = 72   # 3 days minimum (2 full daily cycles for STL)
STL_PERIOD     = 24   # daily seasonality for hourly data


def _flat_zscore(series: pd.Series) -> tuple[float, None, None]:
    """Simple (value - mean) / std. Fallback for sparse proxies."""
    if len(series) < 2:
        return 0.0, None, None
    mean = series.mean()
    std  = series.std()
    if std == 0:
        return 0.0, None, None
    return float((series.iloc[-1] - mean) / std), None, None


def zscore_and_forecast(
    series: pd.Series,
    forecast_hours: int = 2,
) -> tuple[float, float | None, float | None]:
    """Compute a seasonality-aware Z-score and a forward forecast.

    Args:
        series:         Hourly time series (7-day window recommended).
        forecast_hours: Hours ahead to project for predictive alerting.

    Returns:
        (z_score, forecast_z, predicted_value)
        - z_score:        Z-score of the latest STL residual.
        - forecast_z:     Predicted residual in z-score units at t+forecast_hours.
                          None if forecasting fails.
        - predicted_value: Forecast in original series units at t+forecast_hours.
                          Use this to store a meaningful predicted error rate or
                          traffic count in InfluxDB. None if forecasting fails.

    Method:
        1. STL decomposes the series into trend + seasonal + residual.
        2. Z-score is applied to the residual only (seasonal patterns removed).
        3. AR(1) is fitted on the STL residuals (already stationary, so d=0).
        4. residual_forecast = AR(1).forecast(forecast_hours)
        5. forecast_z = residual_forecast / residual_std
        6. predicted_value = (STL trend extrapolation)
                           + (STL seasonal at t+forecast_hours)
                           + residual_forecast
    """
    if len(series) < STL_MIN_POINTS:
        log.debug("insufficient data (%d pts) — falling back to flat Z-score", len(series))
        return _flat_zscore(series)

    try:
        from statsmodels.tsa.seasonal import STL

        stl    = STL(series, period=STL_PERIOD, robust=True)
        result = stl.fit()

        residuals = result.resid
        std = residuals.std()
        if std == 0:
            return 0.0, None, None

        z_current = float(residuals.iloc[-1] / std)

        forecast_z: float | None       = None
        predicted_value: float | None  = None

        try:
            from statsmodels.tsa.arima.model import ARIMA

            arima_fit         = ARIMA(residuals, order=(1, 0, 0)).fit()
            residual_forecast = float(arima_fit.forecast(forecast_hours).iloc[-1])
            forecast_z        = residual_forecast / std

            # Reconstruct the forecast in original units:
            # predicted = trend_at_t+h + seasonal_at_t+h + AR(1)_residual_forecast
            trend_slope     = (result.trend.iloc[-1] - result.trend.iloc[-24]) / 24
            trend_future    = float(result.trend.iloc[-1] + trend_slope * forecast_hours)
            seasonal_idx    = -(STL_PERIOD - forecast_hours) % STL_PERIOD
            seasonal_future = float(result.seasonal.iloc[seasonal_idx])
            predicted_value = trend_future + seasonal_future + residual_forecast

        except Exception as exc:
            log.debug("AR(1) forecast failed (%s) — no predictive alert", exc)

        return z_current, forecast_z, predicted_value

    except Exception as exc:
        log.debug("STL failed (%s) — falling back to flat Z-score", exc)
        return _flat_zscore(series)
