"""Tests for fullpcr.degen — degenerate primer expansion and summarisation."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

from fullpcr.degen import (
    DEGEN_SUMMARY_FIELDNAMES,
    count_degenerate_variants,
    expand_degenerate_sequence,
    has_degenerate_bases,
    summarize_degenerate_primers,
    write_degen_outputs,
)
from fullpcr.primers import Primer

# ── helpers ────────────────────────────────────────────────────────────────


def _make_primers(*, degenerate: bool = False) -> list[Primer]:
    """Build a list of Primer objects for testing."""
    if degenerate:
        return [
            Primer(
                primer_id="TEST_RY",
                forward="ART",        # R = A/G → 2 variants
                reverse="AYT",        # Y = C/T → 2 variants
                min_length=100,
                max_length=300,
            ),
            Primer(
                primer_id="TEST_N4",
                forward="NNNN",       # NNNN = 4^4 = 256
                reverse="ACGT",
                min_length=100,
                max_length=300,
            ),
        ]
    return [
        Primer(
            primer_id="COI_short",
            forward="GGTCAACAAATCATAAAGATATTGG",
            reverse="TAAACTTCAGGGTGACCAAAAAATCA",
            min_length=100,
            max_length=300,
        ),
        Primer(
            primer_id="16S_short",
            forward="GACGAGAAGACCCTATGGAGC",
            reverse="CGCTGTTATCCCTAGGGTAACT",
            min_length=100,
            max_length=300,
        ),
    ]


def _read_tsv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


# ── has_degenerate_bases ──────────────────────────────────────────────────


class TestHasDegenerateBases:
    def test_no_degenerate(self):
        assert has_degenerate_bases("ACGT") is False

    def test_empty_sequence(self):
        assert has_degenerate_bases("") is False

    def test_single_r(self):
        assert has_degenerate_bases("R") is True

    def test_mixed(self):
        assert has_degenerate_bases("ACRYGT") is True

    def test_all_iupac_non_degenerate(self):
        assert has_degenerate_bases("ACGT") is False


# ── count_degenerate_variants ─────────────────────────────────────────────


class TestCountDegenerateVariants:
    def test_no_degenerate(self):
        assert count_degenerate_variants("ACGT") == 1

    def test_r_expands_to_2(self):
        assert count_degenerate_variants("R") == 2

    def test_y_expands_to_2(self):
        assert count_degenerate_variants("Y") == 2

    def test_n_expands_to_4(self):
        assert count_degenerate_variants("N") == 4

    def test_ry_expands_to_4(self):
        assert count_degenerate_variants("RY") == 4

    def test_nnnn_is_256(self):
        assert count_degenerate_variants("NNNN") == 256

    def test_nnnnn_is_1024(self):
        assert count_degenerate_variants("NNNNN") == 1024

    def test_empty_sequence(self):
        assert count_degenerate_variants("") == 0


# ── expand_degenerate_sequence ────────────────────────────────────────────


class TestExpandDegenerateSequence:
    def test_no_degeneracy(self):
        variants, status, reason = expand_degenerate_sequence("ACGT", 256)
        assert status == "NO_DEGENERACY"
        assert variants == ["ACGT"]
        assert reason == ""

    def test_r_expansion(self):
        variants, status, reason = expand_degenerate_sequence("R", 256)
        assert status == "EXPANDED"
        assert sorted(variants) == ["A", "G"]
        assert "R->A/G" in reason

    def test_y_expansion(self):
        variants, status, reason = expand_degenerate_sequence("Y", 256)
        assert status == "EXPANDED"
        assert sorted(variants) == ["C", "T"]

    def test_n_expansion(self):
        variants, status, reason = expand_degenerate_sequence("N", 256)
        assert status == "EXPANDED"
        assert sorted(variants) == ["A", "C", "G", "T"]

    def test_ry_expansion(self):
        variants, status, reason = expand_degenerate_sequence("RY", 256)
        assert status == "EXPANDED"
        assert len(variants) == 4
        assert "R->A/G" in reason
        assert "Y->C/T" in reason

    def test_nnnn_boundary_256(self):
        variants, status, reason = expand_degenerate_sequence("NNNN", 256)
        assert status == "EXPANDED"
        assert len(variants) == 256

    def test_nnnnn_explosion(self):
        variants, status, reason = expand_degenerate_sequence("NNNNN", 256)
        assert status == "FAIL_DEGENERATE_EXPLOSION"
        assert variants == []
        assert "1024" in reason
        assert "256" in reason

    def test_invalid_base(self):
        variants, status, reason = expand_degenerate_sequence("ACXGT", 256)
        assert status == "INVALID_BASE"
        assert variants == []
        assert "非法字符" in reason
        assert "X" in reason

    def test_empty_sequence(self):
        variants, status, reason = expand_degenerate_sequence("", 256)
        assert status == "NO_DEGENERACY"
        assert variants == []

    def test_high_max_allows_large_expansion(self):
        variants, status, reason = expand_degenerate_sequence("NNNNN", 2000)
        assert status == "EXPANDED"
        assert len(variants) == 1024


# ── summarize_degenerate_primers ──────────────────────────────────────────


class TestSummarizeDegeneratePrimers:
    def test_non_degenerate_primers(self):
        primers = _make_primers(degenerate=False)
        rows = summarize_degenerate_primers(primers, 256)

        assert len(rows) == 4  # 2 primers × 2 sides
        for r in rows:
            assert r["has_degenerate_bases"] is False
            assert r["variant_count"] == 1
            assert r["expanded_count"] == 1
            assert r["status"] == "NO_DEGENERACY"

    def test_degenerate_primers(self):
        primers = _make_primers(degenerate=True)
        rows = summarize_degenerate_primers(primers, 256)

        assert len(rows) == 4

        fwd_ry = next(
            r for r in rows
            if r["primer_id"] == "TEST_RY" and r["primer_side"] == "F"
        )
        assert fwd_ry["has_degenerate_bases"] is True
        assert fwd_ry["variant_count"] == 2
        assert fwd_ry["expanded_count"] == 2
        assert fwd_ry["status"] == "EXPANDED"

        fwd_n4 = next(
            r for r in rows
            if r["primer_id"] == "TEST_N4" and r["primer_side"] == "F"
        )
        assert fwd_n4["variant_count"] == 256
        assert fwd_n4["expanded_count"] == 256

        rev_n4 = next(
            r for r in rows
            if r["primer_id"] == "TEST_N4" and r["primer_side"] == "R"
        )
        assert rev_n4["status"] == "NO_DEGENERACY"

    def test_explosion_marked(self):
        primers = _make_primers(degenerate=True)
        rows = summarize_degenerate_primers(primers, max_variants=200)

        fwd_n4 = next(
            r for r in rows
            if r["primer_id"] == "TEST_N4" and r["primer_side"] == "F"
        )
        assert fwd_n4["status"] == "FAIL_DEGENERATE_EXPLOSION"
        assert fwd_n4["expanded_count"] == 0


# ── write_degen_outputs ───────────────────────────────────────────────────


class TestWriteDegenOutputs:
    def test_expanded_fasta_generated(self, tmp_path):
        primers = _make_primers(degenerate=True)
        outdir = tmp_path / "qc_results"

        written = write_degen_outputs(primers, outdir, max_variants=256)

        fasta_path = written["expanded_primers"]
        assert fasta_path.is_file()

        content = fasta_path.read_text(encoding="utf-8")
        assert ">TEST_RY__F__variant_1" in content
        assert ">TEST_RY__F__variant_2" in content
        assert ">TEST_RY__R__variant_1" in content
        assert ">TEST_N4__F__variant_1" in content
        assert ">TEST_N4__F__variant_256" in content
        assert ">TEST_N4__R__variant_1" in content

    def test_summary_tsv_generated(self, tmp_path):
        primers = _make_primers(degenerate=True)
        outdir = tmp_path / "qc_results"

        written = write_degen_outputs(primers, outdir, max_variants=256)

        summary_path = written["degen_summary"]
        assert summary_path.is_file()

        rows = _read_tsv(summary_path)
        assert len(rows) == 4
        for field in DEGEN_SUMMARY_FIELDNAMES:
            assert field in rows[0]

    def test_non_degenerate_primers_still_output(self, tmp_path):
        primers = _make_primers(degenerate=False)
        outdir = tmp_path / "qc_results"

        written = write_degen_outputs(primers, outdir, max_variants=256)

        fasta_content = written["expanded_primers"].read_text(encoding="utf-8")
        assert ">COI_short__F__variant_1" in fasta_content
        assert ">COI_short__R__variant_1" in fasta_content
        assert ">16S_short__F__variant_1" in fasta_content
        assert ">16S_short__R__variant_1" in fasta_content

    def test_explosion_excluded_from_fasta(self, tmp_path):
        primers = _make_primers(degenerate=True)
        outdir = tmp_path / "qc_results"

        written = write_degen_outputs(primers, outdir, max_variants=200)

        fasta_content = written["expanded_primers"].read_text(encoding="utf-8")
        assert ">TEST_N4__F__variant" not in fasta_content
        assert ">TEST_RY__F__variant" in fasta_content
        assert ">TEST_N4__R__variant" in fasta_content


# ── CLI qc-pre --degen ────────────────────────────────────────────────────


class TestCliDegen:
    def test_degen_dry_run(self, tmp_path, monkeypatch):
        primers_tsv = tmp_path / "primers.tsv"
        primers_tsv.write_text(
            "primer_id\tforward\treverse\tmin_length\tmax_length\n"
            "TEST\tACGT\tTGCA\t100\t300\n",
            encoding="utf-8",
        )

        from fullpcr.cli import main

        monkeypatch.setattr(sys, "exit", lambda code: None)

        main([
            "qc-pre",
            "--primers", str(primers_tsv),
            "--outdir", str(tmp_path / "qc_results"),
            "--degen",
            "--dry-run",
        ])

        degen_dir = tmp_path / "qc_results" / "degen"
        assert not degen_dir.exists()

    def test_degen_real_run(self, tmp_path, monkeypatch):
        primers_tsv = tmp_path / "primers.tsv"
        primers_tsv.write_text(
            "primer_id\tforward\treverse\tmin_length\tmax_length\n"
            "TEST_RY\tART\tAYT\t100\t300\n",
            encoding="utf-8",
        )

        from fullpcr.cli import main

        monkeypatch.setattr(sys, "exit", lambda code: None)

        main([
            "qc-pre",
            "--primers", str(primers_tsv),
            "--outdir", str(tmp_path / "qc_results"),
            "--degen",
        ])

        degen_dir = tmp_path / "qc_results" / "degen"
        assert degen_dir.is_dir()
        assert (degen_dir / "expanded_primers.fasta").is_file()
        assert (degen_dir / "degen_summary.tsv").is_file()

        summary_rows = _read_tsv(degen_dir / "degen_summary.tsv")
        fwd = next(
            r for r in summary_rows
            if r["primer_id"] == "TEST_RY" and r["primer_side"] == "F"
        )
        assert fwd["status"] == "EXPANDED"
        assert int(fwd["variant_count"]) == 2

    def test_degen_with_max_variants(self, tmp_path, monkeypatch):
        primers_tsv = tmp_path / "primers.tsv"
        primers_tsv.write_text(
            "primer_id\tforward\treverse\tmin_length\tmax_length\n"
            "TEST_N3\tNNN\tACGT\t100\t300\n",
            encoding="utf-8",
        )

        from fullpcr.cli import main

        monkeypatch.setattr(sys, "exit", lambda code: None)

        main([
            "qc-pre",
            "--primers", str(primers_tsv),
            "--outdir", str(tmp_path / "qc_results"),
            "--degen",
            "--max-degenerate-variants", "32",
        ])

        degen_dir = tmp_path / "qc_results" / "degen"
        summary_rows = _read_tsv(degen_dir / "degen_summary.tsv")
        fwd = next(
            r for r in summary_rows
            if r["primer_id"] == "TEST_N3" and r["primer_side"] == "F"
        )
        # NNN = 4^3 = 64 > 32 → explosion
        assert fwd["status"] == "FAIL_DEGENERATE_EXPLOSION"
