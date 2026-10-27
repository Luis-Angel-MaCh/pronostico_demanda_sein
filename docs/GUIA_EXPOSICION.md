# Guía de exposición

Duración objetivo: 10 a 12 minutos.

## 1. Problema

La demanda del SEIN cambia cada 30 minutos. El objetivo es estimar los siguientes 6, 12 y 24 horas y medir si el modelo reduce el error de los pronósticos de referencia publicados por COES.

## 2. Datos

Se consolidaron 48.048 intervalos desde enero de 2024. Cada registro incluye demanda ejecutada y programaciones diaria y semanal. Las reprogramaciones se descargaron por día y las nuevas versiones se guardan en SQLite.

## 3. Preparación

Las fechas se ordenan, los valores se convierten a MW y se controlan duplicados y faltantes. Se generan retardos, medias móviles, rampas, hora, día de semana y feriados. Ninguna variable puede usar demanda posterior al origen del pronóstico.

## 4. Validación

El entrenamiento termina el 31 de agosto de 2026 y septiembre queda como prueba. No se usa una división aleatoria porque mezclaría pasado y futuro.

## 5. Comparación de modelos

Se comparan persistencia del día anterior, programación semanal, programación diaria y Ridge residual. También se evalúan HistGradientBoosting y Ridge para corregir la última reprogramación disponible.

## 6. Resultados

En septiembre, el modelo obtuvo MAE de 83,6 MW a 6 horas, 90,3 MW a 12 horas y 88,7 MW a 24 horas. La programación diaria obtuvo 95,2 MW. Las mejoras fueron 12,3 %, 5,1 % y 6,9 %.

## 7. Aplicación

Al actualizar, el sistema consulta COES, guarda cambios, incorpora ejecutados confirmados, reentrena y genera 48 intervalos futuros. El panel muestra demanda actual, pico previsto, curvas comparadas, métricas y cobertura por horizonte.

## 8. Cierre

El resultado es un flujo completo de recopilación, preparación, validación temporal, despliegue, monitoreo y reentrenamiento. La mejora futura prioritaria es acumular más versiones intradía para medir la corrección de reprogramaciones con trazabilidad exacta.

## Preguntas frecuentes

**¿Por qué Ridge?**  
Fue estable con variables correlacionadas, se reentrena rápidamente y redujo el MAE en los tres horizontes oficiales.

**¿Por qué no una red neuronal?**  
La selección se basó en validación temporal. Mayor complejidad solo se justifica si mejora de manera consistente el error fuera de muestra.

**¿Usar COES hace dependiente al modelo?**  
La aplicación conserva un modelo histórico independiente y una corrección de referencias COES. Si una fuente deja de estar disponible, el sistema puede seguir con la alternativa validada.

**¿La reprogramación genera fuga de información?**  
Puede generarla si se usa una versión publicada después del intervalo. Por eso el monitor registra la hora de captura y la evaluación operativa usa únicamente versiones disponibles al emitir el pronóstico.

**¿Siempre gana a COES?**  
No. El objetivo es reducir el error promedio fuera de muestra. Los resultados se presentan con MAE y porcentaje de intervalos ganados, sin afirmar superioridad en cada punto.

**¿Qué ocurre al presionar Actualizar?**  
Se descarga la última información, se guardan cambios, se reentrena con demanda confirmada y se reemplaza la curva futura de 48 intervalos.
