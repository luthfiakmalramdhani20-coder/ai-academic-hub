"""Sinkronisasi opsional outputs/ dan data/users.json ke Hugging Face Dataset (agar tahan restart Space).

Aktif hanya jika HF_TOKEN dan HF_DATASET_REPO terisi; selain itu semua fungsi no-op.
Tata letak di dataset: outputs/... dan data/users.json.
"""
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR") or (ROOT / "outputs"))
USERS_FILE = Path(os.getenv("DATA_DIR") or (ROOT / "data")) / "users.json"
DEBOUNCE = 3.0

_lock = threading.Lock()
_pending: set[Path] = set()     # file/folder lokal yang perlu diunggah
_deleted: set[str] = set()      # path di repo yang perlu dihapus (file atau folder)
_worker_running = False


def _cfg():
    token = os.getenv("HF_TOKEN", "").strip()
    repo = os.getenv("HF_DATASET_REPO", "").strip()
    return (token, repo) if token and repo else None


def enabled() -> bool:
    return _cfg() is not None


def _log(msg: str):
    print(f"[hfsync] {msg}", flush=True)


def _repo_path(p: Path) -> str | None:
    p = Path(p).resolve()
    out = OUTPUT_DIR.resolve()
    if p == USERS_FILE.resolve():
        return "data/users.json"
    if p == out:
        return "outputs"
    if out in p.parents:
        return "outputs/" + p.relative_to(out).as_posix()
    return None


# ------------------------------------------------------------------ pull
def pull() -> None:
    cfg = _cfg()
    if not cfg:
        return
    token, repo = cfg
    try:
        from huggingface_hub import HfApi, snapshot_download
        HfApi(token=token).create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="hfpull_"))
        try:
            snapshot_download(repo_id=repo, repo_type="dataset", token=token, local_dir=str(tmp),
                              allow_patterns=["outputs/**", "data/users.json"])
            # Di Space, dataset = sumber kebenaran (timpa). Di lokal: hanya isi file yang belum ada.
            overwrite = bool(os.getenv("SPACE_ID"))
            n = 0
            src_root = tmp / "outputs"
            if src_root.is_dir():
                for src in src_root.rglob("*"):
                    if src.is_file():
                        dst = OUTPUT_DIR / src.relative_to(src_root)
                        if overwrite or not dst.exists():
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dst)
                            n += 1
            u = tmp / "data" / "users.json"
            if u.is_file() and (overwrite or not USERS_FILE.exists()):
                USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(u, USERS_FILE)
                n += 1
            _log(f"Unduh dari dataset selesai ({n} file).")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:  # jangan pernah menjatuhkan aplikasi
        _log(f"Gagal mengunduh dari dataset: {e}")


# ------------------------------------------------------------------ push
def queue_upload(path: Path) -> None:
    """Jadwalkan unggah file/folder (folder arsip atau users.json) di background."""
    if not enabled():
        return
    with _lock:
        _pending.add(Path(path))
    _kick()


def queue_delete(path: Path) -> None:
    """Jadwalkan penghapusan path (yang sudah dihapus lokal) dari dataset."""
    if not enabled():
        return
    rp = _repo_path(Path(path))
    if not rp:
        return
    with _lock:
        _deleted.add(rp)
        for p in list(_pending):
            pr = _repo_path(p)
            if pr and (pr == rp or pr.startswith(rp + "/")):
                _pending.discard(p)
    _kick()


def _kick():
    global _worker_running
    with _lock:
        if _worker_running:
            return
        _worker_running = True
    threading.Thread(target=_worker, daemon=True).start()


def _worker():
    global _worker_running
    try:
        while True:
            time.sleep(DEBOUNCE)  # gabungkan perubahan beruntun jadi satu commit
            with _lock:
                up, dele = set(_pending), set(_deleted)
                _pending.clear()
                _deleted.clear()
            if not up and not dele:
                return
            if not _commit(up, dele):
                with _lock:  # dicoba lagi pada perubahan berikutnya
                    _pending.update(up)
                    _deleted.update(dele)
                return
    finally:
        with _lock:
            _worker_running = False


def _commit(up: set[Path], dele: set[str]) -> bool:
    cfg = _cfg()
    if not cfg:
        return True
    token, repo = cfg
    try:
        from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi
        api = HfApi(token=token)
        api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
        remote = set(api.list_repo_files(repo, repo_type="dataset"))
        ops, seen = [], set()
        for rp in dele:
            for f in remote:
                if f == rp or f.startswith(rp + "/"):
                    ops.append(CommitOperationDelete(path_in_repo=f))
        for p in up:
            if p.is_file():
                files = [p]
            elif p.is_dir():
                files = [f for f in p.rglob("*") if f.is_file()]
            else:
                files = []
            for f in files:
                rp = _repo_path(f)
                if rp and rp not in seen:
                    seen.add(rp)
                    ops.append(CommitOperationAdd(path_in_repo=rp, path_or_fileobj=str(f)))
        if not ops:
            return True
        api.create_commit(repo_id=repo, repo_type="dataset", operations=ops,
                          commit_message="sync " + time.strftime("%Y-%m-%d %H:%M:%S"))
        _log(f"Sinkron ke dataset: {len(ops)} operasi.")
        return True
    except Exception as e:
        _log(f"Gagal sinkron ke dataset (akan dicoba lagi): {e}")
        return False
