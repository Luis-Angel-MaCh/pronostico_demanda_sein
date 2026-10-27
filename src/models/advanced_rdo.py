from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def build_features(df: pd.DataFrame, horizon: int) -> tuple[pd.DataFrame, pd.Series]:
    actual = df["ejecutado"]
    rdo = df["rdo"].where(df["rdo"] > 1000)
    residual = actual - rdo
    origin = np.arange(len(df)) - horizon
    minute = df["fecha"].dt.hour * 60 + df["fecha"].dt.minute
    angle = 2 * math.pi * minute / 1440
    x = pd.DataFrame({
        "rdo": rdo / 1000,
        "daily": df["diaria"] / 1000,
        "weekly": df["semanal"] / 1000,
        "rdo_daily": (rdo - df["diaria"]) / 100,
        "rdo_weekly": (rdo - df["semanal"]) / 100,
        "rdo_slope": rdo.diff() / 100,
        "daily_slope": df["diaria"].diff() / 100,
        "actual_d1": actual.shift(48) / 1000,
        "actual_w1": actual.shift(336) / 1000,
        "sin1": np.sin(angle), "cos1": np.cos(angle),
        "sin2": np.sin(2 * angle), "cos2": np.cos(2 * angle),
        "sin3": np.sin(3 * angle), "cos3": np.cos(3 * angle),
        "dow_sin": np.sin(2 * math.pi * df["fecha"].dt.dayofweek / 7),
        "dow_cos": np.cos(2 * math.pi * df["fecha"].dt.dayofweek / 7),
        "doy_sin": np.sin(2 * math.pi * df["fecha"].dt.dayofyear / 365.25),
        "doy_cos": np.cos(2 * math.pi * df["fecha"].dt.dayofyear / 365.25),
    })
    series = {
        "actual_origin": actual,
        "rdo_error": residual,
        "rdo_error4": residual.rolling(4, min_periods=2).mean(),
        "rdo_error12": residual.rolling(12, min_periods=6).mean(),
        "rdo_error48": residual.rolling(48, min_periods=24).mean(),
        "actual_ramp1": actual.diff(),
        "actual_ramp2": actual.diff(2),
        "actual_ramp6": actual.diff(6),
    }
    for name, source in series.items():
        values = np.full(len(df), np.nan)
        valid = origin >= 0
        values[valid] = source.to_numpy()[origin[valid]]
        x[name] = values / (1000 if name == "actual_origin" else 100)
    return x, residual


def specification(horizon: int) -> tuple[str, int, object]:
    if horizon == 1:
        return "HistGradientBoosting", 730, HistGradientBoostingRegressor(
            max_iter=260, learning_rate=0.045, max_leaf_nodes=31,
            min_samples_leaf=25, l2_regularization=10, random_state=42
        )
    if horizon <= 4:
        window = 180
    elif horizon <= 12:
        window = 730
    else:
        window = 365
    return "Ridge", window, make_pipeline(StandardScaler(), Ridge(alpha=40))
