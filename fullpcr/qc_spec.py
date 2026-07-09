"""MFEprimer spec output parser and specificity summary.

Phase 4.1: parse ``.spec.tsv``, summarise per-primer specificity metrics,
and generate ``primer_spec.tsv`` + ``qc_spec_failed_jobs.tsv``.
Phase 4.1.1: FASTA validation, normalisation, index-output checks,
and database_stats.tsv.
"""

from __future__ import annotations

import csv
import json
import shutil
import statistics
from pathlib import Path

from fullpcr.mfeprimer_runner import (
    QC_FAILED_JOBS_FIELDNAMES,
    run_mfeprimer_index,
)
from fullpcr.qc import parse_primer_name

# ── constants ──────────────────────────────────────────────────────────────

SPEC_TSV_FIELDNAMES = [
    "name",
    "chrom",
    "ampStart",
    "ampEnd",
    "ampGC",
    "ampSize",
    "fpName",
    "fpStart",
    "fpEnd",
    "fpSeq",
    "fpTm",
    "fpGC",
    "fpDg",
    "rpName",
    "rpEnd",
    "rpStart",
    "rpSeq",
    "rpTm",
    "rpGC",
    "rpDg",
    "note",
]

PRIMER_SPEC_FIELDNAMES = [
    "primer_id",
    "spec_amplicon_count",
    "unique_reference_count",
    "unique_taxid_count",
    "unique_species_count",
    "min_amplicon_size",
    "max_amplicon_size",
    "mean_amplicon_size",
    "multi_amplicon_reference_count",
    "max_amplicons_per_reference",
    "fp_tm_min",
    "fp_tm_max",
    "rp_tm_min",
    "rp_tm_max",
    "size_outlier_count",
    "database_reference_count",
    "spec_reference_fraction",
    "status",
    "reason",
]

DATABASE_STATS_FIELDNAMES = [
    "source_database",
    "prepared_database",
    "source_record_count",
    "prepared_record_count",
    "source_total_bases",
    "prepared_total_bases",
    "index_files_present",
    "status",
    "reason",
]

_NA = "NA"

# ── helpers ────────────────────────────────────────────────────────────────


def _safe_float(value: str) -> float | str:
    """Convert *value* to float, returning ``"NA"`` on failure."""
    if not value or not value.strip():
        return _NA
    try:
        return float(value.strip())
    except (ValueError, TypeError):
        return _NA


def _safe_int(value: str) -> int | str:
    """Convert *value* to int, returning ``"NA"`` on failure."""
    if not value or not value.strip():
        return _NA
    try:
        return int(value.strip())
    except (ValueError, TypeError):
        return _NA


def _write_tsv(
    path: Path, fieldnames: list[str], rows: list[dict],
) -> Path:
    """Write a list of dicts to a TSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return path


def _extract_note_json(note: str) -> dict[str, str]:
    """Extract taxid / scientific_name from the note field.

    The note typically contains a JSON object followed by arbitrary text.
    e.g. ``{"taxid":"451427","scientific_name":"Foo"} Bar mitochondrion``

    Returns:
        Dict with keys ``taxid``, ``scientific_name`` (both ``"NA"`` on
        failure).
    """
    result: dict[str, str] = {"taxid": _NA, "scientific_name": _NA}
    if not note or not note.strip():
        return result

    note = note.strip()
    if not note.startswith("{"):
        return result

    depth = 0
    end = 0
    for i, ch in enumerate(note):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == 0:
        return result

    json_part = note[:end]
    try:
        meta = json.loads(json_part)
    except (json.JSONDecodeError, TypeError):
        return result

    if isinstance(meta, dict):
        result["taxid"] = str(meta.get("taxid", _NA))
        result["scientific_name"] = str(
            meta.get("scientific_name", _NA)
        )
    return result


# ── FASTA utilities ─────────────────────────────────────────────────────


def count_fasta_records(path: str | Path) -> int:
    """Count the number of FASTA records (``>`` markers anywhere in the file).

    Normally ``>`` appears at the start of a line, but this function also
    handles malformed FASTA where records were concatenated without
    newlines (``>`` embedded mid-line).

    Returns 0 if the file is missing or unreadable.
    """
    path = Path(path)
    if not path.is_file():
        return 0
    count = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            count += line.count(">")
    return count


def count_fasta_bases(path: str | Path) -> int:
    """Sum the lengths of all sequence lines (non-header, non-empty).

    Each sequence line is ``.strip()``-ed so that trailing spaces,
    tabs, and carriage returns are **not** counted as bases.
    Empty lines are ignored.
    """
    path = Path(path)
    if not path.is_file():
        return 0
    total = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith(">"):
                continue
            total += len(stripped)
    return total


def normalize_fasta_for_mfeprimer(
    input_path: str | Path,
    output_path: str | Path,
    line_width: int = 80,
) -> Path:
    """Re-wrap a FASTA file so every sequence line is *line_width* bases.

    MFEprimer index requires consistent line lengths within each sequence.
    This function reads *input_path*, strips all whitespace from sequence
    lines, and rewrites them wrapped at *line_width*.

    Handles malformed concatenated FASTA where ``>`` record separators
    appear mid-line (no newline between records).  Such embedded ``>``
    markers are treated as record boundaries.

    Args:
        input_path: Source FASTA (any line width, including single-line).
        output_path: Destination path for the normalised FASTA.
        line_width: Wrapped line width in bases (default 80).

    Returns:
        The resolved *output_path*.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as out:
        current_seq: list[str] = []
        current_header = ""

        def _flush() -> None:
            nonlocal current_header, current_seq
            if not current_header:
                return
            out.write(current_header + "\n")
            seq = "".join(current_seq)
            for i in range(0, len(seq), line_width):
                out.write(seq[i : i + line_width] + "\n")
            current_header = ""
            current_seq.clear()

        with open(input_path, encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith(">"):
                    _flush()
                    current_header = stripped
                elif ">" in stripped:
                    # Malformed concatenation: ">" separator embedded
                    # mid-line (records joined without newlines).
                    parts = stripped.split(">")
                    # First chunk is trailing sequence of current record.
                    if parts[0]:
                        current_seq.append(parts[0])
                    # Each subsequent chunk starts a new record.
                    for part in parts[1:]:
                        _flush()
                        current_header = ">" + part
                else:
                    current_seq.append(stripped)
            _flush()

    return output_path


def validate_mfeprimer_index_outputs(
    index_dir: str | Path,
    database_path: str | Path,
) -> tuple[bool, list[str]]:
    """Check that all MFEprimer index output files exist and are non-empty.

    Args:
        index_dir: Directory containing the indexed database copy.
        database_path: Path to the FASTA file that was indexed.

    Returns:
        ``(all_ok, missing)`` where *all_ok* is True when every expected
        file is present and non-empty, and *missing* lists any absent or
        empty file paths.
    """
    index_dir = Path(index_dir)
    db_path = Path(database_path)
    db_stem = str(db_path)

    expected = [
        db_stem + ".fai",
        db_stem + ".json",
        db_stem + ".primerqc",
        db_stem + ".primerqc.fai",
        db_stem + ".log",
    ]

    missing: list[str] = []
    for fpath in expected:
        p = Path(fpath)
        if not p.is_file():
            missing.append(str(p))
        elif p.stat().st_size == 0:
            missing.append(str(p) + " (空文件)")

    return len(missing) == 0, missing


# ── database preparation ───────────────────────────────────────────────────


def prepare_spec_database(
    database_path: str | Path,
    index_dir: str | Path,
    force: bool = False,
    kvalue: int = 9,
    cpu: int = 2,
    timeout: float | None = None,
) -> tuple[dict, dict]:
    """Normalise the database FASTA, copy into *index_dir*, and build an
    MFEprimer index.

    The original database is never modified.  The FASTA is first re-wrapped
    to consistent *line_width* (80 bp) so MFEprimer index can process it
    reliably.

    If source and prepared record counts differ,
    ``FAIL_DATABASE_PREP`` is returned and indexing is **skipped**.

    Args:
        database_path: Path to the original FASTA database.
        index_dir: Directory where the copy and index files are written.
        force: If True, re-normalise and re-index even when outputs exist.
        kvalue: k-mer size for indexing (default 9).
        cpu: Number of CPU threads (default 2).
        timeout: Optional timeout in seconds for the index command.

    Returns:
        ``(index_result, db_stats)`` where *index_result* has keys from
        ``QC_FAILED_JOBS_FIELDNAMES`` and *db_stats* has keys from
        ``DATABASE_STATS_FIELDNAMES``.
    """
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)

    db_name = Path(database_path).name
    db_copy = index_dir / db_name

    # ── count source ───────────────────────────────────────────────────
    source_count = count_fasta_records(database_path)
    source_bases = count_fasta_bases(database_path)

    # ── normalise and write wrapped FASTA ──────────────────────────────
    if force or not db_copy.is_file():
        normalize_fasta_for_mfeprimer(database_path, db_copy, line_width=80)

    prepared_count = count_fasta_records(db_copy)
    prepared_bases = count_fasta_bases(db_copy)

    # ── build db_stats ─────────────────────────────────────────────────
    index_files_ok, _missing_files = validate_mfeprimer_index_outputs(
        index_dir, db_copy,
    )

    db_stats: dict = {
        "source_database": str(Path(database_path).resolve()),
        "prepared_database": str(db_copy.resolve()),
        "source_record_count": source_count,
        "prepared_record_count": prepared_count,
        "source_total_bases": source_bases,
        "prepared_total_bases": prepared_bases,
        "index_files_present": str(index_files_ok),
        "status": "PASS",
        "reason": "",
    }

    # ── validate record counts match ───────────────────────────────────
    if source_count != prepared_count:
        db_stats["status"] = "FAIL_DATABASE_PREP"
        db_stats["reason"] = (
            f"source_record_count={source_count} != "
            f"prepared_record_count={prepared_count}"
        )
        index_result: dict = {
            "module": "index",
            "command": "skipped — database preparation failed",
            "output": str(db_copy),
            "status": "failed",
            "error_message": db_stats["reason"],
        }
        return index_result, db_stats

    # ── detect sequence cleaning ─────────────────────────────────────
    if source_bases != prepared_bases:
        delta = source_bases - prepared_bases
        db_stats["status"] = "WARN_SEQUENCE_CLEANED"
        db_stats["reason"] = (
            f"source_total_bases={source_bases} → "
            f"prepared_total_bases={prepared_bases} "
            f"(Δ={delta}, 规范化去除了行尾空白/非法字符)"
        )

    # ── run index ──────────────────────────────────────────────────────
    index_result = run_mfeprimer_index(
        database_path=str(db_copy),
        outdir=str(index_dir.parent),
        kvalue=kvalue,
        cpu=cpu,
        resume=not force,
        force=force,
        timeout=timeout,
    )

    # ── validate index outputs ────────────────────────────────────────
    index_ok, missing = validate_mfeprimer_index_outputs(index_dir, db_copy)
    db_stats["index_files_present"] = str(index_ok)

    if not index_ok:
        if index_result["status"] == "success":
            index_result["status"] = "failed"
            index_result["error_message"] = (
                "index 文件缺失或为空: " + ", ".join(missing)
            )
        db_stats["status"] = "FAIL_INDEX"
        db_stats["reason"] = "缺失/空的 index 文件: " + ", ".join(missing)

    return index_result, db_stats


# ── primer pairs export ────────────────────────────────────────────────────


def write_spec_primer_pairs(
    primers, output_path: str | Path,
) -> Path:
    """Write primer pairs as a 3-column TSV (no header) for MFEprimer spec.

    Columns: ``name``, ``fp``, ``rp``.

    Args:
        primers: List of ``Primer`` records.
        output_path: Path where the TSV should be written.

    Returns:
        The resolved output Path.

    Raises:
        ValueError: If *primers* is empty.
    """
    if not primers:
        raise ValueError("primers 列表不能为空。")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for p in primers:
        lines.append(f"{p.primer_id}\t{p.forward}\t{p.reverse}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


# ── spec.tsv parser ────────────────────────────────────────────────────────


def parse_spec_tsv(path: str | Path) -> list[dict]:
    """Parse an MFEprimer ``.spec.tsv`` file.

    The file has a leading comment line (``#1-based coordinate...``),
    followed by a header line prefixed with ``#name``, then data rows.

    Returns:
        List of dicts with keys from ``SPEC_TSV_FIELDNAMES``, with numeric
        columns (ampStart, ampEnd, ampGC, ampSize, fpTm, fpGC, fpDg, rpTm,
        rpGC, rpDg) converted to float/int and ``taxid`` /
        ``scientific_name`` extracted from the ``note`` field.
        Empty list if the file is missing or unparseable.
    """
    path = Path(path)
    if not path.is_file():
        return []

    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            # Skip comment / header lines
            if line.startswith("#"):
                continue

            parts = line.split("\t")
            if len(parts) < 21:
                continue

            note_raw = parts[20].strip() if len(parts) > 20 else ""
            note_meta = _extract_note_json(note_raw)

            rows.append(
                {
                    "name": parts[0].strip(),
                    "chrom": parts[1].strip(),
                    "ampStart": _safe_int(parts[2]),
                    "ampEnd": _safe_int(parts[3]),
                    "ampGC": _safe_float(parts[4]),
                    "ampSize": _safe_int(parts[5]),
                    "fpName": parts[6].strip(),
                    "fpStart": _safe_int(parts[7]),
                    "fpEnd": _safe_int(parts[8]),
                    "fpSeq": parts[9].strip(),
                    "fpTm": _safe_float(parts[10]),
                    "fpGC": _safe_float(parts[11]),
                    "fpDg": _safe_float(parts[12]),
                    "rpName": parts[13].strip(),
                    "rpEnd": _safe_int(parts[14]),
                    "rpStart": _safe_int(parts[15]),
                    "rpSeq": parts[16].strip(),
                    "rpTm": _safe_float(parts[17]),
                    "rpGC": _safe_float(parts[18]),
                    "rpDg": _safe_float(parts[19]),
                    "note": note_raw,
                    "taxid": note_meta["taxid"],
                    "scientific_name": note_meta["scientific_name"],
                }
            )

    return rows


# ── specificity summary ────────────────────────────────────────────────────


def _infer_primer_id(record: dict) -> str:
    """Infer primer_id from a spec record's fpName / rpName.

    Handles MFEprimer TSV-input naming conventions:

    - ``12S_long_fp`` → ``12S_long``
    - ``12S_long_rp`` → ``12S_long``
    - ``16S_short_fp.144`` → ``16S_short``
    - ``16S_short_rp.216`` → ``16S_short``
    - ``12S_long_F`` → ``12S_long`` (FASTA-input convention)

    Falls back to fpName as-is if no pattern matches.
    """
    fp_name = record.get("fpName", "")

    # Try the FASTA convention first: _F / _R / __F / __R
    primer_id, _side = parse_primer_name(fp_name)
    if primer_id and primer_id != fp_name:
        return primer_id

    # Try the TSV convention: _fp / _rp [.NNN]
    if "_fp" in fp_name:
        idx = fp_name.find("_fp")
        return fp_name[:idx]
    if "_rp" in fp_name:
        idx = fp_name.find("_rp")
        return fp_name[:idx]

    return fp_name


def _detect_size_outliers(sizes: list[int]) -> int:
    """Count size outliers.

    Uses the IQR method (1.5 × IQR) when there is enough spread.
    Falls back to a 2-standard-deviation method when the IQR is zero
    (e.g. many identical values plus one extreme).
    Returns 0 when fewer than 5 data points.
    """
    if len(sizes) < 5:
        return 0

    sorted_sizes = sorted(sizes)
    n = len(sorted_sizes)

    # Linear-interpolation percentile
    def _pct(p: float) -> float:
        k = (n - 1) * p
        f = int(k)
        c = k - f
        if f + 1 < n:
            return sorted_sizes[f] + c * (
                sorted_sizes[f + 1] - sorted_sizes[f]
            )
        return float(sorted_sizes[f])

    q1 = _pct(0.25)
    q3 = _pct(0.75)
    iqr = q3 - q1

    if iqr > 0:
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
    else:
        # Fallback: 2 standard deviations from the mean
        mean = statistics.mean(sizes)
        if len(sizes) >= 2:
            stdev = statistics.stdev(sizes)
        else:
            return 0
        if stdev == 0:
            return 0
        lower = mean - 2.0 * stdev
        upper = mean + 2.0 * stdev

    return sum(1 for s in sizes if s < lower or s > upper)


def summarize_spec_records(
    records: list[dict],
    primer_pairs: list | None = None,
    max_amp_count: int = 10000,
    database_reference_count: int = 0,
) -> list[dict]:
    """Summarise spec records per primer pair.

    Groups amplicon records by primer_id (inferred from ``fpName``) and
    computes specificity statistics.

    Important: ``unique_taxid_count > 1`` is **not** treated as
    non-specific — metabarcoding primers are expected to amplify across
    multiple species.

    Args:
        records: Parsed spec records from ``parse_spec_tsv()``.
        primer_pairs: Optional list of Primer records for cross-referencing.
        max_amp_count: Threshold for ``WARN_OVERAMP`` status.
        database_reference_count: Total sequences in the indexed database
            (from ``database_stats.tsv``).  Used to compute
            ``spec_reference_fraction``.

    Returns:
        List of dicts with keys from ``PRIMER_SPEC_FIELDNAMES``.
    """
    # Group records by primer_id
    by_primer: dict[str, list[dict]] = {}
    for rec in records:
        pid = _infer_primer_id(rec)
        by_primer.setdefault(pid, []).append(rec)

    # Collect all known primer IDs
    all_ids: set[str] = set(by_primer.keys())
    if primer_pairs:
        for p in primer_pairs:
            all_ids.add(p.primer_id)

    rows: list[dict] = []
    for pid in sorted(all_ids):
        amp_records = by_primer.get(pid, [])

        if not amp_records:
            rows.append(
                {
                    "primer_id": pid,
                    "spec_amplicon_count": 0,
                    "unique_reference_count": 0,
                    "unique_taxid_count": 0,
                    "unique_species_count": 0,
                    "min_amplicon_size": _NA,
                    "max_amplicon_size": _NA,
                    "mean_amplicon_size": _NA,
                    "multi_amplicon_reference_count": 0,
                    "max_amplicons_per_reference": 0,
                    "fp_tm_min": _NA,
                    "fp_tm_max": _NA,
                    "rp_tm_min": _NA,
                    "rp_tm_max": _NA,
                    "size_outlier_count": 0,
                    "database_reference_count": database_reference_count,
                    "spec_reference_fraction": (
                        0.0 if database_reference_count > 0 else _NA
                    ),
                    "status": "WARN_NO_AMP",
                    "reason": "spec 未产生任何 amplicon",
                }
            )
            continue

        amp_count = len(amp_records)
        references: set[str] = set()
        taxids: set[str] = set()
        species: set[str] = set()
        sizes: list[int] = []
        fp_tms: list[float] = []
        rp_tms: list[float] = []

        ref_counter: dict[str, int] = {}

        for rec in amp_records:
            chrom = rec.get("chrom", "")
            if chrom:
                references.add(chrom)
                ref_counter[chrom] = ref_counter.get(chrom, 0) + 1

            taxid = rec.get("taxid", _NA)
            if taxid and taxid != _NA:
                taxids.add(str(taxid))

            sp = rec.get("scientific_name", _NA)
            if sp and sp != _NA:
                species.add(sp)

            size = rec.get("ampSize")
            if isinstance(size, int):
                sizes.append(size)

            fp_tm = rec.get("fpTm")
            if isinstance(fp_tm, (int, float)):
                fp_tms.append(float(fp_tm))

            rp_tm = rec.get("rpTm")
            if isinstance(rp_tm, (int, float)):
                rp_tms.append(float(rp_tm))

        multi_amp_refs = sum(
            1 for cnt in ref_counter.values() if cnt > 1
        )
        max_per_ref = max(ref_counter.values()) if ref_counter else 0

        min_size = min(sizes) if sizes else _NA
        max_size = max(sizes) if sizes else _NA
        mean_size: float | str
        if sizes:
            mean_size = round(statistics.mean(sizes), 1)
        else:
            mean_size = _NA

        fp_tm_min = min(fp_tms) if fp_tms else _NA
        fp_tm_max = max(fp_tms) if fp_tms else _NA
        rp_tm_min = min(rp_tms) if rp_tms else _NA
        rp_tm_max = max(rp_tms) if rp_tms else _NA

        size_outliers = _detect_size_outliers(sizes)

        # ── spec_reference_fraction ───────────────────────────────────
        unique_refs = len(references)
        if database_reference_count > 0:
            spec_ref_frac: float | str = round(
                unique_refs / database_reference_count, 4
            )
        else:
            spec_ref_frac = _NA

        # ── determine status ──────────────────────────────────────────
        statuses: list[str] = []
        reasons: list[str] = []

        if multi_amp_refs > 0:
            statuses.append("WARN_MULTI_AMP")
            reasons.append(
                f"{multi_amp_refs} 条参考序列在同一 primer 上产生多个 amplicon"
            )

        if amp_count > max_amp_count:
            statuses.append("WARN_OVERAMP")
            reasons.append(
                f"amplicon_count={amp_count} > max_amp_count={max_amp_count}"
            )

        if size_outliers > 0:
            statuses.append("WARN_SIZE")
            reasons.append(f"{size_outliers} 个 amplicon 长度异常")

        if not statuses:
            status = "PASS"
            reason = ""
        else:
            status = "; ".join(statuses)
            reason = "; ".join(reasons)

        rows.append(
            {
                "primer_id": pid,
                "spec_amplicon_count": amp_count,
                "unique_reference_count": unique_refs,
                "unique_taxid_count": len(taxids),
                "unique_species_count": len(species),
                "min_amplicon_size": min_size,
                "max_amplicon_size": max_size,
                "mean_amplicon_size": mean_size,
                "multi_amplicon_reference_count": multi_amp_refs,
                "max_amplicons_per_reference": max_per_ref,
                "fp_tm_min": fp_tm_min,
                "fp_tm_max": fp_tm_max,
                "rp_tm_min": rp_tm_min,
                "rp_tm_max": rp_tm_max,
                "size_outlier_count": size_outliers,
                "database_reference_count": database_reference_count,
                "spec_reference_fraction": spec_ref_frac,
                "status": status,
                "reason": reason,
            }
        )

    return rows


# ── output writer ──────────────────────────────────────────────────────────


def write_spec_outputs(
    spec_dir: str | Path,
    records: list[dict] | None = None,
    primer_pairs: list | None = None,
    failed_jobs: list[dict] | None = None,
    max_amp_count: int = 10000,
    database_reference_count: int = 0,
    db_stats: dict | None = None,
) -> dict[str, Path]:
    """Write spec summary outputs.

    Reads ``spec/spec_output.txt.spec.tsv`` if *records* is not provided.

    Generates:
    - ``spec/primer_spec.tsv``
    - ``index/database_stats.tsv`` (if *db_stats* provided)
    - ``qc_spec_failed_jobs.tsv`` (if *failed_jobs* provided)

    Args:
        spec_dir: Path to the spec output directory (contains ``spec/``).
        records: Pre-parsed spec records (parsed from file if None).
        primer_pairs: Optional list of Primer records.
        failed_jobs: Optional list of failed job dicts.
        max_amp_count: Threshold for ``WARN_OVERAMP``.
        database_reference_count: Total sequences in the indexed database.
        db_stats: Optional database stats dict (written to
            ``index/database_stats.tsv``).

    Returns:
        Dict mapping logical name to written path.
    """
    spec_dir = Path(spec_dir)
    spec_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}

    # Parse spec.tsv if records not provided
    if records is None:
        spec_tsv_path = spec_dir / "spec" / "spec_output.txt.spec.tsv"
        records = parse_spec_tsv(spec_tsv_path)

    # Summarise
    summary_rows = summarize_spec_records(
        records,
        primer_pairs=primer_pairs,
        max_amp_count=max_amp_count,
        database_reference_count=database_reference_count,
    )
    written["primer_spec"] = _write_tsv(
        spec_dir / "spec" / "primer_spec.tsv",
        PRIMER_SPEC_FIELDNAMES,
        summary_rows,
    )

    # Database stats
    if db_stats is not None:
        written["database_stats"] = _write_tsv(
            spec_dir / "index" / "database_stats.tsv",
            DATABASE_STATS_FIELDNAMES,
            [db_stats],
        )

    # Failed jobs
    if failed_jobs is not None:
        written["qc_spec_failed_jobs"] = _write_tsv(
            spec_dir / "qc_spec_failed_jobs.tsv",
            QC_FAILED_JOBS_FIELDNAMES,
            failed_jobs,
        )

    return written
