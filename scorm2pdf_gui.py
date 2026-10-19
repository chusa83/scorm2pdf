#!/usr/bin/env python3
"""
SCORM2PDF: rebuilds a course from a SCORM or IMS Common Cartridge package
(.imscc, .zip) as a single PDF, in the real teaching order of the manifest.

Run it directly (python scorm2pdf_gui.py) or build a double click app with
PyInstaller. See README.txt.
"""
import base64
import html
import io
import os
import posixpath
import queue
import re
import subprocess
import sys
import textwrap
import threading
import traceback
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import unquote, unquote_to_bytes
from xml.sax.saxutils import escape

from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, HRFlowable, Image, ListFlowable,
                                ListItem, PageBreak, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

APP_TITLE = "SCORM / IMSCC to PDF"
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
FILEBASE_RE = re.compile(r"\$IMS[-_]CC[-_]FILEBASE\$", re.I)
HTML_EXT = {".html", ".htm", ".xhtml"}
ASSET_EXT = {".xml", ".css", ".js", ".json", ".png", ".jpg", ".jpeg", ".gif",
             ".svg", ".webp", ".ico", ".bmp", ".woff", ".woff2", ".ttf", ".eot",
             ".map", ".xsd", ".dtd", ".swf"}

SKIP = {"script", "style", "noscript", "head", "title", "meta", "link",
        "template", "input", "button", "select", "textarea", "option"}
MEDIA = {"iframe", "video", "audio", "embed", "object"}
INLINE = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u", "ins": "u",
          "sup": "super", "sub": "sub", "s": "strike", "del": "strike",
          "strike": "strike"}
MONOTAGS = {"code", "kbd", "tt", "samp"}
HEADS = {"h1": "ch1", "h2": "ch1", "h3": "ch2", "h4": "ch3", "h5": "ch3", "h6": "ch3"}
BLOCK = {"p", "div", "section", "article", "header", "footer", "main", "aside",
         "nav", "figure", "figcaption", "details", "summary", "dl", "dd", "tr",
         "td", "th", "tbody", "thead", "tfoot", "caption", "address", "fieldset",
         "legend", "body", "html", "center", "form"}
TAG_RE = re.compile(r"<(/?)(b|i|u|super|sub|strike|font|a)\b[^>]*>")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def resource_dir(name):
    """Folder next to the script, or inside the PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def balance(markup):
    """Closes or drops unbalanced inline tags so Paragraph does not fail."""
    stack, out, pos = [], [], 0
    for m in TAG_RE.finditer(markup):
        out.append(markup[pos:m.start()])
        pos = m.end()
        closing, name = m.group(1), m.group(2)
        if not closing:
            stack.append(name)
            out.append(m.group(0))
        elif name in stack:
            while stack:
                top = stack.pop()
                out.append("</%s>" % top)
                if top == name:
                    break
    out.append(markup[pos:])
    while stack:
        out.append("</%s>" % stack.pop())
    return "".join(out)


# ---------------------------------------------------------------- fonts and styles

_FONTS = None


def setup_fonts():
    """Bundled DejaVu first (works everywhere), then system fonts, then Helvetica."""
    global _FONTS
    if _FONTS:
        return _FONTS
    mac = "/System/Library/Fonts/Supplemental"
    win = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    candidates = [
        (resource_dir("fonts"),
         ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf",
          "DejaVuSans-BoldOblique.ttf"), "DejaVuSansMono.ttf"),
        (win, ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"), "consola.ttf"),
        (mac, ("Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf"),
         "Courier New.ttf"),
    ]
    for folder, files, mono in candidates:
        paths = [os.path.join(folder, f) for f in files]
        if not all(os.path.exists(p) for p in paths):
            continue
        try:
            names = ("AppRegular", "AppBold", "AppItalic", "AppBoldItalic")
            for name, path in zip(names, paths):
                pdfmetrics.registerFont(TTFont(name, path))
            pdfmetrics.registerFontFamily("AppRegular", normal="AppRegular", bold="AppBold",
                                          italic="AppItalic", boldItalic="AppBoldItalic")
            mono_path = os.path.join(folder, mono)
            if os.path.exists(mono_path):
                pdfmetrics.registerFont(TTFont("AppMono", mono_path))
                _FONTS = ("AppRegular", "AppBold", "AppMono")
            else:
                _FONTS = ("AppRegular", "AppBold", "Courier")
            return _FONTS
        except Exception:
            continue
    _FONTS = ("Helvetica", "Helvetica-Bold", "Courier")
    return _FONTS


def make_styles(regular, bold, mono):
    grey = colors.HexColor("#666666")
    body = ParagraphStyle("body", fontName=regular, fontSize=10, leading=14, spaceAfter=6)
    return {
        "body": body,
        "quote": ParagraphStyle("quote", parent=body, leftIndent=18, textColor=grey),
        "ch1": ParagraphStyle("ch1", parent=body, fontName=bold, fontSize=12, leading=15,
                              spaceBefore=8, spaceAfter=4),
        "ch2": ParagraphStyle("ch2", parent=body, fontName=bold, fontSize=11, leading=14,
                              spaceBefore=6, spaceAfter=3),
        "ch3": ParagraphStyle("ch3", parent=body, fontName=bold, fontSize=10, leading=13,
                              spaceBefore=4, spaceAfter=2),
        "H0": ParagraphStyle("H0", fontName=bold, fontSize=20, leading=24, spaceAfter=10,
                             textColor=colors.HexColor("#1f3a5f")),
        "H1": ParagraphStyle("H1", fontName=bold, fontSize=15, leading=19, spaceBefore=14,
                             spaceAfter=6, textColor=colors.HexColor("#1f3a5f")),
        "H2": ParagraphStyle("H2", fontName=bold, fontSize=12.5, leading=16, spaceBefore=10,
                             spaceAfter=4, textColor=colors.HexColor("#333333")),
        "note": ParagraphStyle("note", parent=body, fontSize=8.5, leading=11, textColor=grey),
        "mono": ParagraphStyle("mono", fontName=mono, fontSize=8, leading=10,
                               backColor=colors.HexColor("#f3f3f3"), leftIndent=4,
                               spaceAfter=6),
    }


# ---------------------------------------------------------------- package

class Package:
    def __init__(self, path):
        if not zipfile.is_zipfile(path):
            raise ValueError("This file is not a valid zip. A .imscc or SCORM package is a zip archive.")
        self.zf = zipfile.ZipFile(path)
        names = [n for n in self.zf.namelist() if not n.endswith("/")]
        manifest = [n for n in names if posixpath.basename(n).lower() == "imsmanifest.xml"]
        if not manifest:
            raise ValueError("imsmanifest.xml was not found inside the package.")
        manifest.sort(key=lambda n: n.count("/"))
        self.root_dir = posixpath.dirname(manifest[0])
        prefix = self.root_dir + "/" if self.root_dir else ""
        self.files = {}
        for n in names:
            if n.startswith(prefix):
                self.files[n[len(prefix):].lower()] = n
        self.manifest = ET.fromstring(self.zf.read(manifest[0]))
        self.resources = {}
        for r in self.manifest.iter():
            if local(r.tag) != "resource":
                continue
            base = r.get(XML_BASE, "")
            href = r.get("href")
            files = [posixpath.join(base, f.get("href")) for f in r
                     if local(f.tag) == "file" and f.get("href")]
            self.resources[r.get("identifier")] = {
                "href": posixpath.join(base, href) if href else None,
                "type": r.get("type"),
                "files": files,
            }

    def resolve(self, base_dir, src):
        m = FILEBASE_RE.search(src)
        path = "web_resources" + src[m.end():] if m else src
        path = unquote(re.split(r"[?#]", path)[0])
        if m:
            cand = path
        elif path.startswith("/"):
            cand = path.lstrip("/")
        else:
            cand = posixpath.join(base_dir, path)
        return self.files.get(posixpath.normpath(cand).lower())

    def read(self, full):
        return self.zf.read(full)

    def main_file(self, res):
        if res["href"]:
            return re.split(r"[?#]", res["href"])[0]
        for f in res["files"]:
            if posixpath.splitext(f)[1].lower() in HTML_EXT:
                return f
        return res["files"][0] if res["files"] else None

    def course_title(self):
        for el in self.manifest.iter():
            if local(el.tag) == "organization":
                for c in el:
                    if local(c.tag) == "title":
                        t = "".join(c.itertext()).strip()
                        if t:
                            return t
        return ""

    def items(self):
        """Flat list of items in manifest order."""
        orgs = [e for e in self.manifest.iter() if local(e.tag) == "organization"]
        out = []
        if orgs:
            default = None
            for e in self.manifest.iter():
                if local(e.tag) == "organizations":
                    default = e.get("default")
            org = next((o for o in orgs if o.get("identifier") == default), orgs[0])
            self._walk(org, 0, out)
        else:
            for ident in self.resources:
                out.append({"depth": 0, "title": ident, "ref": ident, "desc": "", "hidden": False})
        return out

    def _walk(self, parent, depth, out):
        for it in parent:
            if local(it.tag) != "item":
                continue
            title = ""
            for c in it:
                if local(c.tag) == "title":
                    title = "".join(c.itertext()).strip()
            ref = it.get("identifierref")
            kids = [c for c in it if local(c.tag) == "item"]
            if not title and not ref and kids:
                self._walk(it, depth, out)
                continue
            out.append({"depth": depth, "title": title or "(untitled)", "ref": ref,
                        "desc": self._desc(it), "hidden": it.get("isvisible") == "false"})
            self._walk(it, depth + 1, out)

    @staticmethod
    def _desc(item):
        for child in item:
            if local(child.tag) in ("item", "title"):
                continue
            for el in child.iter():
                if local(el.tag) == "description":
                    text = "".join(el.itertext()).strip()
                    if text:
                        return text
        return ""


# ---------------------------------------------------------------- HTML to flowables

class Renderer:
    def __init__(self, pkg, base_dir, styles, mono, report, where, maxw):
        self.pkg, self.base_dir, self.S, self.mono = pkg, base_dir, styles, mono
        self.report, self.where, self.maxw = report, where, maxw
        self.flows, self.buf, self.stack, self.chars = [], [], ["body"], 0

    def note(self, kind, detail):
        self.report.append((self.where, kind, detail))

    def child(self, maxw):
        return Renderer(self.pkg, self.base_dir, self.S, self.mono, self.report,
                        self.where, maxw)

    def flush(self):
        raw = "".join(self.buf).strip()
        self.buf = []
        plain = re.sub(r"<[^>]+>", "", raw).strip()
        if not plain:
            return
        self.chars += len(plain)
        style = self.S[self.stack[-1]]
        try:
            self.flows.append(Paragraph(balance(raw), style))
        except Exception:
            self.flows.append(Paragraph(escape(html.unescape(plain)), style))

    def render(self, node):
        for c in node.children:
            if type(c) is NavigableString:
                t = re.sub(r"\s+", " ", str(c).replace("\xa0", " "))
                if t.strip() or self.buf:
                    self.buf.append(escape(t))
            elif isinstance(c, Tag):
                self.tag(c)

    def tag(self, el):
        n = el.name
        if n in SKIP:
            return
        if n == "br":
            self.buf.append("<br/>")
        elif n == "img":
            self.image(el)
        elif n in MEDIA:
            self.media(el)
        elif n == "a":
            self.link(el)
        elif n in INLINE:
            t = INLINE[n]
            self.buf.append("<%s>" % t)
            self.render(el)
            self.buf.append("</%s>" % t)
        elif n in MONOTAGS:
            self.buf.append('<font face="%s">' % self.mono)
            self.render(el)
            self.buf.append("</font>")
        elif n in HEADS or n == "blockquote":
            self.flush()
            self.stack.append(HEADS.get(n, "quote"))
            self.render(el)
            self.flush()
            self.stack.pop()
        elif n == "pre":
            self.pre(el)
        elif n in ("ul", "ol"):
            self.lst(el)
        elif n == "table":
            self.table(el)
        elif n == "hr":
            self.flush()
            self.flows.append(HRFlowable(width="100%", thickness=0.5,
                                         color=colors.HexColor("#bbbbbb")))
        elif n == "li":
            self.flush()
            self.buf.append("• ")
            self.render(el)
            self.flush()
        elif n == "dt":
            self.flush()
            self.buf.append("<b>")
            self.render(el)
            self.buf.append("</b>")
            self.flush()
        elif n in BLOCK:
            self.flush()
            self.render(el)
            self.flush()
        else:
            self.render(el)

    def link(self, a):
        href = (a.get("href") or "").strip()
        if re.match(r"(https?://|mailto:)", href, re.I) and not FILEBASE_RE.search(href):
            self.buf.append('<a href="%s" color="blue">' % escape(href, {'"': "&quot;"}))
            self.render(a)
            self.buf.append("</a>")
            return
        if href and not href.startswith("#"):
            ext = posixpath.splitext(re.split(r"[?#]", href)[0])[1].lower()
            is_local = bool(FILEBASE_RE.search(href)) or (
                not re.match(r"[a-z][a-z0-9+.\-]*:", href, re.I)
                and self.pkg.resolve(self.base_dir, href))
            if is_local and ext not in HTML_EXT:
                self.note("Linked file, not included",
                          "%s (%s)" % (a.get_text(strip=True) or href, href))
        self.render(a)

    def media(self, el):
        src = el.get("src") or el.get("data") or ""
        if not src:
            s = el.find("source")
            src = (s.get("src") if s else "") or ""
        self.flush()
        label = "[Embedded %s%s]" % (el.name, ": " + src if src else "")
        self.flows.append(Paragraph(escape(label), self.S["note"]))
        self.note("Embedded content, not included", "%s %s" % (el.name, src))

    def load(self, src):
        if src.startswith("data:"):
            m = re.match(r"data:[^,]*?(;base64)?,(.*)$", src, re.S)
            if not m:
                return None
            try:
                return base64.b64decode(m.group(2)) if m.group(1) else unquote_to_bytes(m.group(2))
            except Exception:
                return None
        if re.match(r"[a-z][a-z0-9+.\-]*:", src, re.I):
            return None
        full = self.pkg.resolve(self.base_dir, src)
        return self.pkg.read(full) if full else None

    def image(self, el):
        src = (el.get("src") or "").strip()
        alt = (el.get("alt") or "").strip()
        data = self.load(src)
        if data is None:
            remote = re.match(r"https?:", src, re.I)
            self.note("Remote image, not included" if remote else "Image not found",
                      src[:120] or "(no src)")
            if alt:
                self.buf.append(escape("[Image: %s]" % alt))
            return
        try:
            im = PILImage.open(io.BytesIO(data))
            im.load()
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = PILImage.new("RGB", im.size, "white")
                bg.paste(im, mask=im.split()[3])
                im = bg
            else:
                im = im.convert("RGB")
            w, h = im.size
            if w < 4 or h < 4:
                return
            out = io.BytesIO()
            im.save(out, "JPEG", quality=90)
            out.seek(0)
        except Exception:
            self.note("Unsupported image format", src[:120])
            if alt:
                self.buf.append(escape("[Image: %s]" % alt))
            return
        wpt, hpt = w * 0.75, h * 0.75
        scale = min(1.0, self.maxw / wpt, (20 * cm) / hpt)
        self.flush()
        self.flows.append(Image(out, width=wpt * scale, height=hpt * scale))
        self.flows.append(Spacer(1, 4))
        self.chars += 1

    def pre(self, el):
        self.flush()
        text = el.get_text().expandtabs(4).strip("\n")
        lines = []
        for line in text.split("\n"):
            lines += textwrap.wrap(line.rstrip(), 90, drop_whitespace=False,
                                   replace_whitespace=False) or [""]
        self.chars += len(text)
        if text.strip():
            self.flows.append(Preformatted("\n".join(lines), self.S["mono"]))

    def lst(self, el):
        self.flush()
        items = []
        for li in el.find_all("li", recursive=False):
            sub = self.child(self.maxw - 18)
            sub.render(li)
            sub.flush()
            self.chars += sub.chars
            if sub.flows:
                items.append(ListItem(sub.flows))
        if not items:
            return
        font = self.S["body"].fontName
        if el.name == "ol":
            lf = ListFlowable(items, bulletType="1", bulletFormat="%s.", leftIndent=18,
                              bulletFontName=font)
        else:
            lf = ListFlowable(items, bulletType="bullet", start="•", leftIndent=18,
                              bulletFontName=font)
        self.flows.append(lf)

    def table(self, el):
        self.flush()
        rows = []
        for tr in el.find_all("tr"):
            if tr.find_parent("table") is not el:
                continue
            cells = tr.find_all(["td", "th"], recursive=False)
            if cells:
                rows.append(cells)
        if not rows:
            return
        ncols = max(len(r) for r in rows)
        colw = self.maxw / ncols
        data = []
        for cells in rows:
            row = []
            for c in cells:
                sub = self.child(colw - 12)
                if c.name == "th":
                    sub.buf.append("<b>")
                sub.render(c)
                if c.name == "th":
                    sub.buf.append("</b>")
                sub.flush()
                self.chars += sub.chars
                row.append(sub.flows or "")
            row += [""] * (ncols - len(row))
            data.append(row)
        style = TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
        try:
            t = Table(data, colWidths=[colw] * ncols, splitInRow=1)
        except TypeError:
            t = Table(data, colWidths=[colw] * ncols)
        t.setStyle(style)
        self.flows.append(t)
        self.flows.append(Spacer(1, 6))


def render_html(pkg, content, base_dir, styles, mono, report, where, maxw):
    soup = BeautifulSoup(content, "html.parser")
    dynamic = bool(soup.find("script"))
    r = Renderer(pkg, base_dir, styles, mono, report, where, maxw)
    r.render(soup.body or soup)
    r.flush()
    return r.flows, r.chars, dynamic


def xml_to_html(data):
    """Generic reading of XML resources (forums, web links, quizzes)."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return ""
    parts = []
    for el in root.iter():
        name = local(el.tag)
        if name == "title":
            continue
        text = (el.text or "").strip()
        if text and (" " in text or name in ("text", "description", "url")):
            parts.append(text if "<" in text else "<p>%s</p>" % escape(text))
        if name in ("url", "link", "weblink") and el.get("href"):
            parts.append("<p>Link: %s</p>" % escape(el.get("href")))
    return "".join(parts)


# ---------------------------------------------------------------- document

class Doc(SimpleDocTemplate):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._last_level = -1
        self._n = 0

    def afterFlowable(self, fl):
        bm = getattr(fl, "_bm", None)
        if not bm:
            return
        title, level = bm
        level = min(level, self._last_level + 1)
        key = "bm%d" % self._n
        self._n += 1
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(title, key, level, 0)
        self._last_level = level


def heading(text, level, styles):
    level = min(level, 2)
    p = Paragraph(escape(text), styles["H%d" % level])
    p._bm = (text, level)
    return p


def render_resource(pkg, it, styles, mono, report, maxw):
    where = it["title"]
    res = pkg.resources.get(it["ref"])
    if res is None:
        report.append((where, "Resource not found in manifest", str(it["ref"])))
        return []
    main = pkg.main_file(res)
    if not main:
        report.append((where, "Resource has no main file", str(it["ref"])))
        return []
    full = pkg.resolve("", main)
    if not full:
        report.append((where, "Declared file is missing from the package", main))
        return []
    ext = posixpath.splitext(main)[1].lower()
    base_dir = posixpath.dirname(main)
    data = pkg.read(full)
    flows = []
    if ext in HTML_EXT:
        before = len(report)
        flows, chars, dynamic = render_html(pkg, data, base_dir, styles, mono, report, where, maxw)
        if chars < 40 and dynamic:
            report.append((where, "Dynamic content (JavaScript) with no static text", main))
        elif chars == 0 and len(report) == before:
            report.append((where, "Page has no text", main))
    elif ext == ".xml":
        content = xml_to_html(data)
        if content:
            flows, _, _ = render_html(pkg, content, base_dir, styles, mono, report, where, maxw)
            report.append((where, "XML read generically, please review", main))
        else:
            report.append((where, "XML with no readable text", main))
    elif ext in (".txt", ".md", ".csv"):
        text = data.decode("utf-8", "replace")
        flows = [Paragraph(escape(p).replace("\n", "<br/>"), styles["body"])
                 for p in text.split("\n\n") if p.strip()]
    else:
        report.append((where, "File type not readable in PDF", main))
        flows = [Paragraph(escape("[File: %s, not included]" % posixpath.basename(main)),
                           styles["note"])]
    main_norm = posixpath.normpath(main).lower()
    extra_html = 0
    for f in res["files"]:
        if posixpath.normpath(f).lower() == main_norm:
            continue
        e = posixpath.splitext(f)[1].lower()
        if e in HTML_EXT:
            extra_html += 1
        elif e not in ASSET_EXT:
            report.append((where, "Attached file, not included", f))
    if extra_html:
        report.append((where, "Other HTML pages in this resource, not rendered", str(extra_html)))
    return flows


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(A4[0] / 2, 1 * cm, str(doc.page))
    canvas.restoreState()


def build(src, out, log=print):
    """Converts the package at src into a PDF at out. Returns a summary dict."""
    log("Reading package: %s" % src)
    pkg = Package(src)
    regular, bold, mono = setup_fonts()
    styles = make_styles(regular, bold, mono)
    maxw = A4[0] - 4 * cm
    report = []
    title = pkg.course_title() or os.path.splitext(os.path.basename(src))[0]
    story = [Paragraph(escape(title), styles["H0"]),
             Paragraph("Contents extracted in the order of the package manifest.",
                       styles["note"]),
             Spacer(1, 12)]
    items = pkg.items()
    log("Items found in manifest: %d" % len(items))
    started = False
    rendered = 0
    for n, it in enumerate(items, 1):
        log("[%d/%d] %s" % (n, len(items), it["title"]))
        if it["depth"] == 0 and started:
            story.append(PageBreak())
        elif it["depth"] > 0:
            story.append(CondPageBreak(4 * cm))
        started = True
        label = it["title"] + (" (hidden from students)" if it["hidden"] else "")
        story.append(heading(label, it["depth"], styles))
        if it["desc"]:
            flows, _, _ = render_html(pkg, it["desc"], "", styles, mono, report,
                                      it["title"], maxw)
            story += flows
        if it["ref"]:
            try:
                story += render_resource(pkg, it, styles, mono, report, maxw)
                rendered += 1
            except Exception as e:
                report.append((it["title"], "Error reading resource", repr(e)))
    story.append(PageBreak())
    story.append(heading("Extraction report", 0, styles))
    if not report:
        story.append(Paragraph("No issues found.", styles["body"]))
    last = None
    for where, kind, detail in report:
        if where != last:
            story.append(Paragraph("<b>%s</b>" % escape(where), styles["body"]))
            last = where
        line = escape(kind) + (": " + escape(detail) if detail else "")
        story.append(Paragraph("• " + line, styles["note"]))
    log("Building PDF...")
    doc = Doc(out, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
              topMargin=2 * cm, bottomMargin=2 * cm, title=title)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return {"items": len(items), "rendered": rendered, "report": report, "out": out}


# ---------------------------------------------------------------- GUI

def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(APP_TITLE)
            self.geometry("760x560")
            self.minsize(620, 440)
            self.src = tk.StringVar()
            self.out = tk.StringVar()
            self.q = queue.Queue()
            self.last_pdf = None
            self.busy = False

            frame = ttk.Frame(self, padding=14)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(1, weight=1)
            frame.rowconfigure(4, weight=1)

            ttk.Label(frame, text="Course package (.imscc or .zip)").grid(
                row=0, column=0, columnspan=3, sticky="w")
            ttk.Entry(frame, textvariable=self.src).grid(
                row=1, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 10))
            ttk.Button(frame, text="Browse...", command=self.pick_src).grid(row=1, column=2)

            ttk.Label(frame, text="Save PDF as").grid(row=2, column=0, columnspan=3, sticky="w")
            ttk.Entry(frame, textvariable=self.out).grid(
                row=3, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 10))
            ttk.Button(frame, text="Browse...", command=self.pick_out).grid(row=3, column=2)

            self.log = tk.Text(frame, height=12, wrap="word", state="disabled")
            self.log.grid(row=4, column=0, columnspan=2, sticky="nsew")
            sb = ttk.Scrollbar(frame, command=self.log.yview)
            sb.grid(row=4, column=2, sticky="ns")
            self.log.configure(yscrollcommand=sb.set)

            bar = ttk.Frame(frame)
            bar.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 0))
            bar.columnconfigure(2, weight=1)
            self.btn = ttk.Button(bar, text="Convert to PDF", command=self.convert)
            self.btn.grid(row=0, column=0)
            self.open_btn = ttk.Button(bar, text="Open PDF", command=self.open_pdf,
                                       state="disabled")
            self.open_btn.grid(row=0, column=1, padx=8)
            self.progress = ttk.Progressbar(bar, mode="indeterminate")
            self.progress.grid(row=0, column=2, sticky="ew", padx=(8, 0))

            self.write("Choose a course package, then click Convert to PDF.\n")
            self.after(100, self.poll)

        def write(self, text):
            self.log.configure(state="normal")
            self.log.insert("end", text)
            self.log.see("end")
            self.log.configure(state="disabled")

        def pick_src(self):
            path = filedialog.askopenfilename(
                title="Choose the course package",
                filetypes=[("Course packages", "*.imscc *.zip"), ("All files", "*.*")])
            if path:
                self.src.set(path)
                self.out.set(os.path.splitext(path)[0] + ".pdf")

        def pick_out(self):
            path = filedialog.asksaveasfilename(
                title="Save PDF as", defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf")], initialfile=os.path.basename(self.out.get()) or "course.pdf")
            if path:
                self.out.set(path)

        def convert(self):
            if self.busy:
                return
            src, out = self.src.get().strip(), self.out.get().strip()
            if not src or not os.path.isfile(src):
                messagebox.showerror(APP_TITLE, "Please choose a course package first.")
                return
            if not out:
                out = os.path.splitext(src)[0] + ".pdf"
                self.out.set(out)
            self.busy = True
            self.last_pdf = None
            self.btn.configure(state="disabled")
            self.open_btn.configure(state="disabled")
            self.progress.start(12)
            self.write("\n--- Starting conversion ---\n")
            threading.Thread(target=self.worker, args=(src, out), daemon=True).start()

        def worker(self, src, out):
            try:
                result = build(src, out, log=lambda m: self.q.put(("log", m)))
                self.q.put(("done", result))
            except Exception as e:
                detail = str(e) if isinstance(e, ValueError) else traceback.format_exc()
                self.q.put(("error", detail))

        def poll(self):
            try:
                while True:
                    kind, payload = self.q.get_nowait()
                    if kind == "log":
                        self.write(payload + "\n")
                    elif kind == "done":
                        self.finish(payload)
                    else:
                        self.fail(payload)
            except queue.Empty:
                pass
            self.after(100, self.poll)

        def finish(self, result):
            self.progress.stop()
            self.btn.configure(state="normal")
            self.busy = False
            self.last_pdf = result["out"]
            self.open_btn.configure(state="normal")
            report = result["report"]
            self.write("\nDone. %d items in the manifest, %d resources rendered.\n"
                       % (result["items"], result["rendered"]))
            self.write("PDF saved to: %s\n" % result["out"])
            if report:
                self.write("\n%d item(s) need your attention (also listed at the end of the PDF):\n"
                           % len(report))
                for where, kind, detail in report:
                    self.write("  • %s: %s%s\n" % (where, kind, (" (" + detail + ")") if detail else ""))
            else:
                self.write("No issues found.\n")

        def fail(self, detail):
            self.progress.stop()
            self.btn.configure(state="normal")
            self.busy = False
            self.write("\nConversion failed:\n%s\n" % detail)
            messagebox.showerror(APP_TITLE, "Conversion failed. See the log for details.")

        def open_pdf(self):
            path = self.last_pdf
            if not path or not os.path.exists(path):
                return
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)

    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()


if __name__ == "__main__":
    run_gui()
