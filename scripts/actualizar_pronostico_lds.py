"""Entrena el pronóstico LDS con todos los datos confirmados hasta ahora.

El modelo predice la corrección sobre la Programación Diaria de COES. Para
cada horizonte de 30 minutos a 24 horas usa solamente variables que ya eran
conocidas en el origen del pronóstico. El archivo de salida se reemplaza de
forma atómica para que el dashboard nunca lea un resultado incompleto.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import joblib
    from src.models.advanced_rdo import build_features as build_advanced_features
except ImportError:
    joblib = None
    build_advanced_features = None


ROOT = Path(__file__).resolve().parents[1]
BASE_XLSX = ROOT / "Demanda_COES_2024-01-01_2026-09-01.xlsx"
SEPT_XLSX = ROOT / "data/coes/Demanda_COES_septiembre_2026_corte_2026-09-27.xlsx"
DB_PATH = ROOT / "data/monitor/coes_versiones.sqlite"
OUTPUT = ROOT / "data/modelo/pronostico_live.json"
ADVANCED_MODEL = ROOT / "models/advanced_rdo.joblib"
RDO_HISTORY = ROOT / "data/coes/reprogramaciones_agregadas_2026-09-01_2026-09-27.csv"
TZ = ZoneInfo("America/Lima")
VALIDATION_STEPS = (12, 24, 48)
TRAINING_WINDOW = 365 * 48


def load_excel(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, header=3).iloc[:, :4]
    df.columns = ["fecha", "ejecutado", "diaria", "semanal"]
    df["fecha"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y %H:%M", errors="coerce")
    for col in ("ejecutado", "diaria", "semanal"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["fecha"])


def load_live() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        raw = pd.read_sql_query(
            "SELECT target_time, serie, value, observed_at FROM estado_actual "
            "WHERE serie IN ('ejecutado_portal','prog_diaria_portal','prog_semanal_portal')",
            con,
        )
    raw["fecha"] = pd.to_datetime(raw["target_time"], errors="coerce")
    observed = pd.to_datetime(raw["observed_at"], errors="coerce", utc=True)
    raw["observado_local"] = observed.dt.tz_convert(TZ).dt.tz_localize(None)
    # Un valor futuro capturado como "ejecutado" no se convierte en real solo
    # porque el reloj haya alcanzado esa hora. Debe existir una observación del
    # portal hecha después del intervalo objetivo.
    confirmed = (raw["serie"] != "ejecutado_portal") | (raw["observado_local"] >= raw["fecha"])
    raw = raw.loc[confirmed].copy()
    raw["campo"] = raw["serie"].map(
        {
            "ejecutado_portal": "ejecutado",
            "prog_diaria_portal": "diaria",
            "prog_semanal_portal": "semanal",
        }
    )
    live = raw.pivot_table(index="fecha", columns="campo", values="value", aggfunc="last").reset_index()
    # Defensa adicional para la respuesta que se está procesando ahora.
    cutoff = pd.Timestamp(datetime.now(TZ).replace(tzinfo=None)).floor("30min")
    live.loc[live["fecha"] > cutoff, "ejecutado"] = np.nan
    return live


def load_series() -> pd.DataFrame:
    frames = [load_excel(BASE_XLSX)]
    if SEPT_XLSX.exists():
        frames.append(load_excel(SEPT_XLSX))
    frames.append(load_live())
    df = pd.concat(frames, ignore_index=True).sort_values("fecha")
    df = df.groupby("fecha", as_index=False).last()
    full_index = pd.date_range(df["fecha"].min(), df["fecha"].max(), freq="30min")
    df = df.set_index("fecha").reindex(full_index).rename_axis("fecha").reset_index()
    rdo_frames = []
    if RDO_HISTORY.exists():
        historic = pd.read_csv(RDO_HISTORY, usecols=["fecha", "reprogramacion"])
        historic["fecha"] = pd.to_datetime(historic["fecha"], errors="coerce")
        rdo_frames.append(historic.rename(columns={"reprogramacion": "rdo"}))
    with sqlite3.connect(DB_PATH) as con:
        live_rdo = pd.read_sql_query(
            "SELECT target_time fecha, value rdo FROM estado_actual WHERE serie='reprogramacion_api'",
            con,
        )
    live_rdo["fecha"] = pd.to_datetime(live_rdo["fecha"], errors="coerce")
    rdo_frames.append(live_rdo)
    rdo = pd.concat(rdo_frames, ignore_index=True).dropna(subset=["fecha"]).groupby("fecha", as_index=False).last()
    df = df.merge(rdo, on="fecha", how="left")
    df["diaria"] = df["diaria"].fillna(df["semanal"])
    return df


def prepare_arrays(df: pd.DataFrame) -> dict[str, np.ndarray]:
    actual = df["ejecutado"].to_numpy(dtype=float)
    daily = df["diaria"].to_numpy(dtype=float)
    weekly = df["semanal"].to_numpy(dtype=float)
    residual = actual - daily
    rdo = df["rdo"].to_numpy(dtype=float)
    residual_rdo = actual - rdo
    rs = pd.Series(residual)
    idx = df["fecha"]
    minute = idx.dt.hour.to_numpy() * 60 + idx.dt.minute.to_numpy()
    hour_angle = 2 * math.pi * minute / 1440
    dow = idx.dt.dayofweek.to_numpy()
    doy = idx.dt.dayofyear.to_numpy()
    return {
        "actual": actual,
        "daily": daily,
        "weekly": weekly,
        "rdo": rdo,
        "residual": residual,
        "residual_rdo": residual_rdo,
        "res_mean4": rs.rolling(4, min_periods=2).mean().to_numpy(),
        "res_mean12": rs.rolling(12, min_periods=6).mean().to_numpy(),
        "res_mean48": rs.rolling(48, min_periods=24).mean().to_numpy(),
        "rdo_mean1": pd.Series(residual_rdo).to_numpy(),
        "rdo_mean4": pd.Series(residual_rdo).rolling(4, min_periods=2).mean().to_numpy(),
        "rdo_mean12": pd.Series(residual_rdo).rolling(12, min_periods=6).mean().to_numpy(),
        "rdo_mean48": pd.Series(residual_rdo).rolling(48, min_periods=24).mean().to_numpy(),
        "sin1": np.sin(hour_angle),
        "cos1": np.cos(hour_angle),
        "sin2": np.sin(2 * hour_angle),
        "cos2": np.cos(2 * hour_angle),
        "sin3": np.sin(3 * hour_angle),
        "cos3": np.cos(3 * hour_angle),
        "dow_sin": np.sin(2 * math.pi * dow / 7),
        "dow_cos": np.cos(2 * math.pi * dow / 7),
        "doy_sin": np.sin(2 * math.pi * doy / 365.25),
        "doy_cos": np.cos(2 * math.pi * doy / 365.25),
    }


def rdo_matrix(a: dict[str, np.ndarray], targets: np.ndarray, horizon: int) -> np.ndarray:
    origin = targets - horizon
    return np.column_stack(
        [
            a["rdo"][targets] / 1000,
            (a["rdo"][targets] - a["daily"][targets]) / 100,
            (a["rdo"][targets] - a["weekly"][targets]) / 100,
            a["actual"][targets - 48] / 1000,
            a["actual"][targets - 336] / 1000,
            a["rdo_mean1"][origin] / 100,
            a["rdo_mean4"][origin] / 100,
            a["rdo_mean12"][origin] / 100,
            a["rdo_mean48"][origin] / 100,
            a["sin1"][targets], a["cos1"][targets],
            a["sin2"][targets], a["cos2"][targets],
            a["dow_sin"][targets], a["dow_cos"][targets],
        ]
    )


def rdo_training_data(a: dict[str, np.ndarray], horizon: int, last_actual: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    targets = np.arange(max(336, horizon + 49, last_actual - TRAINING_WINDOW), last_actual + 1)
    x = rdo_matrix(a, targets, horizon)
    y = a["residual_rdo"][targets]
    mask = np.isfinite(x).all(axis=1) & np.isfinite(y)
    return targets[mask], x[mask], np.clip(y[mask], -500, 500)


def matrix(a: dict[str, np.ndarray], targets: np.ndarray, horizon: int) -> np.ndarray:
    origin = targets - horizon
    return np.column_stack(
        [
            a["daily"][targets] / 1000,
            a["weekly"][targets] / 1000,
            (a["daily"][targets] - a["weekly"][targets]) / 1000,
            a["actual"][targets - 48] / 1000,
            a["actual"][targets - 336] / 1000,
            a["actual"][origin] / 1000,
            a["residual"][origin] / 100,
            a["res_mean4"][origin] / 100,
            a["res_mean12"][origin] / 100,
            a["res_mean48"][origin] / 100,
            (a["actual"][origin] - a["actual"][origin - 1]) / 100,
            (a["actual"][origin] - a["actual"][origin - 48]) / 100,
            (a["daily"][targets] - a["actual"][origin]) / 1000,
            a["sin1"][targets], a["cos1"][targets],
            a["sin2"][targets], a["cos2"][targets],
            a["sin3"][targets], a["cos3"][targets],
            a["dow_sin"][targets], a["dow_cos"][targets],
            a["doy_sin"][targets], a["doy_cos"][targets],
            np.full(len(targets), horizon / 48),
        ]
    )


def fit_ridge(x: np.ndarray, y: np.ndarray, alpha: float = 18.0) -> dict[str, np.ndarray]:
    mean = np.nanmean(x, axis=0)
    std = np.nanstd(x, axis=0)
    std[std < 1e-8] = 1
    z = (x - mean) / std
    z = np.column_stack([np.ones(len(z)), z])
    penalty = np.eye(z.shape[1]) * alpha
    penalty[0, 0] = 0
    coef = np.linalg.solve(z.T @ z + penalty, z.T @ y)
    return {"mean": mean, "std": std, "coef": coef}


def predict(model: dict[str, np.ndarray], x: np.ndarray) -> np.ndarray:
    z = (x - model["mean"]) / model["std"]
    return np.column_stack([np.ones(len(z)), z]) @ model["coef"]


def training_data(a: dict[str, np.ndarray], horizon: int, last_actual: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    targets = np.arange(max(336, horizon + 49, last_actual - TRAINING_WINDOW), last_actual + 1)
    x = matrix(a, targets, horizon)
    y = a["residual"][targets]
    mask = np.isfinite(x).all(axis=1) & np.isfinite(y)
    return targets[mask], x[mask], np.clip(y[mask], -800, 800)


def validate(a: dict[str, np.ndarray], dates: pd.Series, last_actual: int) -> dict:
    cutoff_date = dates.iloc[last_actual] - pd.Timedelta(days=30)
    result = {}
    for horizon in VALIDATION_STEPS:
        targets, x, y = training_data(a, horizon, last_actual)
        train_mask = dates.iloc[targets].to_numpy() < np.datetime64(cutoff_date)
        valid_mask = ~train_mask
        model = fit_ridge(x[train_mask], y[train_mask])
        correction = predict(model, x[valid_mask])
        actual = a["actual"][targets[valid_mask]]
        daily = a["daily"][targets[valid_mask]]
        forecast = daily + correction
        mae_model = float(np.mean(np.abs(forecast - actual)))
        mae_daily = float(np.mean(np.abs(daily - actual)))
        rmse = float(np.sqrt(np.mean((forecast - actual) ** 2)))
        result[str(horizon)] = {
            "hours": horizon / 2,
            "samples": int(valid_mask.sum()),
            "maeModel": mae_model,
            "maeDaily": mae_daily,
            "rmseModel": rmse,
            "improvementPct": (mae_daily - mae_model) / mae_daily * 100,
        }
    return result


def main() -> None:
    df = load_series()
    a = prepare_arrays(df)
    advanced = joblib.load(ADVANCED_MODEL) if joblib and ADVANCED_MODEL.exists() else None
    advanced_features = {}
    actual_indexes = np.flatnonzero(np.isfinite(a["actual"]))
    if len(actual_indexes) == 0:
        raise RuntimeError("No hay demanda ejecutada para entrenar")
    last_actual = int(actual_indexes[-1])
    validation = validate(a, df["fecha"], last_actual)

    forecasts = []
    max_target = min(last_actual + 48, len(df) - 1)
    for target in range(last_actual + 1, max_target + 1):
        horizon = target - last_actual
        x_live = matrix(a, np.array([target]), horizon)
        if not np.isfinite(x_live).all():
            continue
        _, x_train, y_train = training_data(a, horizon, last_actual)
        model = fit_ridge(x_train, y_train)
        correction = float(predict(model, x_live)[0])
        forecast = float(a["daily"][target] + correction)
        rdo_calibrated = None
        rdo_advanced = None
        if advanced and np.isfinite(a["rdo"][target]):
            advanced_model = advanced["models"].get(horizon)
            if advanced_model is not None:
                if horizon not in advanced_features:
                    advanced_features[horizon] = build_advanced_features(df, horizon)[0]
                advanced_x = advanced_features[horizon].iloc[[target]]
                if advanced_x.notna().all(axis=None):
                    correction_advanced = float(np.clip(advanced_model.predict(advanced_x)[0], -400, 400))
                    rdo_advanced = float(a["rdo"][target] + correction_advanced)
        if horizon <= 6 and np.isfinite(a["rdo"][target]):
            rdo_targets, rdo_x, rdo_y = rdo_training_data(a, horizon, last_actual)
            rdo_live = rdo_matrix(a, np.array([target]), horizon)
            if len(rdo_targets) >= 300 and np.isfinite(rdo_live).all():
                rdo_model = fit_ridge(rdo_x, rdo_y, alpha=100.0)
                rdo_calibrated = float(a["rdo"][target] + predict(rdo_model, rdo_live)[0])
        keys = np.array([12, 24, 48])
        closest = str(int(keys[np.argmin(np.abs(keys - horizon))]))
        sigma = float(validation[closest]["rmseModel"])
        forecasts.append(
            {
                "time": df["fecha"].iloc[target].isoformat(timespec="minutes"),
                "horizonSteps": horizon,
                "prediction": forecast,
                "rdoCalibrated": rdo_calibrated,
                "rdoAdvanced": rdo_advanced,
                "lower": forecast - 1.64 * sigma,
                "upper": forecast + 1.64 * sigma,
            }
        )

    output = {
        "model": "LDS residual directo v1.1",
        "generatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "trainedThrough": df["fecha"].iloc[last_actual].isoformat(timespec="minutes"),
        "trainingRows": int(last_actual + 1),
        "validation": validation,
        "forecast": forecasts,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".tmp")
    temp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, OUTPUT)
    print(json.dumps({
        "trainedThrough": output["trainedThrough"],
        "trainingRows": output["trainingRows"],
        "forecastPoints": len(forecasts),
        "validation": validation,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
