"""Registra versiones y modificaciones de la demanda y pronósticos COES.

Ejemplos:
    python scripts/monitor_versiones_coes.py --once
    python scripts/monitor_versiones_coes.py --intervalo-minutos 5

El monitor solo añade registros. Nunca reemplaza el historial observado.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


PORTAL = "https://www.coes.org.pe/Portal/portalinformacion/Demanda"
API = "https://appserver.coes.org.pe/waMediciones/api/Mediciones"
ZONA = ZoneInfo("America/Lima")
LECTURAS = {3: "prog_semanal_api", 4: "prog_diaria_api", 5: "reprogramacion_api"}


def request_json(url: str, datos: dict | None = None) -> dict | list:
    cuerpo = urllib.parse.urlencode(datos).encode() if datos is not None else None
    req = urllib.request.Request(
        url,
        data=cuerpo,
        headers={
            "User-Agent": "MonitorPronosticoCOES/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def portal(inicio: date, fin: date) -> list[tuple[str, str, float]]:
    data = request_json(
        PORTAL,
        {"fechaInicial": inicio.strftime("%d/%m/%Y"), "fechaFinal": fin.strftime("%d/%m/%Y")},
    )
    nombres = {
        "ValorEjecutado": "ejecutado_portal",
        "ValorProgramacionDiaria": "prog_diaria_portal",
        "ValorProgramacionSemanal": "prog_semanal_portal",
    }
    filas = []
    for item in data.get("Data", []):
        objetivo = datetime.strptime(item["Fecha"], "%Y/%m/%d %H:%M").isoformat(timespec="minutes")
        for campo, serie in nombres.items():
            valor = item.get(campo)
            if valor is not None:
                filas.append((objetivo, serie, float(valor)))
    return filas


def curva_api(tipo: int, inicio: date, fin: date) -> list[tuple[str, str, float]]:
    params = urllib.parse.urlencode(
        {"lectcodi": tipo, "fechaIni": inicio.isoformat(), "fechaFin": fin.isoformat()}
    )
    data = request_json(f"{API}?{params}")
    acumulado: dict[tuple[str, int], float] = {}
    presentes: set[tuple[str, int]] = set()
    for item in data:
        dia = datetime.fromisoformat(item["Medifecha"]).date()
        for i in range(1, 49):
            valor = item.get(f"h{i}")
            if valor is None:
                continue
            clave = (dia.isoformat(), i)
            acumulado[clave] = acumulado.get(clave, 0.0) + float(valor)
            presentes.add(clave)
    filas = []
    for (dia_texto, i) in sorted(presentes):
        objetivo = datetime.combine(date.fromisoformat(dia_texto), datetime.min.time()) + timedelta(minutes=30 * i)
        filas.append((objetivo.isoformat(timespec="minutes"), LECTURAS[tipo], acumulado[(dia_texto, i)]))
    return filas


def conectar(ruta: Path) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS estado_actual (
            target_time TEXT NOT NULL,
            serie TEXT NOT NULL,
            value REAL NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (target_time, serie)
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at TEXT NOT NULL,
            target_time TEXT NOT NULL,
            serie TEXT NOT NULL,
            value REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_snapshots_target ON snapshots(target_time, serie, observed_at);
        CREATE TABLE IF NOT EXISTS cambios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at TEXT NOT NULL,
            target_time TEXT NOT NULL,
            serie TEXT NOT NULL,
            event_type TEXT NOT NULL,
            old_value REAL,
            new_value REAL NOT NULL,
            diff_mw REAL
        );
        """
    )
    return con


def guardar(con: sqlite3.Connection, filas: list[tuple[str, str, float]], observado: str) -> tuple[int, int]:
    nuevas = cambios = 0
    for objetivo, serie, valor in filas:
        anterior = con.execute(
            "SELECT value FROM estado_actual WHERE target_time=? AND serie=?",
            (objetivo, serie),
        ).fetchone()
        if anterior is not None and abs(float(anterior[0]) - valor) <= 0.0005:
            continue
        evento = "insert" if anterior is None else "update"
        viejo = None if anterior is None else float(anterior[0])
        con.execute(
            "INSERT INTO snapshots(observed_at,target_time,serie,value) VALUES(?,?,?,?)",
            (observado, objetivo, serie, valor),
        )
        con.execute(
            "INSERT INTO cambios(observed_at,target_time,serie,event_type,old_value,new_value,diff_mw) VALUES(?,?,?,?,?,?,?)",
            (observado, objetivo, serie, evento, viejo, valor, None if viejo is None else valor - viejo),
        )
        con.execute(
            "INSERT INTO estado_actual(target_time,serie,value,observed_at) VALUES(?,?,?,?) "
            "ON CONFLICT(target_time,serie) DO UPDATE SET value=excluded.value, observed_at=excluded.observed_at",
            (objetivo, serie, valor, observado),
        )
        nuevas += evento == "insert"
        cambios += evento == "update"
    con.commit()
    return nuevas, cambios


def ciclo(con: sqlite3.Connection) -> None:
    ahora = datetime.now(ZONA)
    inicio = ahora.date()
    fin = inicio + timedelta(days=1)
    observado = ahora.isoformat(timespec="seconds")
    filas = portal(inicio, fin)
    for tipo in LECTURAS:
        filas.extend(curva_api(tipo, inicio, fin))
    nuevas, cambios = guardar(con, filas, observado)
    print(
        f"{observado} | valores consultados={len(filas)} | "
        f"nuevos={nuevas} | modificaciones={cambios}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/monitor/coes_versiones.sqlite")
    parser.add_argument("--intervalo-minutos", type=float, default=5)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    con = conectar(Path(args.db))
    try:
        while True:
            try:
                ciclo(con)
            except Exception as exc:
                print(f"{datetime.now(ZONA).isoformat(timespec='seconds')} | error={exc}")
            if args.once:
                break
            time.sleep(max(30, args.intervalo_minutos * 60))
    finally:
        con.close()


if __name__ == "__main__":
    main()
