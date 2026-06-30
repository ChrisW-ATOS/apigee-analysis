"""Seasonality-aware baseline using STL decomposition + AR(1) on residuals.

Z-score is computed on STL residuals (daily seasonality removed).
Forecasting fits AR(1) on those same residuals and returns predictions
for each hour from t+1 to t+forecast_hours, so callers can store a
full forecast curve in InfluxDB rather than a single endpoint.
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
    forecast_hours: int = 4,
) -> tuple[float, list[float] | None, list[float] | None]:
    """Compute a seasonality-aware Z-score and a multi-step forward forecast.

    Args:
        series:         Hourly time series (7-day window recommended).
        forecast_hours: Number of hours ahead to forecast (default 4).

    Returns:
        (z_score, forecast_zs, predicted_values)
        - z_score:        Z-score of the latest STL residual.
        - forecast_zs:    List of residual z-scores at t+1, t+2, ..., t+forecast_hours.
                          None if forecasting fails.
        - predicted_values: List of forecasts in original series units at each step.
                            Use these to store predicted error rates or traffic values
                            directly in InfluxDB. None if forecasting fails.

    Method:
        1. STL decomposes the series into trend + seasonal + residual.
        2. Z-score is applied to the residual only.
        3. AR(1) is fitted on the STL residuals (already stationary, d=0).
        4. ARIMA.forecast(forecast_hours) produces multi-step residual forecasts.
        5. For each step h:
               trend_future   = trend[-1] + slope * h
               seasonal_future = seasonal at the same hour-of-day as t+h
               predicted[h]   = trend_future + seasonal_future + residual_forecast[h]
               forecast_z[h]  = residual_forecast[h] / residual_std
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

        forecast_zs: list[float] | None      = None
        predicted_values: list[float] | None = None

        try:
            from statsmodels.tsa.arima.model import ARIMA

            arima_fit        = ARIMA(residuals, order=(1, 0, 0)).fit()
            residual_forecasts = arima_fit.forecast(forecast_hours)  # length = forecast_hours

            trend_slope = (result.trend.iloc[-1] - result.trend.iloc[-24]) / 24

            forecast_zs      = []
            predicted_values = []

            for h in range(1, forecast_hours + 1):
                rf  = float(residual_forecasts.iloc[h - 1])
                fz  = rf / std

                trend_future    = float(result.trend.iloc[-1] + trend_slope * h)
                seasonal_idx    = -(STL_PERIOD - h) % STL_PERIOD
                seasonal_future = float(result.seasonal.iloc[seasonal_idx])
                pv              = trend_future + seasonal_future + rf

                forecast_zs.append(fz)
                predicted_values.append(pv)

        except Exception as exc:
            log.debug("AR(1) forecast failed (%s) — no predictive alert", exc)

        return z_current, forecast_zs, predicted_values

    except Exception as exc:
        log.debug("STL failed (%s) — falling back to flat Z-score", exc)
        return _flat_zscore(series)
