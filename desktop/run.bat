@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.11 from https://www.python.org/downloads/
  echo         and tick "Add python.exe to PATH" during install.
  pause
  exit /b 1
)

echo Installing dependencies, first run only takes a few minutes...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [FAILED] Dependency install failed. See the error messages above.
  pause
  exit /b 1
)

if not exist "models" mkdir "models"
if not exist "models\u2net.onnx" (
  echo Downloading u2net.onnx, about 170MB...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri 'https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx' -OutFile 'models\u2net.onnx'"
)

python main.py
if errorlevel 1 pause
