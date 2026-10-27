import json

import numpy as np
import pandas as pd

from src.config import HORIZONS, MODELS_DIR, REPORTS_DIR, RIDGE_ALPHA, TEST_START, TRAIN_END
from src.features.build_features import build_matrix, prepare_arrays
from src.models.ridge import fit, predict, save


def metrics(actual, forecast):
    error = actual - forecast
    return {
        "mae_mw": float(np.mean(np.abs(error))),
        "rmse_mw": float(np.sqrt(np.mean(error ** 2))),
        "mape_pct": float(np.mean(np.abs(error / actual)) * 100),
        "bias_mw": float(np.mean(forecast - actual)),
    }


def train_and_evaluate(df):
    MODELS_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)
    a = prepare_arrays(df)
    dates = df["fecha"].to_numpy()
    results = []
    predictions = []

    for horizon in HORIZONS:
        targets = np.arange(max(336, horizon + 49), len(df))
        x = build_matrix(a, targets, horizon)
        valid = np.isfinite(x).all(axis=1) & np.isfinite(a["actual"][targets])
        targets, x = targets[valid], x[valid]
        y = np.clip(a["residual"][targets], -800, 800)
        train = dates[targets] <= np.datetime64(TRAIN_END)
        test = dates[targets] >= np.datetime64(TEST_START)
        model = fit(x[train], y[train], RIDGE_ALPHA)
        save(model, MODELS_DIR / f"ridge_residual_{horizon // 2}h.npz", horizon, RIDGE_ALPHA)

        target_test = targets[test]
        actual = a["actual"][target_test]
        forecasts = {
            "Ridge residual": a["daily"][target_test] + predict(model, x[test]),
            "Programacion diaria": a["daily"][target_test],
            "Programacion semanal": a["weekly"][target_test],
            "Persistencia D-1": a["actual"][target_test - 48],
        }
        for name, forecast in forecasts.items():
            row = {"horizonte_h": horizon // 2, "modelo": name, "n": int(len(actual))}
            row.update(metrics(actual, forecast))
            results.append(row)
        for index, target in enumerate(target_test):
            predictions.append({
                "fecha": df["fecha"].iloc[target],
                "horizonte_h": horizon // 2,
                "ejecutado": actual[index],
                **{name: values[index] for name, values in forecasts.items()},
            })

    metrics_df = pd.DataFrame(results).sort_values(["horizonte_h", "mae_mw"])
    predictions_df = pd.DataFrame(predictions)
    metrics_df.to_csv(REPORTS_DIR / "metricas_validacion.csv", index=False)
    predictions_df.to_csv(REPORTS_DIR / "predicciones_validacion.csv", index=False)
    (REPORTS_DIR / "metricas_validacion.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metrics_df

