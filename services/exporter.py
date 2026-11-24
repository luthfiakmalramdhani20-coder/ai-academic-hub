"""Ekspor hasil arsip menjadi 1 file Microsoft Word (.docx) yang rapi."""
import io
import re

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

FONT = "Calibri"
MONO = "Consolas"
ACCENT = RGBColor(0x31, 0x2E, 0x81)   # indigo tua
MUTED = RGBColor(0x64, 0x74, 0x8B)

INLINE_RE = re.compile(
    r"(\*\*\*(?P<bi>.+?)\*\*\*"
    r"|\*\*(?P<b>.+?)\*\*"
    r"|__(?P<b2>.+?)__"
    r"|(?<![\w*])\*(?P<i>[^*\n]+?)\*(?!\w)"
    r"|(?<![\w_])_(?P<i2>[^_\n]+?)_(?![\w])"
    r"|`(?P<c>[^`]+)`"
    r"|\$\$(?P<m2>.+?)\$\$"
    r"|\$(?P<m>[^$\n]+?)\$"
    r"|\[(?P<lt>[^\]]+)\]\((?P<lu>[^)]+)\))"
)
XML_BAD_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


# ---------------------------------------------------------------- helpers
def _shade(cell, hex_fill: str):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _left_border(paragraph, color="6366F1"):
    pPr = paragraph._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    for k, v in (("val", "single"), ("sz", "18"), ("space", "8"), ("color", color)):
        left.set(qn(f"w:{k}"), v)
    bdr.append(left)
    pPr.append(bdr)


def _bottom_border(paragraph, color="CBD5E1"):
    pPr = paragraph._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    for k, v in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", color)):
        b.set(qn(f"w:{k}"), v)
    bdr.append(b)
    pPr.append(bdr)


def _clean_latex(s: str) -> str:
    s = re.sub(r"\\(?:text|mathrm|mathbf|operatorname)\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1) / (\2)", s)
    for a, b in ((r"\times", "×"), (r"\cdot", "·"), (r"\sum", "Σ"), (r"\bar", ""), (r"\leq", "≤"),
                 (r"\geq", "≥"), (r"\neq", "≠"), (r"\pm", "±"), (r"\sqrt", "√"), (r"\left", ""),
                 (r"\right", ""), (r"\,", " "), (r"\quad", " ")):
        s = s.replace(a, b)
    return s.replace("{", "").replace("}", "").strip()


def add_inline(paragraph, text: str, base_bold=False, size=None, font=None):
    """Tambahkan teks dengan **bold**, *italic*, `code`, $math$ sebagai run Word asli."""
    pos = 0
    text = text.replace("<br>", "\n").replace("<br/>", "\n")
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            _run(paragraph, text[pos:m.start()], bold=base_bold, size=size, font=font)
        g = m.groupdict()
        if g["bi"]:
            _run(paragraph, g["bi"], bold=True, italic=True, size=size, font=font)
        elif g["b"] or g["b2"]:
            add_inline(paragraph, g["b"] or g["b2"], base_bold=True, size=size, font=font)
        elif g["i"] or g["i2"]:
            _run(paragraph, g["i"] or g["i2"], bold=base_bold, italic=True, size=size, font=font)
        elif g["c"]:
            _run(paragraph, g["c"], font=MONO, size=size, color=RGBColor(0xB9, 0x1C, 0x1C))
        elif g["m2"] or g["m"]:
            _run(paragraph, _clean_latex(g["m2"] or g["m"]), italic=True, size=size, font="Cambria Math")
        elif g["lt"]:
            _run(paragraph, f"{g['lt']} ({g['lu']})", bold=base_bold, size=size, font=font)
        pos = m.end()
    if pos < len(text):
        _run(paragraph, text[pos:], bold=base_bold, size=size, font=font)


def _run(paragraph, text, bold=False, italic=False, size=None, font=None, color=None):
    text = XML_BAD_RE.sub("", text or "")
    if not text:
        return
    parts = text.split("\n")
    for idx, part in enumerate(parts):
        r = paragraph.add_run(part)
        r.bold, r.italic = bold or None, italic or None
        if size:
            r.font.size = Pt(size)
        if font:
            r.font.name = font
            r._element.rPr.rFonts.set(qn("w:eastAsia"), font)
        if color:
            r.font.color.rgb = color
        if idx < len(parts) - 1:
            r.add_break()


# ---------------------------------------------------------------- markdown -> docx
def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def _add_table(doc, rows: list[list[str]]):
    ncols = max(len(r) for r in rows)
    table = doc.add_table(rows=0, cols=ncols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for ri, row in enumerate(rows):
        cells = table.add_row().cells
        for ci in range(ncols):
            cell = cells[ci]
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            add_inline(p, row[ci] if ci < len(row) else "", base_bold=(ri == 0), size=10)
            if ri == 0:
                _shade(cell, "E0E7FF")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def markdown_to_docx(doc, md: str, heading_offset: int = 1):
    """Render Markdown ke elemen Word. heading_offset: '#' -> Heading(1+offset-1)..."""
    lines = (md or "").replace("\r\n", "\n").split("\n")
    i, n = 0, len(lines)
    para_buf: list[str] = []
    indents: list[int] = []  # tumpukan indentasi list yang sedang aktif

    def flush_para():
        if para_buf:
            p = doc.add_paragraph()
            add_inline(p, " ".join(s.strip() for s in para_buf))
            para_buf.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped and not re.match(r"^\s*([-*+]|\d+[.)])\s+", line):
            indents.clear()

        if not stripped:
            flush_para()
            i += 1
            continue

        # Code fence
        if stripped.startswith("```"):
            flush_para()
            i += 1
            code = []
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.5)
            _run(p, "\n".join(code), font=MONO, size=9.5)
            continue

        # Block math $$ ... $$
        if stripped.startswith("$$"):
            flush_para()
            body = stripped[2:]
            if body.endswith("$$") and len(body) >= 2:
                body = body[:-2]
            else:
                i += 1
                while i < n and "$$" not in lines[i]:
                    body += " " + lines[i].strip()
                    i += 1
                if i < n:
                    body += " " + lines[i].strip().replace("$$", "")
            i += 1
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _run(p, _clean_latex(body), italic=True, font="Cambria Math", size=12)
            continue

        # Heading
        hm = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", stripped)
        if hm:
            flush_para()
            level = min(len(hm.group(1)) + heading_offset - 1, 4)
            h = doc.add_heading(level=max(level, 1))
            add_inline(h, hm.group(2))
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$", stripped):
            flush_para()
            p = doc.add_paragraph()
            _bottom_border(p)
            i += 1
            continue

        # Table
        if "|" in stripped and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]):
            flush_para()
            rows = [_split_row(stripped)]
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            _add_table(doc, rows)
            continue

        # Blockquote
        if stripped.startswith(">"):
            flush_para()
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            p = doc.add_paragraph(style="Quote")
            p.paragraph_format.left_indent = Cm(0.6)
            _left_border(p)
            add_inline(p, "\n".join(q for q in quote))
            continue

        # Lists
        lm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if lm:
            flush_para()
            indent = len(lm.group(1).replace("\t", "    "))
            # tingkat bullet dari tumpukan indentasi (aman untuk indent 2 maupun 4 spasi)
            while indents and indent < indents[-1]:
                indents.pop()
            if not indents or indent > indents[-1]:
                indents.append(indent)
            level = min(len(indents) - 1, 2)
            ordered = lm.group(2)[0].isdigit()
            style = "List Bullet" + ("" if level == 0 else f" {level + 1}")
            content = lm.group(3)
            # checkbox
            content = re.sub(r"^\[ \]\s*", "☐ ", re.sub(r"^\[[xX]\]\s*", "☑ ", content))
            i += 1
            # baris lanjutan (indentasi tanpa penanda list)
            while i < n and lines[i].strip() and not re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]) \
                    and lines[i].startswith((" ", "\t")) and not lines[i].strip().startswith((">", "|", "#", "```", "$$")):
                content += " " + lines[i].strip()
                i += 1
            if ordered:
                # nomor asli dipertahankan agar persis seperti tampilan web
                p = doc.add_paragraph()
                pf = p.paragraph_format
                pf.left_indent = Cm(0.9 + 0.75 * level)
                pf.first_line_indent = Cm(-0.6)
                pf.space_after = Pt(3)
                pf.tab_stops.add_tab_stop(pf.left_indent)
                _run(p, lm.group(2).rstrip(".)") + ".\t", bold=True)
            else:
                p = doc.add_paragraph(style=style)
            add_inline(p, content)
            continue

        para_buf.append(stripped)
        i += 1
    flush_para()


# ---------------------------------------------------------------- dokumen
def _setup_styles(doc):
    st = doc.styles
    normal = st["Normal"]
    normal.font.name = FONT
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25
    sizes = {1: 18, 2: 15, 3: 13, 4: 12}
    for lvl, sz in sizes.items():
        h = st[f"Heading {lvl}"]
        h.font.name = FONT
        h.element.rPr.rFonts.set(qn("w:ascii"), FONT)
        h.element.rPr.rFonts.set(qn("w:hAnsi"), FONT)
        h.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        h.font.size = Pt(sz)
        h.font.bold = True
        h.font.color.rgb = ACCENT if lvl <= 2 else RGBColor(0x43, 0x38, 0xCA)
        h.paragraph_format.space_before = Pt(14 if lvl <= 2 else 10)
        h.paragraph_format.space_after = Pt(6)
        h.paragraph_format.keep_with_next = True
    for name in ("List Bullet", "List Bullet 2", "List Bullet 3", "List Number", "List Number 2", "List Number 3"):
        if name in [s.name for s in st]:
            st[name].paragraph_format.space_after = Pt(3)
    q = st["Quote"]
    q.font.italic = False
    q.font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)


def _section_title(doc, roman: str, title: str):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    _run(p, f"BAGIAN {roman}", size=10, color=MUTED, bold=True)
    h = doc.add_paragraph()
    _run(h, title, bold=True, size=20, color=ACCENT)
    h.paragraph_format.space_after = Pt(12)
    _bottom_border(h, "6366F1")


def _page_break(doc):
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def build_docx(data: dict) -> bytes:
    meta = data.get("metadata") or {}
    kategori = data.get("kategori") or meta.get("kategori", "")
    semester = data.get("semester") or meta.get("semester", "")
    matkul = data.get("matkul") or meta.get("matkul", "")
    pertemuan = data.get("pertemuan") or meta.get("pertemuan", "")
    judul = data.get("judul") or " — ".join(x for x in (matkul, pertemuan) if x) or "Laporan Rekaman"
    created = data.get("created_at") or data.get("dibuat", "")
    model = data.get("model", "")
    kuliah = kategori == "Kuliah"

    doc = Document()
    for s in doc.sections:
        s.top_margin = s.bottom_margin = Cm(2.2)
        s.left_margin = s.right_margin = Cm(2.4)
    _setup_styles(doc)

    # ---- Cover
    for _ in range(5):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(p, "LAPORAN CATATAN " + ("PERKULIAHAN" if kuliah else "KEGIATAN"), bold=True, size=12, color=MUTED)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(24)
    _run(p, judul, bold=True, size=28, color=ACCENT)

    rows = [
        ("Kategori", kategori or "-"),
        ("Semester / Periode", semester or "-"),
        ("Mata Kuliah" if kuliah else "Topik / Organisasi", matkul or "-"),
        ("Pertemuan" if kuliah else "Nama Kegiatan", pertemuan or "-"),
        ("Waktu Dibuat", created or "-"),
        ("Model AI", model or "-"),
    ]
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for k, v in rows:
        c = t.add_row().cells
        c[0].width, c[1].width = Cm(5), Cm(10)
        _shade(c[0], "E0E7FF")
        _run(c[0].paragraphs[0], k, bold=True, size=10.5)
        _run(c[1].paragraphs[0], str(v), size=10.5)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(36)
    _run(p, "Dibuat otomatis oleh AI Academic Transkriptor V4", italic=True, size=9, color=MUTED)

    # ---- Bagian I
    _page_break(doc)
    _section_title(doc, "I", "RINGKASAN KONTEKSTUAL")
    markdown_to_docx(doc, data.get("ringkasan", "") or "_(Tidak ada ringkasan)_", heading_offset=1)

    # ---- Bagian II
    _page_break(doc)
    _section_title(doc, "II", "CATATAN KOMPREHENSIF (100%)")
    markdown_to_docx(doc, data.get("catatan", "") or "_(Tidak ada catatan)_", heading_offset=1)

    # ---- Bagian III
    _page_break(doc)
    _section_title(doc, "III", "TRANSKRIP LENGKAP (DENGAN TIMESTAMP)")
    for line in (data.get("transkrip") or "(Transkrip kosong)").splitlines():
        if not line.strip():
            continue
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.1
        m = re.match(r"^(\[\d{1,2}:\d{2}:\d{2}\])\s*(.*)$", line)
        if m:
            _run(p, m.group(1) + "  ", font=MONO, size=9.5, color=ACCENT, bold=True)
            _run(p, m.group(2), font=MONO, size=10)
        else:
            _run(p, line, font=MONO, size=10)

    # ---- Footer nomor halaman
    sec = doc.sections[0]
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(fp, f"{judul}  ·  Halaman ", size=8.5, color=MUTED)
    r = fp.add_run()
    r.font.size = Pt(8.5)
    for tag, txt in (("begin", None), (None, "PAGE"), ("end", None)):
        if tag:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tag)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = txt
        r._r.append(el)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def docx_filename(data: dict) -> str:
    meta = data.get("metadata") or {}
    name = data.get("pertemuan") or meta.get("pertemuan") or data.get("judul") or "Hasil"
    matkul = data.get("matkul") or meta.get("matkul") or ""
    kategori = data.get("kategori") or meta.get("kategori") or ""
    # Kuliah: sertakan matkul (agar "Pertemuan 1" tidak bentrok antar-matkul); Kegiatan Lain: nama kegiatan saja
    base = f"Laporan_{matkul}_{name}" if (matkul and kategori == "Kuliah") else f"Laporan_{name}"
    base = re.sub(r"[^\w\-]+", "_", base, flags=re.UNICODE).strip("_")
    base = re.sub(r"_+", "_", base)
    return (base[:120] or "Laporan") + ".docx"

