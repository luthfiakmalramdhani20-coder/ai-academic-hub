"""Tahap 4: Otak AI Gemini (2 panggilan hemat token)."""
import json
import os
import re
import time

import httpx

from .transcribe import APIError

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
STATIC_FALLBACKS = ["gemini-flash-latest", "gemini-3.5-flash", "gemini-3-flash-preview"]
RETRY_STATUS = {429, 500, 502, 503, 504}
PER_MODEL_RETRIES = 2
ROUNDS = 3
TS_RE = re.compile(r"^\s*\[\d{1,2}:\d{2}:\d{2}\]\s*", re.MULTILINE)
EXCLUDE = ("image", "tts", "audio", "live", "embedding", "omni", "robotics", "computer")

_working_model: str | None = None  # cache model yang terbukti jalan
_discovered: list[str] | None = None


def strip_timestamps(text: str) -> str:
    """Hapus [00:00:00] agar hemat token, gabungkan jadi paragraf."""
    cleaned = TS_RE.sub("", text)
    return " ".join(line.strip() for line in cleaned.splitlines() if line.strip())


def _key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY belum diisi di file .env")
    return key


def _rank(name: str):
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    ver = float(m.group(1)) if m else 0.0
    return ("lite" in name, "preview" in name or "exp" in name, -ver, name)


def list_active_models() -> list[str]:
    """Daftar model 'flash' aktif yang mendukung generateContent, terbaru dulu (non-lite didahulukan)."""
    global _discovered
    if _discovered is not None:
        return _discovered
    try:
        r = httpx.get(f"{API_BASE}/models", headers={"x-goog-api-key": _key()},
                      params={"pageSize": 300}, timeout=30)
        names = []
        if r.status_code == 200:
            for m in r.json().get("models", []):
                n = m.get("name", "").removeprefix("models/")
                if ("generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n
                        and not any(x in n for x in EXCLUDE)):
                    names.append(n)
        _discovered = sorted(names, key=_rank)
    except Exception:
        _discovered = []
    return _discovered


def _candidate_models() -> list[str]:
    configured = os.getenv("GEMINI_MODEL", "").strip() or "gemini-flash-latest"
    order = [m for m in [_working_model, configured] if m] + list_active_models() + STATIC_FALLBACKS
    seen, out = set(), []
    for m in order:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _call_model(model: str, prompt: str, json_mode: bool, log) -> str:
    """Panggil via streaming SSE: error cepat terdeteksi & progres terlihat."""
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 65536},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    delay = 8.0
    for attempt in range(1, PER_MODEL_RETRIES + 1):
        chunks, finish, last_log = [], None, time.time()
        try:
            with httpx.stream(
                "POST", f"{API_BASE}/models/{model}:streamGenerateContent",
                params={"alt": "sse"},
                headers={"x-goog-api-key": _key(), "Content-Type": "application/json"},
                json=body, timeout=httpx.Timeout(connect=30, read=240, write=120, pool=30),
            ) as r:
                if r.status_code != 200:
                    status, text = r.status_code, r.read().decode("utf-8", "replace")
                else:
                    status, text = 200, ""
                    for line in r.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = json.loads(line[5:].strip() or "{}")
                        if "error" in data:
                            raise APIError("Gemini", int(data["error"].get("code", 500)), json.dumps(data)[:2000])
                        for c in data.get("candidates") or []:
                            for p in (c.get("content") or {}).get("parts") or []:
                                if not p.get("thought") and p.get("text"):
                                    chunks.append(p["text"])
                            finish = c.get("finishReason") or finish
                        if data.get("promptFeedback", {}).get("blockReason"):
                            raise APIError("Gemini", 200, "Prompt diblokir: " + json.dumps(data["promptFeedback"]))
                        if time.time() - last_log > 6:
                            log(f"AI sedang menulis... ({sum(map(len, chunks)):,} karakter, model {model})")
                            last_log = time.time()
        except httpx.TransportError as e:
            status, text = 0, f"{type(e).__name__}: {e}"
            if chunks:
                raise RuntimeError(f"Koneksi ke Gemini terputus di tengah jalan: {text}") from e
        if status == 200:
            out = "".join(chunks)
            if not out.strip():
                raise APIError("Gemini", 200, f"Teks kosong. finishReason={finish}")
            return out
        retryable = status in RETRY_STATUS or status == 0
        if retryable and attempt < PER_MODEL_RETRIES:
            log(f"Gemini sibuk (HTTP {status or 'timeout'}) di model {model}, tunggu {int(delay)} detik...")
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue
        raise APIError("Gemini", status, text[:2000] or "Tidak ada respons (timeout)")
    raise RuntimeError("Gemini gagal")


def generate(prompt: str, json_mode: bool = False, log=lambda m: None) -> tuple[str, str]:
    """Coba model dari .env, lalu fallback ke model aktif lain. Return (teks, model_dipakai)."""
    global _working_model
    models = _candidate_models()
    last_err: Exception | None = None
    for rnd in range(1, ROUNDS + 1):
        for model in models:
            try:
                text = _call_model(model, prompt, json_mode, log)
                _working_model = model
                return text, model
            except APIError as e:
                last_err = e
                if e.status in (401, 403):  # API key salah -> percuma ganti model
                    raise
                low = e.body.lower()
                if e.status == 400 and "not found" not in low and "not supported" not in low:
                    raise
                if e.status == 200:  # respons kosong/diblokir -> coba model lain sekali
                    pass
                log(f"Model {model} gagal (HTTP {e.status or 'timeout'}), mencoba model cadangan...")
        if rnd < ROUNDS:
            log(f"Semua model sedang sibuk. Menunggu 30 detik lalu mencoba lagi (putaran {rnd + 1}/{ROUNDS})...")
            time.sleep(30)
    raise last_err or RuntimeError("Tidak ada model Gemini yang bisa dipakai")


def parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            return json.loads(t[start:end + 1])
        raise


PROMPT_CATATAN = """Kamu adalah asisten akademik ahli. Di bawah ini adalah transkrip lisan dari {jenis} "{judul}".

TUGAS: Buat **Catatan Komprehensif Lengkap** dalam Bahasa Indonesia.
ATURAN WAJIB:
1. Muat 100% SEMUA detail, contoh, angka, definisi, istilah, analogi, tanya-jawab, tugas, dan pengumuman. JANGAN meringkas atau membuang informasi apa pun.
2. Rapikan bahasa lisan (ehm, eh, pengulangan, kalimat terputus) menjadi bahasa akademik yang baku, jelas, dan terstruktur.
3. Susun dengan Markdown: heading (##, ###), poin-poin, **tebal** untuk istilah kunci, tabel bila cocok, dan blok kutipan untuk definisi penting.
4. Urutkan sesuai alur penjelasan. Jika ada bagian yang tidak jelas terdengar, tandai dengan _(kurang jelas di rekaman)_.
5. Langsung tulis catatannya tanpa kata pengantar.

TRANSKRIP:
{transkrip}
"""

PROMPT_TURUNAN = """Kamu adalah asisten belajar. Berdasarkan CATATAN KOMPREHENSIF{ada_materi} di bawah, buat output JSON VALID (tanpa teks lain) dengan struktur persis:

{{
  "ringkasan": "string Markdown: Ringkasan Kontekstual (konteks & tujuan pembahasan, poin-poin utama, keterkaitan antar konsep, hal yang perlu diingat untuk ujian). 300-700 kata.",
  "mindmap": "string Markdown khusus Markmap: baris pertama '# Judul Utama', lalu cabang memakai '## ', '### ', '#### ' dan boleh '- ' untuk daun. Ringkas per node (maks 8 kata).",
  "flashcards": [{{"depan": "pertanyaan/istilah", "belakang": "jawaban/penjelasan singkat"}}],
  "kuis": [{{"pertanyaan": "string", "pilihan": ["A", "B", "C", "D"], "jawaban": 0, "pembahasan": "kenapa jawaban itu benar"}}]
}}

Ketentuan: 12-20 flashcard, 10-15 soal kuis pilihan ganda dengan 4 pilihan, "jawaban" adalah indeks 0-3 dari pilihan yang benar. Variasikan posisi jawaban benar. Semua dalam Bahasa Indonesia. Gunakan materi slide (jika ada) untuk melengkapi konteks.

CATATAN KOMPREHENSIF:
{catatan}
{materi}
"""


PROMPT_HIMPUNAN = """Kamu adalah asisten akademik ahli. Di bawah ini adalah kumpulan catatan komprehensif dari beberapa pertemuan mata kuliah "{judul}".
Susun menjadi SATU "Himpunan Catatan & Bahan {jenis}" yang terpadu dalam Bahasa Indonesia (Markdown):
- Kelompokkan per topik/bab (bukan per pertemuan), hilangkan duplikasi, pertahankan semua definisi, rumus, contoh, dan poin penting.
- Beri bagian akhir "Poin Wajib Hafal untuk {jenis}" dan "Prediksi Pertanyaan {jenis}".
- Jangan menambah fakta yang tidak ada di catatan.

CATATAN PER PERTEMUAN:
{transkrip}
"""
