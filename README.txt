SCORM / IMSCC to PDF
====================

Rebuilds a course from a SCORM or IMS Common Cartridge package (.imscc, .zip)
as one PDF, in the teaching order of the package manifest. Items that cannot be
turned into text (videos, attached files, dynamic JavaScript content, missing
images) are listed in an "Extraction report" at the end of the PDF and in the
app window.

USING THE APP
1. Open SCORM2PDF.
2. Click Browse and choose the .imscc or .zip file.
3. Click Convert to PDF. Use Open PDF when it finishes.

FIRST LAUNCH WARNINGS (the app is not code signed)
Windows: SmartScreen may say "Windows protected your PC". Click More info, then Run anyway.
macOS: Control click (right click) the app, choose Open, then confirm Open.
       If macOS still blocks it: System Settings, Privacy and Security, Open Anyway.

BUILDING THE APP (developers)
Windows: run build_windows.bat on a Windows PC. Result: dist\SCORM2PDF.exe
macOS:   run ./build_macos.sh on a Mac. Result: dist/SCORM2PDF.app
Both:    push this folder to a GitHub repository and run the "Build apps" workflow
         (Actions tab). Download the apps from the run artifacts.
PyInstaller cannot build a Mac app on Windows or the reverse, so each system
needs its own build.

Run from source (needs Python with Tk):
  pip install reportlab beautifulsoup4 pillow
  python scorm2pdf_gui.py

The bundled fonts in fonts/ are DejaVu fonts (free license, see DEJAVU_LICENSE.txt).
