@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Chua co moi truong. Dang tao...
    python -m venv .venv
    if errorlevel 1 (
        echo Khong tao duoc .venv. Cai Python 3.10+ truoc.
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

if not exist "weights\ppe_yolov8.pt" (
    echo Dang tai trong so model...
    .venv\Scripts\python.exe scripts\download_model.py
)

if not exist "data" mkdir data
if not exist "evidence" mkdir evidence

echo.
echo ============================================
echo   PPE MONITOR
echo   Dashboard: http://127.0.0.1:8000
echo ============================================
echo.
echo Chon che do:
echo   [1] Demo    - chay bang anh cong truong mau
echo   [2] Webcam  - camera so 0
echo   [3] Server  - chi mo dashboard, them camera sau
echo   [4] Kiem tra - tu kiem moi truong, model, GPU
echo   [5] Bao cao - xuat Excel/CSV 7 ngay gan nhat
echo.
set /p CHOICE="Lua chon (1/2/3/4/5): "

if "%CHOICE%"=="1" (
    .venv\Scripts\python.exe run.py --demo
) else if "%CHOICE%"=="2" (
    .venv\Scripts\python.exe run.py --camera webcam=0
) else if "%CHOICE%"=="4" (
    .venv\Scripts\python.exe scripts\selftest.py
    pause
    exit /b 0
) else if "%CHOICE%"=="5" (
    if not exist "reports" mkdir reports
    echo Dang xuat bao cao...
    powershell -NoProfile -Command "try { Invoke-WebRequest 'http://127.0.0.1:8000/api/reports/summary.xlsx?days=7' -OutFile 'reports\ppe_7ngay.xlsx' -UseBasicParsing; Write-Host 'Da luu: reports\ppe_7ngay.xlsx' } catch { Write-Host 'Server chua chay. Mo che do 3 truoc.' }"
    pause
    exit /b 0
) else (
    .venv\Scripts\python.exe run.py
)

pause
