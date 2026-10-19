#!/bin/bash
# Run this on a Mac with Python 3.10 or newer (from python.org, so Tk is included).
set -e
python3 -m pip install pyinstaller reportlab beautifulsoup4 pillow certifi
python3 -m PyInstaller --windowed --name SCORM2PDF --add-data "fonts:fonts" scorm2pdf_gui.py
ditto -c -k --keepParent dist/SCORM2PDF.app dist/SCORM2PDF_macos.zip
echo "Done. Your app is dist/SCORM2PDF.app and dist/SCORM2PDF_macos.zip"
