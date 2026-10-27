import math

import numpy as np
import pandas as pd


def prepare_arrays(df):
    actual = df["ejecutado"].to_numpy(float)
    daily = df["prog_diaria"].to_numpy(float)
    weekly = df["prog_semanal"].to_numpy(float)
    residual = actual - daily
    rolling = pd.Series(residual)
    minute = df["fecha"].dt.hour.to_numpy() * 60 + df["fecha"].dt.minute.to_numpy()
    hour = 2 * math.pi * minute / 1440
    dow = df["fecha"].dt.dayofweek.to_numpy()
    doy = df["fecha"].dt.dayofyear.to_numpy()
    return {
        "actual": actual,
        "daily": daily,
        "weekly": weekly,
        "residual": residual,
        "res4": rolling.rolling(4, min_periods=2).mean().to_numpy(),
        "res12": rolling.rolling(12, min_periods=6).mean().to_numpy(),
        "res48": rolling.rolling(48, min_periods=24).mean().to_numpy(),
        "sin1": np.sin(hour), "cos1": np.cos(hour),
        "sin2": np.sin(2 * hour), "cos2": np.cos(2 * hour),
        "sin3": np.sin(3 * hour), "cos3": np.cos(3 * hour),
        "dow_sin": np.sin(2 * math.pi * dow / 7),
        "dow_cos": np.cos(2 * math.pi * dow / 7),
        "doy_sin": np.sin(2 * math.pi * doy / 365.25),
        "doy_cos": np.cos(2 * math.pi * doy / 365.25),
    }


def build_matrix(a, targets, horizon):
    origin = targets - horizon
    return np.column_stack([
        a["daily"][targets] / 1000,
        a["weekly"][targets] / 1000,
        (a["daily"][targets] - a["weekly"][targets]) / 1000,
        a["actual"][targets - 48] / 1000,
        a["actual"][targets - 336] / 1000,
        a["actual"][origin] / 1000,
        a["residual"][origin] / 100,
        a["res4"][origin] / 100,
        a["res12"][origin] / 100,
        a["res48"][origin] / 100,
        (a["actual"][origin] - a["actual"][origin - 1]) / 100,
        (a["actual"][origin] - a["actual"][origin - 48]) / 100,
        (a["daily"][targets] - a["actual"][origin]) / 1000,
        a["sin1"][targets], a["cos1"][targets],
        a["sin2"][targets], a["cos2"][targets],
        a["sin3"][targets], a["cos3"][targets],
        a["dow_sin"][targets], a["dow_cos"][targets],
        a["doy_sin"][targets], a["doy_cos"][targets],
        np.full(len(targets), horizon / 48),
    ])

