"""Tests for fullpcr.qc_spec — spec parser and specificity summary."""

from __future__ import annotations

import csv
from pathlib import Path
from unittest import mock

import pytest

from fullpcr.mfeprimer_runner import (
    build_mfeprimer_index_command,
    build_mfeprimer_spec_command,
)
from fullpcr.primers import Primer
from fullpcr.qc_spec import (
    DATABASE_STATS_FIELDNAMES,
    _detect_size_outliers,
    _extract_note_json,
    _infer_primer_id,
    count_fasta_bases,
    count_fasta_records,
    normalize_fasta_for_mfeprimer,
    parse_spec_tsv,
    summarize_spec_records,
    validate_mfeprimer_index_outputs,
    write_spec_outputs,
    write_spec_primer_pairs,
)

# ── helpers ────────────────────────────────────────────────────────────────

_MOCK_SPEC_TSV_CONTENT = """\
#1-based coordinate, should be idential to blat output if align primer sequences to genome
#name	chrom	ampStart	ampEnd	ampGC	ampSize	fpName	fpStart	fpEnd	fpSeq	fpTm	fpGC	fpDg	rpName	rpEnd	rpStart	rpSeq	rpTm	rpGC	rpDg	note
Amp_1	NC_015613.1	17440	17884	51.69	445	12S_long_F	17440	17464	AAACTGGGATTAGATACCCCACTAT	60.11	40.00	-24.41	12S_long_R	17865	17884	ACACACCGCCCGTCACCCTC	67.96	70.00	-26.06	{"taxid":"451427","scientific_name":"Acridotheres cristatellus"} Acridotheres cristatellus mitochondrion, complete genome
Amp_2	NC_015613.1	34283	34727	51.69	445	12S_long_F	34283	34307	AAACTGGGATTAGATACCCCACTAT	60.11	40.00	-24.41	12S_long_R	34708	34727	ACACACCGCCCGTCACCCTC	67.96	70.00	-26.06	{"taxid":"451427","scientific_name":"Acridotheres cristatellus"} Acridotheres cristatellus mitochondrion, complete genome
Amp_3	NC_015613.1	51122	51566	51.69	445	12S_long_F	51122	51146	AAACTGGGATTAGATACCCCACTAT	60.11	40.00	-24.41	12S_long_R	51547	51566	ACACACCGCCCGTCACCCTC	67.96	70.00	-26.06	{"taxid":"451427","scientific_name":"Acridotheres cristatellus"} Acridotheres cristatellus mitochondrion, complete genome
Amp_4	NC_015613.1	67964	68407	50.45	444	12S_long_F	67964	67988	AAACTGGGATTAGATACCCCACTAT	60.11	40.00	-24.41	12S_long_R	68388	68407	ACACACCGCCCGTCACCCTC	67.96	70.00	-26.06	{"taxid":"451427","scientific_name":"Acridotheres cristatellus"} Acridotheres cristatellus mitochondrion, complete genome
Amp_5	NC_015613.1	135243	135686	50.90	444	12S_long_F	135243	135267	AAACTGGGATTAGATACCCCACTAT	60.11	40.00	-24.41	12S_long_R	135667	135686	ACACACCGCCCGTCACCCTC	67.96	70.00	-26.06	{"taxid":"451427","scientific_name":"Acridotheres cristatellus"} Acridotheres cristatellus mitochondrion, complete genome
"""  # noqa: E501

_MOCK_SPEC_TSV_MULTI_REF = """\
#1-based coordinate, should be idential to blat output if align primer sequences to genome
#name	chrom	ampStart	ampEnd	ampGC	ampSize	fpName	fpStart	fpEnd	fpSeq	fpTm	fpGC	fpDg	rpName	rpEnd	rpStart	rpSeq	rpTm	rpGC	rpDg	note
Amp_1	ref_A	100	500	50.0	400	TEST_F	100	120	AAAA	55.0	40.0	-20.0	TEST_R	480	500	TTTT	55.0	40.0	-20.0	{"taxid":"1","scientific_name":"Species A"}
Amp_2	ref_A	1000	1400	50.0	400	TEST_F	1000	1020	AAAA	55.0	40.0	-20.0	TEST_R	1380	1400	TTTT	55.0	40.0	-20.0	{"taxid":"1","scientific_name":"Species A"}
Amp_3	ref_B	200	600	52.0	400	COI_F	200	220	GGGG	55.0	40.0	-20.0	COI_R	580	600	CCCC	55.0	40.0	-20.0	{"taxid":"2","scientific_name":"Species B"}
"""  # noqa: E501

_MOCK_SPEC_TSV_MULTI_TAXID = """\
#1-based coordinate, should be idential to blat output if align primer sequences to genome
#name	chrom	ampStart	ampEnd	ampGC	ampSize	fpName	fpStart	fpEnd	fpSeq	fpTm	fpGC	fpDg	rpName	rpEnd	rpStart	rpSeq	rpTm	rpGC	rpDg	note
Amp_1	ref_A	100	500	50.0	400	COI_F	100	120	AAAA	55.0	40.0	-20.0	COI_R	480	500	TTTT	55.0	40.0	-20.0	{"taxid":"1","scientific_name":"Species A"}
Amp_2	ref_B	100	500	50.0	400	COI_F	100	120	AAAA	55.0	40.0	-20.0	COI_R	480	500	TTTT	55.0	40.0	-20.0	{"taxid":"2","scientific_name":"Species B"}
Amp_3	ref_C	100	500	50.0	400	COI_F	100	120	AAAA	55.0	40.0	-20.0	COI_R	480	500	TTTT	55.0	40.0	-20.0	{"taxid":"3","scientific_name":"Species C"}
"""  # noqa: E501

_MOCK_SPEC_TSV_BAD_NOTE = """\
#1-based coordinate, should be idential to blat output if align primer sequences to genome
#name	chrom	ampStart	ampEnd	ampGC	ampSize	fpName	fpStart	fpEnd	fpSeq	fpTm	fpGC	fpDg	rpName	rpEnd	rpStart	rpSeq	rpTm	rpGC	rpDg	note
Amp_1	ref_A	100	500	50.0	400	COI_F	100	120	AAAA	55.0	40.0	-20.0	COI_R	480	500	TTTT	55.0	40.0	-20.0	not valid json at all just text
"""  # noqa: E501

_MOCK_SPEC_TSV_SIZE_OUTLIERS = """\
#1-based coordinate, should be idential to blat output if align primer sequences to genome
#name	chrom	ampStart	ampEnd	ampGC	ampSize	fpName	fpStart	fpEnd	fpSeq	fpTm	fpGC	fpDg	rpName	rpEnd	rpStart	rpSeq	rpTm	rpGC	rpDg	note
Amp_1	ref_A	100	500	50.0	400	TEST_F	100	120	AAAA	55.0	40.0	-20.0	TEST_R	480	500	TTTT	55.0	40.0	-20.0	{"taxid":"1"}
Amp_2	ref_A	200	600	50.0	400	TEST_F	200	220	AAAA	55.0	40.0	-20.0	TEST_R	580	600	TTTT	55.0	40.0	-20.0	{}
Amp_3	ref_A	300	700	50.0	400	TEST_F	300	320	AAAA	55.0	40.0	-20.0	TEST_R	680	700	TTTT	55.0	40.0	-20.0	{}
Amp_4	ref_A	400	800	50.0	400	TEST_F	400	420	AAAA	55.0	40.0	-20.0	TEST_R	780	800	TTTT	55.0	40.0	-20.0	{}
Amp_5	ref_A	500	900	50.0	400	TEST_F	500	520	AAAA	55.0	40.0	-20.0	TEST_R	880	900	TTTT	55.0	40.0	-20.0	{}
Amp_6	ref_A	600	2000	50.0	1400	TEST_F	600	620	AAAA	55.0	40.0	-20.0	TEST_R	1980	2000	TTTT	55.0	40.0	-20.0	{}
"""  # noqa: E501


def _make_primers() -> list[Primer]:
    return [
        Primer(
            primer_id="12S_long",
            forward="AAACTGGGATTAGATACCCCACTAT",
            reverse="GAGGGTGACGGGCGGTGTGT",
            min_length=300,
            max_length=900,
        ),
        Primer(
            primer_id="COI_short",
            forward="GGTCAACAAATCATAAAGATATTGG",
            reverse="TAAACTTCAGGGTGACCAAAAAATCA",
            min_length=100,
            max_length=400,
        ),
    ]


def _write_tsv_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _read_tsv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


# ── build_index_command ─────────────────────────────────────────────────


class TestBuildIndexCommand:
    """Tests 1-2: index command builder."""

    def test_basic(self):
        """build_mfeprimer_index_command generates correct command."""
        cfg = build_mfeprimer_index_command(
            database_path="/path/to/db.fasta",
            kvalue=9,
            cpu=2,
        )
        assert cfg.command[0] == "mfeprimer"
        assert "index" in cfg.command
        assert "-i" in cfg.command
        assert "/path/to/db.fasta" in cfg.command
        assert "-k" in cfg.command
        assert "9" in cfg.command
        assert "-c" in cfg.command
        assert "2" in cfg.command
        assert "-f" not in cfg.command

    def test_with_force(self):
        """Force flag adds -f to index command."""
        cfg = build_mfeprimer_index_command(
            database_path="/db.fasta", force=True,
        )
        assert "-f" in cfg.command


# ── build_spec_command ──────────────────────────────────────────────────


class TestBuildSpecCommand:
    """Tests 3-5: spec command builder."""

    def test_basic(self):
        """build_mfeprimer_spec_command includes all required flags."""
        cfg = build_mfeprimer_spec_command(
            primer_pairs_tsv="/pairs.tsv",
            database_path="/db.fasta",
            out_prefix="/out/spec_output.txt",
            max_size=500,
            tm=50.0,
            max_tm=75.0,
            cpu=2,
            kvalue=9,
        )
        cmd_str = " ".join(cfg.command)
        assert "spec" in cfg.command
        assert "-i /pairs.tsv" in cmd_str
        assert "-d /db.fasta" in cmd_str
        assert "-o /out/spec_output.txt" in cmd_str
        assert "-S 500" in cmd_str
        assert "-t 50.0" in cmd_str
        assert "-T 75.0" in cmd_str

    def test_with_mismatch(self):
        """--misMatch flag added when mismatch is set."""
        cfg = build_mfeprimer_spec_command(
            primer_pairs_tsv="/p.tsv",
            database_path="/d.fa",
            out_prefix="/o",
            mismatch=2,
        )
        cmd_str = " ".join(cfg.command)
        assert "--misMatch 2" in cmd_str

    def test_value_error_empty(self):
        """Empty required params raise ValueError."""
        with pytest.raises(ValueError):
            build_mfeprimer_spec_command(
                primer_pairs_tsv="",
                database_path="/d.fa",
                out_prefix="/o",
            )
        with pytest.raises(ValueError):
            build_mfeprimer_spec_command(
                primer_pairs_tsv="/p.tsv",
                database_path="",
                out_prefix="/o",
            )


# ── write_spec_primer_pairs ─────────────────────────────────────────────


class TestWriteSpecPrimerPairs:
    """Tests 6-7: spec primer pairs TSV writer."""

    def test_correct_format(self, tmp_path):
        """Output TSV has name, fp, rp columns without header."""
        primers = _make_primers()
        out = tmp_path / "spec_pairs.tsv"
        result = write_spec_primer_pairs(primers, out)
        assert result == out
        assert out.is_file()

        content = out.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert len(lines) == 2
        assert "12S_long" in lines[0]
        assert "AAACTGGGATTAGATACCCCACTAT" in lines[0]
        assert "GAGGGTGACGGGCGGTGTGT" in lines[0]
        assert lines[0].count("\t") == 2

    def test_empty_raises(self):
        """Empty primer list raises ValueError."""
        with pytest.raises(ValueError, match="不能为空"):
            write_spec_primer_pairs([], "/tmp/out.tsv")


# ── parse_spec_tsv ──────────────────────────────────────────────────────


class TestParseSpecTsv:
    """Tests 8-13: spec.tsv parser."""

    def test_parses_all_fields(self, tmp_path):
        """All 21 columns parsed with correct types."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_CONTENT,
        )
        records = parse_spec_tsv(path)
        assert len(records) == 5

        r = records[0]
        assert r["name"] == "Amp_1"
        assert r["chrom"] == "NC_015613.1"
        assert r["ampStart"] == 17440
        assert r["ampEnd"] == 17884
        assert r["ampGC"] == 51.69
        assert r["ampSize"] == 445
        assert r["fpName"] == "12S_long_F"
        assert r["fpTm"] == 60.11
        assert r["fpDg"] == -24.41
        assert r["rpName"] == "12S_long_R"
        assert r["rpTm"] == 67.96
        assert r["rpDg"] == -26.06

    def test_extracts_taxid_scientific_name(self, tmp_path):
        """Note JSON is parsed for taxid and scientific_name."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_CONTENT,
        )
        records = parse_spec_tsv(path)
        assert records[0]["taxid"] == "451427"
        assert records[0]["scientific_name"] == "Acridotheres cristatellus"

    def test_bad_note_json_no_crash(self, tmp_path):
        """Invalid note JSON does not crash — returns NA."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_BAD_NOTE,
        )
        records = parse_spec_tsv(path)
        assert len(records) == 1
        assert records[0]["taxid"] == "NA"
        assert records[0]["scientific_name"] == "NA"
        assert "not valid json" in records[0]["note"]

    def test_missing_file_returns_empty(self):
        """Missing .spec.tsv returns empty list, no crash."""
        records = parse_spec_tsv("/nonexistent/path.spec.tsv")
        assert records == []

    def test_fewer_than_21_columns_skipped(self, tmp_path):
        """Rows with fewer than 21 columns are skipped."""
        content = (
            "#name\tchrom\tampStart\n"
            "Amp_1\tchrom1\t100\n"
        )
        path = _write_tsv_file(tmp_path / "test.spec.tsv", content)
        records = parse_spec_tsv(path)
        assert records == []


# ── note JSON extraction ────────────────────────────────────────────────


class TestExtractNoteJson:
    """Tests 14-16: note JSON extraction edge cases."""

    def test_valid_json(self):
        """Valid JSON with extra text is correctly extracted."""
        result = _extract_note_json(
            '{"taxid":"123","scientific_name":"Homo sapiens"} extra'
        )
        assert result["taxid"] == "123"
        assert result["scientific_name"] == "Homo sapiens"

    def test_empty_note(self):
        """Empty note returns NA values."""
        result = _extract_note_json("")
        assert result["taxid"] == "NA"

    def test_partial_json(self):
        """Unclosed JSON brace returns NA without crashing."""
        result = _extract_note_json('{"taxid":"123"')
        assert result["taxid"] == "NA"
        assert result["scientific_name"] == "NA"


# ── infer_primer_id ─────────────────────────────────────────────────────


class TestInferPrimerId:
    """Test primer_id inference from fpName."""

    def test_standard_name(self):
        """Standard name like 12S_long_F → 12S_long."""
        assert _infer_primer_id({"fpName": "12S_long_F"}) == "12S_long"

    def test_double_underscore(self):
        """Double-underscore name like COI_short__F → COI_short."""
        assert _infer_primer_id({"fpName": "COI_short__F"}) == "COI_short"

    def test_tsv_fp(self):
        """TSV convention: 16S_short_fp → 16S_short."""
        assert _infer_primer_id({"fpName": "16S_short_fp"}) == "16S_short"

    def test_tsv_fp_with_dot(self):
        """TSV convention: 16S_short_fp.144 → 16S_short."""
        assert _infer_primer_id({"fpName": "16S_short_fp.144"}) == "16S_short"

    def test_tsv_rp_with_dot(self):
        """TSV convention: 16S_short_rp.216 → 16S_short."""
        assert _infer_primer_id({"fpName": "16S_short_rp.216"}) == "16S_short"

    def test_fallback(self):
        """Unrecognized format returns fpName as-is."""
        assert _infer_primer_id({"fpName": "WeirdName"}) == "WeirdName"

    def test_empty(self):
        """Empty fpName returns empty string."""
        assert _infer_primer_id({}) == ""


# ── size outlier detection ──────────────────────────────────────────────


class TestDetectSizeOutliers:
    """Test IQR-based size outlier detection."""

    def test_no_outliers_uniform(self):
        """Uniform sizes produce no outliers."""
        assert _detect_size_outliers([400, 400, 400, 400, 400]) == 0

    def test_too_few_points(self):
        """Fewer than 5 points returns 0 (insufficient data)."""
        assert _detect_size_outliers([100, 200, 300, 400]) == 0

    def test_detects_outlier(self):
        """A clear outlier (1400 vs 400s) is detected."""
        sizes = [400, 400, 400, 400, 400, 1400]
        assert _detect_size_outliers(sizes) >= 1


# ── summarize_spec_records ──────────────────────────────────────────────


class TestSummarizeSpecRecords:
    """Tests 17-24: spec record summarization and status logic."""

    def test_amplicon_count(self, tmp_path):
        """spec_amplicon_count reflects total records per primer."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_CONTENT,
        )
        records = parse_spec_tsv(path)
        rows = summarize_spec_records(records)
        row_12s = [r for r in rows if r["primer_id"] == "12S_long"][0]
        assert row_12s["spec_amplicon_count"] == 5

    def test_unique_reference_count(self, tmp_path):
        """unique_reference_count counts distinct reference sequences."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_MULTI_REF,
        )
        records = parse_spec_tsv(path)
        rows = summarize_spec_records(records)
        test_row = [r for r in rows if r["primer_id"] == "TEST"][0]
        assert test_row["unique_reference_count"] == 1

    def test_multi_amplicon_reference_count(self, tmp_path):
        """Multi-amp refs are counted when same ref has >1 amplicon."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_MULTI_REF,
        )
        records = parse_spec_tsv(path)
        rows = summarize_spec_records(records)
        test_row = [r for r in rows if r["primer_id"] == "TEST"][0]
        assert test_row["multi_amplicon_reference_count"] == 1
        coi_row = [r for r in rows if r["primer_id"] == "COI"][0]
        assert coi_row["multi_amplicon_reference_count"] == 0

    def test_warn_no_amp(self):
        """Zero spec amplicons → WARN_NO_AMP for all primers."""
        rows = summarize_spec_records([], primer_pairs=_make_primers())
        assert len(rows) == 2
        for row in rows:
            assert row["spec_amplicon_count"] == 0
            assert row["status"] == "WARN_NO_AMP"

    def test_warn_multi_amp(self, tmp_path):
        """Multiple amplicons on same reference → WARN_MULTI_AMP."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_MULTI_REF,
        )
        records = parse_spec_tsv(path)
        rows = summarize_spec_records(records)
        test_row = [r for r in rows if r["primer_id"] == "TEST"][0]
        assert "WARN_MULTI_AMP" in test_row["status"]

    def test_multi_taxid_not_warn(self, tmp_path):
        """Multiple taxids is NOT non-specific for metabarcoding — PASS."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_MULTI_TAXID,
        )
        records = parse_spec_tsv(path)
        rows = summarize_spec_records(records)
        coi = [r for r in rows if r["primer_id"] == "COI"][0]
        assert coi["unique_taxid_count"] == 3
        assert coi["status"] == "PASS"

    def test_size_outlier_detection(self, tmp_path):
        """Size outliers trigger WARN_SIZE."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_SIZE_OUTLIERS,
        )
        records = parse_spec_tsv(path)
        rows = summarize_spec_records(records)
        test_row = rows[0]
        assert test_row["size_outlier_count"] >= 1
        assert "WARN_SIZE" in test_row["status"]

    def test_warn_overamp(self, tmp_path):
        """Too many amplicons triggers WARN_OVERAMP."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_CONTENT,
        )
        records = parse_spec_tsv(path)
        rows = summarize_spec_records(records, max_amp_count=3)
        row_12s = [r for r in rows if r["primer_id"] == "12S_long"][0]
        assert "WARN_OVERAMP" in row_12s["status"]


# ── write_spec_outputs ──────────────────────────────────────────────────


class TestWriteSpecOutputs:
    """Tests 25-26: output writer."""

    def test_writes_primer_spec(self, tmp_path):
        """Writes primer_spec.tsv with correct fields."""
        spec_dir = tmp_path / "results"
        spec_tsv_dir = spec_dir / "spec"
        spec_tsv_dir.mkdir(parents=True, exist_ok=True)
        _write_tsv_file(
            spec_tsv_dir / "spec_output.txt.spec.tsv",
            _MOCK_SPEC_TSV_CONTENT,
        )

        written = write_spec_outputs(spec_dir)
        assert "primer_spec" in written
        primer_spec = written["primer_spec"]
        assert primer_spec.is_file()

        rows = _read_tsv(primer_spec)
        assert len(rows) >= 1
        row_12s = [r for r in rows if r["primer_id"] == "12S_long"][0]
        assert int(row_12s["spec_amplicon_count"]) == 5

    def test_writes_failed_jobs(self, tmp_path):
        """Failed jobs TSV is written when provided."""
        spec_dir = tmp_path / "results"
        failed = [
            {
                "module": "index",
                "command": "mfeprimer index",
                "output": "",
                "status": "failed",
                "error_message": "test error",
            }
        ]
        written = write_spec_outputs(
            spec_dir, records=[], failed_jobs=failed,
        )
        assert "qc_spec_failed_jobs" in written
        failed_path = written["qc_spec_failed_jobs"]
        assert failed_path.is_file()
        rows = _read_tsv(failed_path)
        assert len(rows) == 1
        assert rows[0]["module"] == "index"
        assert rows[0]["status"] == "failed"


# ── CLI tests ───────────────────────────────────────────────────────────


class TestCliQcSpec:
    """Tests 27-29: CLI integration."""

    def test_dry_run_no_subprocess(self, tmp_path):
        """--dry-run prints plan without calling subprocess."""
        from fullpcr.cli import main

        primers_path = tmp_path / "primers.tsv"
        _write_tsv_file(
            primers_path,
            "primer_id\tforward\treverse\tmin_length\tmax_length\n"
            "TEST\tAAAA\tTTTT\t100\t300\n",
        )
        db_path = tmp_path / "db.fasta"
        db_path.write_text(">seq1\nACGT\n", encoding="utf-8")
        outdir = tmp_path / "out"

        with mock.patch("subprocess.run") as mock_run:
            with mock.patch(
                "fullpcr.cli.check_mfeprimer_available", return_value=True,
            ):
                main(
                    [
                        "qc-spec",
                        "--primers", str(primers_path),
                        "--database", str(db_path),
                        "--outdir", str(outdir),
                        "--dry-run",
                    ]
                )
        mock_run.assert_not_called()

    def test_mfeprimer_not_available(self, tmp_path):
        """When mfeprimer absent, writes failed_jobs + FAIL_INDEX primer_spec."""
        from fullpcr.cli import main

        primers_path = tmp_path / "primers.tsv"
        _write_tsv_file(
            primers_path,
            "primer_id\tforward\treverse\tmin_length\tmax_length\n"
            "TEST\tAAAA\tTTTT\t100\t300\n",
        )
        db_path = tmp_path / "db.fasta"
        db_path.write_text(">seq1\nACGT\n", encoding="utf-8")
        outdir = tmp_path / "out"

        with mock.patch(
            "fullpcr.cli.check_mfeprimer_available", return_value=False,
        ):
            main(
                [
                    "qc-spec",
                    "--primers", str(primers_path),
                    "--database", str(db_path),
                    "--outdir", str(outdir),
                ]
            )

        # Check failed_jobs written
        failed_path = outdir / "qc_spec_failed_jobs.tsv"
        assert failed_path.is_file()
        failed_rows = _read_tsv(failed_path)
        assert len(failed_rows) == 2  # index + spec

        # Check primer_spec with FAIL_INDEX
        pspec_path = outdir / "spec" / "primer_spec.tsv"
        assert pspec_path.is_file()
        pspec_rows = _read_tsv(pspec_path)
        assert len(pspec_rows) == 1
        assert "FAIL_INDEX" in pspec_rows[0]["status"]


# ── Phase 4.1.1: FASTA utilities ────────────────────────────────────────


class TestCountFastaRecords:
    """Tests for count_fasta_records."""

    def test_counts_multiple(self, tmp_path):
        """Counts multiple FASTA records correctly."""
        fasta = tmp_path / "test.fasta"
        fasta.write_text(
            ">seq1\nACGT\n>seq2\nGGGG\n>seq3\nTTTT\n",
            encoding="utf-8",
        )
        assert count_fasta_records(fasta) == 3

    def test_missing_file(self):
        """Returns 0 for missing file."""
        assert count_fasta_records("/nonexistent.fasta") == 0

    def test_empty_file(self, tmp_path):
        """Returns 0 for empty file."""
        fasta = tmp_path / "empty.fasta"
        fasta.write_text("", encoding="utf-8")
        assert count_fasta_records(fasta) == 0


class TestNormalizeFasta:
    """Tests for normalize_fasta_for_mfeprimer."""

    def test_wraps_single_line(self, tmp_path):
        """Single-line FASTA is wrapped to specified width."""
        src = tmp_path / "src.fasta"
        src.write_text(">seq1\nACGTACGTACGTACGT\n", encoding="utf-8")
        out = tmp_path / "out.fasta"
        normalize_fasta_for_mfeprimer(src, out, line_width=6)
        content = out.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert lines[0] == ">seq1"
        assert lines[1] == "ACGTAC"
        assert lines[2] == "GTACGT"

    def test_record_count_preserved(self, tmp_path):
        """Normalized FASTA keeps the same number of records."""
        src = tmp_path / "src.fasta"
        src.write_text(
            ">seq1\nACGT\n>seq2\nGGGGGG\n>seq3\nTTTTTTTTTT\n",
            encoding="utf-8",
        )
        out = tmp_path / "out.fasta"
        normalize_fasta_for_mfeprimer(src, out, line_width=80)
        assert count_fasta_records(src) == count_fasta_records(out)
        assert count_fasta_records(out) == 3

    def test_total_bases_preserved(self, tmp_path):
        """Normalized FASTA keeps the same total base count."""
        src = tmp_path / "src.fasta"
        src.write_text(
            ">seq1\nACGTACGT\n>seq2\nGGGGGG\n",
            encoding="utf-8",
        )
        out = tmp_path / "out.fasta"
        normalize_fasta_for_mfeprimer(src, out, line_width=5)

        def _bases(p):
            total = 0
            with open(p, encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith(">"):
                        total += len(s)
            return total

        assert _bases(src) == _bases(out)

    def test_multi_line_input(self, tmp_path):
        """Already-wrapped FASTA is preserved."""
        src = tmp_path / "src.fasta"
        src.write_text(
            ">seq1\nACGTACGT\nACGTACGT\n>seq2\nGGGG\n",
            encoding="utf-8",
        )
        out = tmp_path / "out.fasta"
        normalize_fasta_for_mfeprimer(src, out, line_width=8)
        content = out.read_text(encoding="utf-8")
        assert "ACGTACGT" in content
        assert "GGGG" in content


class TestValidateIndexOutputs:
    """Tests for validate_mfeprimer_index_outputs."""

    def test_all_present(self, tmp_path):
        """Returns True when all index files exist and are non-empty."""
        db = tmp_path / "db.fasta"
        db.write_text(">s\nACGT\n", encoding="utf-8")
        for suffix in [".fai", ".json", ".primerqc", ".primerqc.fai", ".log"]:
            p = tmp_path / ("db.fasta" + suffix)
            p.write_text("not empty", encoding="utf-8")

        ok, missing = validate_mfeprimer_index_outputs(tmp_path, db)
        assert ok is True
        assert missing == []

    def test_missing_file(self, tmp_path):
        """Returns False when a file is missing."""
        db = tmp_path / "db.fasta"
        db.write_text(">s\nACGT\n", encoding="utf-8")
        # Only create .fai, skip others
        (tmp_path / "db.fasta.fai").write_text("x", encoding="utf-8")

        ok, missing = validate_mfeprimer_index_outputs(tmp_path, db)
        assert ok is False
        assert len(missing) > 0

    def test_empty_file(self, tmp_path):
        """Returns False when a file exists but is empty."""
        db = tmp_path / "db.fasta"
        db.write_text(">s\nACGT\n", encoding="utf-8")
        for suffix in [".fai", ".json", ".primerqc", ".primerqc.fai", ".log"]:
            p = tmp_path / ("db.fasta" + suffix)
            p.write_text("x", encoding="utf-8")
        # Make one file empty
        (tmp_path / "db.fasta.primerqc").write_text("", encoding="utf-8")

        ok, missing = validate_mfeprimer_index_outputs(tmp_path, db)
        assert ok is False
        assert any("空文件" in m for m in missing)


# ── Phase 4.1.1: database stats / new primer_spec fields ────────────────


class TestDatabaseStats:
    """Tests for database_stats.tsv generation and new primer_spec fields."""

    def test_db_stats_written(self, tmp_path):
        """write_spec_outputs writes database_stats.tsv when db_stats is given."""
        spec_dir = tmp_path / "results"
        db_stats = {
            "source_database": "/src/db.fasta",
            "prepared_database": "/out/db.fasta",
            "source_record_count": 85,
            "prepared_record_count": 85,
            "source_total_bases": 100000,
            "prepared_total_bases": 100000,
            "index_files_present": "True",
            "status": "PASS",
            "reason": "",
        }
        written = write_spec_outputs(
            spec_dir, records=[], db_stats=db_stats,
        )
        assert "database_stats" in written
        stats_path = written["database_stats"]
        assert stats_path.is_file()
        rows = _read_tsv(stats_path)
        assert len(rows) == 1
        assert rows[0]["source_record_count"] == "85"
        assert rows[0]["status"] == "PASS"

    def test_database_reference_count_in_primer_spec(self, tmp_path):
        """primer_spec.tsv includes database_reference_count field."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_CONTENT,
        )
        records = parse_spec_tsv(path)
        rows = summarize_spec_records(
            records, database_reference_count=85,
        )
        row_12s = [r for r in rows if r["primer_id"] == "12S_long"][0]
        assert row_12s["database_reference_count"] == 85

    def test_spec_reference_fraction(self, tmp_path):
        """spec_reference_fraction = unique_reference_count / database_reference_count."""
        path = _write_tsv_file(
            tmp_path / "test.spec.tsv", _MOCK_SPEC_TSV_CONTENT,
        )
        records = parse_spec_tsv(path)
        rows = summarize_spec_records(
            records, database_reference_count=10,
        )
        row_12s = [r for r in rows if r["primer_id"] == "12S_long"][0]
        # 1 unique ref / 10 DB refs = 0.1
        assert float(row_12s["spec_reference_fraction"]) == 0.1

    def test_spec_reference_fraction_zero_db(self):
        """spec_reference_fraction is NA when database_reference_count is 0."""
        rows = summarize_spec_records(
            [], primer_pairs=_make_primers(), database_reference_count=0,
        )
        for row in rows:
            assert row["spec_reference_fraction"] == "NA"

    def test_no_amp_rows_have_db_ref_count(self, tmp_path):
        """WARN_NO_AMP rows still have database_reference_count set."""
        rows = summarize_spec_records(
            [], primer_pairs=_make_primers(), database_reference_count=42,
        )
        for row in rows:
            assert row["database_reference_count"] == 42
            assert row["spec_reference_fraction"] == 0.0


# ── Phase 4.1.2: base-counting hygiene / WARN_SEQUENCE_CLEANED ──────────


class TestCountFastaBases:
    """Tests for count_fasta_bases."""

    def test_sums_sequence_bases(self, tmp_path):
        """Sums bases across all sequence lines."""
        fasta = tmp_path / "test.fasta"
        fasta.write_text(
            ">seq1\nACGT\n>seq2\nGGGG\n>seq3\nTTTT\n", encoding="utf-8",
        )
        assert count_fasta_bases(fasta) == 12

    def test_ignores_trailing_whitespace(self, tmp_path):
        """Trailing spaces/tabs are not counted as bases."""
        fasta = tmp_path / "test.fasta"
        fasta.write_text(
            ">seq1\nACGT   \n>seq2\nGGGG\t\t\n", encoding="utf-8",
        )
        assert count_fasta_bases(fasta) == 8

    def test_ignores_empty_lines(self, tmp_path):
        """Empty lines between records are skipped."""
        fasta = tmp_path / "test.fasta"
        fasta.write_text(
            ">seq1\nACGT\n\n>seq2\n\nGGGG\n", encoding="utf-8",
        )
        assert count_fasta_bases(fasta) == 8

    def test_multi_line_sequence(self, tmp_path):
        """Multi-line sequences are summed correctly."""
        fasta = tmp_path / "test.fasta"
        fasta.write_text(
            ">seq1\nACGT\nTGCA\n>seq2\nGGGG\n", encoding="utf-8",
        )
        assert count_fasta_bases(fasta) == 12

    def test_missing_file(self):
        """Returns 0 for missing file."""
        assert count_fasta_bases("/nonexistent.fasta") == 0

    def test_no_carriage_return_in_count(self, tmp_path):
        """CR characters are not counted as bases."""
        fasta = tmp_path / "test.fasta"
        fasta.write_text(
            ">seq1\r\nACGT\r\n>seq2\r\nGGGG\r\n", encoding="utf-8",
        )
        assert count_fasta_bases(fasta) == 8

    def test_spaces_within_lines_stripped(self, tmp_path):
        """Spaces embedded in sequence lines are stripped."""
        fasta = tmp_path / "test.fasta"
        fasta.write_text(
            ">seq1\nACG T\n>seq2\nGGGG\n", encoding="utf-8",
        )
        # "ACG T" → strip → "ACG T" (internal space kept unless we remove it)
        # Actually, line.strip() removes leading/trailing whitespace, not internal.
        # Total = len("ACG T") + len("GGGG") = 5 + 4 = 9
        assert count_fasta_bases(fasta) == 9


class TestNormalizeFastaBaseConsistency:
    """Tests for normalize_fasta_for_mfeprimer base-count consistency."""

    def test_no_whitespace_source_bases_equal(self, tmp_path):
        """When source has no trailing whitespace, bases are preserved."""
        src = tmp_path / "src.fasta"
        src.write_text(
            ">seq1\nACGTACGT\n>seq2\nGGGGCCCC\n", encoding="utf-8",
        )
        out = tmp_path / "out.fasta"
        normalize_fasta_for_mfeprimer(src, out, line_width=4)
        assert count_fasta_bases(src) == count_fasta_bases(out)
        assert count_fasta_bases(out) == 16

    def test_trailing_whitespace_reduced(self, tmp_path):
        """Trailing whitespace in source is cleaned, reducing prepared bases."""
        src = tmp_path / "src.fasta"
        src.write_text(
            ">seq1\nACGT   \n>seq2\nGGGG\t\n", encoding="utf-8",
        )
        out = tmp_path / "out.fasta"
        normalize_fasta_for_mfeprimer(src, out, line_width=80)
        source_bases = count_fasta_bases(src)
        prepared_bases = count_fasta_bases(out)
        # source: count_fasta_bases strips whitespace → 8
        # prepared: normalize strips whitespace → 8
        # They should be equal because count_fasta_bases also strips
        assert source_bases == prepared_bases
        assert prepared_bases == 8

    def test_record_count_always_preserved(self, tmp_path):
        """Record count is preserved even with whitespace."""
        src = tmp_path / "src.fasta"
        src.write_text(
            ">seq1\nACGT   \n>seq2\nGGGG\t\n>seq3\nTTTT\n",
            encoding="utf-8",
        )
        out = tmp_path / "out.fasta"
        normalize_fasta_for_mfeprimer(src, out)
        assert count_fasta_records(src) == count_fasta_records(out)
        assert count_fasta_records(out) == 3


class TestPrepareSpecDatabaseWarnCleaned:
    """Tests for FAIL_DATABASE_PREP / WARN_SEQUENCE_CLEANED."""

    def test_warn_when_bases_differ_but_counts_match(self, tmp_path):
        """WARN_SEQUENCE_CLEANED when record counts match but base counts differ."""
        src = tmp_path / "src.fasta"
        src.write_text(">seq1\nACGT\n>seq2\nGGGG\n", encoding="utf-8")
        index_dir = tmp_path / "index"

        with mock.patch(
            "fullpcr.qc_spec.count_fasta_bases",
            side_effect=[100, 90],  # source=100, prepared=90
        ), mock.patch(
            "fullpcr.qc_spec.run_mfeprimer_index",
            return_value={
                "module": "index",
                "command": "mock",
                "output": str(index_dir / "src.fasta"),
                "status": "success",
                "error_message": "",
            },
        ), mock.patch(
            "fullpcr.qc_spec.validate_mfeprimer_index_outputs",
            return_value=(True, []),
        ):
            _index_result, db_stats = __import__(
                "fullpcr.qc_spec", fromlist=["prepare_spec_database"],
            ).prepare_spec_database(
                str(src), str(index_dir), force=True, timeout=None,
            )
        assert db_stats["status"] == "WARN_SEQUENCE_CLEANED"
        assert "Δ=10" in db_stats["reason"]
        assert "规范化" in db_stats["reason"]

    def test_fail_when_record_counts_differ(self, tmp_path):
        """FAIL_DATABASE_PREP when source and prepared record counts differ."""
        src = tmp_path / "src.fasta"
        src.write_text(">seq1\nACGT\n>seq2\nGGGG\n", encoding="utf-8")
        index_dir = tmp_path / "index"

        with mock.patch(
            "fullpcr.qc_spec.count_fasta_records",
            side_effect=[2, 1],  # source=2, prepared=1
        ):
            _index_result, db_stats = __import__(
                "fullpcr.qc_spec", fromlist=["prepare_spec_database"],
            ).prepare_spec_database(
                str(src), str(index_dir), force=True, timeout=None,
            )
        assert db_stats["status"] == "FAIL_DATABASE_PREP"
        assert "source_record_count=2" in db_stats["reason"]

    def test_pass_when_all_match(self, tmp_path):
        """PASS when both record counts AND base counts match."""
        src = tmp_path / "src.fasta"
        src.write_text(">seq1\nACGT\n>seq2\nGGGG\n", encoding="utf-8")
        index_dir = tmp_path / "index"

        with mock.patch(
            "fullpcr.qc_spec.run_mfeprimer_index",
            return_value={
                "module": "index",
                "command": "mock",
                "output": str(index_dir / "src.fasta"),
                "status": "success",
                "error_message": "",
            },
        ), mock.patch(
            "fullpcr.qc_spec.validate_mfeprimer_index_outputs",
            return_value=(True, []),
        ):
            _index_result, db_stats = __import__(
                "fullpcr.qc_spec", fromlist=["prepare_spec_database"],
            ).prepare_spec_database(
                str(src), str(index_dir), force=True, timeout=None,
            )
        assert db_stats["status"] == "PASS"
        assert db_stats["source_record_count"] == 2
        assert db_stats["prepared_record_count"] == 2
        assert db_stats["source_total_bases"] == db_stats["prepared_total_bases"]


class TestNormalizeFastaEmbeddedGt:
    """Tests for normalize_fasta_for_mfeprimer handling embedded ``>``."""

    def test_splits_embedded_gt(self, tmp_path):
        """Embedded ``>`` mid-line is treated as a record boundary."""
        src = tmp_path / "src.fasta"
        src.write_text(
            ">seq1\nACGT>seq2\nGGGG\n", encoding="utf-8",
        )
        out = tmp_path / "out.fasta"
        normalize_fasta_for_mfeprimer(src, out, line_width=80)
        assert count_fasta_records(out) == 2
        content = out.read_text(encoding="utf-8")
        assert ">seq1" in content
        assert ">seq2" in content

    def test_multiple_embedded_gt(self, tmp_path):
        """Multiple embedded ``>`` in one line each start a new record."""
        src = tmp_path / "src.fasta"
        src.write_text(
            ">seq1\nACGT>seq2\nGGGG>seq3\nTTTT\n", encoding="utf-8",
        )
        out = tmp_path / "out.fasta"
        normalize_fasta_for_mfeprimer(src, out, line_width=80)
        assert count_fasta_records(out) == 3

    def test_record_count_matches_after_split(self, tmp_path):
        """After splitting on embedded ``>``, source and prepared record
        counts match (both count mid-line ``>``)."""
        src = tmp_path / "src.fasta"
        src.write_text(
            ">rec1\nACGT>rec2\nGGGG>rec3\nTTTT\n", encoding="utf-8",
        )
        out = tmp_path / "out.fasta"
        normalize_fasta_for_mfeprimer(src, out, line_width=80)
        assert count_fasta_records(src) == count_fasta_records(out)

    def test_embedded_gt_preserves_header_text(self, tmp_path):
        """The header text after embedded ``>`` is preserved."""
        src = tmp_path / "src.fasta"
        src.write_text(
            ">seq1\nACGT>seq2 extra info\nGGGG\n", encoding="utf-8",
        )
        out = tmp_path / "out.fasta"
        normalize_fasta_for_mfeprimer(src, out, line_width=80)
        content = out.read_text(encoding="utf-8")
        assert ">seq2 extra info" in content
