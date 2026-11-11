"""Self-check for SVG and CSS background images: python test_images.py"""
import io
import os
import tempfile
import zipfile

from PIL import Image as PILImage
from reportlab.graphics.shapes import Drawing
from reportlab.platypus import Image

import scorm2pdf_gui as app


def png(size):
    out = io.BytesIO()
    PILImage.new("RGB", (size, size), "blue").save(out, "PNG")
    return out.getvalue()


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100"/></svg>'
PAGE = """<html><head>
<link rel="stylesheet" href="css/site.css">
<style>.card { background: #fff url('img/card.png') no-repeat; } .card:hover { background-image: url(img/hover.png); }</style>
</head><body style="background-image: url(img/page.png)">
<img src="img/logo.svg" alt="logo">
<div class="banner">Banner</div>
<div class="card">One</div><div class="card">Two</div>
<span style="background-image:url(img/icon.png)">icon</span>
<p style="background: url(&quot;img/inline.png&quot;)">Inline</p>
</body></html>"""
FILES = {
    "imsmanifest.xml": b"""<manifest><organizations default="o"><organization identifier="o">
<item identifierref="r"><title>Page</title></item></organization></organizations>
<resources><resource identifier="r" href="page.html"/></resources></manifest>""",
    "page.html": PAGE.encode(),
    "css/site.css": b"/* url(img/no.png) */ .banner { background-image: url(../img/banner.png); }",
    "img/logo.svg": SVG,
    "img/banner.png": png(100), "img/card.png": png(100), "img/inline.png": png(100),
    "img/page.png": png(100), "img/hover.png": png(100), "img/icon.png": png(16),
}

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # build() leaves the zip open
    path = os.path.join(tmp, "course.zip")
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in FILES.items():
            zf.writestr(name, data)
    pkg = app.Package(path)
    pkg.fetcher.enabled = False
    styles = app.make_styles("Helvetica", "Helvetica-Bold", "Courier")
    report = []
    flows, _, _ = app.render_html(pkg, PAGE, "", styles, "Courier", report, "Page", 400)
    drawings = [f for f in flows if isinstance(f, Drawing)]
    images = [f for f in flows if isinstance(f, Image)]
    assert len(drawings) == 1, drawings  # logo.svg
    # banner (linked css), card once (not twice, not :hover), inline; not body or 16 px icon
    assert len(images) == 3, images
    assert not report, report
    app.build(path, os.path.join(tmp, "out.pdf"), log=lambda *a: None, online=False)
print("ok")
