@echo off
REM ==== Genera dist\SGD_Archivo_Municipal.exe ====
cd /d "%~dp0"
python -m pip install -r requirements.txt
pyinstaller --noconfirm --onefile --windowed ^
  --name "SGD_Archivo_Municipal" ^
  --icon "static\img\logo_archivo.ico" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --hidden-import pythoncom --hidden-import pywintypes --hidden-import win32com.client ^
  --collect-data reportlab ^
  app.py
echo.
echo Ejecutable generado en: dist\SGD_Archivo_Municipal.exe
pause
