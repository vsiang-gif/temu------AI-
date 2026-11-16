@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.11 from https://www.python.org/downloads/
  echo         and tick "Add python.exe to PATH" during install.
  goto :error
)

python --version
echo.
echo [1/4] Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt nuitka ordered-set zstandard
if errorlevel 1 goto :error

echo.
echo [2/4] Checking U2-Net model...
if not exist "models" mkdir "models"
if not exist "models\u2net.onnx" (
  echo Downloading u2net.onnx, about 170MB...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri 'https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx' -OutFile 'models\u2net.onnx'"
  if errorlevel 1 goto :error
)

echo.
echo [3/4] Compiling EXE with Nuitka, first build takes 10-20 minutes...
python -m nuitka main.py --standalone --onefile --assume-yes-for-downloads --enable-plugin=pyside6 --windows-console-mode=disable --include-data-dir=models=models --onefile-tempdir-spec="{CACHE_DIR}/TemuPrintExtractor/1.0.0" --product-name="TemuPrintExtractor" --file-description="Temu POD Print Extractor" --product-version=1.0.0 --file-version=1.0.0 --company-name="POD" --output-filename=TemuPrintExtractor.exe --output-dir=dist
if errorlevel 1 goto :error

echo.
echo [4/4] Done: dist\TemuPrintExtractor.exe
pause
exit /b 0

:error
echo.
echo [FAILED] Build failed. See the error messages above.
pause
exit /b 1
