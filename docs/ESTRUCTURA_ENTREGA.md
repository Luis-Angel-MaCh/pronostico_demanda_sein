# Estructura del proyecto final

## Fase 1. Datos

- Portal y API oficial de COES.
- Datos de enero de 2024 a septiembre de 2026, con frecuencia de 30 minutos.
- Limpieza de fechas, valores numéricos, duplicados y faltantes.
- Análisis de demanda ejecutada y programaciones diaria, semanal y reprogramada.
- Evidencias: `reports/resumen_datos.json` y `data/modelo/dataset_features_2024-01-01_2026-09-01.csv`.

## Fase 2. Modelamiento

- Entrenamiento hasta agosto de 2026 y prueba fuera de muestra en septiembre de 2026.
- Comparación con persistencia, programación semanal y programación diaria.
- Modelos Ridge residuales para horizontes de 6, 12 y 24 horas.
- Comparación adicional de HistGradientBoosting y Ridge para corregir reprogramaciones.
- Métricas MAE, RMSE, MAPE, sesgo y porcentaje de intervalos ganados.
- Evidencias: `reports/metricas_validacion.csv`, `reports/predicciones_validacion.csv` y `reports/comparacion_modelos_rdo.csv`.

## Fase 3. Integración

- Pipeline modular en `src/`.
- Artefactos entrenados en `models/`.
- Captura de versiones de COES en SQLite.
- Reentrenamiento con demanda confirmada.
- Panel local con actualización manual y automática.
- Inicio mediante archivos BAT o Docker Compose.
- Pruebas automáticas en `tests/`.

## Entregables

- Informe técnico en Word y PDF.
- Presentación de diez diapositivas.
- Guía de exposición.
- Repositorio con datos, código, modelos, métricas y documentación reproducible.
