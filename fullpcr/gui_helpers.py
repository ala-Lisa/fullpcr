"""GUI helpers for fullpcr Streamlit app.

Provides environment-check utilities that report the availability
and version of Python, fullpcr, obipcr, and mfeprimer, as well as
input-file validation functions used by the Inputs page.
"""

from __future__ import annotations

import csv
import gzip
import os
import shutil
import subprocess
import sys
from collections.abc import MutableMapping
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as get_package_version
from pathlib import Path

import pandas as pd


# ── Chinese translation helpers (display-layer only) ──────────────────


def translate_status(value: str | None) -> str:
    """Translate generic PASS/FAIL/WARN/TIMEOUT to Chinese.

    Used for command execution results, validation status, and
    file-load status — **not** for final_status (RECOMMENDED, etc.)
    or qc_status/spec_status sub-warnings.

    Args:
        value: Status string such as ``"PASS"``, ``"FAIL"``, ``"WARN"``,
            ``"TIMEOUT"``, or ``None``.

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
    timeout: int | None = 60,
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
    max_tm: float = 75.0,
    mismatch: int = 2,
    cpu: int = 4,
    kvalue: int = 9,
    timeout: int | None = 300,
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
    timeout: int | None = 300,
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
    timeout: int = 600,
) -> dict:
    """Execute a CLI command via ``subprocess.run(list[str])``.

    Args:
        command: The command as ``list[str]``.
        timeout: Timeout in seconds.

    Returns:
        dict with ``status`` (PASS/FAIL/TIMEOUT), ``returncode``,
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
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        result["status"] = "TIMEOUT"
        result["message"] = f"Command timed out after {timeout} s"
        return result
    except FileNotFoundError:
        result["status"] = "FAIL"
        result["message"] = f"Executable not found: {command[0]}"
        return result
    except OSError as exc:
        result["status"] = "FAIL"
        result["message"] = f"OS error: {exc}"
        return result

    result["returncode"] = proc.returncode
    result["stdout"] = proc.stdout
    result["stderr"] = proc.stderr

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
        name: One of ``"12S/16S 短片段"``, ``"COI mini-barcode"``,
            ``"COI Folmer"``, ``"Cytb"``, ``"自定义"``.

    Returns:
        dict with keys ``description``, ``min_size``, ``max_size``,
        ``spec_mismatch``, ``obipcr_mismatches``, ``circular``.
        Unknown names fall back to the ``"自定义"`` preset (all values
        ``None``).
    """
    presets: dict[str, dict] = {
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
#: are derived by prefixing with ``_`` (e.g. ``_wf_s3_timeout``).
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
    "wf_s1_mismatch": 2, "wf_s1_maxdeg": 256, "wf_s1_timeout": 60,
    "wf_s3_minsize": 80, "wf_s3_maxsize": 500, "wf_s3_mismatch": 2,
    "wf_s3_timeout": 300,
    "wf_s3_tm": 50.0, "wf_s3_maxtm": 75.0, "wf_s3_cpu": 4,
    "wf_s3_kvalue": 9, "wf_s3_force": True,
    "wf_s4_mismatches": "0,1,2", "wf_s4_circular": True,
    "wf_s4_summarize": True, "wf_s4_report": True,
    "wf_s4_force": True, "wf_s4_timeout": 300,
    "wf_preset_select": "自定义",
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
            whose current value is ``None``, or whose current value is an
            empty string — existing non-empty user values are always
            preserved.  Temp widget keys (``_<canonical>``) are **not**
            touched; they are managed exclusively by
            :func:`ensure_widget_key` and Streamlit's widget system.
            When ``True``, every mapped canonical key **and** its
            corresponding temp widget key are force-synced from *paths*
            (used by the sync button for immediate UI update).
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
                # Write canonical key only — widget keys are managed by
                # ensure_widget_key() (called right before widget creation)
                # and Streamlit's widget system.  Writing widget keys here
                # would set them "behind Streamlit's back", which causes
                # the framework to reset them to their initial value when
                # the user navigates away from the page.
                state[state_key] = value


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
