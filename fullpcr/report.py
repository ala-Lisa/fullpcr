"""Generate a Markdown report from summarise output TSV files."""

from __future__ import annotations

import csv
from pathlib import Path

# ── constants ──────────────────────────────────────────────────────────

KNOWN_LIMITATIONS = [
    "in silico PCR 只能预测引物与数据库序列的理论匹配，不能完全模拟真实 PCR 效率。",
    "数据库缺失会影响覆盖率和物种分辨率判断。",
    "taxonomy 缺失会导致 missing_taxonomy_count 增加。",
    "真实 eDNA 实验仍需 PCR、建库和测序验证。",
]


# ── table loading ──────────────────────────────────────────────────────


def load_summary_tables(result_dir: str | Path) -> dict[str, list[dict] | None]:
    """Read all summary TSV files from *result_dir*.

    Returns a dict mapping table name → list of rows.
    Missing files → None. Empty files → [].
    """
    result_dir = Path(result_dir)

    files = {
        "combined_summary": "combined_summary.tsv",
        "coverage_by_taxon": "coverage_by_taxon.tsv",
        "length_distribution": "length_distribution.tsv",
        "mismatch_distribution": "mismatch_distribution.tsv",
        "species_resolution": "species_resolution.tsv",
        "failed_jobs": "failed_jobs.tsv",
    }

    tables: dict[str, list[dict] | None] = {}
    for name, filename in files.items():
        path = result_dir / filename
        if not path.is_file():
            tables[name] = None
        else:
            tables[name] = _read_tsv(path)

    return tables


# ── report generation ──────────────────────────────────────────────────


def generate_report(
    result_dir: str | Path, output_path: str | Path | None = None
) -> str:
    """Generate a complete Markdown report.

    If *output_path* is given, writes the report there as well.
    Returns the Markdown string.
    """
    tables = load_summary_tables(result_dir)

    parts: list[str] = []
    parts.append("# fullpcr in silico PCR Report\n")

    parts.append(_build_run_summary(tables))
    parts.append(_build_primer_performance(tables))
    parts.append(_build_taxonomic_coverage(tables))
    parts.append(_build_length_distribution(tables))
    parts.append(_build_mismatch_distribution(tables))
    parts.append(_build_species_resolution(tables))
    parts.append(_build_failed_jobs(tables))
    parts.append(_build_known_limitations())

    markdown = "\n\n".join(parts) + "\n"

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")

    return markdown


def write_report(markdown: str, output_path: str | Path) -> None:
    """Write a Markdown string to *output_path*."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")


# ── section builders ───────────────────────────────────────────────────


def _build_run_summary(tables: dict) -> str:
    lines = ["## Run Summary"]

    cs = tables.get("combined_summary")
    if cs is None:
        lines.append("\n*combined_summary.tsv missing — run summary unavailable.*")
        return "\n".join(lines)

    if not cs:
        lines.append("\n*combined_summary.tsv is empty.*")
        return "\n".join(lines)

    primer_ids = {r.get("primer_id", "") for r in cs}
    mismatches = {r.get("mismatch", "") for r in cs}
    total_amp = sum(_safe_int(r.get("amplicon_count")) for r in cs)

    # Row-level sums (observation counts — may double-count across
    # mismatch levels / primer pairs).
    sum_taxid_obs = sum(_safe_int(r.get("unique_taxid_count")) for r in cs)
    sum_species_obs = sum(_safe_int(r.get("unique_species_count")) for r in cs)

    # Global deduplicated counts computed from coverage_by_taxon.tsv
    # (rank == "species" → unique names).
    global_species = _compute_global_unique_species(tables)
    global_taxids = _compute_global_unique_taxids()

    best_res = _best_resolution(cs)
    best_cov = _best_coverage(cs)

    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Primer 数量 | {len(primer_ids)} |")
    lines.append(f"| Mismatch 条件数 | {len(mismatches)} |")
    lines.append(f"| 总 amplicon 数 | {total_amp} |")
    lines.append(f"| global_unique_taxid_count | {_fmt(global_taxids)} |")
    lines.append(f"| sum_unique_taxid_observations | {sum_taxid_obs} |")
    lines.append(f"| global_unique_species_count | {_fmt(global_species)} |")
    lines.append(f"| sum_unique_species_observations | {sum_species_obs} |")
    lines.append(f"| 最佳 species resolution primer | {best_res} |")
    lines.append(f"| 最高 coverage primer | {best_cov} |")

    return "\n".join(lines)


def _build_primer_performance(tables: dict) -> str:
    lines = ["## Primer Performance"]

    cs = tables.get("combined_summary")
    if cs is None:
        lines.append("\n*combined_summary.tsv missing.*")
        return "\n".join(lines)

    if not cs:
        lines.append("\n*No data available.*")
        return "\n".join(lines)

    fields = [
        "primer_id",
        "mismatch",
        "amplicon_count",
        "unique_taxid_count",
        "unique_species_count",
        "unique_sequence_count",
        "matched_taxonomy_count",
        "missing_taxonomy_count",
        "species_level_unique_resolution_rate",
    ]

    lines.append("")
    lines.append("| " + " | ".join(fields) + " |")
    lines.append("|" + "|".join("---" for _ in fields) + "|")

    for row in cs:
        vals = [str(row.get(f, "")) for f in fields]
        lines.append("| " + " | ".join(vals) + " |")

    return "\n".join(lines)


def _build_taxonomic_coverage(tables: dict) -> str:
    lines = ["## Taxonomic Coverage"]

    ct = tables.get("coverage_by_taxon")
    if ct is None:
        lines.append("\n*coverage_by_taxon.tsv missing.*")
        return "\n".join(lines)

    if not ct:
        lines.append("\n*No coverage data available.*")
        return "\n".join(lines)

    ranks = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]
    shown_ranks = [r for r in ranks if any(
        row.get("rank") == r for row in ct
    )]

    for rank in shown_ranks:
        rank_rows = [r for r in ct if r.get("rank") == rank]
        rank_rows.sort(key=lambda r: -_safe_int(r.get("amplicon_count")))
        top10 = rank_rows[:10]

        lines.append(f"\n### {rank.capitalize()}")
        lines.append("")
        lines.append(
            "| name | amplicon_count | unique_taxid_count | unique_species_count |"
        )
        lines.append(
            "|------|----------------|--------------------|----------------------|"
        )

        for row in top10:
            lines.append(
                f"| {row.get('name', '')} "
                f"| {row.get('amplicon_count', '')} "
                f"| {row.get('unique_taxid_count', '')} "
                f"| {row.get('unique_species_count', '')} |"
            )

    return "\n".join(lines)


def _build_length_distribution(tables: dict) -> str:
    lines = ["## Length Distribution"]

    ld = tables.get("length_distribution")
    if ld is None:
        lines.append("\n*length_distribution.tsv missing.*")
        return "\n".join(lines)

    if not ld:
        lines.append("\n*No length data available.*")
        return "\n".join(lines)

    # Per-primer stats
    primer_lengths: dict[str, list[int]] = {}
    for row in ld:
        pid = row.get("primer_id", "")
        length = _safe_int(row.get("amplicon_length"))
        count = _safe_int(row.get("count"))
        if pid not in primer_lengths:
            primer_lengths[pid] = []
        primer_lengths[pid].extend([length] * count)

    lines.append("")
    lines.append("| primer_id | min_length | max_length | mean_length |")
    lines.append("|-----------|------------|------------|-------------|")

    for pid in sorted(primer_lengths):
        vals = primer_lengths[pid]
        mn = min(vals)
        mx = max(vals)
        avg = round(sum(vals) / len(vals), 1) if vals else 0
        note = " ⚠️" if mx > 1000 else ""
        lines.append(f"| {pid} | {mn} | {mx}{note} | {avg} |")

    all_lengths = [l for v in primer_lengths.values() for l in v]
    if all_lengths and max(all_lengths) > 1000:
        lines.append(
            "\n⚠️ 存在片段长度 > 1000 bp 的 amplicon，"
            "可能影响某些 PCR 方案的扩增效率。"
        )

    return "\n".join(lines)


def _build_mismatch_distribution(tables: dict) -> str:
    lines = ["## Mismatch Distribution"]

    md = tables.get("mismatch_distribution")
    cs = tables.get("combined_summary")

    if md is None:
        lines.append("\n*mismatch_distribution.tsv missing.*")
        return "\n".join(lines)

    if not md:
        lines.append("\n*No mismatch data available.*")
        return "\n".join(lines)

    if cs:
        lines.append("")
        lines.append(
            "| primer_id | mismatch | forward_error_mean | reverse_error_mean |"
        )
        lines.append(
            "|-----------|----------|--------------------|--------------------|"
        )

        for row in sorted(
            cs, key=lambda r: (r.get("primer_id", ""), _safe_int(r.get("mismatch")))
        ):
            lines.append(
                f"| {row.get('primer_id', '')} "
                f"| {row.get('mismatch', '')} "
                f"| {row.get('forward_error_mean', '')} "
                f"| {row.get('reverse_error_mean', '')} |"
            )

        # Check if higher mismatch → more amplicons
        if len({r.get("mismatch") for r in cs}) > 1:
            lines.append("")
            primer_amp: dict[str, dict] = {}
            for row in cs:
                pid = row.get("primer_id", "")
                mm = _safe_int(row.get("mismatch"))
                count = _safe_int(row.get("amplicon_count"))
                if pid not in primer_amp:
                    primer_amp[pid] = {}
                primer_amp[pid][mm] = count

            for pid in sorted(primer_amp):
                mm_counts = primer_amp[pid]
                if len(mm_counts) >= 2:
                    base = mm_counts.get(min(mm_counts.keys()), 1)
                    high = mm_counts.get(max(mm_counts.keys()), 0)
                    if base > 0 and high > base:
                        lines.append(
                            f"⚠️ {pid}: mismatch {max(mm_counts.keys())} 条件下 "
                            f"amplicon 数（{high}）明显多于 "
                            f"mismatch {min(mm_counts.keys())}（{base}），"
                            f"非特异性扩增可能较高。"
                        )

    return "\n".join(lines)


def _build_species_resolution(tables: dict) -> str:
    lines = ["## Species Resolution"]

    sr = tables.get("species_resolution")
    if sr is None:
        lines.append("\n*species_resolution.tsv missing.*")
        return "\n".join(lines)

    if not sr:
        lines.append("\n*No resolution data available.*")
        return "\n".join(lines)

    fields = [
        "primer_id",
        "mismatch",
        "unique_species",
        "resolved_sequence_count",
        "ambiguous_sequence_count",
        "ambiguous_species_count",
        "species_level_unique_resolution_rate",
    ]

    lines.append("")
    lines.append("| " + " | ".join(fields) + " |")
    lines.append("|" + "|".join("---" for _ in fields) + "|")

    for row in sr:
        vals: list[str] = []
        for f in fields:
            v = row.get(f, "")
            if f == "species_level_unique_resolution_rate":
                vals.append(f"{_safe_float(v):.4f}")
            else:
                vals.append(str(v))
        lines.append("| " + " | ".join(vals) + " |")

    return "\n".join(lines)


def _build_failed_jobs(tables: dict) -> str:
    lines = ["## Failed Jobs"]

    fj = tables.get("failed_jobs")
    if fj is None:
        lines.append("\n*No failed jobs recorded.*")
        return "\n".join(lines)

    if not fj:
        lines.append("\n*No failed jobs recorded.*")
        return "\n".join(lines)

    lines.append("")
    headers = list(fj[0].keys()) if fj else []
    if headers:
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join("---" for _ in headers) + "|")

        for row in fj:
            vals = [str(row.get(h, "")) for h in headers]
            lines.append("| " + " | ".join(vals) + " |")

    return "\n".join(lines)


def _build_known_limitations() -> str:
    lines = ["## Known Limitations"]
    lines.append("")
    for lim in KNOWN_LIMITATIONS:
        lines.append(f"- {lim}")
    return "\n".join(lines)


# ── helpers ────────────────────────────────────────────────────────────


def _compute_global_unique_species(tables: dict) -> int | None:
    """Compute deduplicated unique species count from coverage_by_taxon.

    Collects all unique ``name`` values at ``rank == "species"``,
    excluding ``"(unclassified)"`` entries.

    Returns:
        Count of unique species, or ``None`` if coverage_by_taxon is
        unavailable and the count cannot be computed reliably.
    """
    ct = tables.get("coverage_by_taxon")
    if ct is None:
        return None

    species_names: set[str] = set()
    for row in ct:
        if row.get("rank") == "species":
            name = (row.get("name") or "").strip()
            if name and name != "(unclassified)":
                species_names.add(name)

    # Return None when there are no species rows (cannot distinguish
    # "no data" from "genuinely zero species").
    return len(species_names) if species_names else (0 if _has_species_rank_rows(ct) else None)


def _compute_global_unique_taxids() -> int | None:
    """Compute deduplicated unique taxid count.

    The current summary files (combined_summary.tsv, coverage_by_taxon.tsv,
    species_resolution.tsv) do not contain per-record taxid information
    suitable for deduplication across primer × mismatch combinations.
    ``global_unique_taxid_count`` is therefore marked **unavailable** until
    a future version of the pipeline exports data that makes reliable
    deduplication possible.
    """
    return None


def _has_species_rank_rows(coverage: list[dict]) -> bool:
    """Return True if any row has rank == species."""
    return any(r.get("rank") == "species" for r in coverage)


def _fmt(value) -> str:
    """Format a metric value, showing 'unavailable' for None."""
    if value is None:
        return "unavailable"
    return str(value)


def _best_resolution(combined: list[dict]) -> str:
    best = ""
    best_rate = -1.0
    for row in combined:
        rate = _safe_float(row.get("species_level_unique_resolution_rate"))
        if rate > best_rate:
            best_rate = rate
            best = row.get("primer_id", "")
    return best if best else "N/A"


def _best_coverage(combined: list[dict]) -> str:
    best = ""
    best_count = -1
    for row in combined:
        count = _safe_int(row.get("unique_species_count"))
        if count > best_count:
            best_count = count
            best = row.get("primer_id", "")
    return best if best else "N/A"


def _read_tsv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, "r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


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
