"""Tests for primers module."""

import textwrap

import pytest

from fullpcr.primers import Primer, read_primers


def _write_tsv(tmp_path, content: str) -> str:
    """Helper: write TSV content to a temp file and return the path."""
    filepath = tmp_path / "primers.tsv"
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


class TestReadPrimers:
    """Tests for read_primers()."""

    def test_reads_valid_primers(self, tmp_path):
        """Should parse a valid primers.tsv with correct types."""
        content = textwrap.dedent("""\
            primer_id\tforward\treverse\tmin_length\tmax_length
            COI_short\tGGTCAACAAATCATAAAGATATTGG\tTAAACTTCAGGGTGACCAAAAAATCA\t100\t400
            16S\tGACGAGAAGACCCTATGGAGC\tCGCTGTTATCCCTAGGGTAACT\t200\t600
        """)
        path = _write_tsv(tmp_path, content)

        primers = read_primers(path)

        assert len(primers) == 2

        p1 = primers[0]
        assert p1.primer_id == "COI_short"
        assert p1.forward == "GGTCAACAAATCATAAAGATATTGG"
        assert p1.reverse == "TAAACTTCAGGGTGACCAAAAAATCA"
        assert p1.min_length == 100
        assert p1.max_length == 400
        assert isinstance(p1.min_length, int)
        assert isinstance(p1.max_length, int)

        p2 = primers[1]
        assert p2.primer_id == "16S"
        assert p2.min_length == 200
        assert p2.max_length == 600

    def test_raises_on_missing_column(self, tmp_path):
        """Should raise ValueError when a required column is missing."""
        content = textwrap.dedent("""\
            primer_id\tforward\treverse\tmin_length
            COI_short\tGGTCA\tTAAACT\t100
        """)
        path = _write_tsv(tmp_path, content)

        with pytest.raises(ValueError, match="缺少必填字段") as exc_info:
            read_primers(path)

        assert "max_length" in str(exc_info.value)

    def test_raises_on_multiple_missing_columns(self, tmp_path):
        """Should list all missing columns in the error message."""
        content = textwrap.dedent("""\
            primer_id\tforward
            COI_short\tGGTCA
        """)
        path = _write_tsv(tmp_path, content)

        with pytest.raises(ValueError) as exc_info:
            read_primers(path)

        msg = str(exc_info.value)
        assert "max_length" in msg
        assert "min_length" in msg
        assert "reverse" in msg

    def test_raises_on_non_integer_min_length(self, tmp_path):
        """Should raise ValueError when min_length is not an integer."""
        content = textwrap.dedent("""\
            primer_id\tforward\treverse\tmin_length\tmax_length
            COI_short\tGGTCA\tTAAACT\tabc\t400
        """)
        path = _write_tsv(tmp_path, content)

        with pytest.raises(ValueError, match="无法转为整数"):
            read_primers(path)

    def test_raises_on_negative_min_length(self, tmp_path):
        """Should raise ValueError when min_length <= 0."""
        content = textwrap.dedent("""\
            primer_id\tforward\treverse\tmin_length\tmax_length
            COI_short\tGGTCA\tTAAACT\t-1\t400
        """)
        path = _write_tsv(tmp_path, content)

        with pytest.raises(ValueError, match="min_length 必须 > 0"):
            read_primers(path)

    def test_raises_on_zero_max_length(self, tmp_path):
        """Should raise ValueError when max_length <= 0."""
        content = textwrap.dedent("""\
            primer_id\tforward\treverse\tmin_length\tmax_length
            COI_short\tGGTCA\tTAAACT\t100\t0
        """)
        path = _write_tsv(tmp_path, content)

        with pytest.raises(ValueError, match="max_length 必须 > 0"):
            read_primers(path)

    def test_raises_when_min_greater_than_max(self, tmp_path):
        """Should raise ValueError when min_length > max_length."""
        content = textwrap.dedent("""\
            primer_id\tforward\treverse\tmin_length\tmax_length
            COI_short\tGGTCA\tTAAACT\t500\t400
        """)
        path = _write_tsv(tmp_path, content)

        with pytest.raises(ValueError, match="不能大于 max_length"):
            read_primers(path)

    def test_reads_extra_columns_without_error(self, tmp_path):
        """Should ignore extra columns beyond the required ones."""
        content = textwrap.dedent("""\
            primer_id\tforward\treverse\tmin_length\tmax_length\textra\tnotes
            COI_short\tGGTCA\tTAAACT\t100\t400\tfoo\tbar
        """)
        path = _write_tsv(tmp_path, content)

        primers = read_primers(path)

        assert len(primers) == 1
        assert primers[0].primer_id == "COI_short"

    def test_reads_example_data_file(self):
        """Should read the real example_data/primers.tsv without errors."""
        import os

        project_root = os.path.dirname(os.path.dirname(__file__))
        example = os.path.join(project_root, "example_data", "primers.tsv")

        primers = read_primers(example)

        assert len(primers) == 4
        ids = [p.primer_id for p in primers]
        assert "COI_short" in ids
        assert "COI_full" in ids
        assert "16S_short" in ids
        assert "12S_long" in ids

        for p in primers:
            assert isinstance(p.min_length, int)
            assert isinstance(p.max_length, int)
            assert p.min_length > 0
            assert p.max_length > 0
            assert p.min_length <= p.max_length


class TestPrimerDataclass:
    """Tests for the Primer dataclass."""

    def test_primer_is_frozen(self):
        """Primer should be immutable (frozen dataclass)."""
        p = Primer(
            primer_id="test",
            forward="AAAA",
            reverse="TTTT",
            min_length=100,
            max_length=400,
        )

        with pytest.raises(Exception):
            p.min_length = 200

    def test_primer_repr(self):
        """Primer should have a readable repr."""
        p = Primer(
            primer_id="COI",
            forward="AAAA",
            reverse="TTTT",
            min_length=100,
            max_length=400,
        )

        rep = repr(p)
        assert "COI" in rep
        assert "100" in rep
        assert "400" in rep
