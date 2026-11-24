"""AI Academic Hub — server FastAPI (backend + frontend dalam satu uvicorn)."""
import asyncio
import json
import os
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=True)

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from services import audio, auth, exporter, extract, gemini, hfsync, storage, transcribe  # noqa: E402
from services.transcribe import APIError  # noqa: E402

TEMP_DIR = Path(os.getenv("TEMP_WORK_DIR") or (ROOT / "temp"))
INBOX_DIR = Path(os.getenv("INBOX_DIR") or (ROOT / "_INBOX_TRANSKRIP"))
STATIC_DIR = ROOT / "static"
MAX_UPLOAD = 500 * 1024 * 1024
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".mp4", ".mkv", ".webm"}
MATERI_EXT = {".pptx", ".pdf", ".docx", ".txt", ".md"}
TOTAL_STEPS = 5

hfsync.pull()  # unduh arsip & user dari HF Dataset (no-op jika HF_TOKEN/HF_DATASET_REPO kosong)

app = FastAPI(title="AI Academic Hub")
CREATOR = [Depends(auth.require_creator)]
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


# ---------------------------------------------------------------- progress
def push(job_id: str, **event):
    with JOBS_LOCK:
        job = JOBS[job_id]
        if "percent" in event:
            job["percent"] = event["percent"]
        event.setdefault("percent", job.get("percent", 0))
        event["t"] = time.time()
        job["events"].append(event)


def make_logger(job_id: str, step: int):
    def log(msg: str):
        push(job_id, type="progress", step=step, message=f"{step}/{TOTAL_STEPS} {msg}")
    return log


# ---------------------------------------------------------------- pipeline
def ai_stage(job_id: str, meta: dict, source_text: str, materi_text: str, base: dict | None = None,
             himpunan_jenis: str | None = None):
    """Tahap 4-5: 2 panggilan Gemini + simpan. source_text = transkrip (atau kumpulan catatan utk himpunan)."""
    base = base or {}
    log4 = make_logger(job_id, 4)
    jenis = "perkuliahan" if meta["kategori"] == "Kuliah" else "kegiatan"
    judul = f"{meta['matkul']} — {meta['pertemuan']}".strip(" —")
    push(job_id, type="progress", step=4, percent=60,
         message="4/5 Menyusun Catatan Komprehensif dengan AI (bisa beberapa menit)...")
    if himpunan_jenis:
        prompt1 = gemini.PROMPT_HIMPUNAN.format(judul=meta["matkul"], jenis=himpunan_jenis, transkrip=source_text)
    else:
        prompt1 = gemini.PROMPT_CATATAN.format(jenis=jenis, judul=judul,
                                               transkrip=gemini.strip_timestamps(source_text))
    catatan, model1 = gemini.generate(prompt1, log=log4)
    push(job_id, type="progress", step=4, percent=75,
         message="4/5 Catatan selesai. Jeda 8 detik agar aman dari limit Free Tier...")
    time.sleep(8)
    push(job_id, type="progress", step=4, percent=78,
         message="4/5 Menyusun ringkasan, mind map, flashcard & kuis dengan AI...")
    materi_block = f"\nMATERI SLIDE / DOKUMEN:\n{materi_text[:200000]}" if materi_text else ""
    raw, model2 = gemini.generate(
        gemini.PROMPT_TURUNAN.format(ada_materi=" dan MATERI SLIDE" if materi_text else "",
                                     catatan=catatan, materi=materi_block),
        json_mode=True, log=log4)
    try:
        turunan = gemini.parse_json(raw)
    except Exception:
        raise RuntimeError("AI mengembalikan JSON yang tidak valid. Potongan respons: " + raw[:500])

    push(job_id, type="progress", step=5, percent=92, message="5/5 Menyimpan hasil...")
    result = {
        "metadata": meta,
        "dibuat": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": model2 if model1 == model2 else f"{model1} / {model2}",
        "file_sumber": base.get("file_sumber", ""),
        "ringkasan": turunan.get("ringkasan", ""),
        "catatan": catatan,
        "mindmap": turunan.get("mindmap", ""),
        "flashcards": turunan.get("flashcards", []),
        "kuis": turunan.get("kuis", []),
        "materi_teks": materi_text,
        "transkrip": base.get("transkrip", source_text),
    }
    storage.save_result(result)
    push(job_id, type="progress", step=5, percent=96,
         message="5/5 Tersimpan di arsip: " + result["arsip_id"])
    warn = storage.send_webhook(result)
    if warn:
        push(job_id, type="warning", message=warn)
    elif os.getenv("GAS_WEBHOOK_URL", "").strip():
        push(job_id, type="progress", step=5, percent=98, message="5/5 Terkirim ke Google Drive.")
    push(job_id, type="done", percent=100, message="Selesai!", arsip_id=result["arsip_id"])


def finish_job(job_id: str, work: Path | None, fn):
    try:
        fn()
    except APIError as e:
        push(job_id, type="error", message=f"{e.service} API error — HTTP {e.status}", detail=e.body)
    except Exception as e:
        push(job_id, type="error", message=str(e), detail="")
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
        with JOBS_LOCK:
            JOBS[job_id]["finished"] = True


def start_job(target, *args) -> str:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"events": [], "percent": 0, "finished": False}
    threading.Thread(target=target, args=(job_id, *args), daemon=True).start()
    return job_id


def run_pipeline(job_id: str, meta: dict, media_path: Path | None, texts: list[str],
                 materi_path: Path | None, work: Path):
    def body():
        transkrip, file_sumber = "", ""
        if media_path:
            push(job_id, type="progress", step=1, percent=3,
                 message="1/5 Memotong & mengompres audio (FFmpeg)...")
            chunks = audio.split_audio(media_path, work / "chunks")
            push(job_id, type="progress", step=1, percent=12,
                 message=f"1/5 Audio siap: {len(chunks)} bagian (maks. 15 menit per bagian).")
            results, offset = [], 0.0
            for i, ch in enumerate(chunks, 1):
                push(job_id, type="progress", step=2, percent=12 + int(43 * (i - 1) / len(chunks)),
                     message=f"2/5 Mentranskrip bagian {i} dari {len(chunks)} (Groq Whisper)...")
                data = transcribe.transcribe_chunk(ch, log=make_logger(job_id, 2))
                results.append((offset, data))
                dur = audio.get_duration(ch)
                offset += dur if dur > 0 else audio.SEGMENT_SECONDS
            transkrip = transcribe.build_transcript(results)
            file_sumber = media_path.name
            if not transkrip.strip():
                raise RuntimeError("Transkrip kosong — tidak ada suara yang terdeteksi.")
            push(job_id, type="progress", step=2, percent=55, message="2/5 Transkripsi selesai.")
        else:
            transkrip = "\n\n".join(t.strip() for t in texts if t.strip())
            push(job_id, type="progress", step=1, percent=10,
                 message="1/5 Memakai teks yang diberikan — tahap audio dilewati.")
            push(job_id, type="progress", step=2, percent=55,
                 message="2/5 Transkripsi tidak diperlukan — dilewati.")

        materi_text = ""
        if materi_path:
            push(job_id, type="progress", step=3, percent=57,
                 message=f"3/5 Membaca materi {materi_path.suffix.upper().lstrip('.')}...")
            try:
                materi_text = extract.extract_material(materi_path)
            except Exception as e:
                push(job_id, type="warning", message=f"Materi gagal dibaca ({e}). Lanjut tanpa materi.")
        else:
            push(job_id, type="progress", step=3, percent=58, message="3/5 Tidak ada materi slide — dilewati.")
        if not transkrip.strip():
            if not materi_text.strip():
                raise RuntimeError("Tidak ada teks untuk diproses (transkrip kosong dan materi tidak terbaca).")
            transkrip = materi_text  # hanya materi yang diberikan
        storage.save_transcript_only(meta, transkrip)  # aman kalau tahap AI gagal
        ai_stage(job_id, meta, transkrip, materi_text, {"file_sumber": file_sumber, "transkrip": transkrip})
    finish_job(job_id, work, body)


def build_himpunan(job_id: str, meta: dict):
    notes, trs = [], []
    for aid in meta["sumber_ids"]:
        f = storage.resolve_archive(aid) / "hasil.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        title = d.get("metadata", {}).get("pertemuan", aid)
        notes.append(f"## {title}\n\n{d.get('catatan', '')}")
        trs.append(f"===== {title} =====\n{d.get('transkrip', '')}")
    if not notes:
        raise RuntimeError("Tidak ada catatan pada pertemuan yang dipilih.")
    push(job_id, type="progress", step=3, percent=50, message=f"3/5 Menggabungkan {len(notes)} pertemuan...")
    ai_stage(job_id, meta, "\n\n".join(notes), "", {"transkrip": "\n\n".join(trs)},
             himpunan_jenis=meta.get("jenis_ujian", "UTS"))


def run_himpunan(job_id: str, meta: dict):
    finish_job(job_id, None, lambda: build_himpunan(job_id, meta))


def run_regenerate(job_id: str, arsip_id: str):
    def body():
        data = json.loads((storage.resolve_archive(arsip_id) / "hasil.json").read_text(encoding="utf-8"))
        meta = data["metadata"]
        push(job_id, type="progress", step=1, percent=5, message="1/5 Memuat arsip lama...")
        if meta.get("tipe") == "himpunan":
            return build_himpunan(job_id, meta)
        ai_stage(job_id, meta, data.get("transkrip", ""), data.get("materi_teks", ""),
                 {"file_sumber": data.get("file_sumber", ""), "transkrip": data.get("transkrip", "")})
    finish_job(job_id, None, body)


# ---------------------------------------------------------------- routes
async def save_upload(up: UploadFile, dest: Path):
    size = 0
    with open(dest, "wb") as f:
        while chunk := await up.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD:
                raise HTTPException(413, "File melebihi 500MB")
            f.write(chunk)


def safe_inbox_files(names: list[str]) -> list[Path]:
    out = []
    for n in names:
        p = INBOX_DIR / Path(n).name
        if p.suffix.lower() == ".txt" and p.is_file():
            out.append(p)
    return out


@app.post("/api/auth/verify")
def auth_verify(request: Request, data: dict = Body(...)):
    ip = request.client.host if request.client else "?"
    return {"token": auth.check_password(str(data.get("password", "")), ip)}


@app.get("/api/auth/check")
def auth_check(request: Request):
    return {"creator": auth.token_valid(request.headers.get("X-Creator-Token")),
            "enabled": bool(auth.creator_password())}


@app.post("/api/users/register")
def users_register(data: dict = Body(...)):
    return auth.register_user(data.get("nim", ""), data.get("nama", ""), data.get("kampus", ""), data.get("prodi", ""))


@app.post("/api/users/login")
def users_login(data: dict = Body(...)):
    return auth.login_user(data.get("nim", ""))


@app.get("/api/inbox")
def inbox():
    if not INBOX_DIR.is_dir():
        return []
    return [{"name": p.name, "size": p.stat().st_size} for p in sorted(INBOX_DIR.glob("*.txt"))]


@app.post("/api/process", dependencies=CREATOR)
async def process(
    kategori: str = Form("Kuliah"), semester: str = Form(""), matkul: str = Form(""),
    pertemuan: str = Form(""), sumber: str = Form("audio"), teks: str = Form(""),
    inbox_names: list[str] = Form(default=[]),
    media: UploadFile | None = File(None), materi: UploadFile | None = File(None),
    inbox_files: list[UploadFile] = File(default=[]),
):
    kategori = "Kuliah" if kategori == "Kuliah" else "Kegiatan Lain"
    semester, matkul, pertemuan = semester.strip(), matkul.strip(), pertemuan.strip()
    if kategori == "Kuliah" and not semester:
        raise HTTPException(400, "Semester belum diisi")
    if not matkul or not pertemuan:
        raise HTTPException(400, "Mata kuliah/kegiatan dan pertemuan/sesi wajib diisi")
    if kategori != "Kuliah":
        semester = ""

    job_id = uuid.uuid4().hex[:12]
    work = TEMP_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)
    media_path, materi_path, texts, nama_file = None, None, [], ""
    try:
        if sumber == "audio":
            if media is None or not media.filename:
                raise HTTPException(400, "Pilih file audio terlebih dahulu")
            ext = Path(media.filename).suffix.lower()
            if ext not in AUDIO_EXT:
                raise HTTPException(400, f"Format audio/video {ext} tidak didukung")
            if not audio.ffmpeg_available():
                raise HTTPException(500, "FFmpeg tidak ditemukan di server.")
            media_path = work / f"media{ext}"
            await save_upload(media, media_path)
            nama_file = media.filename
        elif sumber == "inbox":
            for p in safe_inbox_files(inbox_names):
                texts.append(p.read_text(encoding="utf-8", errors="replace"))
            for up in inbox_files:
                if up.filename and up.filename.lower().endswith((".txt", ".md")):
                    texts.append((await up.read()).decode("utf-8", errors="replace"))
            if not any(t.strip() for t in texts):
                raise HTTPException(400, "Belum ada file .txt hasil Colab yang dipilih/diunggah")
            nama_file = "inbox-colab"
        else:
            if teks.strip():
                texts.append(teks)
            nama_file = "teks-tempel"
        if materi is not None and materi.filename:
            mext = Path(materi.filename).suffix.lower()
            if mext not in MATERI_EXT:
                raise HTTPException(400, f"Format materi {mext} tidak didukung")
            materi_path = work / f"materi{mext}"
            await save_upload(materi, materi_path)
        if sumber != "audio" and not any(t.strip() for t in texts) and not materi_path:
            raise HTTPException(400, "Tempel teks transkrip atau lampirkan materi terlebih dahulu")
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise

    meta = {"kategori": kategori, "semester": semester, "matkul": matkul,
            "pertemuan": pertemuan, "nama_file": nama_file}
    JOBS[job_id] = {"events": [], "percent": 0, "finished": False}
    threading.Thread(target=run_pipeline, args=(job_id, meta, media_path, texts, materi_path, work),
                     daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/regenerate", dependencies=CREATOR)
def regenerate(data: dict = Body(...)):
    aid = str(data.get("id", ""))
    try:
        ok = (storage.resolve_archive(aid) / "hasil.json").exists()
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "Arsip tidak ditemukan")
    return {"job_id": start_job(run_regenerate, aid)}


@app.post("/api/himpunan", dependencies=CREATOR)
def himpunan(data: dict = Body(...)):
    semester, matkul = str(data.get("semester", "")).strip(), str(data.get("matkul", "")).strip()
    jenis = "UAS" if str(data.get("jenis", "")).upper() == "UAS" else "UTS"
    ids = [str(i) for i in data.get("ids", [])]
    if not semester or not matkul:
        raise HTTPException(400, "Semester dan mata kuliah wajib dipilih")
    if len(ids) < 2:
        raise HTTPException(400, "Pilih minimal 2 pertemuan untuk dihimpun")
    for i in ids:
        try:
            storage.resolve_archive(i)
        except ValueError as e:
            raise HTTPException(400, str(e))
    meta = {"kategori": "Kuliah", "semester": semester, "matkul": matkul, "pertemuan": f"Himpunan {jenis}",
            "nama_file": "himpunan", "tipe": "himpunan", "jenis_ujian": jenis, "sumber_ids": ids}
    return {"job_id": start_job(run_himpunan, meta)}


@app.put("/api/archive", dependencies=CREATOR)
def edit_archive(data: dict = Body(...)):
    try:
        d = storage.resolve_archive(str(data.get("id", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    f = d / "hasil.json"
    if not f.exists():
        raise HTTPException(404, "Arsip tidak ditemukan")
    res = json.loads(f.read_text(encoding="utf-8"))
    for k in ("catatan", "ringkasan"):
        if isinstance(data.get(k), str):
            res[k] = data[k]
    res["diedit"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "catatan.md").write_text(storage.build_markdown(res), encoding="utf-8")
    hfsync.queue_upload(d)
    return {"ok": True}


@app.delete("/api/archive", dependencies=CREATOR)
def delete_archive(id: str):
    try:
        storage.delete_archive(id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@app.get("/api/progress/{job_id}")
async def progress(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Job tidak ditemukan")

    async def stream():
        sent, last_ping = 0, time.time()
        while True:
            with JOBS_LOCK:
                job = JOBS[job_id]
                new = job["events"][sent:]
                finished = job["finished"]
            for ev in new:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            sent += len(new)
            if finished and not new:
                break
            if time.time() - last_ping > 15:
                yield ": ping\n\n"
                last_ping = time.time()
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/history")
def history():
    return storage.list_history()


@app.get("/api/archive")
def archive(id: str):
    try:
        d = storage.resolve_archive(id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    f = d / "hasil.json"
    if not f.exists():
        raise HTTPException(404, "Arsip tidak ditemukan")
    data = json.loads(f.read_text(encoding="utf-8"))
    data["arsip_id"] = id
    return JSONResponse(data)


@app.get("/api/download")
def download(id: str, file: str):
    if file not in ("transkrip.txt", "catatan.md", "hasil.json"):
        raise HTTPException(400, "File tidak valid")
    try:
        d = storage.resolve_archive(id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    p = d / file
    if not p.exists():
        raise HTTPException(404, "File tidak ditemukan")
    nice = storage.safe_name(id.replace("/", "_"), "arsip") + "_" + file
    return FileResponse(p, filename=nice)


def _docx_response(data: dict) -> Response:
    try:
        content = exporter.build_docx(data)
    except Exception as e:
        raise HTTPException(500, f"Gagal membuat .docx: {e}")
    fname = exporter.docx_filename(data)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=\"{fname}\"; filename*=UTF-8''{quote(fname)}"},
    )


@app.get("/api/export-docx/{archive_id:path}")
def export_docx_archive(archive_id: str):
    """Buat .docx dari arsip yang tersimpan di outputs/."""
    try:
        d = storage.resolve_archive(archive_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    f = d / "hasil.json"
    if not f.exists():
        raise HTTPException(404, "Arsip tidak ditemukan")
    return _docx_response(json.loads(f.read_text(encoding="utf-8")))


@app.post("/api/export-docx")
def export_docx_post(data: dict = Body(...)):
    """Buat .docx dari data yang dikirim langsung."""
    return _docx_response(data)


@app.get("/api/status")
def status():
    return {"ffmpeg": audio.ffmpeg_available(),
            "groq_key": bool(os.getenv("GROQ_API_KEY", "").strip()),
            "gemini_key": bool(os.getenv("GEMINI_API_KEY", "").strip()),
            "gemini_model": os.getenv("GEMINI_MODEL", ""),
            "webhook": bool(os.getenv("GAS_WEBHOOK_URL", "").strip()),
            "creator_enabled": bool(auth.creator_password())}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT") or 8000)
    host = os.getenv("HOST") or ("0.0.0.0" if os.getenv("PORT") else "127.0.0.1")
    uvicorn.run(app, host=host, port=port)
