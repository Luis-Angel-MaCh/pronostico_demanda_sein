"""Construye el dataset de variables para el pronóstico de demanda COES.

Las variables retardadas se calculan siempre con datos anteriores al instante
objetivo. Las columnas meteorológicas NASA POWER son observaciones históricas;
para un backtest operativo deben sustituirse por pronósticos archivados (vintages).
"""

from __future__ import annotations

import argparse
import html
import math
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd


CIUDADES = ("lima", "arequipa", "trujillo", "piura", "cusco", "huancayo")
VARIABLES_METEO = ("T2M", "RH2M", "T2MDEW", "WS10M", "PRECTOTCORR", "ALLSKY_SFC_SW_DWN")

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "setiembre": 9,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

PERIODOS_LECTIVOS = (
    ("2024-03-11", "2024-05-10"),
    ("2024-05-13", "2024-07-19"),
    ("2024-08-05", "2024-10-11"),
    ("2024-10-14", "2024-12-20"),
    ("2025-03-17", "2025-05-16"),
    ("2025-05-26", "2025-07-25"),
    ("2025-08-11", "2025-10-10"),
    ("2025-10-20", "2025-12-19"),
    ("2026-03-16", "2026-05-15"),
    ("2026-05-25", "2026-07-24"),
    ("2026-08-10", "2026-10-09"),
    ("2026-10-19", "2026-12-18"),
)


def sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )


def cargar_demanda(ruta: Path) -> pd.DataFrame:
    df = pd.read_excel(ruta, header=3)
    df = df.iloc[:, :4]
    df.columns = ["fecha", "ejecutado", "prog_diaria", "prog_semanal"]
    df["fecha"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y %H:%M", errors="coerce")
    for col in ("ejecutado", "prog_diaria", "prog_semanal"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last")


def fechas_en_texto(texto: str, anio: int) -> list[pd.Timestamp]:
    limpio = sin_acentos(texto)
    hallados = re.findall(r"(\d{1,2})\s+de\s+([a-z]+)", limpio)
    fechas = []
    for dia, mes in hallados:
        if mes in MESES:
            fechas.append(pd.Timestamp(anio, MESES[mes], int(dia)))
    if len(fechas) == 2:
        return list(pd.date_range(fechas[0], fechas[1], freq="D"))
    return fechas[:1]


def cargar_feriados(carpeta: Path) -> pd.DataFrame:
    registros: list[dict] = []
    for ruta in sorted(carpeta.glob("feriados_peru_*.html")):
        anio_match = re.search(r"(20\d{2})", ruta.name)
        if not anio_match:
            continue
        anio = int(anio_match.group(1))
        contenido = ruta.read_text(encoding="utf-8")
        bloque = re.search(
            r"<h2[^>]*>Nacionales:</h2>(.*?)(?:<h2[^>]*>)",
            contenido,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not bloque:
            continue
        filas = re.findall(
            r"<strong[^>]*>(.*?)</strong>\s*<span[^>]*>(.*?)</span>",
            bloque.group(1),
            flags=re.IGNORECASE | re.DOTALL,
        )
        for fecha_html, descripcion_html in filas:
            fecha_texto = html.unescape(re.sub(r"<[^>]+>", " ", fecha_html))
            descripcion = html.unescape(re.sub(r"<[^>]+>", " ", descripcion_html))
            fecha_texto = " ".join(fecha_texto.split())
            descripcion = " ".join(descripcion.split())
            for fecha in fechas_en_texto(fecha_texto, anio):
                registros.append(
                    {
                        "dia": fecha,
                        "nombre_feriado": descripcion,
                        "es_dia_no_laborable": int("no laborable" in sin_acentos(descripcion)),
                    }
                )
    if not registros:
        return pd.DataFrame(columns=["dia", "nombre_feriado", "es_dia_no_laborable"])
    return pd.DataFrame(registros).drop_duplicates("dia", keep="last")


def cargar_meteo(ruta: Path, ciudad: str) -> pd.DataFrame:
    inicio = 0
    with ruta.open("r", encoding="utf-8") as f:
        for i, linea in enumerate(f):
            if linea.startswith("YEAR,"):
                inicio = i
                break
    df = pd.read_csv(ruta, skiprows=inicio)
    utc = pd.to_datetime(
        dict(year=df.YEAR, month=df.MO, day=df.DY, hour=df.HR), errors="coerce", utc=True
    )
    df["fecha_hora"] = utc.dt.tz_convert("America/Lima").dt.tz_localize(None)
    salida = df[["fecha_hora", *VARIABLES_METEO]].copy()
    salida[list(VARIABLES_METEO)] = salida[list(VARIABLES_METEO)].replace(-999, np.nan)
    return salida.rename(columns={v: f"meteo_{ciudad}_{v.lower()}" for v in VARIABLES_METEO})


def agregar_sol(df: pd.DataFrame) -> None:
    # Aproximación NOAA para Lima (hora local UTC-5).
    lat = math.radians(-12.0464)
    lon = -77.0428
    n = df["fecha"].dt.dayofyear.to_numpy()
    gamma = 2 * math.pi / 365 * (n - 1)
    eq = 229.18 * (
        0.000075 + 0.001868 * np.cos(gamma) - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2 * gamma) - 0.040849 * np.sin(2 * gamma)
    )
    decl = (
        0.006918 - 0.399912 * np.cos(gamma) + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2 * gamma) + 0.000907 * np.sin(2 * gamma)
        - 0.002697 * np.cos(3 * gamma) + 0.00148 * np.sin(3 * gamma)
    )
    cos_ha = math.cos(math.radians(90.833)) / (math.cos(lat) * np.cos(decl)) - math.tan(lat) * np.tan(decl)
    ha = np.degrees(np.arccos(np.clip(cos_ha, -1, 1)))
    mediodia = 720 - 4 * lon - eq - 300
    amanecer = mediodia - 4 * ha
    anochecer = mediodia + 4 * ha
    minuto = df["fecha"].dt.hour * 60 + df["fecha"].dt.minute
    df["amanecer_minuto_lima"] = amanecer
    df["anochecer_minuto_lima"] = anochecer
    df["duracion_dia_horas_lima"] = 8 * ha / 60
    df["es_oscuridad_lima"] = ((minuto < amanecer) | (minuto > anochecer)).astype("int8")


def agregar_calendario(df: pd.DataFrame, feriados: pd.DataFrame) -> None:
    dia = df["fecha"].dt.normalize()
    df["anio"] = df["fecha"].dt.year
    df["mes"] = df["fecha"].dt.month
    df["dia_mes"] = df["fecha"].dt.day
    df["dia_semana"] = df["fecha"].dt.dayofweek
    df["minuto_dia"] = df["fecha"].dt.hour * 60 + df["fecha"].dt.minute
    df["es_fin_semana"] = (df["dia_semana"] >= 5).astype("int8")
    df["es_inicio_mes"] = df["fecha"].dt.is_month_start.astype("int8")
    df["es_fin_mes"] = df["fecha"].dt.is_month_end.astype("int8")
    df["es_quincena"] = df["dia_mes"].isin([14, 15, 16, 29, 30, 31, 1]).astype("int8")
    df["hora_sin"] = np.sin(2 * math.pi * df["minuto_dia"] / 1440)
    df["hora_cos"] = np.cos(2 * math.pi * df["minuto_dia"] / 1440)
    df["semana_sin"] = np.sin(2 * math.pi * df["dia_semana"] / 7)
    df["semana_cos"] = np.cos(2 * math.pi * df["dia_semana"] / 7)
    doy = df["fecha"].dt.dayofyear
    df["anio_sin"] = np.sin(2 * math.pi * doy / 365.25)
    df["anio_cos"] = np.cos(2 * math.pi * doy / 365.25)

    mapa_nombre = feriados.set_index("dia")["nombre_feriado"] if len(feriados) else {}
    mapa_nolaborable = feriados.set_index("dia")["es_dia_no_laborable"] if len(feriados) else {}
    df["nombre_feriado"] = dia.map(mapa_nombre).fillna("")
    df["es_feriado_nacional"] = (df["nombre_feriado"] != "").astype("int8")
    df["es_dia_no_laborable"] = dia.map(mapa_nolaborable).fillna(0).astype("int8")
    dias_feriados = set(feriados["dia"]) if len(feriados) else set()
    df["es_vispera_feriado"] = (dia + pd.Timedelta(days=1)).isin(dias_feriados).astype("int8")
    df["es_post_feriado"] = (dia - pd.Timedelta(days=1)).isin(dias_feriados).astype("int8")

    lectivo = np.zeros(len(df), dtype=np.int8)
    for inicio, fin in PERIODOS_LECTIVOS:
        lectivo |= ((dia >= pd.Timestamp(inicio)) & (dia <= pd.Timestamp(fin))).astype(np.int8)
    df["es_periodo_lectivo_minedu"] = lectivo


def agregar_historia(df: pd.DataFrame) -> None:
    for pasos in (1, 2, 4, 6, 12, 24, 48, 96, 336, 672, 1344):
        df[f"ejecutado_lag_{pasos}"] = df["ejecutado"].shift(pasos)
    pasado = df["ejecutado"].shift(1)
    for ventana in (2, 6, 12, 24, 48, 336):
        roll = pasado.rolling(ventana, min_periods=max(1, ventana // 2))
        df[f"ejecutado_media_{ventana}"] = roll.mean()
        df[f"ejecutado_std_{ventana}"] = roll.std()
    df["rampa_30m_mw"] = df["ejecutado"].shift(1) - df["ejecutado"].shift(2)
    df["rampa_1h_mw"] = df["ejecutado"].shift(1) - df["ejecutado"].shift(3)
    df["rampa_3h_mw"] = df["ejecutado"].shift(1) - df["ejecutado"].shift(7)
    df["desvio_diaria_lag_1"] = df["ejecutado"].shift(1) - df["prog_diaria"].shift(1)
    df["desvio_semanal_lag_1"] = df["ejecutado"].shift(1) - df["prog_semanal"].shift(1)
    df["brecha_diaria_semanal"] = df["prog_diaria"] - df["prog_semanal"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demanda", default="Demanda_COES_2024-01-01_2026-09-01.xlsx")
    parser.add_argument("--meteo", default="data/meteorologia/nasa_power")
    parser.add_argument("--feriados", default="data/calendario")
    parser.add_argument("--salida", default="data/modelo/dataset_features_2024-01-01_2026-09-01.csv")
    args = parser.parse_args()

    df = cargar_demanda(Path(args.demanda))
    agregar_calendario(df, cargar_feriados(Path(args.feriados)))
    agregar_sol(df)
    agregar_historia(df)

    df["fecha_hora_meteo"] = df["fecha"].dt.floor("h")
    for ciudad in CIUDADES:
        ruta = Path(args.meteo) / f"{ciudad}_2024-01-01_2026-09-01.csv"
        meteo = cargar_meteo(ruta, ciudad)
        df = df.merge(meteo, left_on="fecha_hora_meteo", right_on="fecha_hora", how="left")
        df = df.drop(columns=["fecha_hora"])
    df = df.drop(columns=["fecha_hora_meteo"])

    for variable in VARIABLES_METEO:
        cols = [f"meteo_{c}_{variable.lower()}" for c in CIUDADES]
        df[f"meteo_promedio_{variable.lower()}"] = df[cols].mean(axis=1)

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(salida, index=False, date_format="%Y-%m-%d %H:%M:%S")
    print(f"Filas: {len(df):,}")
    print(f"Columnas: {len(df.columns):,}")
    print(f"Desde: {df.fecha.min()}  Hasta: {df.fecha.max()}")
    print(f"Feriados identificados: {df.loc[df.es_feriado_nacional.eq(1), 'fecha'].dt.date.nunique()}")
    print(f"Salida: {salida.resolve()}")


if __name__ == "__main__":
    main()
