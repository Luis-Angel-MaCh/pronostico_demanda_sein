from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/coes/reprogramaciones_agregadas_2024-01-01_2026-08-31.csv"
REPORT = ROOT / "reports/comparacion_modelos_rdo.csv"
SUMMARY = ROOT / "reports/resumen_modelo_avanzado.json"
HORIZONS = (1, 2, 4, 6, 12, 24, 48)
WINDOWS = (180, 365, 730)


def features(df: pd.DataFrame, horizon: int) -> tuple[pd.DataFrame, pd.Series]:
    actual = df["ejecutado"]
    rdo = df["reprogramacion"].where(df["reprogramacion"] > 1000)
    residual = actual - rdo
    origin = np.arange(len(df)) - horizon
    minute = df["fecha"].dt.hour * 60 + df["fecha"].dt.minute
    angle = 2 * math.pi * minute / 1440
    x = pd.DataFrame({
        "rdo": rdo / 1000,
        "daily": df["prog_diaria"] / 1000,
        "weekly": df["prog_semanal"] / 1000,
        "rdo_daily": (rdo - df["prog_diaria"]) / 100,
        "rdo_weekly": (rdo - df["prog_semanal"]) / 100,
        "rdo_slope": rdo.diff() / 100,
        "daily_slope": df["prog_diaria"].diff() / 100,
        "actual_d1": actual.shift(48) / 1000,
        "actual_w1": actual.shift(336) / 1000,
        "sin1": np.sin(angle),
        "cos1": np.cos(angle),
        "sin2": np.sin(2 * angle),
        "cos2": np.cos(2 * angle),
        "sin3": np.sin(3 * angle),
        "cos3": np.cos(3 * angle),
        "dow_sin": np.sin(2 * math.pi * df["fecha"].dt.dayofweek / 7),
        "dow_cos": np.cos(2 * math.pi * df["fecha"].dt.dayofweek / 7),
        "doy_sin": np.sin(2 * math.pi * df["fecha"].dt.dayofyear / 365.25),
        "doy_cos": np.cos(2 * math.pi * df["fecha"].dt.dayofyear / 365.25),
    })
    for name, series in {
        "actual_origin": actual,
        "rdo_error": residual,
        "rdo_error4": residual.rolling(4, min_periods=2).mean(),
        "rdo_error12": residual.rolling(12, min_periods=6).mean(),
        "rdo_error48": residual.rolling(48, min_periods=24).mean(),
        "actual_ramp1": actual.diff(),
        "actual_ramp2": actual.diff(2),
        "actual_ramp6": actual.diff(6),
    }.items():
        values = np.full(len(df), np.nan)
        valid = origin >= 0
        values[valid] = series.to_numpy()[origin[valid]]
        x[name] = values / (1000 if name == "actual_origin" else 100)
    return x, residual


def models() -> dict[str, object]:
    return {
        "Ridge": make_pipeline(StandardScaler(), Ridge(alpha=40)),
        "Random Forest": RandomForestRegressor(n_estimators=220, max_depth=14, min_samples_leaf=6, max_features=0.8, n_jobs=-1, random_state=42),
        "Extra Trees": ExtraTreesRegressor(n_estimators=220, max_depth=None, min_samples_leaf=5, max_features=0.85, n_jobs=-1, random_state=42),
        "HistGradientBoosting": HistGradientBoostingRegressor(max_iter=260, learning_rate=0.045, max_leaf_nodes=31, min_samples_leaf=25, l2_regularization=10, random_state=42),
        "XGBoost": XGBRegressor(n_estimators=450, learning_rate=0.035, max_depth=5, min_child_weight=12, subsample=0.85, colsample_bytree=0.85, reg_lambda=12, objective="reg:squarederror", n_jobs=4, random_state=42),
    }


def mae(actual: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - forecast)))


def main() -> None:
    df = pd.read_csv(SOURCE, parse_dates=["fecha"]).sort_values("fecha").reset_index(drop=True)
    records = []
    winners = {}
    for horizon in HORIZONS:
        x, y = features(df, horizon)
        valid = x.notna().all(axis=1) & y.notna()
        validation = valid & df["fecha"].between("2026-07-01", "2026-07-31 23:59:59")
        test = valid & df["fecha"].between("2026-08-01", "2026-08-31 23:59:59")
        actual_validation = df.loc[validation, "ejecutado"].to_numpy()
        rdo_validation = df.loc[validation, "reprogramacion"].to_numpy()
        actual_test = df.loc[test, "ejecutado"].to_numpy()
        rdo_test = df.loc[test, "reprogramacion"].to_numpy()
        candidates = []
        for window in WINDOWS:
            start = pd.Timestamp("2026-07-01") - pd.Timedelta(days=window)
            train = valid & (df["fecha"] >= start) & (df["fecha"] < "2026-07-01")
            for name, model in models().items():
                model.fit(x.loc[train], y.loc[train].clip(-600, 600))
                correction = np.clip(model.predict(x.loc[validation]), -400, 400)
                score = mae(actual_validation, rdo_validation + correction)
                candidates.append((score, name, window, model))
        score, name, window, _ = min(candidates, key=lambda item: item[0])
        start = pd.Timestamp("2026-08-01") - pd.Timedelta(days=window)
        train_final = valid & (df["fecha"] >= start) & (df["fecha"] < "2026-08-01")
        model = models()[name]
        model.fit(x.loc[train_final], y.loc[train_final].clip(-600, 600))
        correction = np.clip(model.predict(x.loc[test]), -400, 400)
        forecast = rdo_test + correction
        mae_rdo = mae(actual_test, rdo_test)
        mae_model = mae(actual_test, forecast)
        mae_daily = mae(actual_test, df.loc[test, "prog_diaria"].to_numpy())
        records.append({
            "horizonte_h": horizon / 2,
            "modelo": name,
            "ventana_dias": window,
            "n_validacion": int(validation.sum()),
            "mae_validacion_mw": score,
            "n_prueba": int(test.sum()),
            "mae_rdo_mw": mae_rdo,
            "mae_modelo_mw": mae_model,
            "mae_diaria_mw": mae_daily,
            "mejora_vs_rdo_pct": (mae_rdo - mae_model) / mae_rdo * 100,
            "gana_rdo_pct": float((np.abs(actual_test - forecast) < np.abs(actual_test - rdo_test)).mean() * 100),
        })
        winners[str(horizon)] = {"model": name, "windowDays": window}
        print(records[-1], flush=True)
    result = pd.DataFrame(records)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(REPORT, index=False)
    SUMMARY.write_text(json.dumps({"testMonth": "2026-08", "winners": winners, "results": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
