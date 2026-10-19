SCORM / IMSCC to PDF
====================

Rebuilds a course from a SCORM or IMS Common Cartridge package (.imscc, .zip)
as one PDF, in the teaching order of the package manifest.

Images that live on the web (public addresses) are downloaded and embedded.
YouTube and Vimeo videos, and other embedded content such as Google Slides,
appear as clickable links in the text, in the same place they had in the course.
The video itself is not included.

Items that cannot be turned into text (video files stored inside the package,
attached files, dynamic JavaScript content, images that need a login or are no
longer online) are listed in an "Extraction report" at the end of the PDF and
in the app window.

USING THE APP
1. Open SCORM2PDF.
2. Click Browse and choose the .imscc or .zip file.
3. Keep "Download images that live on the web" ticked to embed online images.
   It needs internet and makes the conversion slower. Untick it to work offline.
4. Click Convert to PDF. Use Open PDF when it finishes.

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
  pip install reportlab beautifulsoup4 pillow certifi
  python scorm2pdf_gui.py

The bundled fonts in fonts/ are DejaVu fonts (free license, see DEJAVU_LICENSE.txt).
