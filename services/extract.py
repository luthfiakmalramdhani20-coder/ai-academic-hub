"""Tahap 3: Ekstraksi teks dari materi (PPTX / PDF / DOCX / TXT)."""
from pathlib import Path


def extract_pptx(path: Path) -> str:
    from pptx import Presentation
    prs = Presentation(str(path))
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                t = shape.text_frame.text.strip()
                if t:
                    texts.append(t)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    texts.append(" | ".join(cells))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                texts.append(f"(Catatan pembicara: {notes})")
        if texts:
            parts.append(f"--- Slide {i} ---\n" + "\n".join(texts))
    return "\n\n".join(parts)


def extract_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    parts = []
    for i, page in enumerate(reader.pages, 1):
        t = (page.extract_text() or "").strip()
        if t:
            parts.append(f"--- Halaman {i} ---\n{t}")
    return "\n\n".join(parts)


def extract_docx(path: Path) -> str:
    import docx
    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def extract_txt(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


EXTRACTORS = {".pptx": extract_pptx, ".pdf": extract_pdf, ".docx": extract_docx, ".txt": extract_txt, ".md": extract_txt}


def extract_material(path: Path) -> str:
    fn = EXTRACTORS.get(path.suffix.lower())
    if not fn:
        raise RuntimeError(f"Format materi {path.suffix} tidak didukung (pakai .pptx, .pdf, .docx, .txt)")
    return fn(path).strip()
