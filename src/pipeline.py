import json

from src.config import REPORTS_DIR
from src.data.load_data import load_dataset
from src.models.train_model import train_and_evaluate


def run():
    df, summary = load_dataset()
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "resumen_datos.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metrics = train_and_evaluate(df)
    print(metrics.to_string(index=False, float_format=lambda value: f"{value:,.3f}"))


if __name__ == "__main__":
    run()
