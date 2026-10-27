"""Descarga y evalúa programación semanal, diaria y reprogramación de COES.

La API histórica entrega la última curva guardada para cada tipo de lectura, pero
no incluye la hora de publicación de cada versión. Por eso este análisis sirve
para medir el valor potencial de la reprogramación, no para un backtest "as-of"
perfecto. El monitor en tiempo real deberá guardar las versiones futuras.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


API = "https://appserver.coes.org.pe/waMediciones/api/Mediciones"
LECTURAS = {3: "prog_semanal", 4: "prog_diaria", 5: "reprogramacion"}


def intervalos(inicio: date, fin: date, dias: int = 7):
    actual = inicio
    while actual <= fin:
        cierre = min(actual + timedelta(days=dias - 1), fin)
        yield actual, cierre
        actual = cierre + timedelta(days=1)


def descargar(tipo: int, inicio: date, fin: date, reintentos: int = 3) -> list[dict]:
    params = urllib.parse.urlencode(
        {"lectcodi": tipo, "fechaIni": inicio.isoformat(), "fechaFin": fin.isoformat()}
    )
    req = urllib.request.Request(
        f"{API}?{params}", headers={"User-Agent": "PronosticoDemandaCOES/1.0"}
    )
    for intento in range(reintentos):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except Exception:
            if intento + 1 == reintentos:
                raise
            time.sleep(2 ** intento)
    return []


def descargar_rango(tipo: int, inicio: date, fin: date) -> list[dict]:
    bloques = list(intervalos(inicio, fin))
    registros: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        tareas = {pool.submit(descargar, tipo, a, b): (a, b) for a, b in bloques}
        for numero, tarea in enumerate(as_completed(tareas), 1):
            registros.extend(tarea.result())
            if numero % 20 == 0 or numero == len(bloques):
                print(f"Lectura {tipo}: {numero}/{len(bloques)} bloques", flush=True)
    return registros


def agregar_curva(registros: list[dict], nombre: str) -> pd.DataFrame:
    filas: list[dict] = []
    por_fecha: dict[pd.Timestamp, list[dict]] = {}
    for registro in registros:
        fecha = pd.Timestamp(registro["Medifecha"]).normalize()
        por_fecha.setdefault(fecha, []).append(registro)

    for fecha, items in por_fecha.items():
        for i in range(1, 49):
            valores = [r.get(f"h{i}") for r in items]
            valores = [float(v) for v in valores if v is not None and math.isfinite(float(v))]
            momento = fecha + pd.Timedelta(minutes=30 * i)
            filas.append({"fecha": momento, nombre: sum(valores) if valores else float("nan")})
    return pd.DataFrame(filas)


def cargar_ejecutado(ruta: Path) -> pd.DataFrame:
    datos = pd.read_excel(ruta, header=3)
    datos.columns = [str(c).strip().lower() for c in datos.columns]
    fecha_col = next(c for c in datos.columns if "fecha" in c)
    ejecutado_col = next(c for c in datos.columns if "ejecutado" in c)
    salida = datos[[fecha_col, ejecutado_col]].rename(
        columns={fecha_col: "fecha", ejecutado_col: "ejecutado"}
    )
    # Los archivos exportados por el portal COES usan dd/mm/aaaa HH:MM como texto.
    salida["fecha"] = pd.to_datetime(
        salida["fecha"], format="%d/%m/%Y %H:%M", errors="coerce"
    )
    salida["ejecutado"] = pd.to_numeric(salida["ejecutado"], errors="coerce")
    return salida.dropna(subset=["fecha"]).drop_duplicates("fecha", keep="last")


def metricas(datos: pd.DataFrame, columna: str) -> dict:
    muestra = datos.dropna(subset=["ejecutado", columna]).copy()
    error = muestra[columna] - muestra["ejecutado"]
    abs_error = error.abs()
    return {
        "pronostico": columna,
        "n": len(muestra),
        "mae_mw": abs_error.mean(),
        "rmse_mw": math.sqrt((error.pow(2)).mean()),
        "mape_pct": (abs_error / muestra["ejecutado"].abs()).mean() * 100,
        "sesgo_mw": error.mean(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", default="2026-09-01")
    parser.add_argument("--fin", default="2026-09-27")
    parser.add_argument(
        "--ejecutado",
        default="data/coes/Demanda_COES_septiembre_2026_corte_2026-09-27.xlsx",
    )
    parser.add_argument("--salida", default="data/coes")
    args = parser.parse_args()

    inicio = date.fromisoformat(args.inicio)
    fin = date.fromisoformat(args.fin)
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    curvas: list[pd.DataFrame] = []
    for tipo, nombre in LECTURAS.items():
        registros = descargar_rango(tipo, inicio, fin)
        curvas.append(agregar_curva(registros, nombre))

    combinado = cargar_ejecutado(Path(args.ejecutado))
    for curva in curvas:
        combinado = combinado.merge(curva, on="fecha", how="outer")
    combinado = combinado.sort_values("fecha")
    combinado = combinado[
        (combinado["fecha"] >= pd.Timestamp(inicio))
        & (combinado["fecha"] < pd.Timestamp(fin + timedelta(days=1)))
    ].copy()

    combinado["cambio_reprog_vs_diaria_mw"] = (
        combinado["reprogramacion"] - combinado["prog_diaria"]
    )
    combinado["abs_cambio_reprog_vs_diaria_mw"] = combinado[
        "cambio_reprog_vs_diaria_mw"
    ].abs()

    metricas_df = pd.DataFrame(
        metricas(combinado, c)
        for c in ["prog_semanal", "prog_diaria", "reprogramacion"]
    )
    base = float(
        metricas_df.loc[metricas_df["pronostico"] == "prog_diaria", "mae_mw"].iloc[0]
    )
    metricas_df["mejora_mae_vs_diaria_pct"] = (base - metricas_df["mae_mw"]) / base * 100

    valida = combinado.dropna(subset=["ejecutado", "prog_diaria", "reprogramacion"]).copy()
    valida["gana_reprogramacion"] = (
        (valida["reprogramacion"] - valida["ejecutado"]).abs()
        < (valida["prog_diaria"] - valida["ejecutado"]).abs()
    )
    resumen = {
        "generado_en": datetime.now().astimezone().isoformat(),
        "inicio": inicio.isoformat(),
        "fin": fin.isoformat(),
        "intervalos_con_ejecutado_y_ambos_pronosticos": int(len(valida)),
        "intervalos_donde_reprogramacion_gana_pct": float(valida["gana_reprogramacion"].mean() * 100),
        "intervalos_modificados_por_reprogramacion": int(
            (valida["abs_cambio_reprog_vs_diaria_mw"] > 0.001).sum()
        ),
        "cambio_absoluto_mediano_mw": float(
            valida["abs_cambio_reprog_vs_diaria_mw"].median()
        ),
        "cambio_absoluto_p95_mw": float(
            valida["abs_cambio_reprog_vs_diaria_mw"].quantile(0.95)
        ),
        "advertencia": (
            "La API histórica no entrega timestamp de publicación ni todas las versiones. "
            "La reprogramación descargada puede ser la última del día y no debe usarse como "
            "si hubiera estado disponible a las 00:00."
        ),
    }

    etiqueta = f"{inicio.isoformat()}_{fin.isoformat()}"
    combinado.to_csv(salida / f"reprogramaciones_agregadas_{etiqueta}.csv", index=False)
    metricas_df.to_csv(salida / f"metricas_reprogramacion_{etiqueta}.csv", index=False)
    (salida / f"resumen_reprogramacion_{etiqueta}.json").write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(metricas_df.to_string(index=False))
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
