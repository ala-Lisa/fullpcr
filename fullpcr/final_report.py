"""Integrate obipcr summary, MFEprimer QC, and MFEprimer spec into a unified
primer evaluation report."""

from __future__ import annotations

import csv
from pathlib import Path

_NA = "NA"

PRIMER_RANK_FIELDNAMES = [
    "primer_id",
    "best_mismatch",
    "obipcr_amplicon_count",
    "obipcr_unique_species_count",
    "obipcr_species_resolution_rate",
    "mean_amplicon_length",
    "missing_taxonomy_count",
    "qc_status",
    "tm_difference",
    "dimer_count",
    "hairpin_count",
    "degen_status",
    "degen_variant_count",
    "spec_status",
    "spec_amplicon_count",
    "spec_unique_reference_count",
    "spec_unique_species_count",
    "spec_reference_fraction",
    "final_score",
    "final_status",
    "recommendation",
    "reason",
]

# ── helpers ────────────────────────────────────────────────────────────────


def _safe_float(value: str | float | int | None) -> float | str:
    """Convert *value* to float, returning ``"NA"`` on failure."""
    if value is None or (isinstance(value, str) and (not value or not value.strip())):
        return _NA
    try:
        return float(value)
    except (ValueError, TypeError):
        return _NA


def _safe_int(value: str | int | None) -> int | str:
    """Convert *value* to int, returning ``"NA"`` on failure."""
    if value is None or (isinstance(value, str) and (not value or not value.strip())):
        return _NA
    try:
        return int(value)
    except (ValueError, TypeError):
        return _NA


def _coerce_float(value, default: float = 0.0) -> float:
    """Return float(value) or *default* for ``"NA"`` / missing."""
    if value == _NA or value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_str(value) -> str:
    """Convert value to str, return ``"NA"`` on None / empty."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return _NA
    return str(value)


def _read_tsv(path: Path) -> list[dict]:
    """Read TSV as list[dict], returning [] if missing or unreadable."""
    if not path.is_file():
        return []
    with open(path, "r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _write_tsv(path: Path, fieldnames: list[str], rows: list[dict]) -> Path:
    """Write a list of dicts to a TSV file, return *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return path

# ── loaders ────────────────────────────────────────────────────────────────


def load_obipcr_summary(obipcr_dir: str | Path) -> list[dict]:
    """Read ``combined_summary.tsv`` from the obipcr results directory.

    Returns an empty list if the file is missing.
    """
    obipcr_dir = Path(obipcr_dir)
    return _read_tsv(obipcr_dir / "combined_summary.tsv")


def load_qc_summary(qc_dir: str | Path) -> list[dict]:
    """Read ``primer_qc_summary.tsv`` from the MFEprimer QC directory.

    Returns an empty list if the file is missing.
    """
    qc_dir = Path(qc_dir)
    return _read_tsv(qc_dir / "primer_qc_summary.tsv")


def load_spec_summary(spec_dir: str | Path) -> list[dict]:
    """Read ``spec/primer_spec.tsv`` from the MFEprimer spec directory.

    Returns an empty list if the file is missing.
    """
    spec_dir = Path(spec_dir)
    return _read_tsv(spec_dir / "spec" / "primer_spec.tsv")


def load_database_stats(spec_dir: str | Path) -> dict | None:
    """Read ``index/database_stats.tsv`` from the spec directory.

    Returns the first data row as a dict, or ``None`` if the file is missing.
    """
    spec_dir = Path(spec_dir)
    path = spec_dir / "index" / "database_stats.tsv"
    if not path.is_file():
        return None
    rows = _read_tsv(path)
    return rows[0] if rows else None


def load_degen_summary(qc_dir: str | Path) -> dict[str, dict]:
    """Read ``degen/degen_summary.tsv`` from the QC directory.

    Returns ``{primer_id: {degen_status, degen_variant_count}}``.
    Returns an empty dict if the file is missing.
    """
    qc_dir = Path(qc_dir)
    path = qc_dir / "degen" / "degen_summary.tsv"
    if not path.is_file():
        return {}
    result: dict[str, dict] = {}
    for row in _read_tsv(path):
        pid = row.get("primer_id", "")
        if pid:
            result[pid] = {
                "degen_status": row.get("degen_status", _NA),
                "degen_variant_count": row.get("degen_variant_count", _NA),
            }
    return result

# ── best-mismatch selection ────────────────────────────────────────────────


def select_best_mismatch(obipcr_rows: list[dict], primer_id: str) -> dict | None:
    """Select the mismatch level with the best coverage for *primer_id*.

    Primary sort: ``unique_species_count`` descending.
    Tie-break: ``species_level_unique_resolution_rate`` descending.

    Returns a shallow copy of the best row, or ``None`` if no data exists.
    """
    candidates = [r for r in obipcr_rows if r.get("primer_id") == primer_id]
    if not candidates:
        return None
    candidates.sort(
        key=lambda r: (
            _coerce_float(r.get("unique_species_count"), default=0.0),
            _coerce_float(r.get("species_level_unique_resolution_rate"), default=0.0),
        ),
        reverse=True,
    )
    return dict(candidates[0])

# ── scoring ────────────────────────────────────────────────────────────────


def compute_final_score(
    obipcr_row: dict | None,
    qc_row: dict | None,
    spec_row: dict | None,
    max_species: int = 0,
) -> float:
    """Compute a weighted composite score in [0.0, 1.0].

    Weights: obipcr coverage 40%, QC health 30%, spec 30%.
    """
    obipcr = _compute_obipcr_score(obipcr_row, max_species)
    qc = _compute_qc_score(qc_row)
    spec = _compute_spec_score(spec_row)
    return round(obipcr * 0.40 + qc * 0.30 + spec * 0.30, 4)


def _compute_obipcr_score(row: dict | None, max_species: int) -> float:
    """Score obipcr coverage (0-1)."""
    if row is None:
        return 0.0
    species_count = _coerce_float(row.get("unique_species_count"))
    resolution_rate = _coerce_float(row.get("species_level_unique_resolution_rate"))
    amplicon_count = _coerce_float(row.get("amplicon_count"))
    missing_tax = _coerce_float(row.get("missing_taxonomy_count"))

    # Normalize species count
    denominator = max(1, max_species)
    species_norm = min(1.0, species_count / denominator)

    # Penalty for missing taxonomy
    if amplicon_count > 0:
        missing_ratio = missing_tax / amplicon_count
    elif missing_tax > 0:
        missing_ratio = 1.0
    else:
        missing_ratio = 0.0
    penalty = min(0.5, missing_ratio * 0.5)

    # Low-count floor: fewer than 3 amplicons halves coverage score
    coverage = species_norm * 0.6 + resolution_rate * 0.4
    if amplicon_count < 3:
        coverage *= 0.5

    return max(0.0, coverage * (1.0 - penalty))


def _compute_qc_score(row: dict | None) -> float:
    """Score MFEprimer QC health (0-1)."""
    if row is None:
        return 0.5  # neutral when data missing
    score = 1.0
    qc_status = str(row.get("qc_status", ""))
    if "FAIL_DEGENERATE_EXPLOSION" in qc_status:
        score -= 0.5
    if "FAIL_PARSE" in qc_status:
        score -= 0.4
    if "WARN_DIMER" in qc_status:
        score -= 0.3
    if "WARN_HAIRPIN" in qc_status:
        score -= 0.15
    if "WARN_TM_DIFF" in qc_status:
        score -= 0.15
    return max(0.0, min(1.0, score))


def _compute_spec_score(row: dict | None) -> float:
    """Score MFEprimer specificity (0-1)."""
    if row is None:
        return 0.5  # neutral when data missing
    spec_status = str(row.get("status", ""))
    ref_fraction = _coerce_float(row.get("spec_reference_fraction"), default=0.0)

    if "WARN_NO_AMP" in spec_status or "FAIL_INDEX" in spec_status or "FAIL_SPEC" in spec_status:
        return 0.0

    if spec_status == "PASS":
        score = 1.0
    else:
        score = 0.6

    if "WARN_MULTI_AMP" in spec_status:
        score -= 0.15
    if "WARN_SIZE" in spec_status:
        score -= 0.1
    if "WARN_OVERAMP" in spec_status:
        score -= 0.15

    # Reference fraction bonus
    if ref_fraction > 0:
        score = max(score, ref_fraction * 0.8 + 0.2)

    return max(0.0, min(1.0, score))

# ── status ─────────────────────────────────────────────────────────────────


def determine_final_status(merged: dict) -> str:
    """Classify the primer into a final status tier.

    Returns one of:
      - ``"RECOMMENDED"``
      - ``"ACCEPTABLE_WITH_WARNINGS"``
      - ``"NOT_RECOMMENDED"``
      - ``"NEEDS_REVIEW"``
    """
    species_count = _coerce_float(merged.get("obipcr_unique_species_count"))
    qc_status = str(merged.get("qc_status", ""))
    spec_status = str(merged.get("spec_status", ""))
    score = _coerce_float(merged.get("final_score"))

    # NEEDS_REVIEW: all three key sources unavailable
    obipcr_missing = merged.get("obipcr_amplicon_count", _NA) == _NA
    qc_missing = merged.get("qc_status", _NA) == _NA
    spec_missing = merged.get("spec_status", _NA) == _NA
    if obipcr_missing and qc_missing and spec_missing:
        return "NEEDS_REVIEW"

    # NOT_RECOMMENDED: dealbreakers
    if "FAIL_DEGENERATE_EXPLOSION" in qc_status:
        return "NOT_RECOMMENDED"
    if species_count == 0 and ("WARN_NO_AMP" in spec_status or spec_missing):
        return "NOT_RECOMMENDED"
    if score < 0.25:
        return "NOT_RECOMMENDED"

    # ACCEPTABLE_WITH_WARNINGS
    if score < 0.70:
        return "ACCEPTABLE_WITH_WARNINGS"
    if "WARN_" in qc_status or "FAIL_" in qc_status:
        return "ACCEPTABLE_WITH_WARNINGS"
    if "WARN_" in spec_status:
        return "ACCEPTABLE_WITH_WARNINGS"

    return "RECOMMENDED"

# ── reason & recommendation text ───────────────────────────────────────────


def _build_reason(obipcr_row: dict | None, qc_row: dict | None,
                  spec_row: dict | None, degen_row: dict | None) -> str:
    """Build a semicolon-delimited reason string from key findings."""
    parts: list[str] = []

    # obipcr
    if obipcr_row is None:
        parts.append("no obipcr data")
    else:
        ac = _coerce_float(obipcr_row.get("amplicon_count"))
        if ac == 0:
            parts.append("obipcr produced 0 amplicons")

    # qc
    if qc_row is not None:
        qr = str(qc_row.get("qc_reason", ""))
        if qr and qr != _NA and qr.strip():
            parts.append(qr.strip())

    # spec
    if spec_row is not None:
        sr = str(spec_row.get("reason", ""))
        if sr and sr != _NA and sr.strip():
            parts.append(sr.strip())

    # degen
    if degen_row is not None:
        ds = degen_row.get("degen_status", _NA)
        if ds != _NA and ds != "PASS" and ds != "":
            parts.append(f"degen: {ds}")

    return "; ".join(parts) if parts else ""


def _build_recommendation(merged: dict) -> str:
    """Generate a human-readable recommendation sentence."""
    status = merged.get("final_status", "")
    species = _safe_int(merged.get("obipcr_unique_species_count", 0))
    rate = _coerce_float(merged.get("obipcr_species_resolution_rate"))
    qc_status = str(merged.get("qc_status", ""))
    spec_status = str(merged.get("spec_status", ""))
    primer_id = str(merged.get("primer_id", ""))

    final_score = merged.get("final_score", _NA)

    if status == "RECOMMENDED":
        return (
            f"Recommended — covers {species} species, "
            f"resolution rate {rate:.1%}, "
            f"clean QC ({qc_status}) and spec ({spec_status}) profiles."
        )
    if status == "ACCEPTABLE_WITH_WARNINGS":
        issues: list[str] = []
        if "WARN_TM_DIFF" in qc_status:
            tm_diff = merged.get("tm_difference", "")
            issues.append(f"Tm difference {tm_diff}")
        if "WARN_DIMER" in qc_status:
            issues.append("dimer detected")
        if "WARN_HAIRPIN" in qc_status:
            issues.append("hairpin detected")
        if spec_status != "PASS" and spec_status != _NA:
            issues.append(f"spec: {spec_status}")
        if species == 0:
            issues.append("low or no obipcr coverage")
        issue_text = ", ".join(issues) if issues else "minor warnings"
        return (
            f"Acceptable with warnings — {issue_text}. "
            f"Score: {final_score}. Verify with wet-lab PCR."
        )
    if status == "NOT_RECOMMENDED":
        if species == 0 and "WARN_NO_AMP" in spec_status:
            return (
                f"Not recommended — no amplification in either "
                f"in silico PCR or specificity analysis for {primer_id}."
            )
        if "FAIL_DEGENERATE_EXPLOSION" in qc_status:
            return f"Not recommended — degenerate primer explosion makes {primer_id} impractical."
        return f"Not recommended — low overall score ({final_score}). Re-evaluate primer design."
    if status == "NEEDS_REVIEW":
        return "Needs review — essential input data is missing or unparseable."
    return ""

# ── ranking ────────────────────────────────────────────────────────────────


def rank_primers(
    obipcr_summary: list[dict],
    qc_summary: list[dict],
    spec_summary: list[dict],
    degen_summary: dict[str, dict] | None = None,
) -> list[dict]:
    """Merge three data sources into a ranked primer list.

    Returns a list of dicts sorted by ``final_score`` descending.
    """
    if degen_summary is None:
        degen_summary = {}

    # Index by primer_id
    qc_index: dict[str, dict] = {r.get("primer_id", ""): r for r in qc_summary}
    spec_index: dict[str, dict] = {r.get("primer_id", ""): r for r in spec_summary}

    # Collect all primer_ids
    primer_ids: set[str] = set()
    for r in obipcr_summary:
        pid = r.get("primer_id", "")
        if pid:
            primer_ids.add(pid)
    primer_ids.update(qc_index.keys())
    primer_ids.update(spec_index.keys())

    # First pass: select best mismatch for each primer
    best_rows: dict[str, dict | None] = {}
    for pid in primer_ids:
        best_rows[pid] = select_best_mismatch(obipcr_summary, pid)

    # Compute max_species for normalization
    max_species = 0
    for pid in primer_ids:
        br = best_rows.get(pid)
        if br is not None:
            sc = _coerce_float(br.get("unique_species_count"))
            if sc > max_species:
                max_species = int(sc)

    # Second pass: build merged rows with scores
    merged_rows: list[dict] = []
    for pid in primer_ids:
        obipcr_row = best_rows.get(pid)
        qc_row = qc_index.get(pid)
        spec_row = spec_index.get(pid)
        degen_entry = degen_summary.get(pid)

        # Compute hairpin_count from qc
        if qc_row is not None:
            f_hp = _safe_int(qc_row.get("forward_hairpin_count"))
            r_hp = _safe_int(qc_row.get("reverse_hairpin_count"))
            if f_hp != _NA and r_hp != _NA:
                hairpin_count = f_hp + r_hp
            elif f_hp != _NA:
                hairpin_count = f_hp
            elif r_hp != _NA:
                hairpin_count = r_hp
            else:
                hairpin_count = _NA
        else:
            hairpin_count = _NA

        species_count = _safe_int(obipcr_row.get("unique_species_count") if obipcr_row else None)

        merged: dict = {
            "primer_id": pid,
            "best_mismatch": _safe_int(obipcr_row.get("mismatch")) if obipcr_row else _NA,
            "obipcr_amplicon_count": _safe_int(obipcr_row.get("amplicon_count") if obipcr_row else None),
            "obipcr_unique_species_count": species_count,
            "obipcr_species_resolution_rate": (
                _safe_float(obipcr_row.get("species_level_unique_resolution_rate"))
                if obipcr_row else _NA
            ),
            "mean_amplicon_length": (
                _safe_float(obipcr_row.get("mean_amplicon_length"))
                if obipcr_row else _NA
            ),
            "missing_taxonomy_count": (
                _safe_int(obipcr_row.get("missing_taxonomy_count"))
                if obipcr_row else _NA
            ),
            "qc_status": qc_row.get("qc_status", _NA) if qc_row else _NA,
            "tm_difference": _safe_float(qc_row.get("tm_difference")) if qc_row else _NA,
            "dimer_count": _safe_int(qc_row.get("dimer_count")) if qc_row else _NA,
            "hairpin_count": hairpin_count,
            "degen_status": degen_entry.get("degen_status", _NA) if degen_entry else _NA,
            "degen_variant_count": degen_entry.get("degen_variant_count", _NA) if degen_entry else _NA,
            "spec_status": spec_row.get("status", _NA) if spec_row else _NA,
            "spec_amplicon_count": (
                _safe_int(spec_row.get("spec_amplicon_count")) if spec_row else _NA
            ),
            "spec_unique_reference_count": (
                _safe_int(spec_row.get("unique_reference_count")) if spec_row else _NA
            ),
            "spec_unique_species_count": (
                _safe_int(spec_row.get("unique_species_count")) if spec_row else _NA
            ),
            "spec_reference_fraction": (
                _safe_float(spec_row.get("spec_reference_fraction")) if spec_row else _NA
            ),
        }

        merged["final_score"] = compute_final_score(obipcr_row, qc_row, spec_row, max_species)
        merged["final_status"] = determine_final_status(merged)
        merged["reason"] = _build_reason(
            obipcr_row, qc_row, spec_row,
            degen_entry,
        )
        merged["recommendation"] = _build_recommendation(merged)

        merged_rows.append(merged)

    # Sort by final_score descending, then species_count descending
    merged_rows.sort(
        key=lambda r: (
            _coerce_float(r.get("final_score")),
            _coerce_float(r.get("obipcr_unique_species_count")),
        ),
        reverse=True,
    )

    return merged_rows

# ── output writers ──────────────────────────────────────────────────────────


def write_primer_rank(records: list[dict], output_path: Path) -> Path:
    """Write ``primer_rank.tsv``."""
    return _write_tsv(output_path, PRIMER_RANK_FIELDNAMES, records)


def generate_final_report(
    records: list[dict],
    db_stats: dict | None,
    output_path: Path,
    obipcr_dir: str,
    qc_dir: str,
    spec_dir: str,
) -> Path:
    """Write ``final_report.md`` with all sections."""
    lines: list[str] = []

    # ── Overview ───────────────────────────────────────────────────────
    lines.append("# Primer Evaluation Final Report")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append(
        "This report integrates three independent analyses to evaluate primer panel performance:"
    )
    lines.append("")
    lines.append(
        "1. **In silico PCR (obipcr)** — batch amplification against a mitochondrial "
        "genome database, measuring species coverage, resolution, and length distribution."
    )
    lines.append(
        "2. **MFEprimer QC** — primer thermodynamics, dimer, hairpin, and degeneracy analysis."
    )
    lines.append(
        "3. **MFEprimer spec** — in silico specificity screening against the same database."
    )
    lines.append("")

    # ── Input Files ───────────────────────────────────────────────────
    lines.append("## Input Files")
    lines.append("")
    lines.append("| Source | Directory | Status |")
    lines.append("|--------|-----------|--------|")
    obipcr_ok = Path(obipcr_dir, "combined_summary.tsv").is_file()
    qc_ok = Path(qc_dir, "primer_qc_summary.tsv").is_file()
    spec_ok = Path(spec_dir, "spec", "primer_spec.tsv").is_file()
    lines.append(f"| obipcr results | `{obipcr_dir}` | {'✓ found' if obipcr_ok else '✗ missing'} |")
    lines.append(f"| MFEprimer QC | `{qc_dir}` | {'✓ found' if qc_ok else '✗ missing'} |")
    lines.append(f"| MFEprimer spec | `{spec_dir}` | {'✓ found' if spec_ok else '✗ missing'} |")
    lines.append("")

    # ── Database Integrity ────────────────────────────────────────────
    if db_stats is not None:
        lines.append("## Database Integrity")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Source database | `{db_stats.get('source_database', _NA)}` |")
        lines.append(f"| Record count | {db_stats.get('source_record_count', _NA)} |")
        lines.append(f"| Total bases | {db_stats.get('source_total_bases', _NA)} |")
        lines.append(f"| Prepared record count | {db_stats.get('prepared_record_count', _NA)} |")
        lines.append(f"| Prepared bases | {db_stats.get('prepared_total_bases', _NA)} |")
        lines.append(f"| Index status | {db_stats.get('status', _NA)} |")
        reason = db_stats.get("reason", "")
        if reason and reason.strip():
            lines.append(f"| Note | {reason.strip()} |")
        lines.append("")

    # ── Primer Ranking ────────────────────────────────────────────────
    lines.append("## Primer Ranking")
    lines.append("")
    _append_markdown_table(lines, records, [
        ("primer_id", "Primer"),
        ("best_mismatch", "Best Mismatch"),
        ("obipcr_unique_species_count", "obipcr Species"),
        ("obipcr_species_resolution_rate", "Resolution Rate"),
        ("qc_status", "QC Status"),
        ("spec_status", "Spec Status"),
        ("final_score", "Score"),
        ("final_status", "Final Status"),
    ])
    lines.append("")

    # ── obipcr Coverage Summary ───────────────────────────────────────
    lines.append("## obipcr Coverage Summary")
    lines.append("")
    lines.append(
        "In silico PCR results using OBITools4 obipcr. "
        "Best mismatch level selected per primer."
    )
    lines.append("")
    _append_markdown_table(lines, records, [
        ("primer_id", "Primer"),
        ("best_mismatch", "Mismatch"),
        ("obipcr_amplicon_count", "Amplicons"),
        ("obipcr_unique_species_count", "Species"),
        ("obipcr_species_resolution_rate", "Resolution Rate"),
        ("mean_amplicon_length", "Mean Length (bp)"),
        ("missing_taxonomy_count", "Missing Taxonomy"),
    ])
    lines.append("")

    # ── MFEprimer QC Summary ──────────────────────────────────────────
    lines.append("## MFEprimer QC Summary")
    lines.append("")
    lines.append("Primer thermodynamics, dimer, hairpin, and degeneracy results from MFEprimer.")
    lines.append("")
    _append_markdown_table(lines, records, [
        ("primer_id", "Primer"),
        ("qc_status", "QC Status"),
        ("tm_difference", "Tm Diff (°C)"),
        ("dimer_count", "Dimers"),
        ("hairpin_count", "Hairpins"),
        ("degen_status", "Degen Status"),
        ("degen_variant_count", "Degen Variants"),
    ])
    lines.append("")

    # ── MFEprimer Spec Summary ────────────────────────────────────────
    lines.append("## MFEprimer Spec Summary")
    lines.append("")
    lines.append(
        "In silico specificity screening using MFEprimer against the same "
        "reference database."
    )
    lines.append("")
    _append_markdown_table(lines, records, [
        ("primer_id", "Primer"),
        ("spec_status", "Spec Status"),
        ("spec_amplicon_count", "Amplicons"),
        ("spec_unique_reference_count", "References"),
        ("spec_unique_species_count", "Species"),
        ("spec_reference_fraction", "Reference Fraction"),
    ])
    lines.append("")

    # ── Recommended Primers ───────────────────────────────────────────
    recommended = [r for r in records if r.get("final_status") == "RECOMMENDED"]
    lines.append("## Recommended Primers")
    lines.append("")
    if recommended:
        for rec in recommended:
            lines.append(f"- **{rec.get('primer_id', '')}** — {rec.get('recommendation', '')}")
    else:
        lines.append("*No primers met the RECOMMENDED threshold.*")
    lines.append("")

    # ── Primers Not Recommended ───────────────────────────────────────
    not_rec = [r for r in records if r.get("final_status") == "NOT_RECOMMENDED"]
    lines.append("## Primers Not Recommended")
    lines.append("")
    if not_rec:
        for nr in not_rec:
            lines.append(f"- **{nr.get('primer_id', '')}** — {nr.get('recommendation', '')}")
    else:
        lines.append("*All primers passed minimum thresholds.*")
    lines.append("")

    # ── Known Limitations ─────────────────────────────────────────────
    lines.append("## Known Limitations")
    lines.append("")
    lines.append(
        "- **In silico PCR cannot replace wet-lab PCR.** Primer performance "
        "in biological samples may differ due to DNA quality, PCR inhibitors, "
        "and annealing conditions."
    )
    lines.append(
        "- **MFEprimer spec and obipcr use different algorithms.** "
        "MFEprimer uses a k-mer index and scoring model; obipcr uses a "
        "string-matching approach. Results may not be perfectly consistent."
    )
    lines.append(
        "- **Database completeness and taxonomy quality affect conclusions.** "
        "A limited or biased reference database will produce misleading "
        "coverage and specificity estimates."
    )
    lines.append(
        "- **Multi-species amplification is a design goal for metabarcoding primers.** "
        "Cross-species amplification should not be treated as non-specific "
        "binding; it is the intended behavior of universal primers."
    )
    lines.append(
        "- **Final primer selection requires wet-lab validation and "
        "sequencing.** In silico prediction reduces but does not eliminate "
        "the need for empirical testing."
    )
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _append_markdown_table(
    lines: list[str], records: list[dict], columns: list[tuple[str, str]],
) -> None:
    """Append a pipe-delimited markdown table to *lines*."""
    if not records:
        lines.append("*No data available.*")
        lines.append("")
        return
    headers = [col[1] for col in columns]
    keys = [col[0] for col in columns]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in records:
        cells = [str(row.get(k, "")) for k in keys]
        lines.append("| " + " | ".join(cells) + " |")

# ── orchestrator ──────────────────────────────────────────────────────────


def write_final_outputs(
    obipcr_dir: str | Path,
    qc_dir: str | Path,
    spec_dir: str | Path,
    outdir: str | Path,
) -> dict[str, Path]:
    """Load all inputs, rank primers, write all output files.

    Returns ``{"primer_rank": path, "final_report": path}``.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    obipcr_summary = load_obipcr_summary(obipcr_dir)
    qc_summary = load_qc_summary(qc_dir)
    spec_summary = load_spec_summary(spec_dir)
    db_stats = load_database_stats(spec_dir)
    degen_summary = load_degen_summary(qc_dir)

    records = rank_primers(obipcr_summary, qc_summary, spec_summary, degen_summary)

    rank_path = write_primer_rank(records, outdir / "primer_rank.tsv")
    report_path = generate_final_report(
        records, db_stats,
        outdir / "final_report.md",
        str(obipcr_dir), str(qc_dir), str(spec_dir),
    )

    return {"primer_rank": rank_path, "final_report": report_path}
