"""Tests for fasta_parser module."""

import gzip
import textwrap
from pathlib import Path

import pytest

from fullpcr.fasta_parser import (
    TSV_FIELDNAMES,
    parse_fasta_header,
    parse_obipcr_fasta,
    write_amplicons_tsv,
)


# ── helpers ────────────────────────────────────────────────────────────


def _write_fasta(tmp_path: Path, content: str, *, name: str = "test.fasta") -> str:
    path = tmp_path / name
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return str(path)


def _write_fasta_gz(tmp_path: Path, content: str, *, name: str = "test.fasta.gz") -> str:
    path = tmp_path / name
    raw = textwrap.dedent(content).lstrip().encode("utf-8")
    with gzip.open(path, "wb") as fh:
        fh.write(raw)
    return str(path)


# ── parse_fasta_header ─────────────────────────────────────────────────


class TestParseFastaHeader:
    def test_json_metadata_header(self):
        header = (
            'NC_012920_sub[5342..5907] {"taxid":"9606",'
            '"scientific_name":"Homo sapiens","forward_error":0,'
            '"reverse_error":1,"direction":"forward",'
            '"forward_match":"GGTCA","reverse_match":"TAAAC"}'
        )
        result = parse_fasta_header(header)

        assert result["accession"] == "NC_012920"
        assert result["definition"] == "_sub[5342..5907]"
        assert result["taxid"] == "9606"
        assert result["scientific_name"] == "Homo sapiens"
        assert result["direction"] == "forward"
        assert result["forward_error"] == "0"
        assert result["reverse_error"] == "1"
        assert result["forward_match"] == "GGTCA"
        assert result["reverse_match"] == "TAAAC"

    def test_json_with_definition_field(self):
        """When JSON provides definition, use it over header text."""
        header = (
            'NC_012920_sub[1..100] {"taxid":"9606",'
            '"scientific_name":"Homo sapiens",'
            '"definition":"Homo sapiens COI gene"}'
        )
        result = parse_fasta_header(header)

        assert result["accession"] == "NC_012920"
        assert result["definition"] == "Homo sapiens COI gene"
        assert result["scientific_name"] == "Homo sapiens"

    def test_json_metadata_integer_taxid(self):
        """taxid as integer in JSON should be stringified."""
        header = 'NC_001_sub[1..100] {"taxid":9606,"scientific_name":"Homo"}'
        result = parse_fasta_header(header)
        assert result["taxid"] == "9606"
        assert result["scientific_name"] == "Homo"

    def test_ncbi_style_header(self):
        header = "NC_005089 Homo sapiens mitochondrion, complete genome"
        result = parse_fasta_header(header)

        assert result["accession"] == "NC_005089"
        assert result["definition"] == "Homo sapiens mitochondrion, complete genome"
        assert result["taxid"] == ""
        # Conservative: NCBI header does not imply a validated scientific_name
        assert result["scientific_name"] == ""

    def test_accession_only_header(self):
        header = "NC_006789"
        result = parse_fasta_header(header)

        assert result["accession"] == "NC_006789"
        assert result["definition"] == ""
        assert result["taxid"] == ""
        assert result["scientific_name"] == ""

    def test_definition_from_header_text(self):
        """When no JSON, definition = header text after accession."""
        header = "NC_001 Homo sapiens COI gene, partial cds"
        result = parse_fasta_header(header)

        assert result["accession"] == "NC_001"
        assert result["definition"] == "Homo sapiens COI gene, partial cds"
        assert result["scientific_name"] == ""

    def test_corrupt_json_does_not_crash(self):
        header = 'NC_001_sub[1..100] {"taxid":"9606",corrupt'
        result = parse_fasta_header(header)

        assert result["accession"] == "NC_001"
        assert result["taxid"] == ""
        assert result["scientific_name"] == ""

    def test_corrupt_json_not_a_dict(self):
        """JSON that parses as a list should not crash."""
        header = 'NC_001_sub[1..100] [1, 2, 3]'
        result = parse_fasta_header(header)
        assert result["accession"] == "NC_001"

    def test_no_json_no_spaces(self):
        header = "simple_accession"
        result = parse_fasta_header(header)

        assert result["accession"] == "simple_accession"
        assert result["definition"] == ""
        assert result["taxid"] == ""
        assert result["scientific_name"] == ""

    def test_accession_with_sub_suffix_cleaned(self):
        header = 'NC_012920_sub[10..200] {"taxid":"9606"}'
        result = parse_fasta_header(header)
        assert result["accession"] == "NC_012920"

    def test_all_default_keys_present(self):
        header = "anything"
        result = parse_fasta_header(header)
        for key in [
            "accession", "definition", "taxid", "scientific_name",
            "direction", "forward_error", "reverse_error",
            "forward_match", "reverse_match",
        ]:
            assert key in result


# ── parse_obipcr_fasta ─────────────────────────────────────────────────


class TestParseObipcrFasta:
    def test_parses_multiple_records(self, tmp_path):
        content = """\
            >seq1 {"taxid":"9606","scientific_name":"Homo sapiens"}
            ATCGATCGATCG
            >seq2 {"taxid":"9913","scientific_name":"Bos taurus"}
            GCTAGCTAGCTA
            GCTAGCTAGCTA
            >seq3 Homo sapiens mitochondrion
            TATATATATATA
        """
        path = _write_fasta(tmp_path, content)
        records = parse_obipcr_fasta(path)
        assert len(records) == 3

    def test_record_structure(self, tmp_path):
        content = """\
            >NC_012920_sub[1..100] {"taxid":"9606","scientific_name":"Homo sapiens","forward_error":0,"reverse_error":0,"direction":"forward"}
            ATCGATCGATCG
            ATCGATCGATCG
        """
        path = _write_fasta(tmp_path, content)
        records = parse_obipcr_fasta(path)

        rec = records[0]
        assert rec["record_id"] == "amplicon_0001"
        assert rec["accession"] == "NC_012920"
        assert rec["definition"] == "_sub[1..100]"
        assert rec["taxid"] == "9606"
        assert rec["scientific_name"] == "Homo sapiens"
        assert rec["forward_error"] == "0"
        assert rec["reverse_error"] == "0"
        assert rec["direction"] == "forward"
        assert rec["sequence"] == "ATCGATCGATCGATCGATCGATCG"
        assert rec["amplicon_length"] == 24
        for key in TSV_FIELDNAMES:
            assert key in rec

    def test_multi_line_sequence_concatenation(self, tmp_path):
        content = """\
            >seq1
            AAAA
            CCCC
            GGGG
            TTTT
        """
        path = _write_fasta(tmp_path, content)
        records = parse_obipcr_fasta(path)

        assert records[0]["sequence"] == "AAAACCCCGGGGTTTT"
        assert records[0]["amplicon_length"] == 16

    def test_amplicon_length_from_sequence(self, tmp_path):
        """amplicon_length must be computed from actual sequence length."""
        content = """\
            >seq1 {"taxid":"9606"}
            ATCGATCG
        """
        path = _write_fasta(tmp_path, content)
        records = parse_obipcr_fasta(path)

        assert records[0]["amplicon_length"] == 8

    def test_missing_taxid_and_scientific_name(self, tmp_path):
        """Records with no taxid/scientific_name should still be returned."""
        content = """\
            >bare_accession
            ATCGATCG
        """
        path = _write_fasta(tmp_path, content)
        records = parse_obipcr_fasta(path)

        assert len(records) == 1
        assert records[0]["taxid"] == ""
        assert records[0]["scientific_name"] == ""
        assert records[0]["accession"] == "bare_accession"

    def test_empty_file_returns_empty_list(self, tmp_path):
        path = _write_fasta(tmp_path, "")
        records = parse_obipcr_fasta(path)
        assert records == []

    def test_fasta_gz_reading(self, tmp_path):
        content = """\
            >seq1 {"taxid":"9606","scientific_name":"Homo"}
            ATCGATCGATCG
            >seq2 Bos taurus
            GCTAGCTAGCTA
        """
        path = _write_fasta_gz(tmp_path, content)
        records = parse_obipcr_fasta(path)

        assert len(records) == 2
        assert records[0]["taxid"] == "9606"
        # NCBI-style: definition = text after accession, scientific_name = ""
        assert records[1]["definition"] == "Bos taurus"
        assert records[1]["scientific_name"] == ""

    def test_fa_gz_reading(self, tmp_path):
        """Should also handle .fa.gz extension."""
        content = """\
            >seq1
            ATCG
        """
        path = _write_fasta_gz(tmp_path, content, name="test.fa.gz")
        records = parse_obipcr_fasta(path)
        assert len(records) == 1

    def test_fa_extension_reading(self, tmp_path):
        """Should handle .fa extension."""
        content = """\
            >seq1
            ATCG
        """
        path = _write_fasta(tmp_path, content, name="test.fa")
        records = parse_obipcr_fasta(path)
        assert len(records) == 1

    def test_file_not_found(self, tmp_path):
        nonexistent = str(tmp_path / "no_such_file.fasta")
        with pytest.raises(FileNotFoundError, match="不存在"):
            parse_obipcr_fasta(nonexistent)

    def test_invalid_suffix(self, tmp_path):
        path = tmp_path / "test.txt"
        path.write_text(">seq1\nATCG", encoding="utf-8")
        with pytest.raises(ValueError, match="不支持的文件格式"):
            parse_obipcr_fasta(str(path))

    def test_whitespace_lines_ignored(self, tmp_path):
        content = """\
            >seq1

            ATCG

            GCTA

            >seq2
            TATA
        """
        path = _write_fasta(tmp_path, content)
        records = parse_obipcr_fasta(path)

        assert len(records) == 2
        assert records[0]["sequence"] == "ATCGGCTA"

    def test_reads_example_data(self):
        import os
        project_root = os.path.dirname(os.path.dirname(__file__))
        example = os.path.join(project_root, "example_data", "mock_obipcr_amplicons.fasta")

        records = parse_obipcr_fasta(example)

        assert len(records) == 4
        assert records[0]["accession"] == "NC_012920"
        assert records[0]["taxid"] == "9606"
        assert records[0]["scientific_name"] == "Homo sapiens"
        # NCBI-style record
        assert records[2]["accession"] == "NC_005089"
        assert records[2]["definition"] == "Homo sapiens mitochondrion, complete genome"
        assert records[2]["scientific_name"] == ""
        # Accession-only record
        assert records[3]["accession"] == "NC_006789"
        assert records[3]["definition"] == ""
        assert records[3]["taxid"] == ""

        for rec in records:
            assert len(rec["sequence"]) == rec["amplicon_length"]
            assert rec["amplicon_length"] > 0


# ── write_amplicons_tsv ────────────────────────────────────────────────


class TestWriteAmpliconsTsv:
    def test_writes_tsv_with_correct_columns(self, tmp_path):
        records = [
            {
                "record_id": "amplicon_0001",
                "accession": "NC_001",
                "definition": "Homo sapiens COI",
                "taxid": "9606",
                "scientific_name": "Homo sapiens",
                "direction": "forward",
                "forward_error": "0",
                "reverse_error": "1",
                "forward_match": "",
                "reverse_match": "",
                "amplicon_length": 12,
                "sequence": "ATCGATCGATCG",
            },
        ]
        output = tmp_path / "amplicons.tsv"
        write_amplicons_tsv(records, str(output))

        lines = output.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2  # header + 1 data row
        header_cols = lines[0].split("\t")
        assert header_cols == TSV_FIELDNAMES
        data_cols = lines[1].split("\t")
        assert data_cols[header_cols.index("record_id")] == "amplicon_0001"
        assert data_cols[header_cols.index("accession")] == "NC_001"
        assert data_cols[header_cols.index("definition")] == "Homo sapiens COI"

    def test_writes_multiple_records(self, tmp_path):
        records = [
            {"record_id": "amplicon_0001", "sequence": "ATCG"},
            {"record_id": "amplicon_0002", "sequence": "GCTA"},
        ]
        output = tmp_path / "amplicons.tsv"
        write_amplicons_tsv(records, str(output))

        lines = output.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3  # header + 2 rows

    def test_creates_parent_directories(self, tmp_path):
        records = [{"record_id": "amplicon_0001", "sequence": "ATCG"}]
        output = tmp_path / "deep" / "nested" / "amplicons.tsv"
        write_amplicons_tsv(records, str(output))
        assert output.exists()

    def test_empty_records(self, tmp_path):
        output = tmp_path / "empty.tsv"
        write_amplicons_tsv([], str(output))
        # Should not crash
