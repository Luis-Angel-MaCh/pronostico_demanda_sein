from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.advanced_rdo import build_features, specification


HISTORY = ROOT / "data/coes/reprogramaciones_agregadas_2024-01-01_2026-08-31.csv"
SEPTEMBER = ROOT / "data/coes/reprogramaciones_agregadas_2026-09-01_2026-09-27.csv"
DB = ROOT / "data/monitor/coes_versiones.sqlite"
OUTPUT = ROOT / "models/advanced_rdo.joblib"
REPORT = ROOT / "reports/entrenamiento_modelo_avanzado.json"
TZ = ZoneInfo("America/Lima")


def historic(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["fecha"])
    return df.rename(columns={"prog_diaria": "diaria", "prog_semanal": "semanal", "reprogramacion": "rdo"})[["fecha", "ejecutado", "diaria", "semanal", "rdo"]]


def live() -> pd.DataFrame:
    if not DB.exists():
        return pd.DataFrame(columns=["fecha", "ejecutado", "diaria", "semanal", "rdo"])
    with sqlite3.connect(DB) as con:
        raw = pd.read_sql_query("SELECT target_time,serie,value,observed_at FROM estado_actual", con)
    raw["fecha"] = pd.to_datetime(raw["target_time"], errors="coerce")
    observed = pd.to_datetime(raw["observed_at"], errors="coerce", utc=True).dt.tz_convert(TZ).dt.tz_localize(None)
    raw.loc[(raw["serie"] == "ejecutado_portal") & (observed < raw["fecha"]), "value"] = np.nan
    raw["campo"] = raw["serie"].map({"ejecutado_portal": "ejecutado", "prog_diaria_portal": "diaria", "prog_semanal_portal": "semanal", "reprogramacion_api": "rdo"})
    raw = raw.dropna(subset=["campo", "value"])
    return raw.pivot_table(index="fecha", columns="campo", values="value", aggfunc="last").reset_index()


def dataset() -> pd.DataFrame:
    frames = [historic(HISTORY), historic(SEPTEMBER), live()]
    df = pd.concat(frames, ignore_index=True).sort_values("fecha").groupby("fecha", as_index=False).last()
    index = pd.date_range(df["fecha"].min(), df["fecha"].max(), freq="30min")
    return df.set_index("fecha").reindex(index).rename_axis("fecha").reset_index()


def main() -> None:
    df = dataset()
    actual_rows = df["ejecutado"].notna()
    trained_through = df.loc[actual_rows, "fecha"].max()
    bundle = {"version": "LDS RDO residual v2", "trainedThrough": trained_through.isoformat(), "models": {}}
    details = []
    for horizon in range(1, 49):
        x, y = build_features(df, horizon)
        name, days, model = specification(horizon)
        start = trained_through - pd.Timedelta(days=days)
        train = x.notna().all(axis=1) & y.notna() & (df["fecha"] >= start) & (df["fecha"] <= trained_through)
        model.fit(x.loc[train], y.loc[train].clip(-600, 600))
        bundle["models"][horizon] = model
        details.append({"horizonSteps": horizon, "hours": horizon / 2, "model": name, "windowDays": days, "rows": int(train.sum())})
    OUTPUT.parent.mkdir(exist_ok=True)
    joblib.dump(bundle, OUTPUT, compress=3)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps({"generatedAt": datetime.now(TZ).isoformat(), "trainedThrough": bundle["trainedThrough"], "models": details}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"trainedThrough": bundle["trainedThrough"], "models": len(bundle["models"]), "output": str(OUTPUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
