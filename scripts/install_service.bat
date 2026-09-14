@echo off
:: ============================================================
:: Piploci Engine — NSSM Windows Service Installer
:: Installs server.py as an auto-restarting Windows Service
:: via NSSM (Non-Sucking Service Manager).
::
:: Prerequisites:
::   - NSSM installed and on PATH (https://nssm.cc/download)
::   - Python 3.10+ installed
::   - Run this batch file as Administrator
:: ============================================================

setlocal EnableDelayedExpansion

set SERVICE_NAME=PiplociEngine
set PYTHON_EXE=C:\Python313\python.exe
set BOT_DIR=C:\Users\Jack.Ouma\Downloads\New folder\Bot
set UVICORN_CMD=-m uvicorn server:app --host 0.0.0.0 --port 8000 --log-level info
set LOG_DIR=%BOT_DIR%\logs

echo ============================================================
echo  Piploci Engine -- Windows Service Installer (NSSM)
echo ============================================================

:: Check for administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script must be run as Administrator.
    pause
    exit /b 1
)

:: Check NSSM availability
where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] NSSM not found on PATH.
    echo         Download from: https://nssm.cc/download
    echo         Extract and place nssm.exe in C:\Windows\System32\
    pause
    exit /b 1
)

:: Create log directory
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: Remove old service if it exists
echo [INFO] Removing existing service (if any)...
nssm stop %SERVICE_NAME% >nul 2>&1
nssm remove %SERVICE_NAME% confirm >nul 2>&1

:: Install service
echo [INFO] Installing %SERVICE_NAME% service...
nssm install %SERVICE_NAME% "%PYTHON_EXE%" %UVICORN_CMD%

:: Configure working directory
nssm set %SERVICE_NAME% AppDirectory "%BOT_DIR%"

:: Logging
nssm set %SERVICE_NAME% AppStdout "%LOG_DIR%\engine_stdout.log"
nssm set %SERVICE_NAME% AppStderr "%LOG_DIR%\engine_stderr.log"
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateBytes 10485760

:: Restart policy — always restart with 5-second backoff
nssm set %SERVICE_NAME% AppExit Default Restart
nssm set %SERVICE_NAME% AppRestartDelay 5000

:: Startup type — automatic (starts on reboot)
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START

:: Set description
nssm set %SERVICE_NAME% Description "Piploci Quantitative Trading Engine — FastAPI/MT5 Gateway"

:: Start service immediately
echo [INFO] Starting %SERVICE_NAME%...
nssm start %SERVICE_NAME%

echo.
echo ============================================================
echo  Service installed and started successfully.
echo  Name     : %SERVICE_NAME%
echo  Port     : 8000
echo  Log Dir  : %LOG_DIR%
echo  Restart  : Auto (5s backoff on crash)
echo ============================================================
pause
