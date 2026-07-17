"""GUI helpers for fullpcr Streamlit app.

Provides environment-check utilities that report the availability
and version of Python, fullpcr, obipcr, and mfeprimer, as well as
input-file validation functions used by the Inputs page.
"""

from __future__ import annotations

import csv
import gzip
import os
import signal
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, MutableMapping
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as get_package_version
from pathlib import Path

import pandas as pd


_COMMAND_POLL_SECONDS = 1.0


# ── Chinese translation helpers (display-layer only) ──────────────────


def translate_status(value: str | None) -> str:
    """Translate generic PASS/FAIL/WARN/TIMEOUT/CANCELLED to Chinese.

    Used for command execution results, validation status, and
    file-load status — **not** for final_status (RECOMMENDED, etc.)
    or qc_status/spec_status sub-warnings.

    Args:
        value: Status string such as ``"PASS"``, ``"FAIL"``, ``"WARN"``,
            ``"TIMEOUT"``, ``"CANCELLED"``, or ``None``.

    Returns:
        Chinese label, or the original string when no mapping exists.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)
    mapping: dict[str, str] = {
        "PASS": "正常",
        "FAIL": "异常",
        "WARN": "警告",
        "TIMEOUT": "超时",
        "CANCELLED": "用户已终止",
    }
    return mapping.get(value, value)


def translate_recommendation(value: str | None) -> str:
    """Translate final_status recommendation tier to Chinese.

    Used for the ``final_status`` column in ``primer_rank.tsv``
    (RECOMMENDED / ACCEPTABLE_WITH_WARNINGS / NOT_RECOMMENDED /
    NEEDS_REVIEW).  Applied only on the display copy — the original
    TSV is never modified.

    Args:
        value: One of the four ``final_status`` strings, or ``None``.

    Returns:
        Chinese label, or the original string when no mapping exists.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)
    mapping: dict[str, str] = {
        "RECOMMENDED": "推荐",
        "ACCEPTABLE_WITH_WARNINGS": "可用但有警告",
        "NOT_RECOMMENDED": "不推荐",
        "NEEDS_REVIEW": "需要人工检查",
    }
    return mapping.get(value, value)


def translate_warning_label(value: str | None) -> str:
    """Translate WARN_* / FAIL_* sub-status labels to Chinese.

    Used for qc_status and spec_status sub-strings (e.g.
    ``"WARN_DIMER"``, ``"FAIL_SPEC"``).  Supports semicolon-delimited
    compound values such as ``"WARN_DIMER; WARN_HAIRPIN"``.

    Args:
        value: A single status token, a ``"; "``-delimited compound
            string, or ``None``.

    Returns:
        Comma-joined Chinese labels for compound values, a single
        Chinese label for a known token, or the original string when
        no mapping exists.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)

    mapping: dict[str, str] = {
        "PASS": "通过",
        "WARN_DIMER": "引物二聚体警告",
        "WARN_HAIRPIN": "发卡结构警告",
        "WARN_TM_DIFF": "Tm 差异偏大",
        "WARN_NO_AMP": "未检测到扩增",
        "WARN_MULTI_AMP": "存在多个扩增产物",
        "WARN_SIZE": "扩增片段长度异常",
        "WARN_OVERAMP": "过度扩增",
        "FAIL_PARSE": "解析失败",
        "FAIL_DEGENERATE_EXPLOSION": "简并引物展开爆炸",
        "FAIL_INDEX": "索引构建失败",
        "FAIL_SPEC": "特异性分析失败",
        "NO_DEGENERACY": "无简并碱基",
        "EXPANDED": "已展开",
        "INVALID_BASE": "无效碱基",
        "OK": "正常",
        "NA": "无数据",
    }

    # Compound status like "WARN_DIMER; WARN_HAIRPIN"
    if "; " in value:
        parts = value.split("; ")
        translated = [mapping.get(p, p) for p in parts]
        return "；".join(translated)

    return mapping.get(value, value)


# ── environment status (Phase 7A) ─────────────────────────────────────────


def collect_environment_status() -> dict:
    """Run all environment checks and return a structured status dict.

    Calls :func:`get_python_info`, :func:`get_fullpcr_info`, and
    :func:`check_command_available` for obipcr and MFEprimer — each
    via ``subprocess.run(list[str])`` with no ``shell=True``.

    Returns:
        dict with keys:

        - ``python``: result of :func:`get_python_info`
        - ``fullpcr``: result of :func:`get_fullpcr_info`
        - ``obipcr``: result of ``check_command_available(["obipcr", "--version"])``
        - ``mfeprimer``: result of ``check_command_available(["mfeprimer", "version"])``
        - ``cwd``: ``os.getcwd()``
        - ``ok_count`` (int): number of available tools (0–4)
        - ``fail_count`` (int): 4 – ok_count
        - ``all_ok`` (bool): ``True`` when all four tools are available
        - ``checked_at`` (float): ``time.time()`` when this result was collected
    """
    py_info = get_python_info()
    fp_info = get_fullpcr_info()
    obi = check_command_available(["obipcr", "--version"])
    mfe = check_command_available(["mfeprimer", "version"])

    ok_count = sum([
        1,  # Python is always available
        1 if fp_info["importable"] else 0,
        1 if obi["available"] else 0,
        1 if mfe["available"] else 0,
    ])

    return {
        "python": py_info,
        "fullpcr": fp_info,
        "obipcr": obi,
        "mfeprimer": mfe,
        "cwd": os.getcwd(),
        "ok_count": ok_count,
        "fail_count": 4 - ok_count,
        "all_ok": ok_count == 4,
        "checked_at": time.time(),
    }


def should_refresh_environment_status(
    checked_at: float | None,
    now: float,
    ttl_seconds: int = 60,
) -> bool:
    """Return ``True`` when the environment status should be re-collected.

    Args:
        checked_at: ``time.time()`` value from the last collection, or
            ``None`` when no previous collection exists.
        now: Current ``time.time()`` value.
        ttl_seconds: Maximum age in seconds before a refresh is needed
            (default 60).

    Returns:
        ``True`` when *checked_at* is ``None`` (never collected) or
        ``now - checked_at > ttl_seconds``.
    """
    if checked_at is None:
        return True
    return (now - checked_at) > ttl_seconds


def check_command_available(command: list[str]) -> dict:
    """Check whether an external command is available.

    Uses ``subprocess.run(list[str])`` — no ``shell=True``.

    Args:
        command: The command plus arguments as a list of strings.
                 Example: ``["obipcr", "--version"]``.

    Returns:
        dict with keys:
        - ``available`` (bool): ``True`` if the command ran successfully.
        - ``version`` (str | None): stdout first line on success.
        - ``error`` (str | None): stderr or exception message on failure.
    """
    executable = command[0]
    if shutil.which(executable) is None:
        return {
            "available": False,
            "version": None,
            "error": f"'{executable}' not found on PATH",
        }

    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return {
            "available": False,
            "version": None,
            "error": f"'{executable}' executable not found",
        }
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "version": None,
            "error": f"'{executable}' timed out after 30 s",
        }
    except OSError as exc:
        return {
            "available": False,
            "version": None,
            "error": f"'{executable}': OS error — {exc}",
        }

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    # Many tools report version on stderr (e.g. obipcr --version).
    version_line = stdout.split("\n")[0] if stdout else None

    if proc.returncode != 0:
        error_detail = stderr or stdout or f"exit code {proc.returncode}"
        return {
            "available": False,
            "version": version_line,
            "error": error_detail,
        }

    return {
        "available": True,
        "version": version_line,
        "error": None,
    }


def get_python_info() -> dict:
    """Return information about the current Python interpreter.

    Returns:
        dict with keys:
        - ``version`` (str): ``sys.version`` string.
        - ``executable`` (str): Path to the Python interpreter.
    """
    return {
        "version": sys.version,
        "executable": sys.executable,
    }


def get_fullpcr_info() -> dict:
    """Return information about the fullpcr package.

    Returns:
        dict with keys:
        - ``importable`` (bool): ``True`` if fullpcr can be imported.
        - ``version`` (str | None): Installed version, or ``None``.
        - ``path`` (str | None): Package filesystem path, or ``None``.
        - ``error`` (str | None): Error message when import fails.
    """
    try:
        import fullpcr  # noqa: F811

        pkg_version = get_package_version("fullpcr")
        pkg_path = getattr(fullpcr, "__path__", [None])[0]
        return {
            "importable": True,
            "version": pkg_version,
            "path": pkg_path,
            "error": None,
        }
    except ImportError as exc:
        return {
            "importable": False,
            "version": None,
            "path": None,
            "error": str(exc),
        }
    except PackageNotFoundError:
        return {
            "importable": True,
            "version": "unknown (editable install?)",
            "path": None,
            "error": None,
        }


# ── input validation ────────────────────────────────────────────────────

_PRIMERS_REQUIRED = ["primer_id", "forward", "reverse", "min_length", "max_length"]
_TAXONOMY_REQUIRED = ["taxid", "scientific_name"]
_FASTA_EXTENSIONS = {".fasta", ".fa", ".fasta.gz", ".fa.gz"}


def validate_file_exists(path: str) -> dict:
    """Check whether a file path exists and is a regular file.

    Args:
        path: Filesystem path to check.

    Returns:
        dict with ``status`` (PASS/FAIL), ``exists``, ``path``, ``error``.
    """
    if not path:
        return {
            "status": "FAIL",
            "path": path,
            "exists": False,
            "error": "No path provided",
        }
    p = Path(path)
    if p.is_file():
        return {
            "status": "PASS",
            "path": str(p),
            "exists": True,
            "error": None,
        }
    return {
        "status": "FAIL",
        "path": str(p),
        "exists": False,
        "error": f"File not found: {path}",
    }


def validate_primers_file(path: str) -> dict:
    """Validate a primers TSV file.

    Checks file existence, required fields, primer count, and returns a
    preview of the first 10 data rows.

    Args:
        path: Path to ``primers.tsv``.

    Returns:
        dict with ``status``, ``file_exists``, ``required_fields``,
        ``missing_fields``, ``primer_count``, ``preview``, ``error``.
    """
    result: dict = {
        "status": "FAIL",
        "path": path,
        "file_exists": False,
        "required_fields": list(_PRIMERS_REQUIRED),
        "missing_fields": [],
        "primer_count": None,
        "preview": [],
        "error": None,
    }

    if not path:
        result["error"] = "No path provided"
        return result

    p = Path(path)
    if not p.is_file():
        result["error"] = f"File not found: {path}"
        return result

    result["file_exists"] = True

    try:
        with open(p, encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t")
            rows = list(reader)
    except OSError as exc:
        result["error"] = f"Cannot read file: {exc}"
        return result

    if len(rows) < 2:
        result["error"] = "File must have a header row and at least one data row"
        return result

    header = [h.strip() for h in rows[0]]
    missing = [f for f in _PRIMERS_REQUIRED if f not in header]
    result["missing_fields"] = missing

    if missing:
        result["status"] = "FAIL"
        result["error"] = f"Missing required fields: {', '.join(missing)}"
        # Still return preview of what we can parse.
        result["preview"] = _build_tsv_preview(rows, header)
        return result

    data_rows = rows[1:]
    result["primer_count"] = len(data_rows)
    result["preview"] = _build_tsv_preview(rows, header)
    result["status"] = "PASS"
    return result


def validate_database_file(path: str) -> dict:
    """Validate a FASTA database file.

    Supports ``.fasta``, ``.fa``, ``.fasta.gz``, ``.fa.gz``.

    Args:
        path: Path to the FASTA or FASTA.GZ file.

    Returns:
        dict with ``status``, ``file_exists``, ``format``, ``record_count``,
        ``total_bases``, ``error``.
    """
    result: dict = {
        "status": "FAIL",
        "path": path,
        "file_exists": False,
        "format": None,
        "record_count": None,
        "total_bases": None,
        "error": None,
    }

    if not path:
        result["error"] = "No path provided"
        return result

    p = Path(path)
    if not p.is_file():
        result["error"] = f"File not found: {path}"
        return result

    result["file_exists"] = True
    suffix = p.suffix.lower()
    if p.name.lower().endswith(".fasta.gz") or p.name.lower().endswith(".fa.gz"):
        suffix = ".fa.gz"

    if suffix not in _FASTA_EXTENSIONS:
        result["error"] = (
            f"Unsupported format '{suffix}'. "
            f"Expected: {', '.join(sorted(_FASTA_EXTENSIONS))}"
        )
        return result

    is_gz = suffix in {".fasta.gz", ".fa.gz"}
    result["format"] = suffix

    try:
        record_count, total_bases = _count_fasta(p, is_gz)
    except OSError as exc:
        result["error"] = f"Cannot read file: {exc}"
        return result

    result["record_count"] = record_count
    result["total_bases"] = total_bases

    if record_count == 0:
        result["status"] = "FAIL"
        result["error"] = "FASTA file has 0 records"
    else:
        result["status"] = "PASS"

    return result


def validate_taxonomy_file(path: str) -> dict:
    """Validate a taxonomy TSV file.

    Checks file existence, required fields (taxid, scientific_name),
    record count, unique species count, and returns a preview.

    Args:
        path: Path to ``taxonomy.tsv``.

    Returns:
        dict with ``status``, ``file_exists``, ``required_fields``,
        ``missing_fields``, ``record_count``, ``unique_species``,
        ``preview``, ``error``.
    """
    result: dict = {
        "status": "FAIL",
        "path": path,
        "file_exists": False,
        "required_fields": list(_TAXONOMY_REQUIRED),
        "missing_fields": [],
        "record_count": None,
        "unique_species": None,
        "preview": [],
        "error": None,
    }

    if not path:
        result["error"] = "No path provided"
        return result

    p = Path(path)
    if not p.is_file():
        result["error"] = f"File not found: {path}"
        return result

    result["file_exists"] = True

    try:
        with open(p, encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t")
            rows = list(reader)
    except OSError as exc:
        result["error"] = f"Cannot read file: {exc}"
        return result

    if len(rows) < 2:
        result["error"] = "File must have a header row and at least one data row"
        return result

    header = [h.strip() for h in rows[0]]
    missing = [f for f in _TAXONOMY_REQUIRED if f not in header]
    result["missing_fields"] = missing

    if missing:
        result["status"] = "FAIL"
        result["error"] = f"Missing required fields: {', '.join(missing)}"
        result["preview"] = _build_tsv_preview(rows, header)
        return result

    data_rows = rows[1:]
    result["record_count"] = len(data_rows)
    result["preview"] = _build_tsv_preview(rows, header)

    # Unique species — look for 'species' column (optional but useful).
    species_idx = None
    for idx, col in enumerate(header):
        if col.lower() == "species":
            species_idx = idx
            break

    if species_idx is not None:
        species_values: set[str] = set()
        for row in data_rows:
            if species_idx < len(row):
                val = row[species_idx].strip()
                if val:
                    species_values.add(val)
        result["unique_species"] = len(species_values)

    result["status"] = "PASS"
    return result


def validate_output_directory(path: str) -> dict:
    """Validate an output root directory path.

    Does **not** create or delete any directory.

    Args:
        path: Desired output directory path.

    Returns:
        dict with ``status`` (PASS/WARN), ``exists``, ``will_create``,
        ``path``, ``error``.
    """
    result: dict = {
        "status": "WARN",
        "path": path,
        "exists": False,
        "will_create": False,
        "error": None,
    }

    if not path:
        result["error"] = "No path provided"
        result["status"] = "FAIL"
        return result

    p = Path(path)
    if p.is_dir():
        result["status"] = "PASS"
        result["exists"] = True
        return result

    if p.exists() and not p.is_dir():
        result["status"] = "FAIL"
        result["error"] = f"Path exists but is not a directory: {path}"
        return result

    # Path does not exist — will be created at run time.
    result["will_create"] = True
    return result


# ── internal helpers ─────────────────────────────────────────────────────


def _build_tsv_preview(rows: list[list[str]], header: list[str]) -> list[list[str]]:
    """Build a preview list: header + up to 10 data rows."""
    preview = [header]
    preview.extend(rows[1:11])
    return preview


def _count_fasta(path: Path, is_gz: bool) -> tuple[int, int]:
    """Count FASTA records and bases, supporting plain and gzipped files.

    Returns:
        (record_count, total_bases).
    """
    if is_gz:
        fh = gzip.open(path, "rt", encoding="utf-8")
    else:
        fh = open(path, encoding="utf-8")  # noqa: SIM115

    record_count = 0
    total_bases = 0
    try:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(">"):
                record_count += 1
            else:
                total_bases += len(stripped)
    finally:
        fh.close()

    return record_count, total_bases


# ── workflow command builders ────────────────────────────────────────────


def build_qc_pre_command(
    *,
    primers: str = "",
    outdir: str = "",
    thermo: bool = True,
    dimer: bool = True,
    hairpin: bool = True,
    degen: bool = True,
    max_degenerate_variants: int = 256,
    score: int = 5,
    mismatch: int = 2,
    dg: float = -5.0,
    tm: float = 50.0,
    timeout: int | None = None,
) -> list[str]:
    """Build ``python -m fullpcr qc-pre`` command as list[str].

    Boolean flags are only included when ``True``.
    """
    cmd: list[str] = ["python3", "-m", "fullpcr", "qc-pre"]

    if primers:
        cmd.extend(["--primers", primers])
    if outdir:
        cmd.extend(["--outdir", outdir])

    if thermo:
        cmd.append("--thermo")
    if dimer:
        cmd.append("--dimer")
    if hairpin:
        cmd.append("--hairpin")
    if degen:
        cmd.append("--degen")

    cmd.extend(["--max-degenerate-variants", str(max_degenerate_variants)])
    cmd.extend(["--score", str(score)])
    cmd.extend(["--mismatch", str(mismatch)])
    cmd.extend(["--dg", str(dg)])
    cmd.extend(["--tm", str(tm)])

    if timeout is not None:
        cmd.extend(["--timeout", str(timeout)])

    return cmd


def build_qc_summary_command(
    *,
    qc_dir: str = "",
) -> list[str]:
    """Build ``python -m fullpcr qc-summary`` command as list[str]."""
    cmd: list[str] = ["python3", "-m", "fullpcr", "qc-summary"]

    if qc_dir:
        cmd.extend(["--qc-dir", qc_dir])

    return cmd


def build_qc_spec_command(
    *,
    primers: str = "",
    database: str = "",
    outdir: str = "",
    min_size: int | None = 80,
    max_size: int = 500,
    tm: float = 50.0,
    max_tm: float = 100.0,
    mismatch: int = 2,
    mis_start: int | None = None,
    mis_end: int | None = None,
    cpu: int = 4,
    kvalue: int = 9,
    bind: bool = False,
    cut_primer: bool = False,
    mono: float | None = None,
    diva: float | None = None,
    dntp: float | None = None,
    oligo: float | None = None,
    timeout: int | None = None,
    force: bool = True,
) -> list[str]:
    """Build ``python -m fullpcr qc-spec`` command as list[str]."""
    cmd: list[str] = ["python3", "-m", "fullpcr", "qc-spec"]

    if primers:
        cmd.extend(["--primers", primers])
    if database:
        cmd.extend(["--database", database])
    if outdir:
        cmd.extend(["--outdir", outdir])

    if min_size is not None:
        cmd.extend(["--min-size", str(min_size)])
    cmd.extend(["--max-size", str(max_size)])
    cmd.extend(["--tm", str(tm)])
    cmd.extend(["--max-tm", str(max_tm)])
    cmd.extend(["--mismatch", str(mismatch)])
    cmd.extend(["--cpu", str(cpu)])
    cmd.extend(["--kvalue", str(kvalue)])

    if mis_start is not None:
        cmd.extend(["--mis-start", str(mis_start)])
    if mis_end is not None:
        cmd.extend(["--mis-end", str(mis_end)])
    if bind:
        cmd.append("--bind")
    if cut_primer:
        cmd.append("--cut-primer")
    if mono is not None:
        cmd.extend(["--mono", str(mono)])
    if diva is not None:
        cmd.extend(["--diva", str(diva)])
    if dntp is not None:
        cmd.extend(["--dntp", str(dntp)])
    if oligo is not None:
        cmd.extend(["--oligo", str(oligo)])

    if timeout is not None:
        cmd.extend(["--timeout", str(timeout)])
    if force:
        cmd.append("--force")

    return cmd


def build_obipcr_run_command(
    *,
    primers: str = "",
    database: str = "",
    outdir: str = "",
    taxonomy: str = "",
    mismatches: str = "0,1,2",
    circular: bool = True,
    summarize: bool = True,
    report: bool = True,
    force: bool = True,
    timeout: int | None = None,
) -> list[str]:
    """Build ``python -m fullpcr run`` command as list[str]."""
    cmd: list[str] = ["python3", "-m", "fullpcr", "run"]

    if primers:
        cmd.extend(["--primers", primers])
    if database:
        cmd.extend(["--database", database])
    if outdir:
        cmd.extend(["--outdir", outdir])
    if taxonomy:
        cmd.extend(["--taxonomy", taxonomy])
    if mismatches:
        cmd.extend(["--mismatches", mismatches])

    if circular:
        cmd.append("--circular")
    if summarize:
        cmd.append("--summarize")
    if report:
        cmd.append("--report")
    if force:
        cmd.append("--force")

    if timeout is not None:
        cmd.extend(["--timeout", str(timeout)])

    return cmd


def build_final_report_command(
    *,
    obipcr_dir: str = "",
    qc_dir: str = "",
    spec_dir: str = "",
    outdir: str = "",
) -> list[str]:
    """Build ``python -m fullpcr final-report`` command as list[str]."""
    cmd: list[str] = ["python3", "-m", "fullpcr", "final-report"]

    if obipcr_dir:
        cmd.extend(["--obipcr-dir", obipcr_dir])
    if qc_dir:
        cmd.extend(["--qc-dir", qc_dir])
    if spec_dir:
        cmd.extend(["--spec-dir", spec_dir])
    if outdir:
        cmd.extend(["--outdir", outdir])

    return cmd


def run_gui_command(
    command: list[str],
    timeout: int | float | None = None,
    *,
    cancel_requested: Callable[[], bool] | None = None,
    on_process_started: Callable[[int], None] | None = None,
    on_poll: Callable[[int], None] | None = None,
) -> dict:
    """Execute a CLI command in its own process group.

    Args:
        command: The command as ``list[str]``.
        timeout: Timeout in seconds, or ``None`` to wait without a deadline.
        cancel_requested: Optional callback checked while an observed command
            is running.  A true value stops the complete process group.
        on_process_started: Optional callback receiving the new process-group
            id immediately after the command starts.
        on_poll: Optional best-effort observation callback receiving the
            process-group id after each bounded wait.

    Returns:
        dict with ``status`` (PASS/FAIL/TIMEOUT/CANCELLED), ``returncode``,
        ``stdout``, ``stderr``, ``command``, ``message``.
    """
    result: dict = {
        "status": "FAIL",
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "command": command,
        "message": "",
    }

    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            start_new_session=True,
        )
    except FileNotFoundError:
        result["status"] = "FAIL"
        result["message"] = f"Executable not found: {command[0]}"
        return result
    except OSError as exc:
        result["status"] = "FAIL"
        result["message"] = f"OS error: {exc}"
        return result

    if on_process_started is not None:
        try:
            on_process_started(proc.pid)
        except Exception:
            # Monitoring must never turn a healthy analysis into a failure.
            pass

    def stop_process_group() -> tuple[str, str, str]:
        cleanup_error = ""
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            cleanup_error = f"; process-group cleanup error: {exc}"

        try:
            stopped_stdout, stopped_stderr = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                cleanup_error = f"; process-group cleanup error: {exc}"
                try:
                    proc.kill()
                except OSError:
                    pass
            stopped_stdout, stopped_stderr = proc.communicate()
        return stopped_stdout or "", stopped_stderr or "", cleanup_error

    observed = cancel_requested is not None or on_poll is not None
    if observed:
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        while True:
            if cancel_requested is not None and cancel_requested():
                stdout, stderr, cleanup_error = stop_process_group()
                result.update(
                    {
                        "status": "CANCELLED",
                        "returncode": proc.returncode,
                        "stdout": stdout,
                        "stderr": stderr,
                        "message": f"Analysis cancelled by user{cleanup_error}",
                    }
                )
                return result

            wait_seconds = _COMMAND_POLL_SECONDS
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    stdout, stderr, cleanup_error = stop_process_group()
                    result.update(
                        {
                            "status": "TIMEOUT",
                            "returncode": proc.returncode,
                            "stdout": stdout,
                            "stderr": stderr,
                            "message": (
                                f"Command timed out after {timeout} s"
                                f"{cleanup_error}"
                            ),
                        }
                    )
                    return result
                wait_seconds = min(wait_seconds, remaining)
            try:
                stdout, stderr = proc.communicate(timeout=wait_seconds)
                break
            except subprocess.TimeoutExpired:
                if on_poll is not None:
                    try:
                        on_poll(proc.pid)
                    except Exception:
                        pass
                continue
    else:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stdout, stderr, cleanup_error = stop_process_group()
            result["status"] = "TIMEOUT"
            result["returncode"] = proc.returncode
            result["stdout"] = stdout
            result["stderr"] = stderr
            result["message"] = (
                f"Command timed out after {timeout} s{cleanup_error}"
            )
            return result

    result["returncode"] = proc.returncode
    result["stdout"] = stdout
    result["stderr"] = stderr

    if proc.returncode == 0:
        result["status"] = "PASS"
        result["message"] = "Command completed successfully"
    else:
        result["status"] = "FAIL"
        result["message"] = f"Command exited with code {proc.returncode}"

    return result


# ── result reading (Phase 4) ──────────────────────────────────────────────


def load_tsv_file(path: str) -> dict:
    """Read a TSV file into a pandas DataFrame.

    Args:
        path: Path to the TSV file.

    Returns:
        dict with keys:
        - ``status`` (PASS/FAIL)
        - ``df`` (pandas.DataFrame | None)
        - ``row_count`` (int | None)
        - ``columns`` (list[str] | None)
        - ``error`` (str | None)
    """
    result: dict = {
        "status": "FAIL",
        "path": path,
        "df": None,
        "row_count": None,
        "columns": None,
        "error": None,
    }

    if not path:
        result["error"] = "No path provided"
        return result

    p = Path(path)
    if not p.is_file():
        result["error"] = f"File not found: {path}"
        return result

    try:
        df = pd.read_csv(p, sep="\t", dtype=str)
    except Exception as exc:
        result["error"] = f"Failed to parse TSV: {exc}"
        return result

    if df.empty:
        result["status"] = "FAIL"
        result["error"] = "File exists but contains no data rows"
        result["row_count"] = 0
        result["columns"] = list(df.columns)
        return result

    result["status"] = "PASS"
    result["df"] = df
    result["row_count"] = len(df)
    result["columns"] = list(df.columns)
    return result


def load_markdown_file(path: str) -> dict:
    """Read a Markdown file as a string.

    Args:
        path: Path to the ``.md`` file.

    Returns:
        dict with keys:
        - ``status`` (PASS/FAIL/WARN)
        - ``content`` (str | None)
        - ``error`` (str | None)
    """
    result: dict = {
        "status": "FAIL",
        "path": path,
        "content": None,
        "error": None,
    }

    if not path:
        result["error"] = "No path provided"
        return result

    p = Path(path)
    if not p.is_file():
        result["error"] = f"File not found: {path}"
        return result

    try:
        content = p.read_text(encoding="utf-8")
    except OSError as exc:
        result["error"] = f"Cannot read file: {exc}"
        return result

    if not content.strip():
        result["status"] = "WARN"
        result["content"] = content
        result["error"] = "File is empty"
        return result

    result["status"] = "PASS"
    result["content"] = content
    return result


def load_primer_rank(path: str) -> dict:
    """Load ``primer_rank.tsv`` via ``load_tsv_file``.

    Convenience wrapper — identical behaviour to ``load_tsv_file``.
    """
    return load_tsv_file(path)


def summarize_primer_rank(df: pd.DataFrame) -> dict:
    """Extract summary statistics from the primer rank DataFrame.

    Args:
        df: DataFrame loaded from ``primer_rank.tsv``.

    Returns:
        dict with keys:
        - ``top_primer`` (str | None)
        - ``top_final_score`` (float | None)
        - ``recommended_count`` (int)
        - ``not_recommended_count`` (int)
        - ``acceptable_count`` (int)
        - ``needs_review_count`` (int)
        - ``final_statuses`` (dict[str, int])
        - ``error`` (str | None)
    """
    result: dict = {
        "top_primer": None,
        "top_final_score": None,
        "recommended_count": 0,
        "not_recommended_count": 0,
        "acceptable_count": 0,
        "needs_review_count": 0,
        "final_statuses": {},
        "error": None,
    }

    if df is None or df.empty:
        result["error"] = "No data to summarize"
        return result

    # Top primer by final_score
    if "final_score" in df.columns and "primer_id" in df.columns:
        try:
            scores = pd.to_numeric(df["final_score"], errors="coerce")
            best_idx = scores.idxmax()
            if not pd.isna(best_idx):
                result["top_primer"] = str(df.loc[best_idx, "primer_id"])
                result["top_final_score"] = float(scores[best_idx])
        except (ValueError, KeyError):
            pass

    # Status counts
    if "final_status" in df.columns:
        statuses = df["final_status"].fillna("NEEDS_REVIEW").astype(str)
        counts = statuses.value_counts().to_dict()
        result["final_statuses"] = {str(k): int(v) for k, v in counts.items()}
        result["recommended_count"] = int(counts.get("RECOMMENDED", 0))
        result["not_recommended_count"] = int(counts.get("NOT_RECOMMENDED", 0))
        result["acceptable_count"] = int(counts.get("ACCEPTABLE_WITH_WARNINGS", 0))
        result["needs_review_count"] = int(counts.get("NEEDS_REVIEW", 0))

    return result


def summarize_status_counts(df: pd.DataFrame, column: str) -> dict:
    """Count occurrences of each unique value in *column*.

    Args:
        df: A pandas DataFrame.
        column: Column name to summarize.

    Returns:
        dict with keys:
        - ``counts`` (dict[str, int] | None)
        - ``total`` (int)
        - ``error`` (str | None)
    """
    result: dict = {
        "counts": None,
        "total": 0,
        "error": None,
    }

    if df is None or df.empty:
        result["error"] = "No data to summarize"
        return result

    if column not in df.columns:
        result["error"] = f"Column '{column}' not found in data. Available: {', '.join(df.columns)}"
        return result

    counts = df[column].fillna("NA").astype(str).value_counts().to_dict()
    result["counts"] = {str(k): int(v) for k, v in counts.items()}
    result["total"] = sum(result["counts"].values())
    return result


# ── Phase 6B: project paths & primer presets ───────────────────────────────


def derive_project_paths(output_root: str) -> dict:
    """Derive project sub-directory paths from a root output directory.

    Does **not** create any directories on disk.

    Args:
        output_root: Root directory path for project outputs.

    Returns:
        dict with keys ``output_root``, ``qc_results_dir``,
        ``qc_spec_results_dir``, ``obipcr_results_dir``,
        ``final_results_dir``.  All values are empty strings when
        *output_root* is falsy.
    """
    if not output_root:
        return {
            "output_root": "",
            "qc_results_dir": "",
            "qc_spec_results_dir": "",
            "obipcr_results_dir": "",
            "final_results_dir": "",
        }
    root = Path(output_root)
    return {
        "output_root": str(root),
        "qc_results_dir": str(root / "qc_results"),
        "qc_spec_results_dir": str(root / "qc_spec_results"),
        "obipcr_results_dir": str(root / "obipcr_results"),
        "final_results_dir": str(root / "final_results"),
    }


def compute_inputs_validated(
    primers_status: str,
    database_status: str,
    taxonomy_status: str,
    output_status: str,
) -> bool:
    """Determine whether all four inputs pass validation.

    Returns ``True`` **only** when:

    * *primers_status* is ``"PASS"``
    * *database_status* is ``"PASS"``
    * *taxonomy_status* is ``"PASS"``
    * *output_status* is ``"PASS"`` or ``"WARN"``

    Every ``"FAIL"`` (including taxonomy and output) forces ``False``.
    """
    return (
        primers_status == "PASS"
        and database_status == "PASS"
        and taxonomy_status == "PASS"
        and output_status in ("PASS", "WARN")
    )


def get_primer_preset(name: str) -> dict:
    """Return parameter defaults for a named primer preset.

    Args:
        name: One of ``"默认参数"``, ``"12S/16S 短片段"``,
            ``"COI mini-barcode"``, ``"COI Folmer"``, ``"Cytb"``,
            ``"自定义"``.

    Returns:
        dict with keys ``description``, ``min_size``, ``max_size``,
        ``spec_mismatch``, ``obipcr_mismatches``, ``circular``.
        Unknown names fall back to the ``"自定义"`` preset (all values
        ``None``).
    """
    presets: dict[str, dict] = {
        "默认参数": {
            "description": "使用 fullpcr 默认分析参数，适合首次使用",
            "min_size": 80,
            "max_size": 500,
            "spec_mismatch": 2,
            "obipcr_mismatches": "0,1,2",
            "circular": True,
        },
        "12S/16S 短片段": {
            "description": "适用于 12S/16S rRNA 短片段扩增；推荐长度 80-500 bp，circular 模式",
            "min_size": 80,
            "max_size": 500,
            "spec_mismatch": 2,
            "obipcr_mismatches": "0,1,2",
            "circular": True,
        },
        "COI mini-barcode": {
            "description": "适用于 COI mini-barcode (100-350 bp)；推荐长度 100-350 bp，circular 模式",
            "min_size": 100,
            "max_size": 350,
            "spec_mismatch": 2,
            "obipcr_mismatches": "0,1,2,3",
            "circular": True,
        },
        "COI Folmer": {
            "description": "适用于 COI Folmer 区域 (500-800 bp)；推荐长度 500-800 bp，circular 模式",
            "min_size": 500,
            "max_size": 800,
            "spec_mismatch": 3,
            "obipcr_mismatches": "0,1,2,3",
            "circular": True,
        },
        "Cytb": {
            "description": "适用于 Cytb 基因片段 (300-1200 bp)；推荐长度 300-1200 bp，circular 模式",
            "min_size": 300,
            "max_size": 1200,
            "spec_mismatch": 3,
            "obipcr_mismatches": "0,1,2,3",
            "circular": True,
        },
        "自定义": {
            "description": "不自动修改参数，请根据实验需求手动设置",
            "min_size": None,
            "max_size": None,
            "spec_mismatch": None,
            "obipcr_mismatches": None,
            "circular": None,
        },
    }
    return presets.get(name, presets["自定义"])


#: Fixed mapping: project-path key → workflow canonical key.
#: Used by :func:`apply_project_paths_to_state` to keep the two in sync.
_WORKFLOW_PATH_MAP: list[tuple[str, str]] = [
    ("primers_path", "wf_s1_primers"),
    ("qc_results_dir", "wf_s1_outdir"),
    ("qc_results_dir", "wf_s2_qcdir"),
    ("primers_path", "wf_s3_primers"),
    ("database_path", "wf_s3_database"),
    ("qc_spec_results_dir", "wf_s3_outdir"),
    ("primers_path", "wf_s4_primers"),
    ("spec_index_database", "wf_s4_database"),
    ("taxonomy_path", "wf_s4_taxonomy"),
    ("obipcr_results_dir", "wf_s4_outdir"),
    ("obipcr_results_dir", "wf_s5_obipcr_dir"),
    ("qc_results_dir", "wf_s5_qc_dir"),
    ("qc_spec_results_dir", "wf_s5_spec_dir"),
    ("final_results_dir", "wf_s5_outdir"),
]

#: Set of workflow canonical keys that are path-derived (the second
#: element of each tuple in :data:`_WORKFLOW_PATH_MAP`).
#: Excluded from eager initialisation by :func:`init_canonical_defaults`
#: so that :func:`apply_project_paths_to_state` can fill them on first
#: Inputs validation.
_WORKFLOW_PATH_KEYS: set[str] = {state_key for _, state_key in _WORKFLOW_PATH_MAP}


#: Canonical defaults for ALL persisted widget state.
#: Keys are canonical (stable across page switches); widget keys
#: are derived by prefixing with ``_`` (e.g. ``_wf_s3_cpu``).
_CANONICAL_DEFAULTS: dict[str, object] = {
    # Inputs
    "inputs_primers_path": "example_data/primers.tsv",
    "inputs_database_path": "example_data/real_mito_small.fasta",
    "inputs_taxonomy_path": "example_data/taxonomy.tsv",
    "inputs_output_dir": "results",
    # Workflow — paths
    "wf_s1_primers": "example_data/primers.tsv",
    "wf_s1_outdir": "qc_results",
    "wf_s2_qcdir": "qc_results",
    "wf_s3_primers": "example_data/primers.tsv",
    "wf_s3_database": "example_data/real_mito_small.fasta",
    "wf_s3_outdir": "qc_spec_results",
    "wf_s4_primers": "example_data/primers.tsv",
    "wf_s4_database": "qc_spec_results/index/database.fasta",
    "wf_s4_taxonomy": "example_data/taxonomy.tsv",
    "wf_s4_outdir": "obipcr_results",
    "wf_s5_obipcr_dir": "obipcr_results",
    "wf_s5_qc_dir": "qc_results",
    "wf_s5_spec_dir": "qc_spec_results",
    "wf_s5_outdir": "final_results",
    # Workflow — params
    "wf_s1_thermo": True, "wf_s1_dimer": True, "wf_s1_hairpin": True, "wf_s1_degen": True,
    "wf_s1_score": 5, "wf_s1_dg": -5.0, "wf_s1_tm": 50.0,
    "wf_s1_mismatch": 2, "wf_s1_maxdeg": 256,
    "wf_s3_minsize": 80, "wf_s3_maxsize": 500, "wf_s3_mismatch": 2,
    "wf_s3_tm": 50.0, "wf_s3_maxtm": 100.0, "wf_s3_cpu": 4,
    "wf_s3_kvalue": 9, "wf_s3_force": True,
    "wf_s3_manual_cpu_enabled": False,
    # Phase 3D-2: spec custom params (None = use MFEprimer default)
    "wf_s3_use_tm": False,
    "wf_s3_use_misstart": False, "wf_s3_use_misend": False,
    "wf_s3_use_mono": False, "wf_s3_use_diva": False,
    "wf_s3_use_dntp": False, "wf_s3_use_oligo": False,
    "wf_s3_misstart": None, "wf_s3_misend": None,
    "wf_s3_bind": False, "wf_s3_cutprimer": False,
    "wf_s3_mono": None, "wf_s3_diva": None,
    "wf_s3_dntp": None, "wf_s3_oligo": None,
    "wf_s4_mismatches": "0,1,2", "wf_s4_circular": True,
    "wf_s4_summarize": True, "wf_s4_report": True,
    "wf_s4_force": True,
    "wf_preset_select": "默认参数",
    # Results
    "res_final_dir": "final_results",
    "res_obipcr_dir": "obipcr_results",
    "res_qc_dir": "qc_results",
    "res_spec_dir": "qc_spec_results",
    # Reports
    "rpt_final_path": "final_results/final_report.md",
    "rpt_obipcr_path": "obipcr_results/report.md",
    # Workflow — dry-run (persisted across page switches)
    "workflow_dry_run": False,
}


#: Set of ALL canonical keys known to the persistence system.
#: Built from :data:`_CANONICAL_DEFAULTS` at import time.
_ALL_CANONICAL_KEYS: set[str] = set(_CANONICAL_DEFAULTS.keys())


def _widget_key(canonical_key: str) -> str:
    """Return the temp widget key for a canonical key (prefix with ``_``)."""
    return f"_{canonical_key}"


def init_canonical_defaults(state: MutableMapping) -> None:
    """Set canonical defaults for keys not already in *state*.

    Called once at the top of the app script, before any widget is
    created.  No temp ``_``-prefixed keys are touched.

    Workflow path keys (the 14 keys in :data:`_WORKFLOW_PATH_KEYS`) are
    deliberately **excluded** from eager initialisation so that
    :func:`apply_project_paths_to_state` can fill them with
    project-derived ``results/*`` paths on the first Inputs validation.
    The fallback values remain in :data:`_CANONICAL_DEFAULTS` for
    :func:`ensure_widget_key` when a user opens the Workflow page first.
    """
    for key, default in _CANONICAL_DEFAULTS.items():
        if key not in state and key not in _WORKFLOW_PATH_KEYS:
            state[key] = default


def ensure_widget_key(state: MutableMapping, widget_key: str) -> None:
    """Load widget value from canonical state before widget creation.

    If *widget_key* is already in *state* (e.g. because the widget was
    created earlier this render cycle), this is a no-op.

    Otherwise, the value is copied from the corresponding canonical key
    (derived by stripping the leading ``_``).  If the canonical key is
    also absent, the default from :data:`_CANONICAL_DEFAULTS` is used.

    Args:
        state: A ``MutableMapping``, typically ``st.session_state``.
        widget_key: The Streamlit widget key (must start with ``_``).
    """
    if widget_key in state:
        return
    canonical_key = widget_key[1:]  # remove _ prefix
    if canonical_key in state:
        state[widget_key] = state[canonical_key]
    else:
        default = _CANONICAL_DEFAULTS.get(canonical_key)
        if default is not None:
            state[widget_key] = default


def sync_widgets_to_canonical(state: MutableMapping) -> None:
    """Copy temp widget values back to their canonical keys.

    Called at the bottom of the app script, after all widgets have been
    rendered.  Only widget keys that currently exist in *state* are
    synced — keys from other pages (cleaned by Streamlit) are skipped.
    """
    for canonical_key in _ALL_CANONICAL_KEYS:
        wk = _widget_key(canonical_key)
        if wk in state:
            state[canonical_key] = state[wk]


def apply_project_paths_to_state(
    state: MutableMapping,
    paths: dict,
    *,
    overwrite: bool = False,
) -> None:
    """Update session state with project-derived workflow paths.

    Only touches canonical keys listed in :data:`_WORKFLOW_PATH_MAP`;
    all other keys in *state* are left unchanged.  Safe to call with an
    empty *paths* dict or when ``paths["output_root"]`` is falsy (no-op).

    Args:
        state: A ``MutableMapping``, typically ``st.session_state``.
        paths: dict returned by :func:`derive_project_paths`, optionally
            extended with ``primers_path``, ``database_path``,
            ``taxonomy_path``, and ``spec_index_database``.
        overwrite: When ``False`` (default), only write to **canonical**
            keys (e.g. ``wf_s1_outdir``) that are missing from *state*,
            ``None``, or an empty string — existing non-empty values are
            always preserved, even if they match the canonical default.
            Temp ``_``-prefixed widget keys are **never** written.
            When ``True``, every mapped canonical key **and** its
            corresponding temp widget key are force-synced from *paths*
            (used by the "从输入文件同步路径" button for immediate UI
            update).  Only keys in :data:`_WORKFLOW_PATH_MAP` are
            affected; params and unrelated state are untouched.
    """
    if not paths or not paths.get("output_root"):
        return

    for path_key, state_key in _WORKFLOW_PATH_MAP:
        value = paths.get(path_key, "")
        if not value:
            continue
        if overwrite:
            state[state_key] = value
            state[_widget_key(state_key)] = value
        else:
            current = state.get(state_key)
            if current is None or current == "":
                state[state_key] = value


# ── workspace upload session state ──────────────────────────────────────


def init_workspace_session_state(state: MutableMapping) -> None:
    """Initialise workspace-related keys in *state* if not already present.

    Call once at app startup before rendering any workspace UI.

    Keys initialised (all default to ``None`` or ``False``):
        ``ws_run_id``, ``ws_uploads_dir``, ``ws_use_upload_primers``,
        ``ws_use_upload_database``, ``ws_use_upload_taxonomy``,
        ``ws_uploaded_primers_path``, ``ws_uploaded_database_path``,
        ``ws_uploaded_taxonomy_path``.
    """
    defaults: dict[str, object] = {
        "ws_run_id": None,
        "ws_uploads_dir": None,
        "ws_use_upload_primers": False,
        "ws_use_upload_database": False,
        "ws_use_upload_taxonomy": False,
        "ws_uploaded_primers_path": None,
        "ws_uploaded_database_path": None,
        "ws_uploaded_taxonomy_path": None,
    }
    for key, default in defaults.items():
        if key not in state:
            state[key] = default


def get_effective_primers_path(state: MutableMapping) -> str:
    """Return the effective primers path: uploaded file or text input."""
    if state.get("ws_use_upload_primers"):
        uploaded = state.get("ws_uploaded_primers_path")
        if uploaded:
            return str(uploaded)
    return str(state.get("inputs_primers_path", ""))


def get_effective_database_path(state: MutableMapping) -> str:
    """Return the effective database path: uploaded file or text input."""
    if state.get("ws_use_upload_database"):
        uploaded = state.get("ws_uploaded_database_path")
        if uploaded:
            return str(uploaded)
    return str(state.get("inputs_database_path", ""))


def get_effective_taxonomy_path(state: MutableMapping) -> str:
    """Return the effective taxonomy path: uploaded file or text input."""
    if state.get("ws_use_upload_taxonomy"):
        uploaded = state.get("ws_uploaded_taxonomy_path")
        if uploaded:
            return str(uploaded)
    return str(state.get("inputs_taxonomy_path", ""))


def clear_upload_mode(state: MutableMapping, file_type: str) -> None:
    """Switch a file type back to server-path mode and clear the uploaded path.

    Args:
        state: Session state dict.
        file_type: One of ``"primers"``, ``"database"``, ``"taxonomy"``.
    """
    key_map = {
        "primers": ("ws_use_upload_primers", "ws_uploaded_primers_path"),
        "database": ("ws_use_upload_database", "ws_uploaded_database_path"),
        "taxonomy": ("ws_use_upload_taxonomy", "ws_uploaded_taxonomy_path"),
    }
    entry = key_map.get(file_type)
    if entry:
        use_key, path_key = entry
        state[use_key] = False
        state[path_key] = None


def build_spec_index_database_path(
    qc_spec_results_dir: str,
    database_path: str,
) -> str:
    """Compute the normalised ``spec/index/`` database path for qc-spec.

    Uses the **basename** of *database_path* so that upload-normalised
    ``database.fasta`` and server-path ``reference.fa`` both produce the
    correct index filename.

    Args:
        qc_spec_results_dir: The ``qc_spec_results/`` directory path.
        database_path: The effective database path (uploaded or server).

    Returns:
        ``<qc_spec_results_dir>/index/<basename>``, or ``""`` when
        *qc_spec_results_dir* or *database_path* is empty.
    """
    if not qc_spec_results_dir or not database_path:
        return ""
    return str(Path(qc_spec_results_dir) / "index" / Path(database_path).name)


# ── manual primer entry ──────────────────────────────────────────────────

_DNA_IUPAC_CHARS: set[str] = set("ACGTRYSWKMBDHVN")

_PRIMERS_TSV_FIELDNAMES = ["primer_id", "forward", "reverse", "min_length", "max_length"]


def _is_safe_primer_id(pid: str) -> bool:
    """Reject primer IDs with ``/``, ``\\``, ``..``, or any non-printable
    character (including C0 controls and DEL)."""
    if not pid.isprintable():
        return False
    if "/" in pid or "\\" in pid:
        return False
    if ".." in pid:
        return False
    return True


def build_manual_primers_tsv(rows: list[dict[str, str]]) -> dict:
    """Validate manual primer rows and produce a ``primers.tsv`` byte string.

    Args:
        rows: List of dicts, each with keys ``primer_id``, ``forward``,
            ``reverse``, ``min_length``, ``max_length``.

    Returns:
        dict with ``status`` (PASS/FAIL), ``content`` (UTF-8 TSV bytes or
        None), ``normalized_rows`` (list of cleaned dicts or None),
        ``error`` (Chinese message or None).
    """
    if not rows:
        return _manual_fail("至少需要填写一对引物。")

    required = _PRIMERS_TSV_FIELDNAMES
    seen_ids: set[str] = set()
    normalized: list[dict[str, str]] = []

    _FIELD_CN = {
        "primer_id": "引物名称", "forward": "前向引物",
        "reverse": "反向引物", "min_length": "最小扩增长度",
        "max_length": "最大扩增长度",
    }

    for i, row in enumerate(rows, start=1):
        for field in required:
            if not row.get(field, "").strip():
                return _manual_fail(
                    f"第 {i} 行：{_FIELD_CN.get(field, field)} 不能为空。"
                )

        pid = row["primer_id"].strip()
        fwd = row["forward"].strip().upper()
        rev = row["reverse"].strip().upper()
        raw_min = row["min_length"].strip()
        raw_max = row["max_length"].strip()

        if not _is_safe_primer_id(pid):
            return _manual_fail(
                f"第 {i} 行：引物名称包含控制字符或不允许的字符。"
            )

        if pid in seen_ids:
            return _manual_fail(f"第 {i} 行：引物名称 '{pid}' 重复。")
        seen_ids.add(pid)

        invalid_fwd = [c for c in fwd if c not in _DNA_IUPAC_CHARS]
        if invalid_fwd:
            return _manual_fail(
                f"第 {i} 行：前向引物包含非法字符 "
                f"'{'、'.join(sorted(set(invalid_fwd)))}'。"
                f"仅允许标准 IUPAC DNA 字符。"
            )
        invalid_rev = [c for c in rev if c not in _DNA_IUPAC_CHARS]
        if invalid_rev:
            return _manual_fail(
                f"第 {i} 行：反向引物包含非法字符 "
                f"'{'、'.join(sorted(set(invalid_rev)))}'。"
                f"仅允许标准 IUPAC DNA 字符。"
            )

        try:
            min_len = int(raw_min)
        except ValueError:
            return _manual_fail(
                f"第 {i} 行：最小扩增长度 '{raw_min}' 不是有效整数。"
            )
        try:
            max_len = int(raw_max)
        except ValueError:
            return _manual_fail(
                f"第 {i} 行：最大扩增长度 '{raw_max}' 不是有效整数。"
            )
        if min_len <= 0:
            return _manual_fail(
                f"第 {i} 行：最小扩增长度必须为正整数（当前: {min_len}）。"
            )
        if max_len <= 0:
            return _manual_fail(
                f"第 {i} 行：最大扩增长度必须为正整数（当前: {max_len}）。"
            )
        if min_len > max_len:
            return _manual_fail(
                f"第 {i} 行：最小扩增长度 ({min_len}) "
                f"不能大于最大扩增长度 ({max_len})。"
            )

        normalized.append({
            "primer_id": pid, "forward": fwd, "reverse": rev,
            "min_length": str(min_len), "max_length": str(max_len),
        })

    import io

    buf = io.StringIO(newline="")
    writer = csv.DictWriter(
        buf,
        fieldnames=_PRIMERS_TSV_FIELDNAMES,
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(normalized)
    content = buf.getvalue().encode("utf-8")
    buf.close()

    return {"status": "PASS", "content": content, "normalized_rows": normalized, "error": None}


def _manual_fail(error: str) -> dict:
    return {"status": "FAIL", "content": None, "normalized_rows": None, "error": error}


# ── full pipeline plan & executor ────────────────────────────────────────

_STEP_SPEC: list[dict[str, object]] = [
    {"key": "s1", "result_key": "wf_s1_result", "label": "基础质控"},
    {"key": "s2", "result_key": "wf_s2_result", "label": "质控汇总"},
    {"key": "s3", "result_key": "wf_s3_result", "label": "特异性分析"},
    {"key": "s4", "result_key": "wf_s4_result", "label": "obipcr 全库模拟 PCR"},
    {"key": "s5", "result_key": "wf_s5_result", "label": "最终综合报告"},
]


def build_full_pipeline_plan(
    *,
    qc_pre_command: list[str],
    qc_summary_command: list[str],
    qc_spec_command: list[str],
    obipcr_command: list[str],
    final_report_command: list[str],
    qc_pre_timeout: int | float | None = None,
    qc_summary_timeout: int | float | None = None,
    qc_spec_timeout: int | float | None = None,
    obipcr_timeout: int | float | None = None,
    final_report_timeout: int | float | None = None,
) -> list[dict]:
    """Build the ordered five-step execution plan.

    Each returned step is a dict with ``key``, ``result_key``, ``label``,
    ``command``, and ``timeout``.  The caller can pass this plan to
    :func:`run_full_pipeline`.
    """
    commands = [
        qc_pre_command,
        qc_summary_command,
        qc_spec_command,
        obipcr_command,
        final_report_command,
    ]
    timeouts = [
        qc_pre_timeout,
        qc_summary_timeout,
        qc_spec_timeout,
        obipcr_timeout,
        final_report_timeout,
    ]
    plan: list[dict] = []
    for spec, cmd, t in zip(_STEP_SPEC, commands, timeouts):
        plan.append({
            "key": spec["key"],
            "result_key": spec["result_key"],
            "label": spec["label"],
            "command": list(cmd),
            "timeout": t,
        })
    return plan


def run_full_pipeline(
    plan: list[dict],
    *,
    runner: object = None,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Execute *plan* sequentially, stopping on failure, timeout or cancellation.

    Args:
        plan: Output of :func:`build_full_pipeline_plan`.
        runner: A callable ``(command, timeout) -> dict``.  Defaults to
            :func:`run_gui_command`.
        on_progress: Optional callback receiving one event dict immediately
            before and after each executed step.  Events contain ``index``,
            ``total``, ``key``, ``label``, ``phase`` and ``status``.

    Returns:
        dict with ``status``, ``results``, ``completed_steps``,
        ``failed_step``, ``message``.
    """
    if runner is None:
        runner = run_gui_command  # type: ignore[assignment]

    results: dict[str, dict] = {}
    completed: list[str] = []
    failed: str | None = None
    final_status = "PASS"

    total_steps = len(plan)
    for index, step in enumerate(plan, start=1):
        if on_progress is not None:
            on_progress(
                {
                    "index": index,
                    "total": total_steps,
                    "key": step["key"],
                    "label": step["label"],
                    "phase": "running",
                    "status": None,
                }
            )
        result = runner(step["command"], timeout=step["timeout"])  # type: ignore[call-arg]
        results[step["result_key"]] = result

        st = result.get("status")
        if on_progress is not None:
            on_progress(
                {
                    "index": index,
                    "total": total_steps,
                    "key": step["key"],
                    "label": step["label"],
                    "phase": "finished",
                    "status": st,
                }
            )
        if st == "PASS":
            completed.append(step["key"])
        elif st == "TIMEOUT":
            failed = step["key"]
            final_status = "TIMEOUT"
            break
        elif st == "CANCELLED":
            failed = step["key"]
            final_status = "CANCELLED"
            break
        else:
            # FAIL, None, or any other value → treat as failure.
            failed = step["key"]
            if final_status == "PASS":
                final_status = "FAIL"
            break

    if final_status == "PASS":
        message = "全部五步完成。"
    elif final_status == "TIMEOUT":
        message = f"第 {_step_index(failed)} 步（{_step_label(plan, failed)}）超时，流程已停止。"
    elif final_status == "CANCELLED":
        message = "分析已由用户终止。"
    else:
        message = f"第 {_step_index(failed)} 步（{_step_label(plan, failed)}）失败，流程已停止。"

    return {
        "status": final_status,
        "results": results,
        "completed_steps": completed,
        "failed_step": failed,
        "message": message,
    }


def _step_index(key: str | None) -> str:
    if key is None:
        return "?"
    return {"s1": "1", "s2": "2", "s3": "3", "s4": "4", "s5": "5"}.get(key, "?")


def _step_label(plan: list[dict], key: str | None) -> str:
    if key is None:
        return "未知"
    for s in plan:
        if s["key"] == key:
            return str(s["label"])
    return "未知"


# ── primer preset application ────────────────────────────────────────────

#: The 5 canonical keys that :func:`apply_primer_preset_to_state` is
#: allowed to touch, and their corresponding preset-parameter names.
_PRESET_KEY_MAP: list[tuple[str, str]] = [
    ("wf_s3_minsize", "min_size"),
    ("wf_s3_maxsize", "max_size"),
    ("wf_s3_mismatch", "spec_mismatch"),
    ("wf_s4_mismatches", "obipcr_mismatches"),
    ("wf_s4_circular", "circular"),
]


def apply_primer_preset_to_state(
    state: MutableMapping, preset_name: str
) -> None:
    """Directly write preset parameter values to the 5 affected keys.

    For ``"自定义"`` this is a **no-op** — no key is touched.

    Updates both canonical keys and temp widget keys so the UI
    reflects changes immediately.

    Args:
        state: A ``MutableMapping``, typically ``st.session_state``.
        preset_name: One of the preset names known to
            :func:`get_primer_preset`.
    """
    if preset_name == "自定义":
        return
    preset = get_primer_preset(preset_name)
    for state_key, preset_key in _PRESET_KEY_MAP:
        val = preset.get(preset_key)
        if val is not None:
            state[state_key] = val
            state[_widget_key(state_key)] = val


# ── CPU thread helpers ───────────────────────────────────────────────────


def get_available_cpu_threads() -> int:
    """Return the number of logical CPU threads available to the current process.

    Uses ``os.sched_getaffinity(0)`` (Linux) when available; falls back to
    ``os.cpu_count()``.  Returns at least 1 even when every source is
    ``None`` or invalid.

    Returns:
        int: Available logical CPU threads (≥ 1).
    """
    try:
        affinity = os.sched_getaffinity(0)  # type: ignore[attr-defined]
    except (AttributeError, NotImplementedError, OSError):
        affinity = None

    if affinity is not None and len(affinity) > 0:
        return max(1, len(affinity))

    cpu_count = os.cpu_count()
    if cpu_count is not None and cpu_count > 0:
        return cpu_count

    return 1


def calculate_auto_cpu_threads(available_threads: int) -> int:
    """Return 60% of *available_threads*, floored, with a minimum of 1.

    Args:
        available_threads: Total logical threads available (≥ 0).

    Returns:
        int: At least 1, at most *available_threads*.
    """
    auto = max(1, int(available_threads * 0.6))
    return auto


def resolve_spec_cpu_threads(
    *,
    manual_enabled: bool,
    manual_threads: int | None,
    available_threads: int | None = None,
) -> int:
    """Resolve the final CPU thread count for MFEprimer spec.

    When *manual_enabled* is ``True`` and *manual_threads* is a positive
    integer, the value is clamped to ``[1, available_threads]``.  When
    *manual_enabled* is ``False``, or *manual_threads* is ``None``, the
    automatic 60% value is used.

    Args:
        manual_enabled: Whether the user has enabled manual override.
        manual_threads: User-entered thread count, or ``None``.
        available_threads: Total available threads; ``None`` defaults to 1.

    Returns:
        int: Resolved thread count (≥ 1, ≤ available_threads).
    """
    if available_threads is None:
        available_threads = get_available_cpu_threads()
    available_threads = max(1, available_threads)

    if manual_enabled and manual_threads is not None:
        if manual_threads < 0:
            return calculate_auto_cpu_threads(available_threads)
        clamped = max(1, min(manual_threads, available_threads))
        return clamped

    return calculate_auto_cpu_threads(available_threads)


# ── execution error details ──────────────────────────────────────────────


def build_execution_error_details(
    *,
    step_key: str,
    step_label: str,
    result: dict | None,
    job_id: str | None = None,
    background_error: str = "",
    background_traceback: str = "",
) -> dict:
    """Build a structured error-details dict for the unified error dialog.

    All raw text fields are preserved in full — no truncation, translation,
    or sanitisation.  Missing values are normalised to empty strings so
    callers can render unconditionally.

    Args:
        step_key: Short step identifier (``"s1"`` … ``"s5"``).
        step_label: Human-readable step label (``"基础质控"`` …).
        result: The per-step result dict returned by :func:`run_gui_command`
            (or ``None`` when no result is available, e.g. a background
            exception).
        job_id: Optional background job id for correlation.
        background_error: High-level error message from the pipeline
            orchestrator (empty string when not applicable).
        background_traceback: Full Python traceback captured in the
            background thread (empty string when not applicable).

    Returns:
        dict with keys ``step_key``, ``step_label``, ``job_id``,
        ``status``, ``returncode``, ``command``, ``stderr``, ``stdout``,
        ``message``, ``background_error``, ``background_traceback``.
    """
    if result is None:
        result = {}

    command_raw = result.get("command")
    if isinstance(command_raw, (list, tuple)):
        command_str = " ".join(str(p) for p in command_raw)
    elif isinstance(command_raw, str):
        command_str = command_raw
    else:
        command_str = ""

    def _str_or_empty(value: object) -> str:
        """Normalise *value* to string, mapping None to empty string."""
        if value is None:
            return ""
        return str(value)

    return {
        "step_key": step_key or "",
        "step_label": step_label or "",
        "job_id": job_id or "",
        "status": _str_or_empty(result.get("status")),
        "returncode": _str_or_empty(result.get("returncode")),
        "command": command_str,
        "stderr": _str_or_empty(result.get("stderr")),
        "stdout": _str_or_empty(result.get("stdout")),
        "message": _str_or_empty(result.get("message")),
        "background_error": _str_or_empty(background_error),
        "background_traceback": _str_or_empty(background_traceback),
    }


# ── Phase 3D-3A: raw spec TSV + results archive ──────────────────────────


def get_raw_spec_tsv_info(qc_spec_results_dir: str | Path) -> dict:
    """Locate the raw MFEprimer spec TSV for download.

    Returns a dict with keys ``status``, ``path``, ``file_name``,
    ``size``, and ``error``.  Never raises — failures are returned as
    ``status="FAIL"`` with a Chinese error message.

    Args:
        qc_spec_results_dir: Path to the ``qc_spec_results`` directory.
    """
    result: dict = {
        "status": "FAIL",
        "path": "",
        "file_name": "spec_output.txt.spec.tsv",
        "size": 0,
        "error": "",
    }
    rd = Path(qc_spec_results_dir)

    # Directory checks.
    if not rd.exists():
        result["error"] = f"目录不存在: {rd}"
        return result
    if rd.is_symlink():
        result["error"] = f"目录是符号链接，拒绝访问: {rd}"
        return result
    if not rd.is_dir():
        result["error"] = f"路径不是目录: {rd}"
        return result

    target = rd / "spec" / "spec_output.txt.spec.tsv"

    # Symlink check on intermediate path.
    try:
        resolved_parts = target.resolve().parts
        rd_resolved = rd.resolve()
        if rd_resolved not in target.resolve().parents and rd_resolved != target.resolve():
            result["error"] = f"文件路径包含符号链接，拒绝访问: {target}"
            return result
    except OSError as exc:
        result["error"] = f"无法解析文件路径: {exc}"
        return result

    if target.is_symlink():
        result["error"] = f"文件是符号链接，拒绝访问: {target}"
        return result
    if not target.exists():
        result["error"] = f"原始 spec TSV 不存在: {target}"
        return result
    if not target.is_file():
        result["error"] = f"目标路径不是普通文件: {target}"
        return result

    try:
        size = target.stat().st_size
    except OSError as exc:
        result["error"] = f"无法读取文件信息: {exc}"
        return result

    result["status"] = "PASS"
    result["path"] = str(target.resolve())
    result["size"] = size
    return result


def build_results_archive(
    output_root: str | Path,
    *,
    included_dirs: list[str] | tuple[str, ...] | None = None,
    archive_name: str = "fullpcr_results.zip",
) -> dict:
    """Create a ZIP archive of selected results under *output_root*.

    The archive is written to
    ``<output_root>/.fullpcr_downloads/<archive_name>`` via an atomic
    temp-file + ``os.replace`` step.  When *included_dirs* is ``None``,
    every regular file below *output_root* is included.  Otherwise only
    the named top-level directories are traversed.

    Returns a dict with keys ``status``, ``path``, ``file_name``,
    ``file_count``, ``size``, and ``error``.
    """
    import os
    import tempfile
    import zipfile

    result: dict = {
        "status": "FAIL",
        "path": "",
        "file_name": archive_name,
        "file_count": 0,
        "size": 0,
        "error": "",
    }
    root = Path(output_root)

    archive_path = Path(archive_name)
    if (
        not archive_name
        or archive_path.name != archive_name
        or "/" in archive_name
        or "\\" in archive_name
        or archive_path.suffix.lower() != ".zip"
    ):
        result["error"] = f"ZIP 文件名不安全: {archive_name}"
        return result

    selected_dirs: tuple[str, ...] | None = None
    if included_dirs is not None:
        selected: list[str] = []
        for raw_name in included_dirs:
            name = str(raw_name).strip()
            candidate = Path(name)
            if (
                not name
                or candidate.name != name
                or "/" in name
                or "\\" in name
                or name in {".", "..", ".fullpcr_downloads", ".fullpcr_jobs"}
            ):
                result["error"] = f"打包目录名称不安全: {raw_name}"
                return result
            if name not in selected:
                selected.append(name)
        if not selected:
            result["error"] = "未选择任何可打包的结果目录。"
            return result
        selected_dirs = tuple(selected)

    # Safety: reject symlinks and non-directories.
    if root.is_symlink():
        result["error"] = f"输出根目录是符号链接，拒绝访问: {root}"
        return result
    if not root.exists():
        result["error"] = f"输出根目录不存在: {root}"
        return result
    if not root.is_dir():
        result["error"] = f"输出根路径不是目录: {root}"
        return result

    downloads_dir = root / ".fullpcr_downloads"
    jobs_dir = root / ".fullpcr_jobs"
    zip_path = downloads_dir / archive_name

    # ── pre-check downloads_dir before any traversal ──────────────────
    if downloads_dir.is_symlink():
        result["error"] = (
            f"下载目录是符号链接，拒绝访问: {downloads_dir}"
        )
        return result
    if downloads_dir.exists() and not downloads_dir.is_dir():
        result["error"] = (
            f"下载目录路径已存在但不是目录: {downloads_dir}"
        )
        return result

    # ── collect regular files, reject special files ──────────────────
    file_list: list[Path] = []
    scan_roots: list[Path]
    if selected_dirs is None:
        scan_roots = [root]
    else:
        scan_roots = []
        for name in selected_dirs:
            selected_root = root / name
            if selected_root.is_symlink():
                result["error"] = f"所选结果目录是符号链接，拒绝访问: {selected_root}"
                return result
            if not selected_root.exists():
                result["error"] = f"所选结果目录不存在: {selected_root}"
                return result
            if not selected_root.is_dir():
                result["error"] = f"所选结果路径不是目录: {selected_root}"
                return result
            scan_roots.append(selected_root)

    entries: list[Path] = []
    try:
        for scan_root in scan_roots:
            entries.extend(scan_root.rglob("*"))
        entries.sort()
    except OSError as exc:
        result["error"] = f"遍历输出目录失败: {exc}"
        return result

    for entry in entries:
        # Skip internal application-state subtrees entirely.
        is_internal = False
        for internal_dir in (downloads_dir, jobs_dir):
            try:
                entry.relative_to(internal_dir)
                is_internal = True
                break
            except ValueError:
                pass
        if is_internal:
            continue

        if entry.is_symlink():
            result["error"] = f"检测到符号链接，拒绝打包: {entry}"
            return result

        if entry.is_dir():
            continue
        if entry.is_file():
            file_list.append(entry)
            continue
        # FIFO, socket, device, etc.
        result["error"] = (
            f"检测到不支持的文件类型，拒绝打包: {entry}"
        )
        return result

    if not file_list:
        result["error"] = "没有可打包的文件。"
        return result

    # ── create downloads_dir (may raise OSError) ─────────────────────
    try:
        downloads_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result["error"] = f"无法创建下载目录: {exc}"
        return result

    # ── temp file for atomic write ──────────────────────────────────
    try:
        fd, tmp_path = tempfile.mkstemp(
            suffix=".zip", prefix=".fullpcr_tmp_", dir=str(downloads_dir),
        )
    except OSError as exc:
        result["error"] = f"无法创建临时文件: {exc}"
        return result
    os.close(fd)
    tmp = Path(tmp_path)

    try:
        with zipfile.ZipFile(str(tmp), "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for fp in file_list:
                arcname = str(fp.relative_to(root).as_posix())
                zf.write(str(fp), arcname=arcname)
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        result["error"] = f"ZIP 创建失败: {exc}"
        return result

    # ── read temp size before replacing (avoid broken state) ─────────
    try:
        zip_size = tmp.stat().st_size
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        result["error"] = f"无法读取临时 ZIP 大小: {exc}"
        return result

    # ── atomic replace ──────────────────────────────────────────────
    try:
        os.replace(str(tmp), str(zip_path))
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        result["error"] = f"ZIP 替换失败: {exc}"
        return result

    result["status"] = "PASS"
    result["path"] = str(zip_path.resolve())
    result["file_count"] = len(file_list)
    result["size"] = zip_size
    return result
