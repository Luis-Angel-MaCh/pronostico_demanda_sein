import pandas as pd

from src.config import BASE_XLSX, SEPT_XLSX


def read_coes(path):
    df = pd.read_excel(path, header=3).iloc[:, :4]
    df.columns = ["fecha", "ejecutado", "prog_diaria", "prog_semanal"]
    df["fecha"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y %H:%M", errors="coerce")
    for column in df.columns[1:]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.dropna(subset=["fecha"])


def load_dataset():
    frames = [read_coes(BASE_XLSX)]
    if SEPT_XLSX.exists():
        frames.append(read_coes(SEPT_XLSX))
    raw = pd.concat(frames, ignore_index=True).sort_values("fecha")
    duplicate_count = int(raw.duplicated("fecha").sum())
    df = raw.groupby("fecha", as_index=False).last()
    index = pd.date_range(df["fecha"].min(), df["fecha"].max(), freq="30min")
    df = df.set_index("fecha").reindex(index).rename_axis("fecha").reset_index()
    summary = {
        "rows_raw": int(len(raw)),
        "rows_final": int(len(df)),
        "duplicates_resolved": duplicate_count,
        "date_start": df["fecha"].min().isoformat(),
        "date_end": df["fecha"].max().isoformat(),
        "missing": {column: int(df[column].isna().sum()) for column in df.columns},
    }
    return df, summary

