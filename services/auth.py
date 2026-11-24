"""Autentikasi Kreator (password hanya di backend) + registri user sederhana (NIM)."""
import hashlib
import hmac
import json
import os
import re
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request

from . import hfsync

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR") or (ROOT / "data"))
USERS_FILE = DATA_DIR / "users.json"
TOKEN_TTL = 12 * 3600
_lock = threading.Lock()
_fails: dict[str, list[float]] = {}  # ip -> waktu gagal terakhir


def creator_password() -> str:
    pw = os.getenv("CREATOR_PASSWORD", "").strip()
    if not pw or "ISI PASSWORD" in pw.upper():
        return ""  # belum dikonfigurasi -> mode kreator nonaktif
    return pw


def _sign(exp: int, pw: str) -> str:
    return hmac.new(pw.encode(), f"creator:{exp}".encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    pw = creator_password()
    exp = int(time.time()) + TOKEN_TTL
    return f"{exp}.{_sign(exp, pw)}"


def token_valid(token: str | None) -> bool:
    pw = creator_password()
    if not pw or not token or "." not in token:
        return False
    exp_s, sig = token.split(".", 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    return exp > time.time() and hmac.compare_digest(sig, _sign(exp, pw))


def check_password(password: str, ip: str) -> str:
    """Return token, atau raise HTTPException."""
    if not creator_password():
        raise HTTPException(503, "Mode Kreator belum aktif: CREATOR_PASSWORD belum diisi di server (.env).")
    now = time.time()
    with _lock:
        recent = [t for t in _fails.get(ip, []) if now - t < 60]
        _fails[ip] = recent
        if len(recent) >= 5:
            raise HTTPException(429, "Terlalu banyak percobaan salah. Coba lagi dalam 1 menit.")
    if not hmac.compare_digest(hashlib.sha256(password.encode()).digest(),
                               hashlib.sha256(creator_password().encode()).digest()):
        with _lock:
            _fails[ip].append(now)
        raise HTTPException(401, "Password Kreator salah.")
    return make_token()


def require_creator(request: Request):
    """Dependency FastAPI: blokir request jika token Kreator tidak valid."""
    token = request.headers.get("X-Creator-Token")
    if not token:
        raise HTTPException(401, "Fitur ini khusus Kreator. Masukkan password Kreator terlebih dahulu.")
    if not token_valid(token):
        raise HTTPException(403, "Token Kreator tidak valid atau kedaluwarsa. Verifikasi ulang password.")


# ------------------------------------------------------------ users (NIM)
def _load() -> dict:
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def register_user(nim: str, nama: str, kampus: str, prodi: str) -> dict:
    nim = re.sub(r"\s+", "", nim or "")
    nama, kampus, prodi = (nama or "").strip(), (kampus or "").strip(), (prodi or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9.\-]{3,30}", nim):
        raise HTTPException(400, "NIM tidak valid (3-30 karakter huruf/angka).")
    if not nama or not kampus or not prodi:
        raise HTTPException(400, "Nama lengkap, kampus, dan prodi wajib diisi.")
    with _lock:
        users = _load()
        if nim in users:
            raise HTTPException(409, "NIM sudah terdaftar. Silakan login.")
        users[nim] = {"nim": nim, "nama": nama[:100], "kampus": kampus[:100], "prodi": prodi[:100],
                      "dibuat": time.strftime("%Y-%m-%d %H:%M:%S")}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
        hfsync.queue_upload(USERS_FILE)
        return users[nim]


def login_user(nim: str) -> dict:
    nim = re.sub(r"\s+", "", nim or "")
    u = _load().get(nim)
    if not u:
        raise HTTPException(404, "NIM belum terdaftar. Silakan daftar di tab 'Daftar User Baru'.")
    return u
