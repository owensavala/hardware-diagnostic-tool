@echo off
title Membangun MSB Hardware Diagnostic Tool (Titan Edition)
echo =====================================================================
echo  Membangun Executable Portable MSB Hardware Diagnostic Tool
echo  MSB Computer & Network Solutions - Muh. Sattar Barakati
echo =====================================================================
echo.

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Mengompilasi binary mandiri (Single-file Portable Executable)...
pyinstaller --noconfirm --onefile --console ^
  --name "HardwareDiagnosticTitan" ^
  --hidden-import "wmi" ^
  --hidden-import "win32timezone" ^
  --hidden-import "psutil" ^
  --hidden-import "rich" ^
  hardware_diagnostic.py

echo.
echo =====================================================================
echo  Kompilasi Selesai! File executable tersedia di folder: dist/
echo =====================================================================
pause
