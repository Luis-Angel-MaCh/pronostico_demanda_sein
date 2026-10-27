@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"
title Aplicativo de Pronostico LDS

echo Iniciando el Centro de Pronostico LDS...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar_dashboard.ps1"

if errorlevel 1 (
    echo.
    echo No se pudo iniciar la aplicacion.
    echo Revisa el mensaje anterior y verifica las dependencias.
    pause
    exit /b 1
)

exit /b 0
