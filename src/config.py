from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_XLSX = ROOT / "Demanda_COES_2024-01-01_2026-09-01.xlsx"
SEPT_XLSX = ROOT / "data/coes/Demanda_COES_septiembre_2026_corte_2026-09-27.xlsx"
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
TRAIN_END = "2026-08-31 23:30"
TEST_START = "2026-09-01 00:30"
HORIZONS = (12, 24, 48)
RIDGE_ALPHA = 18.0

