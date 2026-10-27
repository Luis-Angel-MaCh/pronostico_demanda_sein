# Presentación final

## Diapositiva 1. Pronóstico de demanda eléctrica del SEIN

Modelo de 6, 12 y 24 horas con actualización operativa.

## Diapositiva 2. Problema y objetivo

- La demanda cambia cada 30 minutos.
- Objetivo: reducir el error frente a referencias simples y COES.
- Salida: pronóstico operativo con trazabilidad.

## Diapositiva 3. Recolección de datos

- Portal y API de COES.
- Enero de 2024 a septiembre de 2026.
- 48.048 intervalos de 30 minutos.
- Calendario, feriados y meteorología histórica como fuentes auxiliares.

## Diapositiva 4. Preparación

- Conversión de fechas y valores numéricos.
- Revisión de faltantes y duplicados.
- Retardos, medias móviles, rampas y ciclos temporales.
- Exclusión de información no disponible al momento del pronóstico.

## Diapositiva 5. Validación temporal

- Entrenamiento hasta agosto de 2026.
- Prueba con septiembre de 2026.
- 1.282 intervalos fuera de muestra.
- Horizontes directos de 6, 12 y 24 horas.

## Diapositiva 6. Modelos

- Persistencia del día anterior.
- Programación semanal.
- Programación diaria.
- Ridge residual.

## Diapositiva 7. Resultados

| Horizonte | Ridge MAE | Diaria MAE | Mejora |
|---|---:|---:|---:|
| 6 h | 83,6 MW | 95,2 MW | 12,3 % |
| 12 h | 90,3 MW | 95,2 MW | 5,1 % |
| 24 h | 88,7 MW | 95,2 MW | 6,9 % |

## Diapositiva 8. Arquitectura

COES alimenta el monitor y el dataset. El pipeline limpia los datos, construye variables y reentrena. El servidor combina la fuente campeona y publica el resultado en el panel.

## Diapositiva 9. Demostración

- Ejecutar `INICIAR_APLICACION.bat`.
- Mostrar la curva diaria.
- Revisar horizontes y trazabilidad.
- Forzar una actualización.

## Diapositiva 10. Conclusiones

- Ridge supera la programación diaria en los tres horizontes.
- La validación temporal evita fuga de información.
- El panel integra predicción, monitoreo y reentrenamiento.
- Próximo paso: clima pronosticado y mayor historial de reprogramaciones.

