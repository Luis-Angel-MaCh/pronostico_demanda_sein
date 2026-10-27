@echo off
setlocal
cd /d "%~dp0"
title Instalacion del proyecto LDS

where py >nul 2>nul
if not errorlevel 1 (
    set "BASEPY=py -3"
) else (
    set "BASEPY=python"
)

if not exist ".venv\Scripts\python.exe" %BASEPY% -m venv .venv
if errorlevel 1 goto error

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error

echo.
echo Dependencias instaladas correctamente.
pause
exit /b 0

:error
echo.
echo No se pudieron instalar las dependencias.
pause
exit /b 1
