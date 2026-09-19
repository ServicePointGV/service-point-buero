@echo off
cd /d "%~dp0"
echo Installiere benoetigte Python-Komponenten...
py -m pip install pypdf reportlab pillow pytesseract pywin32 2>nul || python -m pip install pypdf reportlab pillow pytesseract pywin32
where tesseract >nul 2>nul
if errorlevel 1 (
  echo Tesseract OCR wird installiert, falls winget verfuegbar ist...
  winget install --id UB-Mannheim.TesseractOCR -e --accept-package-agreements --accept-source-agreements
)
echo.
echo Installation abgeschlossen. Falls Tesseract gerade neu installiert wurde, SERVICE POINT BÜRO danach neu starten.
pause
