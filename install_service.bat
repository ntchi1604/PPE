@echo off
chcp 65001 >nul
title PPE Monitor - cai dat dich vu
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\install_service.ps1" %*
echo.
pause
