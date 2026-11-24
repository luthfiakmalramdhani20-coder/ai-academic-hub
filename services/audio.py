"""Tahap 1: Ekstrak audio & pecah per 15 menit memakai FFmpeg."""
import os
import shutil
import subprocess
from pathlib import Path

SEGMENT_SECONDS = 900  # 15 menit


def _bin(name: str) -> str:
    custom = os.getenv("FFMPEG_DIR", "").strip()
    if custom:
        candidate = Path(custom) / (name + (".exe" if os.name == "nt" else ""))
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(
            f"{name} tidak ditemukan. Install FFmpeg (misal: winget install Gyan.FFmpeg) "
            "lalu tutup & buka ulang aplikasi, atau isi FFMPEG_DIR di .env."
        )
    return found


def ffmpeg_available() -> bool:
    try:
        _bin("ffmpeg")
        _bin("ffprobe")
        return True
    except RuntimeError:
        return False


def get_duration(path: Path) -> float:
    """Durasi file (detik) via ffprobe. 0 jika gagal."""
    try:
        out = subprocess.run(
            [_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def split_audio(src: Path, out_dir: Path) -> list[Path]:
    """Konversi ke MP3 mono 16kHz 32kbps lalu pecah per 900 detik.

    32 kbps x 900 s ~= 3.6 MB per potongan -> jauh di bawah limit 25 MB Groq.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "chunk_%03d.mp3"
    cmd = [
        _bin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", "-c:a", "libmp3lame",
        "-f", "segment", "-segment_time", str(SEGMENT_SECONDS), "-reset_timestamps", "1",
        str(pattern),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg gagal memproses file: {proc.stderr.strip()[-800:]}")
    chunks = sorted(out_dir.glob("chunk_*.mp3"))
    if not chunks:
        raise RuntimeError("FFmpeg tidak menghasilkan potongan audio. Apakah file berisi suara?")
    return chunks
