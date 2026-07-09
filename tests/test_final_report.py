"""Tests for fullpcr.final_report — primer evaluation integration."""

import csv
import sys
from pathlib import Path
from unittest import mock

from fullpcr.final_report import (
    PRIMER_RANK_FIELDNAMES,
    compute_final_score,
    determine_final_status,
    generate_final_report,
    load_database_stats,
    load_degen_summary,
    load_obipcr_summary,
    load_qc_summary,
    load_spec_summary,
    rank_primers,
    select_best_mismatch,
    write_final_outputs,
    write_primer_rank,
)

# ── helpers ────────────────────────────────────────────────────────────────


def _read_tsv(path: Path) -> list[dict]:
    with open(path, "r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _write_tsv_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


_MOCK_COMBINED = """\
primer_id	mismatch	amplicon_count	unique_taxid_count	unique_species_count	unique_sequence_count	matched_taxonomy_count	missing_taxonomy_count	min_amplicon_length	max_amplicon_length	mean_amplicon_length	forward_error_mean	reverse_error_mean	ambiguous_sequence_count	ambiguous_species_count	species_level_unique_resolution_rate
12S_long	0	55	33	33	42	55	0	388	405	395.05	0.0	0.0	1	3	0.909091
12S_long	1	81	57	57	67	81	0	388	405	394.98	0.0247	0.3086	2	5	0.912281
12S_long	2	83	59	59	69	83	0	388	405	394.87	0.0241	0.3494	2	5	0.915254
16S_short	0	0	0	0	0	0	0	0	0	0	0.0	0.0	0	0	0.0
16S_short	1	0	0	0	0	0	0	0	0	0	0.0	0.0	0	0	0.0
16S_short	2	2	1	1	2	2	0	201	201	201.0	0.0	0.0	0	0	1.0
COI_full	0	0	0	0	0	0	0	0	0	0	0.0	0.0	0	0	0.0
COI_full	1	0	0	0	0	0	0	0	0	0	0.0	0.0	0	0	0.0
COI_full	2	0	0	0	0	0	0	0	0	0	0.0	0.0	0	0	0.0
COI_short	0	0	0	0	0	0	0	0	0	0	0.0	0.0	0	0	0.0
COI_short	1	0	0	0	0	0	0	0	0	0	0.0	0.0	0	0	0.0
COI_short	2	0	0	0	0	0	0	0	0	0	0.0	0.0	0	0	0.0
"""

_MOCK_QC = """\
primer_id	forward_tm	reverse_tm	tm_difference	forward_gc	reverse_gc	forward_delta_g	reverse_delta_g	dimer_count	dimer_max_score	dimer_min_delta_g	has_3prime_dimer	forward_hairpin_count	reverse_hairpin_count	forward_hairpin_max_score	reverse_hairpin_max_score	qc_status	qc_reason
12S_long	59.39	67.48	8.09	40.0	70.0	-23.57	-25.56	0	NA	NA	NA	0	0	NA	NA	WARN_TM_DIFF	Tm difference 8.09C > 5C
16S_short	60.17	59.56	0.61	57.14	50.0	-22.6	-22.55	0	NA	NA	NA	0	0	NA	NA	PASS
COI_full	55.28	60.17	4.89	32.0	34.62	-21.67	-24.7	0	NA	NA	NA	0	0	NA	NA	PASS
COI_short	55.28	60.17	4.89	32.0	34.62	-21.67	-24.7	0	NA	NA	NA	0	0	NA	NA	PASS
"""

_MOCK_SPEC = """\
primer_id	spec_amplicon_count	unique_reference_count	unique_taxid_count	unique_species_count	min_amplicon_size	max_amplicon_size	mean_amplicon_size	multi_amplicon_reference_count	max_amplicons_per_reference	fp_tm_min	fp_tm_max	rp_tm_min	rp_tm_max	size_outlier_count	database_reference_count	spec_reference_fraction	status	reason
12S_long	85	85	60	61	433	450	439.7	0	1	55.22	60.11	56.0	68.03	0	85	1.0	PASS
16S_short	85	85	60	61	224	244	233.6	0	1	56.0	65.69	60.21	64.84	0	85	1.0	PASS
COI_full	0	0	0	0	NA	NA	NA	0	0	NA	NA	NA	NA	0	85	0.0	WARN_NO_AMP	spec did not produce any amplicon
COI_short	0	0	0	0	NA	NA	NA	0	0	NA	NA	NA	NA	0	85	0.0	WARN_NO_AMP	spec did not produce any amplicon
"""

_MOCK_DB_STATS = """\
source_database	prepared_database	source_record_count	prepared_record_count	source_total_bases	prepared_total_bases	index_files_present	status	reason
/mock/db.fasta	/mock/prep.fasta	85	85	1438833	1428733	True	WARN_SEQUENCE_CLEANED	delta=10100
"""


def _make_obipcr_dir(tmp_path: Path) -> Path:
    d = tmp_path / "obipcr"
    _write_tsv_file(d / "combined_summary.tsv", _MOCK_COMBINED)
    return d


def _make_qc_dir(tmp_path: Path) -> Path:
    d = tmp_path / "qc"
    _write_tsv_file(d / "primer_qc_summary.tsv", _MOCK_QC)
    return d


def _make_spec_dir(tmp_path: Path) -> Path:
    d = tmp_path / "spec"
    _write_tsv_file(d / "spec" / "primer_spec.tsv", _MOCK_SPEC)
    _write_tsv_file(d / "index" / "database_stats.tsv", _MOCK_DB_STATS)
    return d

# ── loader tests ───────────────────────────────────────────────────────────


class TestLoadObipcrSummary:
    def test_reads_combined_summary_tsv(self, tmp_path):
        d = _make_obipcr_dir(tmp_path)
        rows = load_obipcr_summary(d)
        assert len(rows) == 12
        assert rows[0]["primer_id"] == "12S_long"

    def test_missing_file_returns_empty_list(self, tmp_path):
        rows = load_obipcr_summary(tmp_path / "nonexistent")
        assert rows == []


class TestLoadQcSummary:
    def test_reads_primer_qc_summary_tsv(self, tmp_path):
        d = _make_qc_dir(tmp_path)
        rows = load_qc_summary(d)
        assert len(rows) == 4
        assert rows[0]["primer_id"] == "12S_long"

    def test_missing_file_returns_empty_list(self, tmp_path):
        rows = load_qc_summary(tmp_path / "nonexistent")
        assert rows == []


class TestLoadSpecSummary:
    def test_reads_primer_spec_tsv(self, tmp_path):
        d = _make_spec_dir(tmp_path)
        rows = load_spec_summary(d)
        assert len(rows) == 4
        assert rows[0]["primer_id"] == "12S_long"

    def test_missing_file_returns_empty_list(self, tmp_path):
        rows = load_spec_summary(tmp_path / "nonexistent")
        assert rows == []


class TestLoadDatabaseStats:
    def test_reads_database_stats(self, tmp_path):
        d = _make_spec_dir(tmp_path)
        stats = load_database_stats(d)
        assert stats is not None
        assert stats["source_record_count"] == "85"

    def test_missing_file_returns_none(self, tmp_path):
        stats = load_database_stats(tmp_path / "nonexistent")
        assert stats is None


class TestLoadDegenSummary:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        result = load_degen_summary(tmp_path / "nonexistent")
        assert result == {}

    def test_reads_degen_summary(self, tmp_path):
        d = tmp_path / "qc"
        _write_tsv_file(d / "degen" / "degen_summary.tsv",
                        "primer_id\tdegen_status\tdegen_variant_count\n"
                        "12S_long\tPASS\t1\n"
                        "16S_short\tWARN_DEGEN\t4\n")
        result = load_degen_summary(d)
        assert result["12S_long"]["degen_status"] == "PASS"
        assert result["12S_long"]["degen_variant_count"] == "1"
        assert result["16S_short"]["degen_status"] == "WARN_DEGEN"

# ── best-mismatch tests ────────────────────────────────────────────────────


class TestSelectBestMismatch:
    def test_chooses_highest_unique_species(self, tmp_path):
        d = _make_obipcr_dir(tmp_path)
        rows = load_obipcr_summary(d)
        best = select_best_mismatch(rows, "12S_long")
        assert best is not None
        assert best["mismatch"] == "2"

    def test_returns_none_for_unknown_primer(self, tmp_path):
        d = _make_obipcr_dir(tmp_path)
        rows = load_obipcr_summary(d)
        best = select_best_mismatch(rows, "NONEXISTENT")
        assert best is None

# ── scoring tests ──────────────────────────────────────────────────────────


class TestComputeFinalScore:
    def test_high_coverage_clean_qc_spec_scores_high(self):
        obipcr = {"unique_species_count": "59", "species_level_unique_resolution_rate": "0.9153",
                  "amplicon_count": "83", "missing_taxonomy_count": "0"}
        qc = {"qc_status": "PASS"}
        spec = {"status": "PASS", "spec_reference_fraction": "1.0"}
        score = compute_final_score(obipcr, qc, spec, max_species=59)
        assert 0.85 <= score <= 1.0

    def test_no_coverage_no_amp_scores_low(self):
        obipcr = {"unique_species_count": "0", "species_level_unique_resolution_rate": "0.0",
                  "amplicon_count": "0", "missing_taxonomy_count": "0"}
        qc = {"qc_status": "PASS"}
        spec = {"status": "WARN_NO_AMP", "spec_reference_fraction": "0.0"}
        score = compute_final_score(obipcr, qc, spec, max_species=59)
        assert score < 0.35

    def test_tm_diff_penalty_reduces_score(self):
        obipcr = {"unique_species_count": "59", "species_level_unique_resolution_rate": "0.9153",
                  "amplicon_count": "83", "missing_taxonomy_count": "0"}
        qc_clean = {"qc_status": "PASS"}
        qc_warn = {"qc_status": "WARN_TM_DIFF", "qc_reason": "Tm diff > 5C"}
        spec = {"status": "PASS", "spec_reference_fraction": "1.0"}
        score_clean = compute_final_score(obipcr, qc_clean, spec, max_species=59)
        score_warn = compute_final_score(obipcr, qc_warn, spec, max_species=59)
        assert score_warn < score_clean

    def test_missing_data_uses_neutral_defaults(self):
        score = compute_final_score(None, None, None, max_species=0)
        assert 0.25 <= score <= 0.35


class TestDetermineFinalStatus:
    def test_recommended_high_score_no_issues(self):
        merged = {
            "obipcr_unique_species_count": 59,
            "obipcr_amplicon_count": 83,
            "qc_status": "PASS",
            "spec_status": "PASS",
            "final_score": 0.94,
        }
        assert determine_final_status(merged) == "RECOMMENDED"

    def test_acceptable_with_tm_warning(self):
        merged = {
            "obipcr_unique_species_count": 59,
            "obipcr_amplicon_count": 83,
            "qc_status": "WARN_TM_DIFF",
            "spec_status": "PASS",
            "final_score": 0.85,
        }
        assert determine_final_status(merged) == "ACCEPTABLE_WITH_WARNINGS"

    def test_not_recommended_no_amplification(self):
        merged = {
            "obipcr_unique_species_count": 0,
            "obipcr_amplicon_count": 0,
            "qc_status": "PASS",
            "spec_status": "WARN_NO_AMP",
            "final_score": 0.30,
        }
        assert determine_final_status(merged) == "NOT_RECOMMENDED"

    def test_needs_review_all_missing(self):
        merged = {
            "obipcr_unique_species_count": "NA",
            "obipcr_amplicon_count": "NA",
            "qc_status": "NA",
            "spec_status": "NA",
            "final_score": 0.0,
        }
        assert determine_final_status(merged) == "NEEDS_REVIEW"

    def test_not_recommended_low_score(self):
        merged = {
            "obipcr_unique_species_count": 1,
            "obipcr_amplicon_count": 2,
            "qc_status": "PASS",
            "spec_status": "PASS",
            "final_score": 0.20,
        }
        assert determine_final_status(merged) == "NOT_RECOMMENDED"

    def test_not_recommended_degen_explosion(self):
        merged = {
            "obipcr_unique_species_count": 10,
            "obipcr_amplicon_count": 20,
            "qc_status": "FAIL_DEGENERATE_EXPLOSION",
            "spec_status": "PASS",
            "final_score": 0.50,
        }
        assert determine_final_status(merged) == "NOT_RECOMMENDED"

# ── ranking tests ──────────────────────────────────────────────────────────


class TestRankPrimers:
    def test_integrates_all_sources(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        assert len(records) == 4
        primer_ids = {r["primer_id"] for r in records}
        assert primer_ids == {"12S_long", "16S_short", "COI_full", "COI_short"}

    def test_sorted_by_score_descending(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        scores = [float(r["final_score"]) for r in records]
        assert scores == sorted(scores, reverse=True)

    def test_rank_includes_all_required_fields(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        for r in records:
            for field in PRIMER_RANK_FIELDNAMES:
                assert field in r, f"Missing field: {field}"

    def test_handles_empty_inputs(self):
        records = rank_primers([], [], [])
        assert records == []

    def test_handles_missing_qc_and_spec(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        records = rank_primers(obipcr, [], [])
        assert len(records) == 4
        for r in records:
            assert r["qc_status"] == "NA"
            assert r["spec_status"] == "NA"

# ── output writer tests ────────────────────────────────────────────────────


class TestWritePrimerRank:
    def test_writes_tsv_with_correct_columns(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        out = tmp_path / "primer_rank.tsv"
        write_primer_rank(records, out)
        assert out.is_file()
        rows = _read_tsv(out)
        assert len(rows) == 4
        for col in PRIMER_RANK_FIELDNAMES:
            assert col in rows[0]

    def test_scores_are_between_zero_and_one(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        out = tmp_path / "primer_rank.tsv"
        write_primer_rank(records, out)
        rows = _read_tsv(out)
        for r in rows:
            score = float(r["final_score"])
            assert 0.0 <= score <= 1.0


class TestGenerateFinalReport:
    def test_generates_markdown_with_all_sections(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        out = tmp_path / "final_report.md"
        generate_final_report(
            records, None, out,
            "/fake/obipcr", "/fake/qc", "/fake/spec",
        )
        content = out.read_text(encoding="utf-8")
        assert "## Overview" in content
        assert "## Input Files" in content
        assert "## Primer Ranking" in content
        assert "## obipcr Coverage Summary" in content
        assert "## MFEprimer QC Summary" in content
        assert "## MFEprimer Spec Summary" in content
        assert "## Recommended Primers" in content
        assert "## Primers Not Recommended" in content
        assert "## Known Limitations" in content

    def test_includes_database_integrity_when_available(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        db_stats = load_database_stats(_make_spec_dir(tmp_path))
        out = tmp_path / "final_report.md"
        generate_final_report(
            records, db_stats, out,
            "/fake/obipcr", "/fake/qc", "/fake/spec",
        )
        content = out.read_text(encoding="utf-8")
        assert "## Database Integrity" in content
        assert "85" in content

    def test_handles_missing_db_stats_gracefully(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        out = tmp_path / "final_report.md"
        generate_final_report(
            records, None, out,
            "/fake/obipcr", "/fake/qc", "/fake/spec",
        )
        content = out.read_text(encoding="utf-8")
        assert "## Database Integrity" not in content


class TestWriteFinalOutputs:
    def test_orchestrator_writes_both_files(self, tmp_path):
        obipcr_dir = _make_obipcr_dir(tmp_path)
        qc_dir = _make_qc_dir(tmp_path)
        spec_dir = _make_spec_dir(tmp_path)
        outdir = tmp_path / "final_results"
        result = write_final_outputs(obipcr_dir, qc_dir, spec_dir, outdir)
        assert result["primer_rank"].is_file()
        assert result["final_report"].is_file()

    def test_creates_output_directory(self, tmp_path):
        obipcr_dir = _make_obipcr_dir(tmp_path)
        qc_dir = _make_qc_dir(tmp_path)
        spec_dir = _make_spec_dir(tmp_path)
        outdir = tmp_path / "new" / "nested" / "final"
        result = write_final_outputs(obipcr_dir, qc_dir, spec_dir, outdir)
        assert outdir.is_dir()
        assert result["primer_rank"].is_file()

# ── CLI test ───────────────────────────────────────────────────────────────


class TestCliFinalReport:
    def test_subcommand_runs_successfully(self, tmp_path):
        obipcr_dir = _make_obipcr_dir(tmp_path)
        qc_dir = _make_qc_dir(tmp_path)
        spec_dir = _make_spec_dir(tmp_path)
        outdir = tmp_path / "final_results"

        from fullpcr.cli import main as cli_main
        with mock.patch.object(sys, "exit"):
            cli_main([
                "final-report",
                "--obipcr-dir", str(obipcr_dir),
                "--qc-dir", str(qc_dir),
                "--spec-dir", str(spec_dir),
                "--outdir", str(outdir),
            ])

        assert (outdir / "primer_rank.tsv").is_file()
        assert (outdir / "final_report.md").is_file()

    def test_missing_input_dirs_dont_crash(self, tmp_path):
        outdir = tmp_path / "final_results"
        from fullpcr.cli import main as cli_main
        with mock.patch.object(sys, "exit"):
            cli_main([
                "final-report",
                "--obipcr-dir", str(tmp_path / "no_obipcr"),
                "--qc-dir", str(tmp_path / "no_qc"),
                "--spec-dir", str(tmp_path / "no_spec"),
                "--outdir", str(outdir),
            ])
        assert (outdir / "primer_rank.tsv").is_file()
        assert (outdir / "final_report.md").is_file()

# ── edge case tests ────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_degen_summary_missing_defaults_to_na(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        for r in records:
            assert r["degen_status"] == "NA"
            assert r["degen_variant_count"] == "NA"

    def test_warn_no_amp_lowers_ranking_below_pass(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        assert records[0]["primer_id"] == "12S_long"
        last_ids = {r["primer_id"] for r in records[-2:]}
        assert "COI_full" in last_ids
        assert "COI_short" in last_ids

    def test_warn_tm_diff_in_reason(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        row_12s = [r for r in records if r["primer_id"] == "12S_long"][0]
        assert "Tm difference" in row_12s["reason"]
        assert "8.09" in row_12s["reason"]

    def test_spec_pass_but_obipcr_low_not_recommended(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        row_16s = [r for r in records if r["primer_id"] == "16S_short"][0]
        assert row_16s["final_status"] != "RECOMMENDED"

    def test_obipcr_high_qc_warn_acceptable(self, tmp_path):
        obipcr = load_obipcr_summary(_make_obipcr_dir(tmp_path))
        qc = load_qc_summary(_make_qc_dir(tmp_path))
        spec = load_spec_summary(_make_spec_dir(tmp_path))
        records = rank_primers(obipcr, qc, spec)
        row_12s = [r for r in records if r["primer_id"] == "12S_long"][0]
        assert row_12s["final_status"] in ("ACCEPTABLE_WITH_WARNINGS", "RECOMMENDED")

    def test_needs_review_when_file_missing(self, tmp_path):
        records = rank_primers([], [], [])
        assert records == []
