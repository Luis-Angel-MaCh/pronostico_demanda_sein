@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Entrenamiento del modelo LDS

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Falta el entorno del proyecto. Ejecuta primero INSTALAR_DEPENDENCIAS.bat.
    pause
    exit /b 1
)

echo Entrenando y validando los modelos de 6, 12 y 24 horas...
"%PYTHON%" -m src.pipeline
if not errorlevel 1 "%PYTHON%" scripts\entrenar_modelo_avanzado.py

if errorlevel 1 (
    echo.
    echo El entrenamiento termino con un error.
    pause
    exit /b 1
)

echo.
echo Modelos guardados en models y resultados guardados en reports.
pause

