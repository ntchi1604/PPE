# Cai PPE Monitor thanh dich vu Windows: tu chay khi khoi dong may, tu chay lai khi loi.
# Chay bang quyen Administrator:
#   powershell -ExecutionPolicy Bypass -File scripts\install_service.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_service.ps1 -Uninstall

param(
    [string]$TaskName = "PPE Monitor",
    [string]$Args = "--no-browser",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $root ".venv\Scripts\pythonw.exe"
$runpy = Join-Path $root "run.py"

if ($Uninstall) {
    schtasks /Delete /TN "$TaskName" /F 2>$null | Out-Null
    Write-Host "Da go cai dat: $TaskName"
    exit 0
}

if (-not (Test-Path $python)) {
    $python = Join-Path $root ".venv\Scripts\python.exe"
}
if (-not (Test-Path $python)) {
    Write-Host "Khong thay python trong .venv. Chay install.bat truoc."
    exit 1
}

$action = "`"$python`" `"$runpy`" $Args"

# Dang nhap bang SYSTEM de chay truoc khi co nguoi dang nhap (can cho camera IP)
schtasks /Create /TN "$TaskName" /TR "$action" /SC ONSTART /RU "SYSTEM" /RL HIGHEST /F | Out-Null
if ($LASTEXITCODE -ne 0) {
    # Khong co quyen SYSTEM: dung tai khoan hien tai, chi chay khi dang nhap
    schtasks /Create /TN "$TaskName" /TR "$action" /SC ONLOGON /F | Out-Null
}

# Thu lai 3 lan neu thoat bat thuong
schtasks /Change /TN "$TaskName" /RI 1 /DU 9999:59 /K /F 2>$null | Out-Null

Write-Host ""
Write-Host "Da cai dat: $TaskName"
Write-Host "  Lenh : $action"
Write-Host "  Chay : schtasks /Run /TN `"$TaskName`""
Write-Host "  Dung : schtasks /End /TN `"$TaskName`""
Write-Host "  Go   : powershell -ExecutionPolicy Bypass -File scripts\install_service.ps1 -Uninstall"
Write-Host ""
Write-Host "Dashboard: http://127.0.0.1:8000"
