"""Tahap 2: Transkripsi tiap potongan via Groq Whisper + gabung dengan offset timestamp."""
import os
import time
from pathlib import Path

import httpx

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 6


class APIError(RuntimeError):
    def __init__(self, service: str, status: int, body: str):
        self.service, self.status, self.body = service, status, body
        super().__init__(f"{service} API error HTTP {status}: {body}")


def fmt_ts(seconds: float) -> str:
    s = int(max(0, seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def transcribe_chunk(path: Path, log=None) -> dict:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY belum diisi di file .env")
    delay = 5.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with open(path, "rb") as f:
                resp = httpx.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": (path.name, f, "audio/mpeg")},
                    data={"model": GROQ_MODEL, "language": "id",
                          "response_format": "verbose_json", "temperature": "0"},
                    timeout=httpx.Timeout(600, connect=30),
                )
        except httpx.TransportError as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Koneksi ke Groq gagal: {e}") from e
            if log:
                log(f"Koneksi bermasalah, mencoba ulang dalam {int(delay)} detik...")
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in RETRY_STATUS and attempt < MAX_RETRIES:
            wait = delay
            ra = resp.headers.get("retry-after")
            if ra:
                try:
                    wait = max(float(ra), 1.0)
                except ValueError:
                    pass
            if log:
                log(f"Groq sibuk/limit (HTTP {resp.status_code}), menunggu {int(wait)} detik lalu coba lagi "
                    f"(percobaan {attempt}/{MAX_RETRIES})...")
            time.sleep(wait)
            delay = min(delay * 2, 60)
            continue
        raise APIError("Groq", resp.status_code, resp.text[:2000])
    raise RuntimeError("Groq gagal setelah beberapa kali percobaan.")


def build_transcript(results: list[tuple[float, dict]]) -> str:
    """results: list (offset_detik, verbose_json). Return transkrip dengan [HH:MM:SS]."""
    lines = []
    for offset, data in results:
        segments = data.get("segments") or []
        if not segments and data.get("text"):
            lines.append(f"[{fmt_ts(offset)}] {data['text'].strip()}")
            continue
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if text:
                lines.append(f"[{fmt_ts(offset + float(seg.get('start', 0)))}] {text}")
    return "\n".join(lines)
