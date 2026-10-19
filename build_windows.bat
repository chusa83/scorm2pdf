@echo off
REM Run this on a Windows PC with Python 3.10 or newer installed.
python -m pip install pyinstaller reportlab beautifulsoup4 pillow
pyinstaller --onefile --windowed --name SCORM2PDF --add-data "fonts;fonts" scorm2pdf_gui.py
echo.
echo Done. Your app is dist\SCORM2PDF.exe
pause
