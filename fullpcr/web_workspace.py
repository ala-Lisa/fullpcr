"""Workspace management for the fullpcr web UI.

Provides run-directory isolation, safe file-upload handling, and session-state
helpers — all independent of Streamlit so the module can be unit-tested without
a browser.
"""

from __future__ import annotations

import gzip
import os
import shutil
import tempfile
import uuid
import zlib
from pathlib import Path
from typing import IO

# ── constants ──────────────────────────────────────────────────────────────

PRIMERS_FILE = "primers"
TAXONOMY_FILE = "taxonomy"
DATABASE_FILE = "database"

_PRIMERS_ALLOWED: set[str] = {".tsv"}
_TAXONOMY_ALLOWED: set[str] = {".tsv"}
_DATABASE_ALLOWED: set[str] = {".fasta", ".fa", ".fasta.gz", ".fa.gz"}

ALLOWED_EXTENSIONS: dict[str, set[str]] = {
    PRIMERS_FILE: _PRIMERS_ALLOWED,
    TAXONOMY_FILE: _TAXONOMY_ALLOWED,
    DATABASE_FILE: _DATABASE_ALLOWED,
}

# ═══════════════════════════════════════════════════════════════════════════
# _is_safe_basename — cross-platform filename validation
# ═══════════════════════════════════════════════════════════════════════════

#: Characters or substrings that are never safe in a user-supplied filename.
_FORBIDDEN_IN_NAME: tuple[str, ...] = ("/", "\\", "..")

#: Length of the longest forbidden substring (used for scanning).
_MAX_FORBIDDEN_LEN: int = max(len(p) for p in _FORBIDDEN_IN_NAME)


def _is_safe_basename(name: str) -> bool:
    """Reject names that are empty, contain path separators, or try traversal.

    Blocks:

    * empty / whitespace-only
    * ``/`` and ``\\`` (Unix + Windows separators)
    * ``..`` path components
    * Windows absolute / drive-letter paths (e.g. ``C:\\fakepath\\db.fasta``)
    * Any name that differs from ``Path(name).name``
    """
    if not name or not name.strip():
        return False

    # Quick scan for forbidden substrings (/, \, ..).
    for i in range(len(name)):
        for fb in _FORBIDDEN_IN_NAME:
            if name[i : i + len(fb)] == fb:
                return False

    # Defence-in-depth: Path.name decomposes the final component.
    if name != Path(name).name:
        return False

    # Windows: reject absolute or drive paths (e.g. C:\..., \\server\...).
    drive, tail = os.path.splitdrive(name)
    if drive:
        return False

    return True


# ═══════════════════════════════════════════════════════════════════════════
# _classify_extension
# ═══════════════════════════════════════════════════════════════════════════


def _classify_extension(filename: str, allowed: set[str]) -> str | None:
    """Return the lowercase extension if *filename* ends with an allowed one.

    Handles compound suffixes such as ``.fasta.gz`` before ``.gz`` alone.
    """
    low = filename.lower()
    for ext in sorted(allowed, key=lambda e: -len(e)):
        if low.endswith(ext):
            return ext
    return None


# ═══════════════════════════════════════════════════════════════════════════
# data root
# ═══════════════════════════════════════════════════════════════════════════


def get_data_root() -> Path:
    """Return the data root directory from ``FULLPCR_DATA_DIR`` or ``./data``.

    Does **not** create the directory.
    """
    raw = os.environ.get("FULLPCR_DATA_DIR", "")
    if raw:
        return Path(raw).resolve()
    return Path("data").resolve()


# ═══════════════════════════════════════════════════════════════════════════
# run workspace
# ═══════════════════════════════════════════════════════════════════════════


def create_run_workspace(
    data_root: str | Path | None = None,
) -> dict:
    """Create a new isolated run workspace with a unique ``run_id``."""
    root = Path(data_root) if data_root else get_data_root()
    run_id = uuid.uuid4().hex
    ws_root = root / "runs" / run_id

    dirs = {
        "uploads_dir": ws_root / "uploads",
        "qc_results_dir": ws_root / "qc_results",
        "qc_spec_results_dir": ws_root / "qc_spec_results",
        "obipcr_results_dir": ws_root / "obipcr_results",
        "final_results_dir": ws_root / "final_results",
    }

    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    return {
        "run_id": run_id,
        "data_root": str(root),
        "workspace_root": str(ws_root),
        "uploads_dir": str(dirs["uploads_dir"]),
        "qc_results_dir": str(dirs["qc_results_dir"]),
        "qc_spec_results_dir": str(dirs["qc_spec_results_dir"]),
        "obipcr_results_dir": str(dirs["obipcr_results_dir"]),
        "final_results_dir": str(dirs["final_results_dir"]),
    }


def get_workspace_paths(run_id: str, data_root: str | Path | None = None) -> dict:
    """Return structured paths for an existing *run_id*.

    Does **not** create directories.
    """
    root = Path(data_root) if data_root else get_data_root()
    ws_root = root / "runs" / run_id
    return {
        "run_id": run_id,
        "data_root": str(root),
        "workspace_root": str(ws_root),
        "uploads_dir": str(ws_root / "uploads"),
        "qc_results_dir": str(ws_root / "qc_results"),
        "qc_spec_results_dir": str(ws_root / "qc_spec_results"),
        "obipcr_results_dir": str(ws_root / "obipcr_results"),
        "final_results_dir": str(ws_root / "final_results"),
    }


# ═══════════════════════════════════════════════════════════════════════════
# streaming copy helper
# ═══════════════════════════════════════════════════════════════════════════

_STREAM_CHUNK = 1 << 18  # 256 KiB


def _stream_to_path(
    src: IO[bytes],
    dst_path: Path,
    *,
    total_limit: int | None = None,
) -> int:
    """Stream *src* → *dst_path* in fixed-size chunks.  Returns bytes written.

    If *total_limit* is set and the stream exceeds it, raises ``ValueError``.
    Does **not** call ``src.read(-1)`` — always reads chunked.
    """
    total = 0
    with open(dst_path, "wb") as out:
        while True:
            chunk = src.read(_STREAM_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total_limit is not None and total > total_limit:
                raise ValueError(f"File exceeds {total_limit} bytes")
            out.write(chunk)
        out.flush()
        os.fsync(out.fileno())
    return total


# ═══════════════════════════════════════════════════════════════════════════
# safe save
# ═══════════════════════════════════════════════════════════════════════════


def save_uploaded_file(
    file_obj: IO[bytes],
    *,
    file_type: str,
    uploads_dir: str | Path,
    original_name: str,
) -> dict:
    """Validate and atomically save an uploaded file into *uploads_dir*.

    For ``DATABASE_FILE``, all formats (``.fasta``, ``.fa``, ``.fasta.gz``,
    ``.fa.gz``) are normalised to ``database.fasta``.  Gzip inputs are
    decompressed on the fly; plain FASTA is stream-copied.

    Returns:
        dict with ``status``, ``saved_path``, ``file_type``, ``file_size``,
        ``run_id``, ``error``.
    """
    uploads = Path(uploads_dir).resolve()

    # ── validate file_type ──────────────────────────────────────────────
    allowed = ALLOWED_EXTENSIONS.get(file_type)
    if allowed is None:
        return _fail(f"不支持的文件类型: {file_type}", file_type)

    # ── validate original_name ──────────────────────────────────────────
    if not _is_safe_basename(original_name):
        return _fail(
            f"文件名不安全或为空: '{original_name}'。"
            f"请使用普通文件名，不要包含路径分隔符。",
            file_type,
        )

    ext = _classify_extension(original_name, allowed)
    if ext is None:
        allowed_str = "、".join(sorted(allowed))
        return _fail(f"文件格式不支持，请上传 {allowed_str}", file_type)

    # ── build target path ───────────────────────────────────────────────
    if file_type == DATABASE_FILE:
        target_name = "database.fasta"
    else:
        target_name = f"{file_type}{ext}"

    target_path = (uploads / target_name).resolve()

    try:
        target_path.relative_to(uploads)
    except ValueError:
        return _fail(f"文件保存路径超出允许范围: {target_name}", file_type)

    # ── seek to start if supported ──────────────────────────────────────
    try:
        file_obj.seek(0)
    except (OSError, AttributeError):
        pass

    # ── stream-copy to temp file, then atomic replace ───────────────────
    uploads.mkdir(parents=True, exist_ok=True)
    tmp_fd: int = -1
    tmp_path: str = ""
    bytes_written: int = 0
    is_gz: bool = ext in {".fasta.gz", ".fa.gz"}

    try:
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(uploads),
            prefix=f".tmp_{target_name}_",
        )

        # Transfer fd ownership to a Python file object via context manager.
        # Once inside the ``with`` block, tmp_fd is set to -1 so the outer
        # ``except OSError`` handler will NOT attempt a second close.
        with os.fdopen(tmp_fd, "wb") as tmp_f:
            tmp_fd = -1

            if is_gz:
                # ── gzip decompression ──────────────────────────────────
                try:
                    with gzip.GzipFile(fileobj=file_obj, mode="rb") as gz:
                        shutil.copyfileobj(gz, tmp_f, length=_STREAM_CHUNK)
                except (gzip.BadGzipFile, EOFError, OSError, zlib.error) as gz_exc:
                    raise ValueError(
                        f"gzip 解压失败: {gz_exc}"
                    ) from gz_exc
            else:
                # ── plain copy in fixed-size chunks ─────────────────────
                while True:
                    chunk = file_obj.read(_STREAM_CHUNK)
                    if not chunk:
                        break
                    tmp_f.write(chunk)
                    bytes_written += len(chunk)

            # ── measure bytes written (for gzip, use file position) ─────
            if is_gz:
                bytes_written = tmp_f.tell()

            # ── flush + fsync BEFORE closing ────────────────────────────
            tmp_f.flush()
            os.fsync(tmp_f.fileno())

        # fd is now closed by the context manager.  tmp_fd == -1.

        # ── validate non-empty BEFORE replacing target ────────────────
        if bytes_written == 0:
            os.unlink(tmp_path)
            return _fail("文件为空，请上传有效文件。", file_type)

        # ── atomic replace (target untouched on failure) ───────────────
        try:
            os.replace(tmp_path, str(target_path))
        except OSError as exc:
            os.unlink(tmp_path)
            return _fail(f"文件保存失败: {exc}", file_type)
        tmp_path = ""  # owned by target now

    except ValueError as exc:
        # gzip / content error — fd was closed by context manager.
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return _fail(str(exc), file_type)

    except OSError as exc:
        # I/O error — fd may still be open if os.fdopen itself failed.
        if tmp_fd >= 0:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return _fail(f"文件保存失败: {exc}", file_type)

    run_id = uploads.parent.name

    return {
        "status": "PASS",
        "saved_path": str(target_path),
        "file_type": file_type,
        "file_size": bytes_written,
        "run_id": run_id,
        "error": None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# internal helpers
# ═══════════════════════════════════════════════════════════════════════════


def _fail(error: str, file_type: str) -> dict:
    return {
        "status": "FAIL",
        "saved_path": None,
        "file_type": file_type,
        "file_size": None,
        "run_id": None,
        "error": error,
    }
