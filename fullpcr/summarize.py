"""Combine amplicon records, taxonomy, and resolution into summary tables."""

from __future__ import annotations

import csv
import warnings
from pathlib import Path

from fullpcr.resolution import RESOLUTION_FIELDNAMES, summarize_resolution
from fullpcr.taxonomy import (
    merge_taxonomy,
    read_taxonomy,
    summarize_taxonomic_coverage,
)

# ── constants ──────────────────────────────────────────────────────────

COMBINED_SUMMARY_FIELDNAMES = [
    "primer_id",
    "mismatch",
    "amplicon_count",
    "unique_taxid_count",
    "unique_species_count",
    "unique_sequence_count",
    "matched_taxonomy_count",
    "missing_taxonomy_count",
    "min_amplicon_length",
    "max_amplicon_length",
    "mean_amplicon_length",
    "forward_error_mean",
    "reverse_error_mean",
    "ambiguous_sequence_count",
    "ambiguous_species_count",
    "species_level_unique_resolution_rate",
]

COVERAGE_FIELDNAMES = [
    "primer_id",
    "mismatch",
    "rank",
    "name",
    "amplicon_count",
    "unique_taxid_count",
    "unique_species_count",
]

LENGTH_DIST_FIELDNAMES = [
    "primer_id",
    "mismatch",
    "amplicon_length",
    "count",
]

MISMATCH_DIST_FIELDNAMES = [
    "primer_id",
    "mismatch",
    "forward_error",
    "reverse_error",
    "count",
]

SPECIES_RESOLUTION_FIELDNAMES = ["primer_id", "mismatch"] + RESOLUTION_FIELDNAMES

OUTPUT_FILES = {
    "combined_summary": "combined_summary.tsv",
    "coverage_by_taxon": "coverage_by_taxon.tsv",
    "length_distribution": "length_distribution.tsv",
    "mismatch_distribution": "mismatch_distribution.tsv",
    "species_resolution": "species_resolution.tsv",
}


# ── per-primer×mismatch stats ──────────────────────────────────────────


def summarize_amplicons(
    records: list[dict],
    primer_id: str | None = None,
    mismatch: int | None = None,
) -> dict:
    """Compute statistics for a single primer × mismatch combination."""
    pid = primer_id or ""
    mm = mismatch if mismatch is not None else ""

    if not records:
        return _empty_summary(pid, mm)

    amplicon_count = len(records)

    # Taxonomy status counts
    matched_count = sum(
        1 for r in records if r.get("taxonomy_status") == "matched"
    )
    missing_count = amplicon_count - matched_count

    # Unique counts
    taxids = {r.get("taxid", "") for r in records if r.get("taxid", "")}
    species_set = {_safe_species(r) for r in records if _safe_species(r)}
    sequences = {
        (r.get("sequence") or "").strip().upper()
        for r in records
        if (r.get("sequence") or "").strip()
    }

    # Length stats
    lengths = [
        _safe_int(r.get("amplicon_length"))
        for r in records
        if _safe_int(r.get("amplicon_length")) > 0
    ]

    # Error stats
    fw_errors = [
        _safe_float(r.get("forward_error"))
        for r in records
        if r.get("forward_error", "") != ""
    ]
    rv_errors = [
        _safe_float(r.get("reverse_error"))
        for r in records
        if r.get("reverse_error", "") != ""
    ]

    # Resolution stats
    res = summarize_resolution(records)

    return {
        "primer_id": pid,
        "mismatch": mm,
        "amplicon_count": amplicon_count,
        "unique_taxid_count": len(taxids),
        "unique_species_count": len(species_set),
        "unique_sequence_count": len(sequences),
        "matched_taxonomy_count": matched_count,
        "missing_taxonomy_count": missing_count,
        "min_amplicon_length": min(lengths) if lengths else 0,
        "max_amplicon_length": max(lengths) if lengths else 0,
        "mean_amplicon_length": round(
            sum(lengths) / len(lengths), 2
        ) if lengths else 0.0,
        "forward_error_mean": round(
            sum(fw_errors) / len(fw_errors), 4
        ) if fw_errors else 0.0,
        "reverse_error_mean": round(
            sum(rv_errors) / len(rv_errors), 4
        ) if rv_errors else 0.0,
        "ambiguous_sequence_count": res["ambiguous_sequence_count"],
        "ambiguous_species_count": res["ambiguous_species_count"],
        "species_level_unique_resolution_rate": res[
            "species_level_unique_resolution_rate"
        ],
    }


def _empty_summary(primer_id: str, mismatch) -> dict:
    """Return a zero-valued summary dict."""
    return {
        "primer_id": primer_id,
        "mismatch": mismatch,
        "amplicon_count": 0,
        "unique_taxid_count": 0,
        "unique_species_count": 0,
        "unique_sequence_count": 0,
        "matched_taxonomy_count": 0,
        "missing_taxonomy_count": 0,
        "min_amplicon_length": 0,
        "max_amplicon_length": 0,
        "mean_amplicon_length": 0.0,
        "forward_error_mean": 0.0,
        "reverse_error_mean": 0.0,
        "ambiguous_sequence_count": 0,
        "ambiguous_species_count": 0,
        "species_level_unique_resolution_rate": 0.0,
    }


# ── result directory processing ────────────────────────────────────────


def summarize_result_dir(
    result_dir: str | Path,
    taxonomy_path: str | Path | None = None,
) -> list[dict]:
    """Process all amplicons.tsv files under a results directory.

    Directory layout expected::

        result_dir/
          primer_id/
            mismatch_0/amplicons.tsv
            mismatch_1/amplicons.tsv

    Returns a list of combined-summary dicts (one per primer × mismatch).
    """
    result_dir = Path(result_dir)
    if not result_dir.is_dir():
        return []

    taxonomy: list[dict] | None = None
    if taxonomy_path is not None and Path(taxonomy_path).exists():
        taxonomy = read_taxonomy(taxonomy_path)

    summaries: list[dict] = []
    pairs = _discover_primer_mismatch_pairs(result_dir)

    for primer_id, mismatch, amplicon_path in sorted(
        pairs, key=lambda x: (x[0], x[1])
    ):
        records = _read_amplicons_tsv(amplicon_path)
        if taxonomy:
            records = merge_taxonomy(records, taxonomy)
        summaries.append(summarize_amplicons(records, primer_id, mismatch))

    return summaries


def _discover_primer_mismatch_pairs(
    result_dir: Path,
) -> list[tuple[str, int, Path]]:
    """Discover (primer_id, mismatch, amplicon_path) triples."""
    pairs: list[tuple[str, int, Path]] = []

    try:
        primer_dirs = sorted(d for d in result_dir.iterdir() if d.is_dir())
    except OSError:
        warnings.warn(
            f"无法读取结果目录 {result_dir}，跳过目录发现。",
            RuntimeWarning,
        )
        return pairs

    for primer_dir in primer_dirs:
        primer_id = primer_dir.name
        try:
            mismatch_dirs = sorted(
                d for d in primer_dir.iterdir() if d.is_dir()
            )
        except OSError:
            warnings.warn(
                f"无法读取 primer 子目录 {primer_dir}，跳过。",
                RuntimeWarning,
            )
            continue

        for mismatch_dir in mismatch_dirs:
            mismatch = _parse_mismatch_from_dirname(mismatch_dir.name)
            if mismatch is None:
                continue
            amplicon_path = mismatch_dir / "amplicons.tsv"
            if amplicon_path.is_file():
                pairs.append((primer_id, mismatch, amplicon_path))

    return pairs


# ── distribution tables ────────────────────────────────────────────────


def build_length_distribution(result_dir: str | Path) -> list[dict]:
    """Build per-primer×mismatch amplicon length distribution."""
    result_dir = Path(result_dir)
    rows: list[dict] = []

    for primer_id, mismatch, amplicon_path in _discover_primer_mismatch_pairs(
        result_dir
    ):
        records = _read_amplicons_tsv(amplicon_path)
        length_counts: dict[int, int] = {}
        for rec in records:
            length = _safe_int(rec.get("amplicon_length"))
            if length > 0:
                length_counts[length] = length_counts.get(length, 0) + 1

        for length, count in sorted(length_counts.items()):
            rows.append({
                "primer_id": primer_id,
                "mismatch": mismatch,
                "amplicon_length": length,
                "count": count,
            })

    return rows


def build_mismatch_distribution(result_dir: str | Path) -> list[dict]:
    """Build per-primer×mismatch forward/reverse error distribution."""
    result_dir = Path(result_dir)
    rows: list[dict] = []

    for primer_id, mismatch, amplicon_path in _discover_primer_mismatch_pairs(
        result_dir
    ):
        records = _read_amplicons_tsv(amplicon_path)
        error_counts: dict[tuple[str, str], int] = {}
        for rec in records:
            fw = _safe_str(rec.get("forward_error"))
            rv = _safe_str(rec.get("reverse_error"))
            key = (fw, rv)
            error_counts[key] = error_counts.get(key, 0) + 1

        for (fw, rv), count in sorted(error_counts.items()):
            rows.append({
                "primer_id": primer_id,
                "mismatch": mismatch,
                "forward_error": fw,
                "reverse_error": rv,
                "count": count,
            })

    return rows


def build_coverage_by_taxon(
    result_dir: str | Path,
    taxonomy_path: str | Path | None = None,
) -> list[dict]:
    """Build taxonomic coverage table across all primer×mismatch combos."""
    if taxonomy_path is None or not Path(taxonomy_path).exists():
        return []

    taxonomy = read_taxonomy(taxonomy_path)
    result_dir = Path(result_dir)
    rows: list[dict] = []

    for primer_id, mismatch, amplicon_path in _discover_primer_mismatch_pairs(
        result_dir
    ):
        records = _read_amplicons_tsv(amplicon_path)
        merged = merge_taxonomy(records, taxonomy)
        coverage = summarize_taxonomic_coverage(merged)
        for cov in coverage:
            cov["primer_id"] = primer_id
            cov["mismatch"] = mismatch
            rows.append(cov)

    return rows


def build_species_resolution(
    result_dir: str | Path,
    taxonomy_path: str | Path | None = None,
) -> list[dict]:
    """Build species resolution table across all primer×mismatch combos."""
    taxonomy = None
    if taxonomy_path is not None and Path(taxonomy_path).exists():
        taxonomy = read_taxonomy(taxonomy_path)

    result_dir = Path(result_dir)
    rows: list[dict] = []

    for primer_id, mismatch, amplicon_path in _discover_primer_mismatch_pairs(
        result_dir
    ):
        records = _read_amplicons_tsv(amplicon_path)
        if taxonomy:
            records = merge_taxonomy(records, taxonomy)
        res = summarize_resolution(records)
        res["primer_id"] = primer_id
        res["mismatch"] = mismatch
        rows.append(res)

    return rows


# ── output writers ─────────────────────────────────────────────────────


def write_summary_outputs(
    result_dir: str | Path,
    taxonomy_path: str | Path | None = None,
) -> dict[str, str]:
    """Write all five summary TSV files to *result_dir*.

    Returns a dict mapping output key → written file path.
    """
    result_dir = Path(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)

    # 1. combined_summary.tsv
    combined = summarize_result_dir(result_dir, taxonomy_path)
    _write_tsv(
        result_dir / OUTPUT_FILES["combined_summary"],
        COMBINED_SUMMARY_FIELDNAMES,
        combined,
    )

    # 2. coverage_by_taxon.tsv
    coverage = build_coverage_by_taxon(result_dir, taxonomy_path)
    _write_tsv(
        result_dir / OUTPUT_FILES["coverage_by_taxon"],
        COVERAGE_FIELDNAMES,
        coverage,
    )

    # 3. length_distribution.tsv
    length_dist = build_length_distribution(result_dir)
    _write_tsv(
        result_dir / OUTPUT_FILES["length_distribution"],
        LENGTH_DIST_FIELDNAMES,
        length_dist,
    )

    # 4. mismatch_distribution.tsv
    mismatch_dist = build_mismatch_distribution(result_dir)
    _write_tsv(
        result_dir / OUTPUT_FILES["mismatch_distribution"],
        MISMATCH_DIST_FIELDNAMES,
        mismatch_dist,
    )

    # 5. species_resolution.tsv
    species_res = build_species_resolution(result_dir, taxonomy_path)
    _write_tsv(
        result_dir / OUTPUT_FILES["species_resolution"],
        SPECIES_RESOLUTION_FIELDNAMES,
        species_res,
    )

    return {
        key: str(result_dir / filename)
        for key, filename in OUTPUT_FILES.items()
    }


def combine_summaries(result_dir: str | Path) -> list[dict]:
    """Read combined_summary.tsv and return rows as list[dict]."""
    path = Path(result_dir) / OUTPUT_FILES["combined_summary"]
    if not path.is_file():
        return []
    return _read_amplicons_tsv(path)


# ── internal helpers ───────────────────────────────────────────────────


def _read_amplicons_tsv(path: str | Path) -> list[dict]:
    """Read TSV as list[dict], returning [] if file is missing."""
    path = Path(path)
    if not path.is_file():
        return []
    with open(path, "r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _write_tsv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _parse_mismatch_from_dirname(dirname: str) -> int | None:
    """Parse mismatch integer from 'mismatch_N' directory name."""
    if not dirname.startswith("mismatch_"):
        return None
    try:
        return int(dirname.split("_", 1)[1])
    except (ValueError, IndexError):
        return None


def _safe_species(rec: dict) -> str:
    sp = (rec.get("species") or "").strip()
    if sp:
        return sp
    return (rec.get("scientific_name") or "").strip()


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_str(value) -> str:
    if value is None:
        return ""
    return str(value)
