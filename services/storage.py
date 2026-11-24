"""Tahap 5: Simpan hasil ke outputs/ dan kirim ke Google Apps Script (opsional)."""
import json
import os
import re
from datetime import datetime
from pathlib import Path

import httpx

from . import hfsync

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR") or (ROOT / "outputs"))


def safe_name(s: str, default: str) -> str:
    s = (s or "").strip()
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:80] or default


def archive_dir(meta: dict) -> Path:
    semester = meta.get("semester") or ("Kegiatan Lain" if meta.get("kategori") != "Kuliah" else "Tanpa Semester")
    return OUTPUT_DIR / safe_name(semester, "Tanpa Semester") / safe_name(meta.get("matkul"), "Umum") / \
        safe_name(meta.get("pertemuan"), datetime.now().strftime("%Y-%m-%d_%H%M"))


def build_markdown(result: dict) -> str:
    m = result["metadata"]
    head = f"# {m.get('matkul') or 'Catatan'} — {m.get('pertemuan') or ''}\n\n"
    head += f"- **Kategori:** {m.get('kategori', '')}\n- **Semester:** {m.get('semester', '-')}\n"
    head += f"- **Dibuat:** {result.get('dibuat', '')}\n\n---\n\n"
    return (head + "## Ringkasan Kontekstual\n\n" + (result.get("ringkasan") or "") +
            "\n\n---\n\n## Catatan Komprehensif\n\n" + (result.get("catatan") or "") + "\n")


def save_transcript_only(meta: dict, transkrip: str) -> Path:
    d = archive_dir(meta)
    d.mkdir(parents=True, exist_ok=True)
    (d / "transkrip.txt").write_text(transkrip, encoding="utf-8")
    hfsync.queue_upload(d)
    return d


def save_result(result: dict) -> Path:
    d = archive_dir(result["metadata"])
    d.mkdir(parents=True, exist_ok=True)
    result["arsip_id"] = d.relative_to(OUTPUT_DIR).as_posix()
    (d / "transkrip.txt").write_text(result.get("transkrip", ""), encoding="utf-8")
    (d / "catatan.md").write_text(build_markdown(result), encoding="utf-8")
    (d / "hasil.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    hfsync.queue_upload(d)
    return d


def delete_archive(arsip_id: str) -> None:
    import shutil
    d = resolve_archive(arsip_id)
    if not d.is_dir():
        raise FileNotFoundError("Arsip tidak ditemukan")
    shutil.rmtree(d)
    hfsync.queue_delete(d)
    for parent in (d.parent, d.parent.parent):  # rapikan folder induk yang kosong
        try:
            if parent != OUTPUT_DIR.resolve() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            break


def send_webhook(result: dict) -> str | None:
    """Return None jika sukses/tidak dipakai, atau pesan peringatan."""
    url = os.getenv("GAS_WEBHOOK_URL", "").strip()
    if not url:
        return None
    payload = {"mode": "FULL_ARCHIVE_FROM_V4", **result["metadata"],
               "metadata": result["metadata"], "dibuat": result.get("dibuat"),
               "ringkasan": result.get("ringkasan"), "catatan": result.get("catatan"),
               "catatan_md": build_markdown(result), "mindmap": result.get("mindmap"),
               "flashcards": result.get("flashcards"), "kuis": result.get("kuis"),
               "transkrip": result.get("transkrip")}
    try:
        r = httpx.post(url, json=payload, timeout=120, follow_redirects=True)
        if r.status_code >= 400:
            return f"Webhook Google Drive gagal (HTTP {r.status_code}): {r.text[:300]}"
    except Exception as e:
        return f"Webhook Google Drive gagal: {e}"
    return None


def resolve_archive(arsip_id: str) -> Path:
    p = (OUTPUT_DIR / arsip_id).resolve()
    if OUTPUT_DIR.resolve() not in p.parents:
        raise ValueError("Path arsip tidak valid")
    return p


def list_history() -> list[dict]:
    items = []
    if not OUTPUT_DIR.exists():
        return items
    for f in OUTPUT_DIR.glob("*/*/*/hasil.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            m = data.get("metadata", {})
            items.append({"id": f.parent.relative_to(OUTPUT_DIR).as_posix(),
                          "semester": m.get("semester", ""), "matkul": m.get("matkul", ""),
                          "pertemuan": m.get("pertemuan", ""), "kategori": m.get("kategori", ""),
                          "dibuat": data.get("dibuat", ""), "tipe": m.get("tipe", "")})
        except Exception:
            continue
    items.sort(key=lambda x: x["dibuat"], reverse=True)
    return items
