"""Build and execute obipcr command lines."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fullpcr.fasta_parser import parse_obipcr_fasta, write_amplicons_tsv

# ── constants ──────────────────────────────────────────────────────────

FAILED_JOBS_FIELDNAMES = [
    "primer_id",
    "mismatch",
    "command",
    "output",
    "status",
    "error_message",
]


@dataclass(frozen=True)
class ObiPCRConfig:
    """Immutable configuration for a single obipcr invocation.

    Attributes:
        command: The command as list[str], ready for subprocess.run().
        output: Path where stdout should be written (not by shell redirect).
    """

    command: list[str]
    output: str | Path


def build_obipcr_command(
    *,
    forward: str,
    reverse: str,
    min_length: int,
    max_length: int,
    allowed_mismatches: int,
    database: str | Path,
    output: str | Path,
    circular: bool = False,
    no_progressbar: bool = True,
) -> ObiPCRConfig:
    """Build an obipcr command as list[str].

    Args:
        forward: Forward primer sequence.
        reverse: Reverse primer sequence.
        min_length: Minimum amplicon length.
        max_length: Maximum amplicon length.
        allowed_mismatches: Allowed mismatches (passed as --allowed-mismatches).
        database: Path to the FASTA database.
        output: Path where amplicon FASTA output should be written.
        circular: If True, add --circular flag.
        no_progressbar: If True, add --no-progressbar flag.

    Returns:
        ObiPCRConfig with the command list and output path.

    Raises:
        ValueError: If required parameters are missing or invalid.
    """
    missing = _validate_params(
        forward=forward,
        reverse=reverse,
        min_length=min_length,
        max_length=max_length,
        allowed_mismatches=allowed_mismatches,
        database=database,
        output=output,
    )
    if missing:
        raise ValueError(
            f"obipcr 缺少必要参数: {', '.join(sorted(missing))}。"
        )

    cmd: list[str] = [
        "obipcr",
        "--forward", forward,
        "--reverse", reverse,
        "--min-length", str(min_length),
        "--max-length", str(max_length),
        "--allowed-mismatches", str(allowed_mismatches),
    ]

    if circular:
        cmd.append("--circular")

    if no_progressbar:
        cmd.append("--no-progressbar")

    cmd.append(str(database))

    return ObiPCRConfig(command=cmd, output=output)


# ── execution ─────────────────────────────────────────────────────────


def check_obipcr_available() -> bool:
    """Return True if obipcr is found on PATH."""
    return shutil.which("obipcr") is not None


def run_obipcr_job(
    *,
    primer_id: str,
    mismatch: int,
    config: ObiPCRConfig,
    resume: bool = False,
    force: bool = False,
    timeout: float | None = None,
) -> dict:
    """Execute a single obipcr job and parse the output.

    Writes stdout to the FASTA path specified in *config.output*,
    stderr to a ``.stderr.log`` sibling, and parsed records to
    ``amplicons.tsv``.

    Args:
        primer_id: Primer pair identifier.
        mismatch: Mismatch level.
        config: ObiPCRConfig with the command and output path.
        resume: If True, skip when output files already exist.
        force: If True, re-run even when resume would skip.
        timeout: Optional timeout in seconds passed to subprocess.run().

    Returns:
        A dict with keys matching ``FAILED_JOBS_FIELDNAMES``.
        ``status`` is one of ``"success"``, ``"failed"``, or ``"skipped"``.
    """
    fasta_path = Path(config.output)
    tsv_path = fasta_path.with_name("amplicons.tsv")
    stderr_path = fasta_path.with_name("obipcr.stderr.log")

    cmd_str = " ".join(config.command)

    # ── resume / skip check ──────────────────────────────────────────
    if resume and not force:
        if fasta_path.is_file() and tsv_path.is_file():
            return {
                "primer_id": primer_id,
                "mismatch": mismatch,
                "command": cmd_str,
                "output": str(config.output),
                "status": "skipped",
                "error_message": "已有结果，跳过（--resume）",
            }

    # ── ensure output directory ──────────────────────────────────────
    fasta_path.parent.mkdir(parents=True, exist_ok=True)

    # ── check obipcr availability ────────────────────────────────────
    if not check_obipcr_available():
        return {
            "primer_id": primer_id,
            "mismatch": mismatch,
            "command": cmd_str,
            "output": str(config.output),
            "status": "failed",
            "error_message": (
                "obipcr 未找到。请确认 OBITools4 已安装且在 PATH 中。"
            ),
        }

    # ── execute ──────────────────────────────────────────────────────
    try:
        proc = subprocess.run(
            config.command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

        fasta_path.write_text(proc.stdout, encoding="utf-8")
        stderr_path.write_text(proc.stderr, encoding="utf-8")

        if proc.returncode != 0:
            error_msg = (
                proc.stderr.strip()[:500]
                if proc.stderr.strip()
                else f"obipcr 返回非零退出码: {proc.returncode}"
            )
            return {
                "primer_id": primer_id,
                "mismatch": mismatch,
                "command": cmd_str,
                "output": str(config.output),
                "status": "failed",
                "error_message": error_msg,
            }

        # Parse FASTA → write amplicons.tsv
        records = parse_obipcr_fasta(fasta_path)
        write_amplicons_tsv(records, tsv_path)

        return {
            "primer_id": primer_id,
            "mismatch": mismatch,
            "command": cmd_str,
            "output": str(config.output),
            "status": "success",
            "error_message": "",
        }

    except subprocess.TimeoutExpired:
        return {
            "primer_id": primer_id,
            "mismatch": mismatch,
            "command": cmd_str,
            "output": str(config.output),
            "status": "failed",
            "error_message": (
                f"obipcr 执行超时 (timeout={timeout}s)。"
            ),
        }
    except FileNotFoundError:
        return {
            "primer_id": primer_id,
            "mismatch": mismatch,
            "command": cmd_str,
            "output": str(config.output),
            "status": "failed",
            "error_message": (
                "obipcr 未找到。请确认 OBITools4 已安装且在 PATH 中。"
            ),
        }
    except Exception as exc:
        return {
            "primer_id": primer_id,
            "mismatch": mismatch,
            "command": cmd_str,
            "output": str(config.output),
            "status": "failed",
            "error_message": str(exc),
        }


# ── internal helpers ──────────────────────────────────────────────────


def _validate_params(
    *,
    forward: str,
    reverse: str,
    min_length: int,
    max_length: int,
    allowed_mismatches: int,
    database: str | Path,
    output: str | Path,
) -> list[str]:
    """Return a list of missing parameter names. Empty list means valid."""
    missing: list[str] = []

    if not forward or not forward.strip():
        missing.append("forward")
    if not reverse or not reverse.strip():
        missing.append("reverse")
    if not database:
        missing.append("database")
    if not output:
        missing.append("output")

    if min_length <= 0:
        missing.append("min_length (必须 > 0)")
    if max_length <= 0:
        missing.append("max_length (必须 > 0)")
    if min_length > max_length:
        missing.append(
            f"min_length ({min_length}) 不能大于 max_length ({max_length})"
        )
    if allowed_mismatches < 0:
        missing.append(
            f"allowed_mismatches ({allowed_mismatches}) 不能为负数"
        )

    return missing
