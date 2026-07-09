"""Tests for report module."""

import textwrap
from pathlib import Path

import pytest

from fullpcr.report import (
    generate_report,
    load_summary_tables,
    write_report,
)


# ── helpers ────────────────────────────────────────────────────────────


def _write_tsv(path: Path, header: str, *rows: str) -> None:
    content = header + "\n" + "\n".join(rows) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_full_result_dir(tmp_path: Path) -> str:
    """Create a result dir with all 5 summary TSVs and failed_jobs.tsv.

    Key test scenario: Homo sapiens appears in both COI_short mismatch=0
    and COI_short mismatch=1, so the row-level sum over-counts.
    global_unique_species_count must deduplicate.
    """
    d = tmp_path / "results"

    _write_tsv(
        d / "combined_summary.tsv",
        "primer_id\tmismatch\tamplicon_count\tunique_taxid_count\tunique_species_count\tunique_sequence_count\tmatched_taxonomy_count\tmissing_taxonomy_count\tmin_amplicon_length\tmax_amplicon_length\tmean_amplicon_length\tforward_error_mean\treverse_error_mean\tambiguous_sequence_count\tambiguous_species_count\tspecies_level_unique_resolution_rate",
        "COI_short\t0\t3\t3\t3\t3\t3\t0\t150\t200\t176.67\t0.3333\t0.3333\t0\t0\t1.0",
        "16S\t0\t2\t1\t1\t2\t1\t1\t160\t300\t230.0\t1.0\t0.5\t0\t0\t0.5",
        "COI_short\t1\t1\t1\t1\t1\t1\t0\t210\t210\t210.0\t0.0\t0.0\t0\t0\t1.0",
        "16S\t1\t0\t0\t0\t0\t0\t0\t0\t0\t0.0\t0.0\t0.0\t0\t0\t0.0",
    )

    _write_tsv(
        d / "coverage_by_taxon.tsv",
        "primer_id\tmismatch\trank\tname\tamplicon_count\tunique_taxid_count\tunique_species_count",
        "COI_short\t0\tkingdom\tAnimalia\t3\t3\t3",
        "COI_short\t0\tphylum\tChordata\t2\t2\t2",
        "COI_short\t0\tphylum\tArthropoda\t1\t1\t1",
        "COI_short\t0\tspecies\tHomo sapiens\t1\t1\t1",
        "COI_short\t0\tspecies\tBos taurus\t1\t1\t1",
        "COI_short\t0\tspecies\tMus musculus\t1\t1\t1",
        "COI_short\t1\tspecies\tHomo sapiens\t1\t1\t1",
        "16S\t0\tkingdom\tAnimalia\t1\t1\t1",
        "16S\t0\tspecies\tDanio rerio\t1\t1\t1",
    )

    _write_tsv(
        d / "length_distribution.tsv",
        "primer_id\tmismatch\tamplicon_length\tcount",
        "COI_short\t0\t150\t1",
        "COI_short\t0\t180\t1",
        "COI_short\t0\t200\t1",
        "16S\t0\t160\t1",
        "16S\t0\t300\t1",
        "COI_short\t1\t210\t1",
    )

    _write_tsv(
        d / "mismatch_distribution.tsv",
        "primer_id\tmismatch\tforward_error\treverse_error\tcount",
        "COI_short\t0\t0\t0\t1",
        "COI_short\t0\t0\t1\t1",
        "COI_short\t0\t1\t0\t1",
        "16S\t0\t0\t0\t1",
        "16S\t0\t2\t1\t1",
        "COI_short\t1\t0\t0\t1",
    )

    _write_tsv(
        d / "species_resolution.tsv",
        "primer_id\tmismatch\ttotal_records\tmatched_records\tunique_sequences\tunique_species\tresolved_sequence_count\tambiguous_sequence_count\tambiguous_species_count\tmissing_species_count\tmissing_sequence_count\tspecies_level_unique_resolution_rate",
        "COI_short\t0\t3\t3\t3\t3\t3\t0\t0\t0\t0\t1.0",
        "16S\t0\t2\t1\t2\t1\t2\t0\t0\t0\t0\t0.5",
        "COI_short\t1\t1\t1\t1\t1\t1\t0\t0\t0\t0\t1.0",
        "16S\t1\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0.0",
    )

    _write_tsv(
        d / "failed_jobs.tsv",
        "primer_id\tmismatch\terror",
        "12S_long\t2\tobipcr not found",
        "12S_long\t3\tobipcr not found",
    )

    return str(d)


# ── load_summary_tables ────────────────────────────────────────────────


class TestLoadSummaryTables:
    def test_loads_all_present_tables(self, tmp_path):
        d = _build_full_result_dir(tmp_path)
        tables = load_summary_tables(d)

        for name in [
            "combined_summary",
            "coverage_by_taxon",
            "length_distribution",
            "mismatch_distribution",
            "species_resolution",
            "failed_jobs",
        ]:
            assert name in tables

        assert isinstance(tables["combined_summary"], list)
        assert len(tables["combined_summary"]) == 4

    def test_missing_file_is_none(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        tables = load_summary_tables(str(empty_dir))

        for name in tables:
            assert tables[name] is None

    def test_empty_file_is_empty_list(self, tmp_path):
        d = tmp_path / "results"
        _write_tsv(d / "combined_summary.tsv", "primer_id\tmismatch\tamplicon_count")
        tables = load_summary_tables(str(d))
        assert tables["combined_summary"] == []

    def test_partial_files(self, tmp_path):
        d = tmp_path / "results"
        _write_tsv(
            d / "combined_summary.tsv",
            "primer_id\tmismatch\tamplicon_count\tunique_taxid_count\tunique_species_count\tunique_sequence_count\tmatched_taxonomy_count\tmissing_taxonomy_count\tmin_amplicon_length\tmax_amplicon_length\tmean_amplicon_length\tforward_error_mean\treverse_error_mean\tambiguous_sequence_count\tambiguous_species_count\tspecies_level_unique_resolution_rate",
            "COI\t0\t1\t1\t1\t1\t1\t0\t100\t100\t100.0\t0.0\t0.0\t0\t0\t1.0",
        )
        tables = load_summary_tables(str(d))
        assert tables["combined_summary"] is not None
        assert tables["coverage_by_taxon"] is None
        assert tables["failed_jobs"] is None


# ── generate_report ────────────────────────────────────────────────────


class TestGenerateReport:
    def test_starts_with_title(self, tmp_path):
        d = _build_full_result_dir(tmp_path)
        md = generate_report(d)
        assert md.startswith("# fullpcr in silico PCR Report")

    def test_contains_all_sections(self, tmp_path):
        d = _build_full_result_dir(tmp_path)
        md = generate_report(d)

        for section in [
            "## Run Summary",
            "## Primer Performance",
            "## Taxonomic Coverage",
            "## Length Distribution",
            "## Mismatch Distribution",
            "## Species Resolution",
            "## Failed Jobs",
            "## Known Limitations",
        ]:
            assert section in md, f"Missing section: {section}"

    def test_run_summary_metrics(self, tmp_path):
        d = _build_full_result_dir(tmp_path)
        md = generate_report(d)

        assert "Primer 数量 | 2" in md
        assert "Mismatch 条件数 | 2" in md
        assert "总 amplicon 数 | 6" in md
        assert "最佳 species resolution primer | COI_short" in md

    def test_global_unique_species_deduplicated(self, tmp_path):
        """Same species in two mismatch levels must be deduplicated."""
        d = _build_full_result_dir(tmp_path)
        md = generate_report(d)

        # Homo sapiens x2, Bos taurus, Mus musculus, Danio rerio = 4 unique
        assert "global_unique_species_count | 4" in md
        # Row sum: 3 + 1 + 1 + 0 = 5
        assert "sum_unique_species_observations | 5" in md

    def test_global_unique_taxid_always_unavailable(self, tmp_path):
        """global_unique_taxid_count 无法从现有 summary 文件可靠计算。"""
        d = _build_full_result_dir(tmp_path)
        md = generate_report(d)

        # 始终 unavailable，不等同于 global_unique_species_count
        assert "global_unique_taxid_count | unavailable" in md
        # 但 sum 仍可计算
        assert "sum_unique_taxid_observations | 5" in md
        # species 独立计算
        assert "global_unique_species_count | 4" in md

    def test_unavailable_when_no_coverage_data(self, tmp_path):
        """When coverage_by_taxon is missing, global counts are unavailable."""
        d = tmp_path / "results"
        _write_tsv(
            d / "combined_summary.tsv",
            "primer_id\tmismatch\tamplicon_count\tunique_taxid_count\tunique_species_count\tunique_sequence_count\tmatched_taxonomy_count\tmissing_taxonomy_count\tmin_amplicon_length\tmax_amplicon_length\tmean_amplicon_length\tforward_error_mean\treverse_error_mean\tambiguous_sequence_count\tambiguous_species_count\tspecies_level_unique_resolution_rate",
            "COI\t0\t1\t1\t1\t1\t1\t0\t100\t100\t100.0\t0.0\t0.0\t0\t0\t1.0",
        )
        _write_tsv(
            d / "length_distribution.tsv",
            "primer_id\tmismatch\tamplicon_length\tcount",
            "COI\t0\t100\t1",
        )
        _write_tsv(
            d / "mismatch_distribution.tsv",
            "primer_id\tmismatch\tforward_error\treverse_error\tcount",
            "COI\t0\t0\t0\t1",
        )
        _write_tsv(
            d / "species_resolution.tsv",
            "primer_id\tmismatch\ttotal_records\tmatched_records\tunique_sequences\tunique_species\tresolved_sequence_count\tambiguous_sequence_count\tambiguous_species_count\tmissing_species_count\tmissing_sequence_count\tspecies_level_unique_resolution_rate",
            "COI\t0\t1\t1\t1\t1\t1\t0\t0\t0\t0\t1.0",
        )

        md = generate_report(str(d))
        assert "global_unique_species_count | unavailable" in md
        assert "global_unique_taxid_count | unavailable" in md
        assert "sum_unique_species_observations | 1" in md
        assert "sum_unique_taxid_observations | 1" in md

    def test_species_resolution_metrics(self, tmp_path):
        d = _build_full_result_dir(tmp_path)
        md = generate_report(d)

        assert "unique_species" in md
        assert "resolved_sequence_count" in md
        assert "ambiguous_sequence_count" in md
        assert "ambiguous_species_count" in md

    def test_length_distribution_stats(self, tmp_path):
        d = _build_full_result_dir(tmp_path)
        md = generate_report(d)

        assert "COI_short" in md
        assert "16S" in md
        assert "min_length" in md
        assert "max_length" in md
        assert "mean_length" in md

    def test_mismatch_distribution_error_means(self, tmp_path):
        d = _build_full_result_dir(tmp_path)
        md = generate_report(d)

        assert "forward_error_mean" in md
        assert "reverse_error_mean" in md

    def test_taxonomic_coverage_by_rank(self, tmp_path):
        d = _build_full_result_dir(tmp_path)
        md = generate_report(d)

        assert "### Kingdom" in md
        assert "Animalia" in md

    def test_failed_jobs_present(self, tmp_path):
        d = _build_full_result_dir(tmp_path)
        md = generate_report(d)

        assert "12S_long" in md
        assert "obipcr not found" in md

    def test_failed_jobs_missing(self, tmp_path):
        """When failed_jobs.tsv doesn't exist, show no failed jobs recorded."""
        d = tmp_path / "results"
        _write_tsv(
            d / "combined_summary.tsv",
            "primer_id\tmismatch\tamplicon_count\tunique_taxid_count\tunique_species_count\tunique_sequence_count\tmatched_taxonomy_count\tmissing_taxonomy_count\tmin_amplicon_length\tmax_amplicon_length\tmean_amplicon_length\tforward_error_mean\treverse_error_mean\tambiguous_sequence_count\tambiguous_species_count\tspecies_level_unique_resolution_rate",
            "COI\t0\t1\t1\t1\t1\t1\t0\t100\t100\t100.0\t0.0\t0.0\t0\t0\t1.0",
        )
        _write_tsv(
            d / "coverage_by_taxon.tsv",
            "primer_id\tmismatch\trank\tname\tamplicon_count\tunique_taxid_count\tunique_species_count",
            "COI\t0\tkingdom\tAnimalia\t1\t1\t1",
        )
        _write_tsv(
            d / "length_distribution.tsv",
            "primer_id\tmismatch\tamplicon_length\tcount",
            "COI\t0\t100\t1",
        )
        _write_tsv(
            d / "mismatch_distribution.tsv",
            "primer_id\tmismatch\tforward_error\treverse_error\tcount",
            "COI\t0\t0\t0\t1",
        )
        _write_tsv(
            d / "species_resolution.tsv",
            "primer_id\tmismatch\ttotal_records\tmatched_records\tunique_sequences\tunique_species\tresolved_sequence_count\tambiguous_sequence_count\tambiguous_species_count\tmissing_species_count\tmissing_sequence_count\tspecies_level_unique_resolution_rate",
            "COI\t0\t1\t1\t1\t1\t1\t0\t0\t0\t0\t1.0",
        )

        md = generate_report(str(d))
        assert "No failed jobs recorded" in md

    def test_missing_all_files_graceful(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        md = generate_report(str(empty_dir))

        assert "## Known Limitations" in md
        # Some sections should mention missing/unavailable
        assert "missing" in md.lower() or "unavailable" in md.lower()

    def test_empty_tsv_files(self, tmp_path):
        """Empty TSV files (header only) should not crash."""
        d = tmp_path / "results"
        for fname in [
            "combined_summary.tsv",
            "coverage_by_taxon.tsv",
            "length_distribution.tsv",
            "mismatch_distribution.tsv",
            "species_resolution.tsv",
        ]:
            _write_tsv(d / fname, "header")
        _write_tsv(d / "failed_jobs.tsv", "header")

        md = generate_report(str(d))
        assert "## Known Limitations" in md

    def test_returns_markdown_string(self, tmp_path):
        d = _build_full_result_dir(tmp_path)
        md = generate_report(d)
        assert isinstance(md, str)
        assert len(md) > 0

    def test_writes_to_output_path(self, tmp_path):
        d = _build_full_result_dir(tmp_path)
        out = tmp_path / "report.md"
        md = generate_report(d, output_path=str(out))
        assert out.is_file()
        assert out.read_text(encoding="utf-8") == md


# ── write_report ───────────────────────────────────────────────────────


class TestWriteReport:
    def test_writes_markdown_to_file(self, tmp_path):
        md = "# Test Report\n\nHello world.\n"
        out = tmp_path / "report.md"
        write_report(md, str(out))

        assert out.is_file()
        assert out.read_text(encoding="utf-8") == md

    def test_creates_parent_directories(self, tmp_path):
        out = tmp_path / "deep" / "nested" / "report.md"
        write_report("# Test\n", str(out))
        assert out.is_file()

    def test_overwrites_existing_file(self, tmp_path):
        out = tmp_path / "report.md"
        out.write_text("old content", encoding="utf-8")

        write_report("# New\n", str(out))
        assert out.read_text(encoding="utf-8") == "# New\n"
