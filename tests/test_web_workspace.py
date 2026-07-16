"""Tests for ``fullpcr.web_workspace`` — workspace isolation, safe upload,
streaming I/O, and fd-leak prevention."""

from __future__ import annotations

import errno
import gzip
import io
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from fullpcr.web_workspace import (
    ALLOWED_EXTENSIONS,
    DATABASE_FILE,
    PRIMERS_FILE,
    TAXONOMY_FILE,
    create_run_workspace,
    get_data_root,
    get_workspace_paths,
    save_uploaded_file,
    _classify_extension,
    _is_safe_basename,
)


# ═══════════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════════

def _save(uploads_dir, content, filename, file_type):
    f = io.BytesIO(content)
    f.name = filename
    return save_uploaded_file(f, file_type=file_type, uploads_dir=uploads_dir, original_name=filename)


def _gzip_content(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(data)
    return buf.getvalue()


def _fd_is_closed(fd: int) -> bool:
    """Return True if *fd* is closed (os.fstat raises OSError with EBADF)."""
    try:
        os.fstat(fd)
        return False
    except OSError as exc:
        return exc.errno == errno.EBADF


def _spy_mkstemp_closes():
    """Return a wrapper of ``tempfile.mkstemp`` that records raw fds and a
    function to assert all recorded fds are now closed."""
    fds: list[int] = []
    _orig = tempfile.mkstemp

    def _wrapped(*a, **kw):
        fd, path = _orig(*a, **kw)
        fds.append(fd)
        return fd, path

    def _assert_all_closed():
        for fd in fds:
            assert _fd_is_closed(fd), f"fd {fd} is still open"

    return _wrapped, _assert_all_closed


# ═══════════════════════════════════════════════════════════════════════════
# get_data_root
# ═══════════════════════════════════════════════════════════════════════════

class TestGetDataRoot:

    def test_default_returns_data(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            root = get_data_root()
        assert root.name == "data"
        assert root.is_absolute()

    def test_env_var_used(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"FULLPCR_DATA_DIR": td}, clear=True):
                root = get_data_root()
            assert str(root) == str(Path(td).resolve())

    def test_does_not_create_directory(self, tmp_path: Path):
        data_root = tmp_path / "nonexistent_data"
        assert not data_root.exists()
        with mock.patch.dict(os.environ, {"FULLPCR_DATA_DIR": str(data_root)}, clear=True):
            result = get_data_root()
        assert str(result) == str(data_root)
        assert not data_root.exists()


# ═══════════════════════════════════════════════════════════════════════════
# create_run_workspace
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateRunWorkspace:

    def test_creates_all_subdirs(self, tmp_path: Path):
        ws = create_run_workspace(data_root=str(tmp_path))
        assert Path(ws["uploads_dir"]).is_dir()
        assert Path(ws["qc_results_dir"]).is_dir()
        assert Path(ws["qc_spec_results_dir"]).is_dir()
        assert Path(ws["obipcr_results_dir"]).is_dir()
        assert Path(ws["final_results_dir"]).is_dir()

    def test_different_run_ids(self, tmp_path: Path):
        ws1 = create_run_workspace(data_root=str(tmp_path))
        ws2 = create_run_workspace(data_root=str(tmp_path))
        assert ws1["run_id"] != ws2["run_id"]

    def test_run_id_length(self, tmp_path: Path):
        ws = create_run_workspace(data_root=str(tmp_path))
        assert len(ws["run_id"]) == 32

    def test_default_data_root(self):
        import shutil
        ws = create_run_workspace()
        root = get_data_root()
        assert ws["data_root"] == str(root)
        runs_dir = root / "runs"
        if runs_dir.exists():
            shutil.rmtree(str(root), ignore_errors=True)

    def test_dirs_are_absolute(self, tmp_path: Path):
        ws = create_run_workspace(data_root=str(tmp_path))
        for key in [
            "uploads_dir", "qc_results_dir", "qc_spec_results_dir",
            "obipcr_results_dir", "final_results_dir",
        ]:
            assert Path(ws[key]).is_absolute(), f"{key} not absolute"


# ═══════════════════════════════════════════════════════════════════════════
# get_workspace_paths
# ═══════════════════════════════════════════════════════════════════════════

class TestGetWorkspacePaths:

    def test_returns_expected_keys(self):
        paths = get_workspace_paths("abc123", data_root="/tmp/data")
        assert paths["run_id"] == "abc123"
        assert "uploads_dir" in paths

    def test_does_not_create_dirs(self, tmp_path: Path):
        paths = get_workspace_paths("test_run", data_root=str(tmp_path))
        for key in ["uploads_dir", "qc_results_dir", "qc_spec_results_dir",
                     "obipcr_results_dir", "final_results_dir"]:
            assert not Path(paths[key]).exists()


# ═══════════════════════════════════════════════════════════════════════════
# _is_safe_basename
# ═══════════════════════════════════════════════════════════════════════════

class TestIsSafeBasename:

    def test_normal_name(self):
        assert _is_safe_basename("primers.tsv")

    def test_empty_rejected(self):
        assert not _is_safe_basename("")

    def test_unix_traversal_rejected(self):
        assert not _is_safe_basename("../../etc/passwd")

    def test_absolute_path_rejected(self):
        assert not _is_safe_basename("/etc/passwd")

    def test_backslash_rejected(self):
        assert not _is_safe_basename("subdir\\file.fasta")

    def test_windows_traversal_rejected(self):
        assert not _is_safe_basename("..\\..\\etc\\passwd.fasta")

    def test_windows_drive_path_rejected(self):
        assert not _is_safe_basename("C:\\fakepath\\db.fasta")


# ═══════════════════════════════════════════════════════════════════════════
# _classify_extension
# ═══════════════════════════════════════════════════════════════════════════

class TestClassifyExtension:

    @pytest.mark.parametrize("filename,expected", [
        ("database.fasta", ".fasta"),
        ("database.fa", ".fa"),
        ("database.fasta.gz", ".fasta.gz"),
        ("database.fa.gz", ".fa.gz"),
    ])
    def test_valid_extensions(self, filename, expected):
        allowed = ALLOWED_EXTENSIONS[DATABASE_FILE]
        assert _classify_extension(filename, allowed) == expected

    def test_tsv_as_database_rejected(self):
        allowed = ALLOWED_EXTENSIONS[DATABASE_FILE]
        assert _classify_extension("data.tsv", allowed) is None


# ═══════════════════════════════════════════════════════════════════════════
# save_uploaded_file — normal cases
# ═══════════════════════════════════════════════════════════════════════════

class TestSaveUploadedFile:

    @pytest.fixture
    def uploads_dir(self, tmp_path: Path) -> str:
        d = tmp_path / "runs" / "testrun" / "uploads"
        d.mkdir(parents=True)
        return str(d)

    def test_save_primers_tsv(self, uploads_dir):
        content = b"primer_id\tforward\treverse\tmin_length\tmax_length\nP1\tATCG\tGCTA\t100\t200\n"
        result = _save(uploads_dir, content, "primers.tsv", PRIMERS_FILE)
        assert result["status"] == "PASS"
        assert result["file_type"] == PRIMERS_FILE
        assert result["run_id"] == "testrun"
        assert result["file_size"] == len(content)
        assert Path(result["saved_path"]).is_absolute()
        assert Path(result["saved_path"]).name == "primers.tsv"

    def test_save_taxonomy_tsv(self, uploads_dir):
        content = b"taxid\tscientific_name\n123\tHomo sapiens\n"
        result = _save(uploads_dir, content, "taxonomy.tsv", TAXONOMY_FILE)
        assert result["status"] == "PASS"
        assert result["file_type"] == TAXONOMY_FILE
        assert result["run_id"] == "testrun"
        assert Path(result["saved_path"]).name == "taxonomy.tsv"

    @pytest.mark.parametrize("filename", [
        "database.fasta", "database.fa", "database.fasta.gz", "database.fa.gz",
    ])
    def test_database_always_produces_fasta(self, uploads_dir, filename):
        content = b">seq1\nACGT\n"
        is_gz = filename.endswith(".gz")
        data = _gzip_content(content) if is_gz else content
        result = _save(uploads_dir, data, filename, DATABASE_FILE)
        assert result["status"] == "PASS"
        assert result["file_type"] == DATABASE_FILE
        assert result["run_id"] == "testrun"
        assert Path(result["saved_path"]).is_absolute()
        assert Path(result["saved_path"]).name == "database.fasta"
        saved = Path(result["saved_path"]).read_text()
        assert saved == ">seq1\nACGT\n"

    def test_gzip_decompression_preserves_content(self, uploads_dir):
        original = b">seq1\nACGTACGTACGT\n>seq2\nTGCATGCATGCA\n"
        gz_data = _gzip_content(original)
        result = _save(uploads_dir, gz_data, "db.fasta.gz", DATABASE_FILE)
        assert result["status"] == "PASS"
        assert Path(result["saved_path"]).read_bytes() == original

    def test_same_file_obj_saved_twice(self, uploads_dir):
        content = b">seq1\nACGT\n"
        f = io.BytesIO(content)
        f.name = "db.fasta"
        r1 = save_uploaded_file(f, file_type=DATABASE_FILE, uploads_dir=uploads_dir, original_name="db.fasta")
        r2 = save_uploaded_file(f, file_type=DATABASE_FILE, uploads_dir=uploads_dir, original_name="db.fasta")
        assert r1["status"] == "PASS"
        assert r2["status"] == "PASS"
        assert r1["file_size"] == r2["file_size"]
        assert Path(r1["saved_path"]).read_bytes() == content


# ═══════════════════════════════════════════════════════════════════════════
# no read(-1)
# ═══════════════════════════════════════════════════════════════════════════

class _NoBulkReadIO(io.BytesIO):
    def read(self, size: int = -1):
        if size is None or size < 0:
            raise RuntimeError("read(-1) is forbidden — use chunked reads")
        return super().read(size)


class TestNoBulkRead:

    def test_no_bulk_read_used(self, tmp_path: Path):
        uploads = tmp_path / "runs" / "r1" / "uploads"
        uploads.mkdir(parents=True)
        content = b">seq1\n" + b"A" * 500_000 + b"\n"
        f = _NoBulkReadIO(content)
        f.name = "db.fasta"
        result = save_uploaded_file(f, file_type=DATABASE_FILE, uploads_dir=str(uploads), original_name="db.fasta")
        assert result["status"] == "PASS"
        assert result["file_size"] == len(content)


# ═══════════════════════════════════════════════════════════════════════════
# save_uploaded_file — error cases
# ═══════════════════════════════════════════════════════════════════════════

class TestSaveUploadedFileErrors:

    @pytest.fixture
    def uploads_dir(self, tmp_path: Path) -> str:
        d = tmp_path / "runs" / "testrun" / "uploads"
        d.mkdir(parents=True)
        return str(d)

    def test_empty_plain_fasta_fails(self, uploads_dir):
        result = _save(uploads_dir, b"", "primers.tsv", PRIMERS_FILE)
        assert result["status"] == "FAIL"
        assert "为空" in result["error"]

    def test_illegal_extension_rejected(self, uploads_dir):
        result = _save(uploads_dir, b"c", "data.exe", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert "格式不支持" in result["error"]

    def test_unix_traversal_rejected(self, uploads_dir):
        result = _save(uploads_dir, b">x\nA\n", "../../etc/passwd", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert "不安全" in result["error"]

    def test_backslash_rejected(self, uploads_dir):
        result = _save(uploads_dir, b">x\nA\n", "sub\\db.fasta", DATABASE_FILE)
        assert result["status"] == "FAIL"

    def test_windows_drive_rejected(self, uploads_dir):
        result = _save(uploads_dir, b">x\nA\n", "C:\\db.fasta", DATABASE_FILE)
        assert result["status"] == "FAIL"

    def test_empty_original_name_rejected(self, uploads_dir):
        f = io.BytesIO(b"content")
        result = save_uploaded_file(f, file_type=PRIMERS_FILE, uploads_dir=uploads_dir, original_name="")
        assert result["status"] == "FAIL"

    # ── bad gzip ───────────────────────────────────────────────────────

    def test_bad_gzip_rejected(self, uploads_dir):
        result = _save(uploads_dir, b"NOT_A_GZIP_FILE", "db.fasta.gz", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert "解压" in result["error"]

    def test_truncated_gzip_rejected_gracefully(self, uploads_dir):
        """b\"\\x1f\\x8b\\x08\\x00\" is a valid gzip header followed by nothing."""
        truncated = b"\x1f\x8b\x08\x00"
        result = _save(uploads_dir, truncated, "db.fasta.gz", DATABASE_FILE)
        assert result["status"] == "FAIL", f"Expected FAIL, got {result}"
        assert "解压" in result["error"]

    def test_absolute_path_save_rejected(self, uploads_dir):
        result = _save(uploads_dir, b">s\nA\n", "/etc/passwd", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert "不安全" in result["error"]

    def test_path_separator_save_rejected(self, uploads_dir):
        result = _save(uploads_dir, b">s\nA\n", "subdir/db.fasta", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert "不安全" in result["error"]

    def test_unknown_file_type_rejected_with_message(self, uploads_dir):
        f = io.BytesIO(b"x")
        result = save_uploaded_file(f, file_type="unknown", uploads_dir=uploads_dir, original_name="f.tsv")
        assert result["status"] == "FAIL"
        assert "不支持的文件类型" in result["error"]

    def test_tsv_as_database_save_rejected(self, uploads_dir):
        result = _save(uploads_dir, b"col1\tcol2\n", "data.tsv", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert "格式不支持" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════
# existing file preservation
# ═══════════════════════════════════════════════════════════════════════════

class TestExistingFilePreservation:

    @pytest.fixture
    def uploads_dir(self, tmp_path: Path) -> str:
        d = tmp_path / "runs" / "testrun" / "uploads"
        d.mkdir(parents=True)
        return str(d)

    def _write_valid_target(self, uploads_dir: str):
        p = Path(uploads_dir) / "database.fasta"
        p.write_text(">real\nACGT\n")
        return p

    def test_empty_plain_preserves_existing(self, uploads_dir):
        """Empty plain FASTA: FAIL, existing database.fasta untouched."""
        target = self._write_valid_target(uploads_dir)
        result = _save(uploads_dir, b"", "db.fasta", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert target.read_text() == ">real\nACGT\n"
        # No leftover temp files.
        assert list(Path(uploads_dir).glob(".tmp_*")) == []

    def test_empty_gzip_preserves_existing(self, uploads_dir):
        """Empty gzip (zero bytes decompressed): FAIL, existing untouched."""
        target = self._write_valid_target(uploads_dir)
        # A valid gzip with zero-length uncompressed content.
        empty_gz = _gzip_content(b"")
        result = _save(uploads_dir, empty_gz, "db.fasta.gz", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert target.read_text() == ">real\nACGT\n"
        assert list(Path(uploads_dir).glob(".tmp_*")) == []

    def test_truncated_gzip_preserves_existing(self, uploads_dir):
        """Truncated gzip: FAIL, no exception, existing untouched."""
        target = self._write_valid_target(uploads_dir)
        truncated = b"\x1f\x8b\x08\x00"
        result = _save(uploads_dir, truncated, "db.fasta.gz", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert target.read_text() == ">real\nACGT\n"
        assert list(Path(uploads_dir).glob(".tmp_*")) == []

    def test_bad_gzip_preserves_existing(self, uploads_dir):
        """Garbage bytes: FAIL, existing untouched."""
        target = self._write_valid_target(uploads_dir)
        result = _save(uploads_dir, b"NOT_GZIP", "db.fasta.gz", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert target.read_text() == ">real\nACGT\n"
        assert list(Path(uploads_dir).glob(".tmp_*")) == []

    def test_corrupt_deflate_rejected(self, uploads_dir):
        """Valid gzip header + corrupt deflate body must return FAIL, not
        raise zlib.error, and preserve existing file."""
        target = self._write_valid_target(uploads_dir)
        corrupt = (
            b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03"
            + b"\xff" * 32
        )
        result = _save(uploads_dir, corrupt, "corrupt.fa.gz", DATABASE_FILE)
        assert result["status"] == "FAIL", f"Expected FAIL, got {result}"
        assert "解压" in result["error"]
        assert target.read_text() == ">real\nACGT\n"
        assert list(Path(uploads_dir).glob(".tmp_*")) == []

    def test_corrupt_deflate_no_fd_leak(self, uploads_dir):
        """Corrupt deflate must not leak fd."""
        spy, assert_closed = _spy_mkstemp_closes()
        corrupt = (
            b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03"
            + b"\xff" * 32
        )
        with mock.patch("tempfile.mkstemp", spy):
            result = _save(uploads_dir, corrupt, "corrupt.fa.gz", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert_closed()


# ═══════════════════════════════════════════════════════════════════════════
# fd leak tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFdLeak:

    @pytest.fixture
    def uploads_dir(self, tmp_path: Path) -> str:
        d = tmp_path / "runs" / "testrun" / "uploads"
        d.mkdir(parents=True)
        return str(d)

    def test_plain_fasta_no_fd_leak(self, uploads_dir):
        """Plain FASTA save: mkstemp fd must be closed afterward."""
        spy, assert_closed = _spy_mkstemp_closes()
        with mock.patch("tempfile.mkstemp", spy):
            result = _save(uploads_dir, b">seq\nACGT\n", "db.fasta", DATABASE_FILE)
        assert result["status"] == "PASS"
        assert_closed()

    def test_gzip_no_fd_leak(self, uploads_dir):
        """Gzip FASTA save: mkstemp fd must be closed afterward."""
        gz_data = _gzip_content(b">seq\nACGT\n")
        spy, assert_closed = _spy_mkstemp_closes()
        with mock.patch("tempfile.mkstemp", spy):
            result = _save(uploads_dir, gz_data, "db.fasta.gz", DATABASE_FILE)
        assert result["status"] == "PASS"
        assert_closed()

    def test_empty_plain_no_fd_leak(self, uploads_dir):
        """Empty plain FASTA: no fd leak even on failure."""
        spy, assert_closed = _spy_mkstemp_closes()
        with mock.patch("tempfile.mkstemp", spy):
            result = _save(uploads_dir, b"", "db.fasta", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert_closed()

    def test_gzip_failure_no_fd_leak(self, uploads_dir):
        """Bad gzip: no fd leak even on failure."""
        spy, assert_closed = _spy_mkstemp_closes()
        with mock.patch("tempfile.mkstemp", spy):
            result = _save(uploads_dir, b"NOT_GZIP", "db.fasta.gz", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert_closed()

    def test_truncated_gzip_no_fd_leak(self, uploads_dir):
        """Truncated gzip: no fd leak."""
        spy, assert_closed = _spy_mkstemp_closes()
        with mock.patch("tempfile.mkstemp", spy):
            result = _save(uploads_dir, b"\x1f\x8b\x08\x00", "db.fasta.gz", DATABASE_FILE)
        assert result["status"] == "FAIL"
        assert_closed()


# ═══════════════════════════════════════════════════════════════════════════
# flush / fsync verification
# ═══════════════════════════════════════════════════════════════════════════

class TestFlushFsync:

    def test_gzip_path_calls_fsync(self, tmp_path):
        """Verify os.fsync is called during gzip save."""
        uploads = tmp_path / "runs" / "r1" / "uploads"
        uploads.mkdir(parents=True)
        gz_data = _gzip_content(b">seq\nACGT\n")

        with mock.patch("os.fsync", wraps=os.fsync) as spy_fsync:
            result = _save(str(uploads), gz_data, "db.fasta.gz", DATABASE_FILE)
        assert result["status"] == "PASS"
        assert spy_fsync.call_count >= 1, "os.fsync was not called"

    def test_plain_path_calls_fsync(self, tmp_path):
        """Verify os.fsync is called during plain FASTA save."""
        uploads = tmp_path / "runs" / "r1" / "uploads"
        uploads.mkdir(parents=True)

        with mock.patch("os.fsync", wraps=os.fsync) as spy_fsync:
            result = _save(str(uploads), b">seq\nACGT\n", "db.fasta", DATABASE_FILE)
        assert result["status"] == "PASS"
        assert spy_fsync.call_count >= 1, "os.fsync was not called"


# ═══════════════════════════════════════════════════════════════════════════
# midstream read failure
# ═══════════════════════════════════════════════════════════════════════════

class _FailingReadIO(io.BytesIO):
    """BytesIO that raises OSError after *fail_after* bytes have been read."""

    def __init__(self, data: bytes, fail_after: int):
        super().__init__(data)
        self._fail_after = fail_after
        self._read_so_far = 0

    def read(self, size=-1):
        if self._read_so_far >= self._fail_after:
            raise OSError("Read interrupted midstream")
        chunk = super().read(size)
        self._read_so_far += len(chunk)
        return chunk


class TestMidstreamReadFailure:

    @pytest.fixture
    def uploads_dir(self, tmp_path: Path) -> str:
        d = tmp_path / "runs" / "testrun" / "uploads"
        d.mkdir(parents=True)
        return str(d)

    def test_midstream_fails_explicitly(self, uploads_dir):
        """Midstream read failure must return FAIL, not pass silently."""
        # Generate data larger than one chunk so the read fails mid-stream.
        data = b">header\n" + b"A" * 500_000 + b"\n"
        f = _FailingReadIO(data, fail_after=100_000)
        f.name = "db.fasta"
        result = save_uploaded_file(
            f, file_type=DATABASE_FILE, uploads_dir=uploads_dir, original_name="db.fasta",
        )
        assert result["status"] == "FAIL", f"Expected FAIL, got {result}"
        assert list(Path(uploads_dir).glob(".tmp_*")) == []

    def test_midstream_preserves_existing(self, uploads_dir):
        """Midstream failure must not overwrite existing target."""
        existing = Path(uploads_dir) / "database.fasta"
        existing.write_text(">real\nACGT\n")

        data = b">header\n" + b"A" * 500_000 + b"\n"
        f = _FailingReadIO(data, fail_after=100_000)
        f.name = "db.fasta"
        result = save_uploaded_file(
            f, file_type=DATABASE_FILE, uploads_dir=uploads_dir, original_name="db.fasta",
        )
        assert result["status"] == "FAIL"
        assert existing.read_text() == ">real\nACGT\n"
        assert list(Path(uploads_dir).glob(".tmp_*")) == []


# ═══════════════════════════════════════════════════════════════════════════
# write failure cleanup
# ═══════════════════════════════════════════════════════════════════════════

class TestSaveUploadedFileWriteFailure:

    def test_no_leftover_files_on_replace_failure(self, tmp_path):
        uploads = tmp_path / "runs" / "run_E" / "uploads"
        uploads.mkdir(parents=True)

        def _failing_replace(src, dst):
            raise OSError("Disk full")

        f = io.BytesIO(b">seq\nACGT\n")
        f.name = "db.fasta"

        with mock.patch("os.replace", _failing_replace):
            result = save_uploaded_file(
                f, file_type=DATABASE_FILE, uploads_dir=str(uploads), original_name="db.fasta",
            )
        assert result["status"] == "FAIL"
        assert "保存失败" in result["error"]
        target = uploads / "database.fasta"
        assert not target.exists()
        assert list(uploads.glob(".tmp_*")) == []


# ═══════════════════════════════════════════════════════════════════════════
# isolation
# ═══════════════════════════════════════════════════════════════════════════

class TestSaveUploadedFileIsolation:

    def test_different_runs_dont_overwrite(self, tmp_path):
        u1 = str(tmp_path / "runs" / "run_A" / "uploads"); Path(u1).mkdir(parents=True)
        u2 = str(tmp_path / "runs" / "run_B" / "uploads"); Path(u2).mkdir(parents=True)
        r1 = _save(u1, b">seq1\nACGT\n", "db.fasta", DATABASE_FILE)
        r2 = _save(u2, b">seq2\nTGCA\n", "db.fasta", DATABASE_FILE)
        assert r1["status"] == "PASS"
        assert r2["status"] == "PASS"
        assert r1["saved_path"] != r2["saved_path"]
        assert Path(r1["saved_path"]).read_bytes() == b">seq1\nACGT\n"
        assert Path(r2["saved_path"]).read_bytes() == b">seq2\nTGCA\n"

    def test_path_is_within_uploads(self, tmp_path):
        u = str(tmp_path / "runs" / "run_D" / "uploads"); Path(u).mkdir(parents=True)
        r = _save(u, b">s\nACGT\n", "db.fasta", DATABASE_FILE)
        Path(r["saved_path"]).resolve().relative_to(Path(u).resolve())


# ═══════════════════════════════════════════════════════════════════════════
# ALLOWED_EXTENSIONS
# ═══════════════════════════════════════════════════════════════════════════

class TestAllowedExtensions:

    def test_all_keys_present(self):
        assert PRIMERS_FILE in ALLOWED_EXTENSIONS
        assert TAXONOMY_FILE in ALLOWED_EXTENSIONS
        assert DATABASE_FILE in ALLOWED_EXTENSIONS

    def test_database_accepts_all_fasta_variants(self):
        assert ".fasta" in ALLOWED_EXTENSIONS[DATABASE_FILE]
        assert ".fa" in ALLOWED_EXTENSIONS[DATABASE_FILE]
        assert ".fasta.gz" in ALLOWED_EXTENSIONS[DATABASE_FILE]
        assert ".fa.gz" in ALLOWED_EXTENSIONS[DATABASE_FILE]
