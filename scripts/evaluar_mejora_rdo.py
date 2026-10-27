"""Evalúa correcciones temporales de la reprogramación COES sin mezclar fechas.

Este análisis usa la última reprogramación histórica disponible como techo
experimental. No sustituye la validación con versiones archivadas según su
hora real de publicación.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/coes/reprogramaciones_agregadas_2026-09-01_2026-09-27.csv"


def fit_ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-8] = 1.0
    z = np.column_stack([np.ones(len(x)), (x - mean) / std])
    penalty = np.eye(z.shape[1]) * alpha
    penalty[0, 0] = 0
    coef = np.linalg.solve(z.T @ z + penalty, z.T @ y)
    return mean, std, coef


def predict(model: tuple[np.ndarray, np.ndarray, np.ndarray], x: np.ndarray) -> np.ndarray:
    mean, std, coef = model
    return np.column_stack([np.ones(len(x)), (x - mean) / std]) @ coef


def main() -> None:
    df = pd.read_csv(SOURCE, parse_dates=["fecha"]).sort_values("fecha").reset_index(drop=True)
    residual = df["ejecutado"] - df["reprogramacion"]
    minute = df["fecha"].dt.hour * 60 + df["fecha"].dt.minute
    angle = 2 * math.pi * minute / 1440
    cutoff = df["fecha"].max() - pd.Timedelta(days=7)
    records = []

    for horizon in (1, 2, 4, 6, 12, 24, 48):
        origin = np.arange(len(df)) - horizon
        features = pd.DataFrame(
            {
                "rdo": df["reprogramacion"] / 1000,
                "daily_gap": (df["reprogramacion"] - df["prog_diaria"]) / 100,
                "weekly_gap": (df["reprogramacion"] - df["prog_semanal"]) / 100,
                "actual_d1": df["ejecutado"].shift(48) / 1000,
                "actual_w1": df["ejecutado"].shift(336) / 1000,
                "sin1": np.sin(angle),
                "cos1": np.cos(angle),
                "sin2": np.sin(2 * angle),
                "cos2": np.cos(2 * angle),
                "dow_sin": np.sin(2 * math.pi * df["fecha"].dt.dayofweek / 7),
                "dow_cos": np.cos(2 * math.pi * df["fecha"].dt.dayofweek / 7),
            }
        )
        for lag_name, window in (("last", 1), ("mean4", 4), ("mean12", 12), ("mean48", 48)):
            known = residual.rolling(window, min_periods=max(1, window // 2)).mean()
            features[lag_name] = known.reindex(origin).to_numpy() / 100

        valid = features.notna().all(axis=1) & residual.notna()
        train = valid & (df["fecha"] < cutoff)
        test = valid & (df["fecha"] >= cutoff)
        x_train = features.loc[train].to_numpy()
        y_train = residual.loc[train].clip(-500, 500).to_numpy()
        x_test = features.loc[test].to_numpy()
        actual = df.loc[test, "ejecutado"].to_numpy()
        rdo = df.loc[test, "reprogramacion"].to_numpy()

        best = None
        for alpha in (5.0, 15.0, 40.0, 100.0):
            correction = predict(fit_ridge(x_train, y_train, alpha), x_test)
            mae = float(np.mean(np.abs(actual - (rdo + correction))))
            if best is None or mae < best[0]:
                best = (mae, alpha)
        mae_rdo = float(np.mean(np.abs(actual - rdo)))
        records.append(
            {
                "horizonte_h": horizon / 2,
                "n_validacion": int(test.sum()),
                "mae_rdo": mae_rdo,
                "mae_rdo_corregida": best[0],
                "mejora_pct": (mae_rdo - best[0]) / mae_rdo * 100,
                "alpha": best[1],
            }
        )

    print(pd.DataFrame(records).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


if __name__ == "__main__":
    main()
