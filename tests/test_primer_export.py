"""Tests for primer_export module."""

import pytest

from fullpcr.primers import Primer
from fullpcr.primer_export import (
    export_primer_pairs_to_tsv,
    export_primers_to_fasta,
)


# ── helpers ────────────────────────────────────────────────────────────


def _make_primers() -> list[Primer]:
    """Return a minimal list of synthetic Primer records for testing."""
    return [
        Primer(
            primer_id="COI_short",
            forward="GGTCAACAAATCATAAAGATATTGG",
            reverse="TAAACTTCAGGGTGACCAAAAAATCA",
            min_length=100,
            max_length=400,
        ),
        Primer(
            primer_id="16S",
            forward="GACGAGAAGACCCTATGGAGC",
            reverse="CGCTGTTATCCCTAGGGTAACT",
            min_length=200,
            max_length=600,
        ),
    ]


# ── export_primers_to_fasta ────────────────────────────────────────────


class TestExportPrimersToFasta:
    def test_creates_file(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "primers.fasta"

        result = export_primers_to_fasta(primers, out)
        assert result == out
        assert out.is_file()

    def test_writes_correct_fasta_format(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "primers.fasta"

        export_primers_to_fasta(primers, out)
        content = out.read_text(encoding="utf-8")

        expected = (
            ">COI_short_F\n"
            "GGTCAACAAATCATAAAGATATTGG\n"
            ">COI_short_R\n"
            "TAAACTTCAGGGTGACCAAAAAATCA\n"
            ">16S_F\n"
            "GACGAGAAGACCCTATGGAGC\n"
            ">16S_R\n"
            "CGCTGTTATCCCTAGGGTAACT\n"
        )
        assert content == expected

    def test_contains_forward_and_reverse(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "primers.fasta"

        export_primers_to_fasta(primers, out)
        content = out.read_text(encoding="utf-8")

        assert ">COI_short_F" in content
        assert ">COI_short_R" in content
        assert ">16S_F" in content
        assert ">16S_R" in content
        assert "GGTCAACAAATCATAAAGATATTGG" in content
        assert "CGCTGTTATCCCTAGGGTAACT" in content

    def test_creates_parent_directories(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "deep" / "nested" / "primers.fasta"

        export_primers_to_fasta(primers, out)
        assert out.is_file()
        assert out.parent.exists()

    def test_raises_on_empty_list(self, tmp_path):
        with pytest.raises(ValueError, match="primers 列表不能为空"):
            export_primers_to_fasta([], tmp_path / "empty.fasta")

    def test_returns_path_instance(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "p.fasta"

        result = export_primers_to_fasta(primers, out)
        assert isinstance(result, type(out))

    def test_single_primer(self, tmp_path):
        primers = [
            Primer(
                primer_id="SINGLE",
                forward="AAAA",
                reverse="TTTT",
                min_length=50,
                max_length=100,
            )
        ]
        out = tmp_path / "single.fasta"

        export_primers_to_fasta(primers, out)
        content = out.read_text(encoding="utf-8")
        assert content == ">SINGLE_F\nAAAA\n>SINGLE_R\nTTTT\n"

    def test_overwrites_existing_file(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "primers.fasta"
        out.write_text("old", encoding="utf-8")

        export_primers_to_fasta(primers, out)
        assert "COI_short" in out.read_text(encoding="utf-8")


# ── export_primer_pairs_to_tsv ─────────────────────────────────────────


class TestExportPrimerPairsToTsv:
    def test_creates_file(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "pairs.tsv"

        result = export_primer_pairs_to_tsv(primers, out)
        assert result == out
        assert out.is_file()

    def test_writes_header_and_data(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "pairs.tsv"

        export_primer_pairs_to_tsv(primers, out)
        lines = out.read_text(encoding="utf-8").strip().split("\n")

        assert lines[0] == "primer_id\tforward\treverse"
        assert len(lines) == 3  # header + 2 primers

    def test_contains_primer_data(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "pairs.tsv"

        export_primer_pairs_to_tsv(primers, out)
        content = out.read_text(encoding="utf-8")

        assert "COI_short\tGGTCAACAAATCATAAAGATATTGG\tTAAACTTCAGGGTGACCAAAAAATCA" in content
        assert "16S\tGACGAGAAGACCCTATGGAGC\tCGCTGTTATCCCTAGGGTAACT" in content

    def test_creates_parent_directories(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "deep" / "nested" / "pairs.tsv"

        export_primer_pairs_to_tsv(primers, out)
        assert out.is_file()

    def test_raises_on_empty_list(self, tmp_path):
        with pytest.raises(ValueError, match="primers 列表不能为空"):
            export_primer_pairs_to_tsv([], tmp_path / "empty.tsv")

    def test_returns_path_instance(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "p.tsv"

        result = export_primer_pairs_to_tsv(primers, out)
        assert isinstance(result, type(out))

    def test_single_primer_pair(self, tmp_path):
        primers = [
            Primer(
                primer_id="SINGLE",
                forward="AAAA",
                reverse="TTTT",
                min_length=50,
                max_length=100,
            )
        ]
        out = tmp_path / "single.tsv"

        export_primer_pairs_to_tsv(primers, out)
        content = out.read_text(encoding="utf-8")
        assert content == "primer_id\tforward\treverse\nSINGLE\tAAAA\tTTTT\n"

    def test_overwrites_existing_file(self, tmp_path):
        primers = _make_primers()
        out = tmp_path / "pairs.tsv"
        out.write_text("old", encoding="utf-8")

        export_primer_pairs_to_tsv(primers, out)
        assert "COI_short" in out.read_text(encoding="utf-8")
