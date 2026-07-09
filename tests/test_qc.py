"""Tests for fullpcr.qc — thermo / dimer / hairpin parsing and QC summary."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

from fullpcr.qc import (
    build_primer_qc_summary,
    parse_dimer_output,
    parse_hairpin_output,
    parse_primer_name,
    parse_thermo_output,
    write_qc_outputs,
)

# ── helpers ────────────────────────────────────────────────────────────────


def _read_tsv(path: Path) -> list[dict]:
    """Read a TSV file into a list of dicts."""
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _make_thermo_raw() -> str:
    """Build a realistic thermo_raw.tsv content string."""
    return (
        "# Name\tSeq(5->3)\tSize\tGC\tTm\tDeltaG\t"
        "ReverseComplementSeq(5->3)\tNote\n"
        "COI_short_F\tGGTCAACAAATCATAAAGATATTGG\t25\t32.00\t55.28\t"
        "-21.67\tCCAATATCTTTATGATTTGTTGACC\t\n"
        "COI_short_R\tTAAACTTCAGGGTGACCAAAAAATCA\t26\t34.62\t60.17\t"
        "-24.70\tTGATTTTTTGGTCACCCTGAAGTTTA\t\n"
        "16S_short_F\tGACGAGAAGACCCTATGGAGC\t21\t57.14\t60.17\t"
        "-22.60\tGCTCCATAGGGTCTTCTCGTC\t\n"
        "16S_short_R\tCGCTGTTATCCCTAGGGTAACT\t22\t50.00\t59.56\t"
        "-22.55\tAGTTACCCTAGGGATAACAGCG\t\n"
    )


def _make_dimer_raw_zero() -> str:
    """Build a dimer_raw.txt with 0 dimers."""
    return (
        "MFEprimer-3.0 Dimer Reports (2026-07-09 14:21:24)\n"
        "\n"
        "Primer ID                      Sequence (5'-->3')                    "
        "Length     GC      Tm      Dg     \n"
        "                                                                      "
        "(bp)      (%)    (°C)  (kcal/mol)\n"
        "\n"
        "COI_short_F                    GGTCAACAAATCATAAAGATATTGG                 "
        "25   32.00   55.28    -21.67\n"
        "COI_short_R                    TAAACTTCAGGGTGACCAAAAAATCA                "
        "26   34.62   60.17    -24.70\n"
        "\n"
        "\n"
        "Dimer List (0)\n"
        "\n"
        "No dimer found.\n"
        "\n"
        "\n"
        "Parameters\n"
        "\n"
        "                   Primer file: primer_input.fasta\n"
    )


def _make_dimer_raw_with_dimers() -> str:
    """Build a dimer_raw.txt with dimers present (simulated)."""
    return (
        "MFEprimer-3.0 Dimer Reports (2026-07-09 14:21:24)\n"
        "\n"
        "Primer ID                      Sequence (5'-->3')                    "
        "Length     GC      Tm      Dg     \n"
        "                                                                      "
        "(bp)      (%)    (°C)  (kcal/mol)\n"
        "\n"
        "COI_short_F                    GGTCAACAAATCATAAAGATATTGG                 "
        "25   32.00   55.28    -21.67\n"
        "COI_short_R                    TAAACTTCAGGGTGACCAAAAAATCA                "
        "26   34.62   60.17    -24.70\n"
        "\n"
        "\n"
        "Dimer List (2)\n"
        "\n"
        "Primer A: COI_short_F\n"
        "Primer B: COI_short_R\n"
        "Score: 7\n"
        "Delta G: -5.2 kcal/mol\n"
        "3' end dimer: Yes\n"
        "\n"
        "Primer A: COI_short_F\n"
        "Primer B: COI_short_F\n"
        "Score: 5\n"
        "Delta G: -4.1 kcal/mol\n"
        "3' end dimer: No\n"
        "\n"
        "\n"
        "Parameters\n"
        "\n"
        "                   Primer file: primer_input.fasta\n"
    )


def _make_hairpin_raw_zero() -> str:
    """Build a hairpin_raw.txt with 0 hairpins."""
    return (
        "MFEprimer-3.0 Hairpin Reports (2026-07-09 14:21:24)\n"
        "\n"
        "Primer ID                      Sequence (5'-->3')                    "
        "Length     GC      Tm      Dg     \n"
        "                                                                      "
        "(bp)      (%)    (°C)  (kcal/mol)\n"
        "\n"
        "COI_short_F                    GGTCAACAAATCATAAAGATATTGG                 "
        "25   32.00   55.28    -21.67\n"
        "COI_short_R                    TAAACTTCAGGGTGACCAAAAAATCA                "
        "26   34.62   60.17    -24.70\n"
        "\n"
        "\n"
        "Hairpin List (0)\n"
        "\n"
        "No hairpins found.\n"
        "\n"
        "\n"
        "Parameters\n"
        "\n"
        "                   Primer file: primer_input.fasta\n"
    )


def _make_hairpin_raw_with_hairpins() -> str:
    """Build a hairpin_raw.txt with hairpins present (simulated)."""
    return (
        "MFEprimer-3.0 Hairpin Reports (2026-07-09 14:21:24)\n"
        "\n"
        "Primer ID                      Sequence (5'-->3')                    "
        "Length     GC      Tm      Dg     \n"
        "                                                                      "
        "(bp)      (%)    (°C)  (kcal/mol)\n"
        "\n"
        "COI_short_F                    GGTCAACAAATCATAAAGATATTGG                 "
        "25   32.00   55.28    -21.67\n"
        "COI_short_R                    TAAACTTCAGGGTGACCAAAAAATCA                "
        "26   34.62   60.17    -24.70\n"
        "\n"
        "\n"
        "Hairpin List (1)\n"
        "\n"
        "Primer: COI_short_F\n"
        "Score: 8\n"
        "Delta G: -6.3 kcal/mol\n"
        "\n"
        "\n"
        "Parameters\n"
        "\n"
        "                   Primer file: primer_input.fasta\n"
    )


# ── parse_primer_name ─────────────────────────────────────────────────────


class TestParsePrimerName:
    def test_single_underscore_f(self):
        pid, side = parse_primer_name("COI_short_F")
        assert pid == "COI_short"
        assert side == "F"

    def test_single_underscore_r(self):
        pid, side = parse_primer_name("COI_short_R")
        assert pid == "COI_short"
        assert side == "R"

    def test_double_underscore_f(self):
        pid, side = parse_primer_name("COI_short__F")
        assert pid == "COI_short"
        assert side == "F"

    def test_double_underscore_r(self):
        pid, side = parse_primer_name("COI_short__R")
        assert pid == "COI_short"
        assert side == "R"

    def test_complex_id_with_underscores(self):
        pid, side = parse_primer_name("16S_short_F")
        assert pid == "16S_short"
        assert side == "F"

    def test_no_side_suffix(self):
        pid, side = parse_primer_name("SOME_PRIMER")
        assert pid == "SOME_PRIMER"
        assert side == "UNKNOWN"

    def test_empty_string(self):
        pid, side = parse_primer_name("")
        assert pid == ""
        assert side == "UNKNOWN"


# ── parse_thermo_output ───────────────────────────────────────────────────


class TestParseThermoOutput:
    def test_normal_parse(self, tmp_path):
        raw = tmp_path / "thermo_raw.tsv"
        raw.write_text(_make_thermo_raw(), encoding="utf-8")

        rows = parse_thermo_output(raw)
        assert len(rows) == 4

        fwd = rows[0]
        assert fwd["primer_name"] == "COI_short_F"
        assert fwd["primer_id"] == "COI_short"
        assert fwd["primer_side"] == "F"
        assert fwd["sequence"] == "GGTCAACAAATCATAAAGATATTGG"
        assert fwd["size"] == 25
        assert fwd["gc"] == pytest.approx(32.00)
        assert fwd["tm"] == pytest.approx(55.28)
        assert fwd["delta_g"] == pytest.approx(-21.67)

    def test_hash_header_parsed(self, tmp_path):
        """Header starting with '# Name' is skipped, data rows parsed."""
        raw = tmp_path / "thermo_raw.tsv"
        raw.write_text(_make_thermo_raw(), encoding="utf-8")

        rows = parse_thermo_output(raw)
        assert len(rows) == 4
        for r in rows:
            assert not r["primer_name"].startswith("#")

    def test_missing_file_returns_empty(self, tmp_path):
        rows = parse_thermo_output(tmp_path / "nonexistent.tsv")
        assert rows == []

    def test_empty_file(self, tmp_path):
        raw = tmp_path / "empty.tsv"
        raw.write_text("", encoding="utf-8")
        rows = parse_thermo_output(raw)
        assert rows == []


# ── parse_dimer_output ────────────────────────────────────────────────────


class TestParseDimerOutput:
    def test_zero_dimers(self, tmp_path):
        raw = tmp_path / "dimer_raw.txt"
        raw.write_text(_make_dimer_raw_zero(), encoding="utf-8")

        rows = parse_dimer_output(raw)
        primer_ids = {r["primer_id"] for r in rows}
        assert "COI_short" in primer_ids
        for r in rows:
            assert r["dimer_count"] == 0
            assert r["parse_status"] == "OK"

    def test_dimer_list_count_extracted(self, tmp_path):
        raw = tmp_path / "dimer_raw.txt"
        raw.write_text(_make_dimer_raw_with_dimers(), encoding="utf-8")

        rows = parse_dimer_output(raw)
        for r in rows:
            assert r["dimer_count"] == 2
            assert r["parse_status"] == "PARSE_WARN"
            assert r["raw_block"] != ""

    def test_missing_file_returns_empty(self, tmp_path):
        rows = parse_dimer_output(tmp_path / "nonexistent.txt")
        assert rows == []


# ── parse_hairpin_output ──────────────────────────────────────────────────


class TestParseHairpinOutput:
    def test_zero_hairpins(self, tmp_path):
        raw = tmp_path / "hairpin_raw.txt"
        raw.write_text(_make_hairpin_raw_zero(), encoding="utf-8")

        rows = parse_hairpin_output(raw)
        assert len(rows) >= 2
        for r in rows:
            assert r["hairpin_count"] == 0
            assert r["parse_status"] == "OK"

    def test_hairpin_list_count_extracted(self, tmp_path):
        raw = tmp_path / "hairpin_raw.txt"
        raw.write_text(_make_hairpin_raw_with_hairpins(), encoding="utf-8")

        rows = parse_hairpin_output(raw)
        for r in rows:
            assert r["hairpin_count"] == 1
            assert r["parse_status"] == "PARSE_WARN"
            assert r["raw_block"] != ""

    def test_missing_file_returns_empty(self, tmp_path):
        rows = parse_hairpin_output(tmp_path / "nonexistent.txt")
        assert rows == []


# ── build_primer_qc_summary ───────────────────────────────────────────────


class TestBuildPrimerQcSummary:
    def _setup_qc_dir(self, qc_dir: Path) -> None:
        """Create all needed raw files in qc_dir."""
        (qc_dir / "thermo").mkdir(parents=True)
        (qc_dir / "dimer").mkdir(parents=True)
        (qc_dir / "hairpin").mkdir(parents=True)

        (qc_dir / "thermo" / "thermo_raw.tsv").write_text(
            _make_thermo_raw(), encoding="utf-8"
        )
        (qc_dir / "dimer" / "dimer_raw.txt").write_text(
            _make_dimer_raw_zero(), encoding="utf-8"
        )
        (qc_dir / "hairpin" / "hairpin_raw.txt").write_text(
            _make_hairpin_raw_zero(), encoding="utf-8"
        )

    def test_normal_summary(self, tmp_path):
        qc_dir = tmp_path / "qc_results"
        self._setup_qc_dir(qc_dir)

        rows = build_primer_qc_summary(qc_dir)
        assert len(rows) >= 2

        coi = next(r for r in rows if r["primer_id"] == "COI_short")
        assert coi["forward_tm"] == pytest.approx(55.28)
        assert coi["reverse_tm"] == pytest.approx(60.17)
        assert coi["tm_difference"] == pytest.approx(4.89)
        assert coi["dimer_count"] == 0
        assert coi["forward_hairpin_count"] == 0
        assert coi["reverse_hairpin_count"] == 0

    def test_pass_status(self, tmp_path):
        qc_dir = tmp_path / "qc_results"
        self._setup_qc_dir(qc_dir)

        rows = build_primer_qc_summary(qc_dir)
        coi = next(r for r in rows if r["primer_id"] == "COI_short")
        assert coi["qc_status"] == "PASS"
        assert coi["qc_reason"] == ""

    def test_warn_tm_diff(self, tmp_path):
        """Tm difference > 5°C triggers WARN_TM_DIFF."""
        qc_dir = tmp_path / "qc_results"
        (qc_dir / "thermo").mkdir(parents=True)
        (qc_dir / "dimer").mkdir(parents=True)
        (qc_dir / "hairpin").mkdir(parents=True)

        thermo = (
            "# Name\tSeq(5->3)\tSize\tGC\tTm\tDeltaG\t"
            "ReverseComplementSeq(5->3)\tNote\n"
            "TEST_F\tGGTCAACAAATCATAAAGATATTGG\t25\t32.00\t50.00\t"
            "-21.67\tCCAATATCTTTATGATTTGTTGACC\t\n"
            "TEST_R\tTAAACTTCAGGGTGACCAAAAAATCA\t26\t34.62\t62.00\t"
            "-24.70\tTGATTTTTTGGTCACCCTGAAGTTTA\t\n"
        )
        (qc_dir / "thermo" / "thermo_raw.tsv").write_text(
            thermo, encoding="utf-8"
        )
        (qc_dir / "dimer" / "dimer_raw.txt").write_text(
            _make_dimer_raw_zero(), encoding="utf-8"
        )
        (qc_dir / "hairpin" / "hairpin_raw.txt").write_text(
            _make_hairpin_raw_zero(), encoding="utf-8"
        )

        rows = build_primer_qc_summary(qc_dir)
        test_row = next(r for r in rows if r["primer_id"] == "TEST")
        assert test_row["tm_difference"] == pytest.approx(12.00)
        assert "WARN_TM_DIFF" in test_row["qc_status"]
        assert "Tm 差异" in test_row["qc_reason"]

    def test_warn_dimer(self, tmp_path):
        """dimer_count > 0 triggers WARN_DIMER."""
        qc_dir = tmp_path / "qc_results"
        (qc_dir / "thermo").mkdir(parents=True)
        (qc_dir / "dimer").mkdir(parents=True)
        (qc_dir / "hairpin").mkdir(parents=True)

        (qc_dir / "thermo" / "thermo_raw.tsv").write_text(
            _make_thermo_raw(), encoding="utf-8"
        )
        (qc_dir / "dimer" / "dimer_raw.txt").write_text(
            _make_dimer_raw_with_dimers(), encoding="utf-8"
        )
        (qc_dir / "hairpin" / "hairpin_raw.txt").write_text(
            _make_hairpin_raw_zero(), encoding="utf-8"
        )

        rows = build_primer_qc_summary(qc_dir)
        coi = next(r for r in rows if r["primer_id"] == "COI_short")
        assert "WARN_DIMER" in coi["qc_status"]
        assert "dimer_count=2" in coi["qc_reason"]

    def test_warn_hairpin(self, tmp_path):
        """hairpin_count > 0 triggers WARN_HAIRPIN."""
        qc_dir = tmp_path / "qc_results"
        (qc_dir / "thermo").mkdir(parents=True)
        (qc_dir / "dimer").mkdir(parents=True)
        (qc_dir / "hairpin").mkdir(parents=True)

        (qc_dir / "thermo" / "thermo_raw.tsv").write_text(
            _make_thermo_raw(), encoding="utf-8"
        )
        (qc_dir / "dimer" / "dimer_raw.txt").write_text(
            _make_dimer_raw_zero(), encoding="utf-8"
        )
        (qc_dir / "hairpin" / "hairpin_raw.txt").write_text(
            _make_hairpin_raw_with_hairpins(), encoding="utf-8"
        )

        rows = build_primer_qc_summary(qc_dir)
        coi = next(r for r in rows if r["primer_id"] == "COI_short")
        assert "WARN_HAIRPIN" in coi["qc_status"]
        assert "hairpin" in coi["qc_reason"]

    def test_missing_thermo_fail_parse(self, tmp_path):
        """Missing thermo file → FAIL_PARSE."""
        qc_dir = tmp_path / "qc_results"
        (qc_dir / "dimer").mkdir(parents=True)
        (qc_dir / "hairpin").mkdir(parents=True)

        (qc_dir / "dimer" / "dimer_raw.txt").write_text(
            _make_dimer_raw_zero(), encoding="utf-8"
        )
        (qc_dir / "hairpin" / "hairpin_raw.txt").write_text(
            _make_hairpin_raw_zero(), encoding="utf-8"
        )

        rows = build_primer_qc_summary(qc_dir)
        for r in rows:
            assert "FAIL_PARSE" in r["qc_status"]
            assert "thermo_missing" in r["qc_reason"]

    def test_missing_dimer_not_crash(self, tmp_path):
        """Missing dimer file should not crash."""
        qc_dir = tmp_path / "qc_results"
        (qc_dir / "thermo").mkdir(parents=True)
        (qc_dir / "hairpin").mkdir(parents=True)

        (qc_dir / "thermo" / "thermo_raw.tsv").write_text(
            _make_thermo_raw(), encoding="utf-8"
        )
        (qc_dir / "hairpin" / "hairpin_raw.txt").write_text(
            _make_hairpin_raw_zero(), encoding="utf-8"
        )

        rows = build_primer_qc_summary(qc_dir)
        assert len(rows) > 0
        for r in rows:
            assert "FAIL_PARSE" in r["qc_status"]

    def test_missing_hairpin_not_crash(self, tmp_path):
        """Missing hairpin file should not crash."""
        qc_dir = tmp_path / "qc_results"
        (qc_dir / "thermo").mkdir(parents=True)
        (qc_dir / "dimer").mkdir(parents=True)

        (qc_dir / "thermo" / "thermo_raw.tsv").write_text(
            _make_thermo_raw(), encoding="utf-8"
        )
        (qc_dir / "dimer" / "dimer_raw.txt").write_text(
            _make_dimer_raw_zero(), encoding="utf-8"
        )

        rows = build_primer_qc_summary(qc_dir)
        assert len(rows) > 0
        for r in rows:
            assert "FAIL_PARSE" in r["qc_status"]


# ── write_qc_outputs ──────────────────────────────────────────────────────


class TestWriteQcOutputs:
    def test_all_outputs_written(self, tmp_path):
        qc_dir = tmp_path / "qc_results"
        (qc_dir / "thermo").mkdir(parents=True)
        (qc_dir / "dimer").mkdir(parents=True)
        (qc_dir / "hairpin").mkdir(parents=True)

        (qc_dir / "thermo" / "thermo_raw.tsv").write_text(
            _make_thermo_raw(), encoding="utf-8"
        )
        (qc_dir / "dimer" / "dimer_raw.txt").write_text(
            _make_dimer_raw_zero(), encoding="utf-8"
        )
        (qc_dir / "hairpin" / "hairpin_raw.txt").write_text(
            _make_hairpin_raw_zero(), encoding="utf-8"
        )

        written = write_qc_outputs(qc_dir)

        assert "primer_thermo" in written
        assert "primer_dimer" in written
        assert "primer_hairpin" in written
        assert "primer_qc_summary" in written

        assert written["primer_thermo"].is_file()
        assert written["primer_dimer"].is_file()
        assert written["primer_hairpin"].is_file()
        assert written["primer_qc_summary"].is_file()

        thermo_rows = _read_tsv(written["primer_thermo"])
        assert len(thermo_rows) == 4
        assert thermo_rows[0]["primer_id"] == "COI_short"

        summary_rows = _read_tsv(written["primer_qc_summary"])
        assert len(summary_rows) >= 2


# ── CLI qc-summary ────────────────────────────────────────────────────────


class TestCliQcSummary:
    def test_cli_runs_successfully(self, tmp_path, monkeypatch):
        """``python -m fullpcr qc-summary --qc-dir <dir>`` exits 0."""
        qc_dir = tmp_path / "qc_results"
        (qc_dir / "thermo").mkdir(parents=True)
        (qc_dir / "dimer").mkdir(parents=True)
        (qc_dir / "hairpin").mkdir(parents=True)

        (qc_dir / "thermo" / "thermo_raw.tsv").write_text(
            _make_thermo_raw(), encoding="utf-8"
        )
        (qc_dir / "dimer" / "dimer_raw.txt").write_text(
            _make_dimer_raw_zero(), encoding="utf-8"
        )
        (qc_dir / "hairpin" / "hairpin_raw.txt").write_text(
            _make_hairpin_raw_zero(), encoding="utf-8"
        )

        from fullpcr.cli import main

        monkeypatch.setattr(sys, "exit", lambda code: None)

        main(["qc-summary", "--qc-dir", str(qc_dir)])

        assert (qc_dir / "thermo" / "primer_thermo.tsv").is_file()
        assert (qc_dir / "dimer" / "primer_dimer.tsv").is_file()
        assert (qc_dir / "hairpin" / "primer_hairpin.tsv").is_file()
        assert (qc_dir / "primer_qc_summary.tsv").is_file()

    def test_cli_missing_dir(self, tmp_path, monkeypatch, capsys):
        """CLI exits with error when qc-dir does not exist."""
        from fullpcr.cli import main

        exit_code = None

        def _fake_exit(code=0):
            nonlocal exit_code
            exit_code = code
            raise SystemExit(code)

        monkeypatch.setattr(sys, "exit", _fake_exit)

        with pytest.raises(SystemExit):
            main(["qc-summary", "--qc-dir", str(tmp_path / "nope")])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "不存在" in captured.err
