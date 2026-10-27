# Pronóstico de demanda eléctrica del SEIN

Sistema reproducible para recopilar datos de COES, entrenar modelos con validación temporal y visualizar pronósticos de demanda eléctrica para las próximas 6, 12 y 24 horas.

## Resultado principal

La evaluación oficial usa datos hasta el 31 de agosto de 2026 para entrenar y septiembre de 2026 como periodo fuera de muestra.

| Horizonte | Modelo LDS MAE | Programación diaria MAE | Mejora |
|---|---:|---:|---:|
| 6 horas | 83,6 MW | 95,2 MW | 12,3 % |
| 12 horas | 90,3 MW | 95,2 MW | 5,1 % |
| 24 horas | 88,7 MW | 95,2 MW | 6,9 % |

El modelo principal es Ridge residual: aprende la corrección de la programación diaria a partir de retardos de demanda, medias móviles, rampas y variables de calendario. La aplicación también incluye una corrección experimental de la última reprogramación disponible.

## Datos

- Fuente principal: portal de demanda y API de mediciones de COES.
- Periodo consolidado: 1 de enero de 2024 al 28 de septiembre de 2026.
- Frecuencia: 30 minutos.
- Registros: 48.048 intervalos.
- Variables: demanda ejecutada, programación diaria, programación semanal, retardos, medias móviles, rampas, hora, día de semana y feriados.
- Actualización operativa: el panel consulta COES, almacena versiones y reentrena con valores ejecutados confirmados.

## Estructura

```text
dashboard/      interfaz web
data/           datos históricos y captura de versiones
deliverables/   informe y presentación final
docs/           guía de exposición y correspondencia metodológica
models/         modelos entrenados
reports/        métricas y predicciones de validación
scripts/        captura, entrenamiento y servidor local
src/            pipeline modular de datos, variables y modelos
tests/          pruebas automáticas
```

## Instalación en Windows

1. Ejecutar `INSTALAR_DEPENDENCIAS.bat`.
2. Ejecutar `ENTRENAR_MODELO.bat` para reconstruir modelos y métricas.
3. Ejecutar `INICIAR_APLICACION.bat`.
4. Abrir `http://localhost:5173/` si el navegador no se abre automáticamente.

La primera actualización puede tardar mientras se descargan los datos recientes y se reentrena el modelo.

## Ejecución manual

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.pipeline
.\.venv\Scripts\python.exe scripts\entrenar_modelo_avanzado.py
node scripts\local-dashboard.mjs
```

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Operación del panel

Al presionar **Actualizar** se ejecuta el siguiente flujo:

1. Consulta la información reciente de COES.
2. Registra cambios de los valores en SQLite.
3. Incorpora únicamente demanda ejecutada ya confirmada.
4. Reentrena el modelo con la información disponible hasta ese momento.
5. Calcula 48 predicciones de media hora y actualiza los horizontes de 6, 12 y 24 horas.

La hora de emisión queda registrada para impedir que una predicción utilice información publicada después del intervalo evaluado.

## Modelos evaluados

- Persistencia del día anterior.
- Programación semanal de COES.
- Programación diaria de COES.
- Ridge residual para 6, 12 y 24 horas.
- HistGradientBoosting y Ridge por horizonte para corregir la última reprogramación disponible.

La corrección de reprogramaciones se validó como experimento histórico. La API histórica puede entregar la versión final del día sin conservar su hora original de publicación; por ello, la medición operativa definitiva se realiza con las versiones guardadas por el monitor desde el momento de su emisión.

## Docker

```powershell
docker compose up --build
```

Después abrir `http://localhost:5173/`.

## Entregables

- `deliverables/Informe_final_SEIN.docx`
- `deliverables/Informe_final_SEIN.pdf`
- `deliverables/Presentacion_final_SEIN.pptx`
- `docs/GUIA_EXPOSICION.md`

## Fuentes

- [Portal de demanda de COES](https://www.coes.org.pe/Portal/portalinformacion/demanda)
- [Ayuda de la API de mediciones de COES](https://appserver.coes.org.pe/waMediciones/Help)
- [Reprogramación diaria de la operación](https://www.coes.org.pe/Portal/Operacion/ProgOperacion/RprogDiarioOp)
- [NASA POWER](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/)

## Limitaciones

- La validación principal corresponde a septiembre de 2026 y debe repetirse de forma rodante al acumular nuevos meses.
- El histórico de reprogramaciones no conserva todas las horas de emisión; el monitor local sí mantiene las versiones futuras.
- Las variables meteorológicas solo deben pasar a producción cuando se disponga del pronóstico que realmente habría estado disponible antes de cada predicción.
- Ningún modelo garantiza superar a COES en todos los intervalos; la comparación se realiza por MAE agregado y porcentaje de intervalos ganados.
