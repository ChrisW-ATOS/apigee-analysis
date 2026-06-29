"""Seasonality-aware baseline using STL decomposition + STLForecast.

Z-score is computed on STL residuals (daily seasonality removed).
Forecasting uses STLForecast with ARIMA(1,1,0) on residuals — replacing
the previous linear trend extrapolation with a proper time-series model.
Falls back to flat Z-score for proxies with insufficient data.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

STL_MIN_POINTS = 72   # 3 days minimum (2 full daily cycles for STL)
STL_PERIOD     = 24   # daily seasonality for hourly data


def _flat_zscore(series: pd.Series) -> tuple[float, None]:
    """Simple (value - mean) / std. Fallback for sparse proxies."""
    if len(series) < 2:
        return 0.0, None
    mean = series.mean()
    std  = series.std()
    if std == 0:
        return 0.0, None
    return float((series.iloc[-1] - mean) / std), None


def zscore_and_forecast(series: pd.Series, forecast_hours: int = 2) -> tuple[float, float | None]:
    """Compute a seasonality-aware Z-score and a forward forecast.

    Args:
        series: Hourly time series (7-day window recommended).
        forecast_hours: Hours ahead to project for predictive alerting.

    Returns:
        (z_score, forecast_z_score)
        - z_score: Z-score of the latest STL residual.
        - forecast_z_score: Z-score of the STLForecast value `forecast_hours`
          ahead, or None if forecasting fails.

    Method:
        STL decomposes the series into trend + seasonal + residual.
        Z-score is applied to the residual only (seasonal patterns removed).

        Forecasting uses STLForecast with ARIMA(1,1,0) on the residuals —
        a first-order autoregressive model with one degree of differencing.
        This captures short-term autocorrelation in error rates and traffic
        far better than linear trend extrapolation.
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
            return 0.0, None

        z_current = float(residuals.iloc[-1] / std)

        forecast_z: float | None = None
        try:
            from statsmodels.tsa.arima.model import ARIMA

            # Fit AR(1) on the STL residuals directly.
            # STL residuals are already stationary, so d=0.
            # This avoids the inconsistency of running a second STL inside
            # STLForecast, which can produce a mismatched decomposition.
            #
            # forecast_z = predicted_residual / residual_std
            # Interpretation: how anomalous will the residual be in `forecast_hours`?
            #   - Normal (near-zero residuals): AR(1) predicts ≈ 0 → forecast_z ≈ 0
            #   - Sustained anomaly: AR(1) predicts continued large residual
            #   - Recovering anomaly: AR(1) captures mean-reversion → smaller forecast_z
            arima_fit          = ARIMA(residuals, order=(1, 0, 0)).fit()
            residual_forecast  = float(arima_fit.forecast(forecast_hours).iloc[-1])
            forecast_z         = residual_forecast / std

        except Exception as exc:
            log.debug("ARIMA on residuals failed (%s) — no predictive alert", exc)

        return z_current, forecast_z

    except Exception as exc:
        log.debug("STL failed (%s) — falling back to flat Z-score", exc)
        return _flat_zscore(series)
