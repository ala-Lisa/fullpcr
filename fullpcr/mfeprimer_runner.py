"""MFEprimer integration — availability check, command building, execution.

Phase 1: availability check + primer export only.
Phase 2: thermo, dimer, hairpin execution with subprocess.
Phase 3: degen command builder and runner.
Phase 4: index / spec command builders and runners.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# ── constants ──────────────────────────────────────────────────────────

QC_FAILED_JOBS_FIELDNAMES = [
    "module",
    "command",
    "output",
    "status",
    "error_message",
]


@dataclass(frozen=True)
class MFEprimerConfig:
    """Immutable configuration for a single MFEprimer invocation.

    Attributes:
        command: The command as list[str], ready for subprocess.run().
        input_fasta: Path to the input primer FASTA.
        output_dir: Path to the output directory.
    """

    command: list[str]
    input_fasta: str
    output_dir: str


# ── availability check ─────────────────────────────────────────────────


def check_mfeprimer_available() -> bool:
    """Return True if ``mfeprimer`` is found on PATH."""
    return shutil.which("mfeprimer") is not None


# ── Phase 1 command builder ────────────────────────────────────────────


def build_mfeprimer_command(
    *,
    primer_fasta: str,
    output_dir: str,
) -> MFEprimerConfig:
    """Build a basic ``mfeprimer`` command for all default QC checks.

    Args:
        primer_fasta: Path to the primer FASTA file.
        output_dir: Directory where MFEprimer writes its output.

    Returns:
        MFEprimerConfig with the command list, input path, and output dir.

    Raises:
        ValueError: If required parameters are missing.
    """
    if not primer_fasta or not primer_fasta.strip():
        raise ValueError("primer_fasta 不能为空。")
    if not output_dir or not output_dir.strip():
        raise ValueError("output_dir 不能为空。")

    cmd: list[str] = [
        "mfeprimer",
        "-i",
        primer_fasta,
        "-o",
        output_dir,
    ]

    return MFEprimerConfig(
        command=cmd,
        input_fasta=primer_fasta,
        output_dir=output_dir,
    )


# ── Phase 2: per-module command builders ───────────────────────────────


def build_mfeprimer_thermo_command(
    *,
    primer_fasta: str,
) -> MFEprimerConfig:
    """Build an ``mfeprimer thermo`` command.

    Uses MFEprimer default thermodynamic parameters (no extra flags).

    Args:
        primer_fasta: Path to the primer FASTA file.

    Returns:
        MFEprimerConfig with the command list.

    Raises:
        ValueError: If *primer_fasta* is empty.
    """
    if not primer_fasta or not primer_fasta.strip():
        raise ValueError("primer_fasta 不能为空。")

    cmd: list[str] = [
        "mfeprimer",
        "thermo",
        primer_fasta,
    ]

    return MFEprimerConfig(
        command=cmd,
        input_fasta=primer_fasta,
        output_dir="",
    )


def build_mfeprimer_dimer_command(
    *,
    primer_fasta: str,
    score: int = 5,
    mismatch: int = 2,
    dg: float = -5.0,
) -> MFEprimerConfig:
    """Build an ``mfeprimer dimer`` command.

    Args:
        primer_fasta: Path to the primer FASTA file.
        score: Alignment score threshold (default 5).
        mismatch: Allowed mismatches (default 2).
        dg: Free energy threshold in kcal/mol (default -5.0).

    Returns:
        MFEprimerConfig with the command list.

    Raises:
        ValueError: If *primer_fasta* is empty.
    """
    if not primer_fasta or not primer_fasta.strip():
        raise ValueError("primer_fasta 不能为空。")

    cmd: list[str] = [
        "mfeprimer",
        "dimer",
        "-i",
        primer_fasta,
        "--score",
        str(score),
        "--mismatch",
        str(mismatch),
        "--dg",
        str(dg),
    ]

    return MFEprimerConfig(
        command=cmd,
        input_fasta=primer_fasta,
        output_dir="",
    )


def build_mfeprimer_hairpin_command(
    *,
    primer_fasta: str,
    tm: float = 50.0,
    dg: float = -5.0,
    score: int = 5,
) -> MFEprimerConfig:
    """Build an ``mfeprimer hairpin`` command.

    Args:
        primer_fasta: Path to the primer FASTA file.
        tm: Melting temperature threshold in °C (default 50.0).
        dg: Free energy threshold in kcal/mol (default -5.0).
        score: Alignment score threshold (default 5).

    Returns:
        MFEprimerConfig with the command list.

    Raises:
        ValueError: If *primer_fasta* is empty.
    """
    if not primer_fasta or not primer_fasta.strip():
        raise ValueError("primer_fasta 不能为空。")

    cmd: list[str] = [
        "mfeprimer",
        "hairpin",
        "-i",
        primer_fasta,
        "--tm",
        str(tm),
        "--dg",
        str(dg),
        "--score",
        str(score),
    ]

    return MFEprimerConfig(
        command=cmd,
        input_fasta=primer_fasta,
        output_dir="",
    )


# ── Phase 3: degen command builder ─────────────────────────────────────


def build_mfeprimer_degen_command(
    *,
    primer_fasta: str,
) -> MFEprimerConfig:
    """Build an ``mfeprimer degen`` command.

    Uses positional FASTA argument (same convention as ``thermo``).

    Args:
        primer_fasta: Path to the primer FASTA file.

    Returns:
        MFEprimerConfig with the command list.

    Raises:
        ValueError: If *primer_fasta* is empty.
    """
    if not primer_fasta or not primer_fasta.strip():
        raise ValueError("primer_fasta 不能为空。")

    cmd: list[str] = [
        "mfeprimer",
        "degen",
        primer_fasta,
    ]

    return MFEprimerConfig(
        command=cmd,
        input_fasta=primer_fasta,
        output_dir="",
    )


# ── Phase 2: execution ─────────────────────────────────────────────────


def run_mfeprimer_qc_job(
    *,
    module: str,
    config: MFEprimerConfig,
    raw_path: str | Path,
    stderr_path: str | Path,
    resume: bool = False,
    force: bool = False,
    timeout: float | None = None,
    generated_file: str | Path | None = None,
) -> dict:
    """Execute a single MFEprimer QC job via subprocess.

    Captures stdout → *raw_path*, stderr → *stderr_path*.

    For modules that write output to a *generated_file* instead of stdout
    (e.g. thermo which writes ``<input>.thermo.tsv`` next to the input),
    pass the expected file path — it will be read and copied to
    *raw_path* after a successful run.

    Args:
        module: QC module name (``"thermo"``, ``"dimer"``, ``"hairpin"``).
        config: MFEprimerConfig with the command to run.
        raw_path: Path for writing captured output.
        stderr_path: Path for writing captured stderr.
        resume: If True, skip when both raw and stderr files already exist.
        force: If True, re-run even when resume would skip.
        timeout: Optional timeout in seconds.
        generated_file: Optional path to a file that mfeprimer generates
            (e.g. ``<input>.thermo.tsv``).  If set, the file is read and
            copied to *raw_path* after a successful run.

    Returns:
        A dict with keys matching ``QC_FAILED_JOBS_FIELDNAMES``.
    """
    raw_path = Path(raw_path)
    stderr_path = Path(stderr_path)
    cmd_str = " ".join(config.command)

    # ── resume / skip check ──────────────────────────────────────────
    if resume and not force:
        if raw_path.is_file() and stderr_path.is_file():
            return {
                "module": module,
                "command": cmd_str,
                "output": str(raw_path),
                "status": "skipped",
                "error_message": "已有结果，跳过（--resume）",
            }

    # ── ensure output directory ──────────────────────────────────────
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    # ── check mfeprimer availability ─────────────────────────────────
    if not check_mfeprimer_available():
        return {
            "module": module,
            "command": cmd_str,
            "output": str(raw_path),
            "status": "failed",
            "error_message": (
                "MFEprimer 未找到。请确认 MFEprimer 已安装且在 PATH 中。"
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

        if proc.returncode != 0:
            stderr_path.write_text(proc.stderr, encoding="utf-8")
            error_msg = (
                proc.stderr.strip()[:500]
                if proc.stderr.strip()
                else f"mfeprimer 返回非零退出码: {proc.returncode}"
            )
            return {
                "module": module,
                "command": cmd_str,
                "output": str(raw_path),
                "status": "failed",
                "error_message": error_msg,
            }

        # ── handle output: generated file or stdout ─────────────────
        if generated_file is not None:
            generated = Path(generated_file)
            if not generated.is_file():
                return {
                    "module": module,
                    "command": cmd_str,
                    "output": str(raw_path),
                    "status": "failed",
                    "error_message": (
                        f"未生成预期输出文件: {generated}"
                    ),
                }
            raw_path.write_text(
                generated.read_text(encoding="utf-8"), encoding="utf-8"
            )
        else:
            raw_path.write_text(proc.stdout, encoding="utf-8")

        stderr_path.write_text(proc.stderr, encoding="utf-8")

        return {
            "module": module,
            "command": cmd_str,
            "output": str(raw_path),
            "status": "success",
            "error_message": "",
        }

    except subprocess.TimeoutExpired:
        return {
            "module": module,
            "command": cmd_str,
            "output": str(raw_path),
            "status": "failed",
            "error_message": f"mfeprimer 执行超时 (timeout={timeout}s)。",
        }
    except FileNotFoundError:
        return {
            "module": module,
            "command": cmd_str,
            "output": str(raw_path),
            "status": "failed",
            "error_message": (
                "MFEprimer 未找到。请确认 MFEprimer 已安装且在 PATH 中。"
            ),
        }
    except Exception as exc:
        return {
            "module": module,
            "command": cmd_str,
            "output": str(raw_path),
            "status": "failed",
            "error_message": str(exc),
        }


# ── Phase 2: per-module runners (thin wrappers) ───────────────────────


def run_mfeprimer_thermo(
    *,
    primer_fasta: str,
    outdir: str | Path,
    resume: bool = False,
    force: bool = False,
    timeout: float | None = None,
) -> dict:
    """Build and run an ``mfeprimer thermo`` job.

    Thermo writes to ``<input_fasta>.thermo.tsv`` (a generated file), not
    stdout.  We copy it to ``<outdir>/thermo/thermo_raw.tsv``.

    Output: ``<outdir>/thermo/thermo_raw.tsv`` + ``thermo.stderr.log``.
    """
    config = build_mfeprimer_thermo_command(primer_fasta=primer_fasta)
    outdir = Path(outdir)
    # mfeprimer replaces the input extension with .thermo.tsv
    # e.g. primer_input.fasta → primer_input.thermo.tsv
    generated = Path(primer_fasta).with_suffix(".thermo.tsv")
    return run_mfeprimer_qc_job(
        module="thermo",
        config=config,
        raw_path=outdir / "thermo" / "thermo_raw.tsv",
        stderr_path=outdir / "thermo" / "thermo.stderr.log",
        generated_file=str(generated),
        resume=resume,
        force=force,
        timeout=timeout,
    )


def run_mfeprimer_dimer(
    *,
    primer_fasta: str,
    outdir: str | Path,
    score: int = 5,
    mismatch: int = 2,
    dg: float = -5.0,
    resume: bool = False,
    force: bool = False,
    timeout: float | None = None,
) -> dict:
    """Build and run an ``mfeprimer dimer`` job.

    Output: ``<outdir>/dimer/dimer_raw.txt`` + ``dimer.stderr.log``.
    """
    config = build_mfeprimer_dimer_command(
        primer_fasta=primer_fasta,
        score=score,
        mismatch=mismatch,
        dg=dg,
    )
    outdir = Path(outdir)
    return run_mfeprimer_qc_job(
        module="dimer",
        config=config,
        raw_path=outdir / "dimer" / "dimer_raw.txt",
        stderr_path=outdir / "dimer" / "dimer.stderr.log",
        resume=resume,
        force=force,
        timeout=timeout,
    )


def run_mfeprimer_hairpin(
    *,
    primer_fasta: str,
    outdir: str | Path,
    tm: float = 50.0,
    dg: float = -5.0,
    score: int = 5,
    resume: bool = False,
    force: bool = False,
    timeout: float | None = None,
) -> dict:
    """Build and run an ``mfeprimer hairpin`` job.

    Output: ``<outdir>/hairpin/hairpin_raw.txt`` + ``hairpin.stderr.log``.
    """
    config = build_mfeprimer_hairpin_command(
        primer_fasta=primer_fasta,
        tm=tm,
        dg=dg,
        score=score,
    )
    outdir = Path(outdir)
    return run_mfeprimer_qc_job(
        module="hairpin",
        config=config,
        raw_path=outdir / "hairpin" / "hairpin_raw.txt",
        stderr_path=outdir / "hairpin" / "hairpin.stderr.log",
        resume=resume,
        force=force,
        timeout=timeout,
    )


def run_mfeprimer_degen(
    *,
    primer_fasta: str,
    outdir: str | Path,
    resume: bool = False,
    force: bool = False,
    timeout: float | None = None,
) -> dict:
    """Build and run an ``mfeprimer degen`` job.

    MFEprimer degen writes results to stdout.  We capture it to
    ``<outdir>/degen/degen_raw.txt``.

    Output: ``<outdir>/degen/degen_raw.txt`` + ``degen.stderr.log``.
    """
    config = build_mfeprimer_degen_command(primer_fasta=primer_fasta)
    outdir = Path(outdir)
    return run_mfeprimer_qc_job(
        module="degen",
        config=config,
        raw_path=outdir / "degen" / "degen_raw.txt",
        stderr_path=outdir / "degen" / "degen.stderr.log",
        resume=resume,
        force=force,
        timeout=timeout,
    )


# ── Phase 4: index command ─────────────────────────────────────────────


def build_mfeprimer_index_command(
    *,
    database_path: str,
    kvalue: int = 9,
    cpu: int = 2,
    force: bool = False,
) -> MFEprimerConfig:
    """Build an ``mfeprimer index`` command.

    Args:
        database_path: Path to the FASTA database file.
        kvalue: k-mer size for indexing (default 9).
        cpu: Number of CPU threads (default 2).
        force: If True, add ``-f`` flag to force re-index.

    Returns:
        MFEprimerConfig with the command list.

    Raises:
        ValueError: If *database_path* is empty.
    """
    if not database_path or not database_path.strip():
        raise ValueError("database_path 不能为空。")

    cmd: list[str] = [
        "mfeprimer",
        "index",
        "-i",
        database_path,
        "-k",
        str(kvalue),
        "-c",
        str(cpu),
    ]
    if force:
        cmd.append("-f")

    return MFEprimerConfig(
        command=cmd,
        input_fasta=database_path,
        output_dir=str(Path(database_path).parent),
    )


def run_mfeprimer_index(
    *,
    database_path: str,
    outdir: str | Path,
    kvalue: int = 9,
    cpu: int = 2,
    resume: bool = False,
    force: bool = False,
    timeout: float | None = None,
) -> dict:
    """Build and run an ``mfeprimer index`` job.

    Index files (``.primerqc``, ``.fai``, ``.json``, ``.log``,
    ``.primerqc.fai``) are written next to *database_path*.

    Output: ``<outdir>/index/index.stderr.log`` and
    ``<outdir>/index/index.stdout.log`` (stdout may be empty; the
    ``.primerqc`` content is binary and NOT captured).

    Returns:
        Dict with keys matching ``QC_FAILED_JOBS_FIELDNAMES``.
    """
    config = build_mfeprimer_index_command(
        database_path=database_path,
        kvalue=kvalue,
        cpu=cpu,
        force=force,
    )
    outdir = Path(outdir)
    index_dir = outdir / "index"
    index_dir.mkdir(parents=True, exist_ok=True)

    # Success indicator: the .primerqc binary index file
    primerqc_path = Path(database_path).with_suffix(
        Path(database_path).suffix + ".primerqc"
    )

    return run_mfeprimer_qc_job(
        module="index",
        config=config,
        raw_path=index_dir / "index.stdout.log",
        stderr_path=index_dir / "index.stderr.log",
        generated_file=str(primerqc_path),
        resume=resume,
        force=force,
        timeout=timeout,
    )


# ── Phase 4: spec command ──────────────────────────────────────────────


def build_mfeprimer_spec_command(
    *,
    primer_pairs_tsv: str,
    database_path: str,
    out_prefix: str,
    min_size: int | None = None,
    max_size: int = 2000,
    tm: float = 30.0,
    max_tm: float = 100.0,
    mismatch: int | None = None,
    mis_start: int | None = None,
    mis_end: int | None = None,
    cpu: int = 4,
    kvalue: int = 9,
    max_amp_count: int = 10000,
    bind: bool = False,
    cut_primer: bool = False,
    mono: float | None = None,
    diva: float | None = None,
    dntp: float | None = None,
    oligo: float | None = None,
    json_output: bool = False,
) -> MFEprimerConfig:
    """Build an ``mfeprimer spec`` command (v4.2.4 parameter contract).

    Args:
        primer_pairs_tsv: Path to primer pairs TSV (name, fp, rp).
        database_path: Path to the indexed FASTA database.
        out_prefix: Output file prefix (``-o`` flag).
        min_size: Min amplicon size in bp (``-s``, optional).
        max_size: Max amplicon size in bp (``-S``, default 2000).
        tm: Minimum Tm cutoff in °C (``-t``, default 30).
        max_tm: Maximum Tm cutoff in °C (``-T``, default 100).
        mismatch: Max allowed mismatches (``--misMatch``, optional).
        mis_start: Mismatch start position from 3' end (``--misStart``, optional).
        mis_end: Mismatch end position from 3' end (``--misEnd``, optional).
        cpu: Number of CPU threads (``-c``, default 4).
        kvalue: k-mer size (``-k``, default 9).
        max_amp_count: Max amplicon threshold (``-M``, default 10000).
        bind: Print binding sites and patterns (``-b``, default False).
        cut_primer: Cut primer from amplicons (``--cutprimer``, default False).
        mono: Monovalent cation concentration in mM (``--mono``, optional).
        diva: Divalent cation concentration in mM (``--diva``, optional).
        dntp: dNTP concentration in mM (``--dntp``, optional).
        oligo: Annealing oligo concentration in nM (``--oligo``, optional).
        json_output: If True, add ``-j`` for JSON output.

    Returns:
        MFEprimerConfig with the command list.

    Raises:
        ValueError: If required parameters are missing.
    """
    if not primer_pairs_tsv or not primer_pairs_tsv.strip():
        raise ValueError("primer_pairs_tsv 不能为空。")
    if not database_path or not database_path.strip():
        raise ValueError("database_path 不能为空。")
    if not out_prefix or not out_prefix.strip():
        raise ValueError("out_prefix 不能为空。")

    cmd: list[str] = [
        "mfeprimer",
        "spec",
        "-i",
        primer_pairs_tsv,
        "-d",
        database_path,
        "-o",
        out_prefix,
        "-S",
        str(max_size),
        "-t",
        str(tm),
        "-T",
        str(max_tm),
        "-k",
        str(kvalue),
        "-c",
        str(cpu),
        "-M",
        str(max_amp_count),
    ]

    if min_size is not None:
        cmd.extend(["-s", str(min_size)])
    if mismatch is not None:
        cmd.extend(["--misMatch", str(mismatch)])
    if mis_start is not None:
        cmd.extend(["--misStart", str(mis_start)])
    if mis_end is not None:
        cmd.extend(["--misEnd", str(mis_end)])
    if bind:
        cmd.append("-b")
    if cut_primer:
        cmd.append("--cutprimer")
    if mono is not None:
        cmd.extend(["--mono", str(mono)])
    if diva is not None:
        cmd.extend(["--diva", str(diva)])
    if dntp is not None:
        cmd.extend(["--dntp", str(dntp)])
    if oligo is not None:
        cmd.extend(["--oligo", str(oligo)])
    if json_output:
        cmd.append("-j")

    return MFEprimerConfig(
        command=cmd,
        input_fasta=primer_pairs_tsv,
        output_dir=str(Path(out_prefix).parent),
    )


def run_mfeprimer_spec(
    *,
    primer_pairs_tsv: str,
    database_path: str,
    outdir: str | Path,
    min_size: int | None = None,
    max_size: int = 2000,
    tm: float = 30.0,
    max_tm: float = 100.0,
    mismatch: int | None = None,
    mis_start: int | None = None,
    mis_end: int | None = None,
    cpu: int = 4,
    kvalue: int = 9,
    max_amp_count: int = 10000,
    bind: bool = False,
    cut_primer: bool = False,
    mono: float | None = None,
    diva: float | None = None,
    dntp: float | None = None,
    oligo: float | None = None,
    json_output: bool = False,
    resume: bool = False,
    force: bool = False,
    timeout: float | None = None,
) -> dict:
    """Build and run an ``mfeprimer spec`` job.

    MFEprimer writes the main report to ``-o <out_prefix>`` and
    auto-generates ``<out_prefix>.spec.tsv`` and ``<out_prefix>.mfe.log``.

    Output files in ``<outdir>/spec/``:

    - ``spec_output.txt`` — main human-readable report (mfeprimer ``-o``)
    - ``spec_output.txt.spec.tsv`` — structured 21-column TSV (auto-generated)
    - ``spec_output.txt.mfe.log`` — execution log (auto-generated)
    - ``spec.stdout.log`` — captured stdout (usually empty)
    - ``spec.stderr.log`` — captured stderr

    Returns:
        Dict with keys matching ``QC_FAILED_JOBS_FIELDNAMES``.
    """
    outdir = Path(outdir)
    spec_dir = outdir / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    out_prefix = str(spec_dir / "spec_output.txt")

    config = build_mfeprimer_spec_command(
        primer_pairs_tsv=primer_pairs_tsv,
        database_path=database_path,
        out_prefix=out_prefix,
        min_size=min_size,
        max_size=max_size,
        tm=tm,
        max_tm=max_tm,
        mismatch=mismatch,
        mis_start=mis_start,
        mis_end=mis_end,
        cpu=cpu,
        kvalue=kvalue,
        max_amp_count=max_amp_count,
        bind=bind,
        cut_primer=cut_primer,
        mono=mono,
        diva=diva,
        dntp=dntp,
        oligo=oligo,
        json_output=json_output,
    )

    # mfeprimer auto-generates <out_prefix>.spec.tsv — use it as the
    # generated_file so run_mfeprimer_qc_job verifies it exists after
    # a successful run.  stdout is captured to spec.stdout.log (which
    # is overwritten with .spec.tsv content by the generated_file
    # copy — harmless since stdout is normally empty for spec).
    generated_spec = out_prefix + ".spec.tsv"

    return run_mfeprimer_qc_job(
        module="spec",
        config=config,
        raw_path=spec_dir / "spec.stdout.log",
        stderr_path=spec_dir / "spec.stderr.log",
        generated_file=str(generated_spec),
        resume=resume,
        force=force,
        timeout=timeout,
    )
