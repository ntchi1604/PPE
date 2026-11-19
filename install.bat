@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   CAI DAT PPE MONITOR
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Cai Python 3.10+ tu python.org
    pause
    exit /b 1
)

where uv >nul 2>nul
if errorlevel 1 (
    echo Dang cai uv...
    python -m pip install --quiet uv
)

echo [1/4] Tao moi truong ao...
if not exist ".venv\Scripts\python.exe" (
    uv venv .venv --python 3.11
)

echo [2/4] Cai thu vien...
uv pip install --python .venv\Scripts\python.exe -r requirements.txt

echo [3/4] Cai PyTorch CUDA 12.6 (bo qua neu da co GPU)...
nvidia-smi >nul 2>nul
if not errorlevel 1 (
    uv pip install --python .venv\Scripts\python.exe --reinstall ^
        --index-url https://download.pytorch.org/whl/cu126 torch torchvision
) else (
    echo   Khong co GPU NVIDIA - dung ban CPU
)

echo [4/4] Tai trong so model...
if not exist "weights\ppe_yolov8.pt" (
    .venv\Scripts\python.exe scripts\download_model.py
)

if not exist "data" mkdir data
if not exist "evidence" mkdir evidence

echo.
echo ============================================
.venv\Scripts\python.exe scripts\selftest.py
echo ============================================
echo.
echo Cai dat xong. Chay: start.bat
pause
