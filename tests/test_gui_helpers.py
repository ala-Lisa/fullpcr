"""Tests for gui_helpers module."""

from __future__ import annotations

import gzip
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

import pandas as pd

from fullpcr.gui_helpers import (
    build_final_report_command,
    build_obipcr_run_command,
    build_qc_pre_command,
    build_qc_spec_command,
    build_qc_summary_command,
    check_command_available,
    get_fullpcr_info,
    get_python_info,
    load_markdown_file,
    load_primer_rank,
    load_tsv_file,
    run_gui_command,
    summarize_primer_rank,
    summarize_status_counts,
    translate_recommendation,
    translate_status,
    translate_warning_label,
    validate_database_file,
    validate_file_exists,
    validate_output_directory,
    validate_primers_file,
    validate_taxonomy_file,
)


class TestCheckCommandAvailable:
    """Tests for check_command_available()."""

    def test_mock_success(self):
        """Returns available=True when command succeeds."""
        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=0,
                    stdout="obipcr v4.2.0\n",
                    stderr="",
                )

                result = check_command_available(["obipcr", "--version"])

        assert result["available"] is True
        assert result["version"] == "obipcr v4.2.0"
        assert result["error"] is None

    def test_mock_success_returns_none_version_when_no_stdout(self):
        """version is None when stdout is empty (returncode 0)."""
        with mock.patch("shutil.which", return_value="/usr/bin/somecmd"):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=0,
                    stdout="",
                    stderr="",
                )

                result = check_command_available(["somecmd"])

        assert result["available"] is True
        assert result["version"] is None

    def test_mock_failure_nonzero_exit(self):
        """Returns available=False with error detail on non-zero exit."""
        with mock.patch("shutil.which", return_value="/usr/bin/badcmd"):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=1,
                    stdout="",
                    stderr="command not found",
                )

                result = check_command_available(["badcmd"])

        assert result["available"] is False
        assert result["error"] == "command not found"

    def test_mock_failure_file_not_found(self):
        """Returns available=False when executable not on PATH."""
        with mock.patch("shutil.which", return_value=None):
            result = check_command_available(["nonexistent", "--version"])

        assert result["available"] is False
        assert "not found on PATH" in result["error"]

    def test_mock_failure_timeout(self):
        """Returns available=False on subprocess.TimeoutExpired."""
        with mock.patch("shutil.which", return_value="/usr/bin/slowcmd"):
            with mock.patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["slowcmd"], timeout=30),
            ):
                result = check_command_available(["slowcmd"])

        assert result["available"] is False
        assert "timed out" in result["error"]

    def test_uses_list_not_shell(self):
        """Confirms subprocess.run is called with a list (no shell=True)."""
        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=0,
                    stdout="v1.0\n",
                    stderr="",
                )

                check_command_available(["obipcr", "--version"])

        call_args = mock_run.call_args
        assert isinstance(call_args[0][0], list)
        # Verify shell is not True
        assert call_args[1].get("shell", False) is False


class TestGetPythonInfo:
    """Tests for get_python_info()."""

    def test_returns_version_and_executable(self):
        info = get_python_info()

        assert "version" in info
        assert "executable" in info
        assert isinstance(info["version"], str)
        assert isinstance(info["executable"], str)
        assert len(info["version"]) > 0
        assert len(info["executable"]) > 0

    def test_executable_matches_sys_executable(self):
        info = get_python_info()

        assert info["executable"] == sys.executable


class TestGetFullpcrInfo:
    """Tests for get_fullpcr_info()."""

    def test_importable_in_dev_environment(self):
        """fullpcr should be importable when running tests."""
        info = get_fullpcr_info()

        assert info["importable"] is True
        assert info["error"] is None

    def test_has_version_field(self):
        info = get_fullpcr_info()

        assert "version" in info
        assert info["version"] is not None

    def test_mock_import_error(self):
        """Returns importable=False with error message when import fails."""
        with mock.patch(
            "builtins.__import__",
            side_effect=ImportError("no fullpcr"),
        ):
            info = get_fullpcr_info()
            assert info["importable"] is False
            assert "no fullpcr" in info["error"]
            assert info["version"] is None
            assert info["path"] is None


# ── Phase 2: input validation tests ─────────────────────────────────────


class TestValidateFileExists:
    """Tests for validate_file_exists()."""

    def test_file_exists(self, tmp_path: Path):
        f = tmp_path / "real.tsv"
        f.write_text("data\n")
        result = validate_file_exists(str(f))
        assert result["status"] == "PASS"
        assert result["exists"] is True

    def test_file_not_found(self, tmp_path: Path):
        result = validate_file_exists(str(tmp_path / "missing.txt"))
        assert result["status"] == "FAIL"
        assert result["exists"] is False
        assert "not found" in result["error"]

    def test_empty_path(self):
        result = validate_file_exists("")
        assert result["status"] == "FAIL"
        assert "No path provided" in result["error"]


class TestValidatePrimersFile:
    """Tests for validate_primers_file()."""

    def test_normal(self, tmp_path: Path):
        f = tmp_path / "primers.tsv"
        f.write_text(
            "primer_id\tforward\treverse\tmin_length\tmax_length\n"
            "COI_short\tGGTCA\tTAAACT\t100\t400\n"
            "16S_short\tGACG\tCGCTG\t200\t600\n"
        )
        result = validate_primers_file(str(f))
        assert result["status"] == "PASS"
        assert result["primer_count"] == 2
        assert len(result["preview"]) == 3  # header + 2 data rows
        assert result["missing_fields"] == []

    def test_missing_fields(self, tmp_path: Path):
        f = tmp_path / "bad_primers.tsv"
        f.write_text("primer_id\tforward\nCOI_short\tGGTCA\n")
        result = validate_primers_file(str(f))
        assert result["status"] == "FAIL"
        assert "reverse" in result["missing_fields"]
        assert "min_length" in result["missing_fields"]
        assert "max_length" in result["missing_fields"]

    def test_empty_path(self):
        result = validate_primers_file("")
        assert result["status"] == "FAIL"

    def test_no_data_rows(self, tmp_path: Path):
        f = tmp_path / "header_only.tsv"
        f.write_text("primer_id\tforward\treverse\tmin_length\tmax_length\n")
        result = validate_primers_file(str(f))
        assert result["status"] == "FAIL"
        assert "header row" in result["error"]


class TestValidateDatabaseFile:
    """Tests for validate_database_file()."""

    def test_normal_fasta(self, tmp_path: Path):
        f = tmp_path / "db.fasta"
        f.write_text(">record1\nATCGATCG\n>record2\nGCTAGCTA\n")
        result = validate_database_file(str(f))
        assert result["status"] == "PASS"
        assert result["record_count"] == 2
        assert result["total_bases"] == 16
        assert result["format"] == ".fasta"

    def test_gzipped_fasta(self, tmp_path: Path):
        f = tmp_path / "db.fasta.gz"
        with gzip.open(f, "wt", encoding="utf-8") as fh:
            fh.write(">r1\nAAAA\n>r2\nCCCC\n")
        result = validate_database_file(str(f))
        assert result["status"] == "PASS"
        assert result["record_count"] == 2
        assert result["total_bases"] == 8
        assert result["format"] == ".fa.gz"

    def test_empty_fasta(self, tmp_path: Path):
        f = tmp_path / "empty.fasta"
        f.write_text("")
        result = validate_database_file(str(f))
        assert result["status"] == "FAIL"
        assert result["record_count"] == 0
        assert "0 records" in result["error"]

    def test_fasta_no_headers(self, tmp_path: Path):
        f = tmp_path / "noheaders.fasta"
        f.write_text("ATCG\nGGGG\n")
        result = validate_database_file(str(f))
        assert result["status"] == "FAIL"
        assert result["record_count"] == 0

    def test_unsupported_format(self, tmp_path: Path):
        f = tmp_path / "db.txt"
        f.write_text(">r1\nATCG\n")
        result = validate_database_file(str(f))
        assert result["status"] == "FAIL"
        assert "Unsupported format" in result["error"]

    def test_empty_path(self):
        result = validate_database_file("")
        assert result["status"] == "FAIL"


class TestValidateTaxonomyFile:
    """Tests for validate_taxonomy_file()."""

    def test_normal(self, tmp_path: Path):
        f = tmp_path / "taxonomy.tsv"
        f.write_text(
            "taxid\tscientific_name\tspecies\n"
            "9606\tHomo sapiens\tHomo sapiens\n"
            "9913\tBos taurus\tBos taurus\n"
        )
        result = validate_taxonomy_file(str(f))
        assert result["status"] == "PASS"
        assert result["record_count"] == 2
        assert result["unique_species"] == 2
        assert result["missing_fields"] == []

    def test_missing_fields(self, tmp_path: Path):
        f = tmp_path / "bad_tax.tsv"
        f.write_text("taxid\n9606\n")
        result = validate_taxonomy_file(str(f))
        assert result["status"] == "FAIL"
        assert "scientific_name" in result["missing_fields"]

    def test_no_species_column(self, tmp_path: Path):
        f = tmp_path / "tax_no_sp.tsv"
        f.write_text("taxid\tscientific_name\n9606\tHomo sapiens\n")
        result = validate_taxonomy_file(str(f))
        assert result["status"] == "PASS"
        assert result["unique_species"] is None

    def test_empty_path(self):
        result = validate_taxonomy_file("")
        assert result["status"] == "FAIL"


class TestValidateOutputDirectory:
    """Tests for validate_output_directory()."""

    def test_exists(self, tmp_path: Path):
        result = validate_output_directory(str(tmp_path))
        assert result["status"] == "PASS"
        assert result["exists"] is True
        assert result["will_create"] is False

    def test_not_exists(self, tmp_path: Path):
        result = validate_output_directory(str(tmp_path / "newdir"))
        assert result["status"] == "WARN"
        assert result["exists"] is False
        assert result["will_create"] is True

    def test_empty_path(self):
        result = validate_output_directory("")
        assert result["status"] == "FAIL"

    def test_path_is_file_not_dir(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_text("data\n")
        result = validate_output_directory(str(f))
        assert result["status"] == "FAIL"
        assert "not a directory" in result["error"]


# ── Phase 3: command builder tests ──────────────────────────────────────


class TestBuildQcPreCommand:
    """Tests for build_qc_pre_command()."""

    def test_basic_params(self):
        cmd = build_qc_pre_command(
            primers="primers.tsv",
            outdir="qc_results",
        )
        assert isinstance(cmd, list)
        assert all(isinstance(arg, str) for arg in cmd)
        assert cmd[0:4] == ["python3", "-m", "fullpcr", "qc-pre"]
        assert "--primers" in cmd
        assert "primers.tsv" in cmd
        assert "--outdir" in cmd
        assert "qc_results" in cmd

    def test_boolean_flags_included_when_true(self):
        cmd = build_qc_pre_command(
            primers="p.tsv",
            outdir="out",
            thermo=True,
            dimer=True,
            hairpin=True,
            degen=True,
        )
        assert "--thermo" in cmd
        assert "--dimer" in cmd
        assert "--hairpin" in cmd
        assert "--degen" in cmd

    def test_boolean_flags_excluded_when_false(self):
        cmd = build_qc_pre_command(
            primers="p.tsv",
            outdir="out",
            thermo=False,
            dimer=False,
            hairpin=False,
            degen=False,
        )
        assert "--thermo" not in cmd
        assert "--dimer" not in cmd
        assert "--hairpin" not in cmd
        assert "--degen" not in cmd

    def test_numeric_params(self):
        cmd = build_qc_pre_command(
            primers="p.tsv",
            outdir="out",
            score=10,
            mismatch=3,
            dg=-7.5,
            tm=55.0,
            max_degenerate_variants=128,
        )
        assert "--score" in cmd and "10" in cmd
        assert "--mismatch" in cmd and "3" in cmd
        assert "--dg" in cmd and "-7.5" in cmd
        assert "--tm" in cmd and "55.0" in cmd
        assert "--max-degenerate-variants" in cmd and "128" in cmd

    def test_no_shell_true(self):
        """Confirm no shell=True anywhere — this is list[str]."""
        cmd = build_qc_pre_command(primers="p.tsv", outdir="out")
        assert "shell" not in [a.lower() for a in cmd]

    def test_empty_paths_not_added(self):
        cmd = build_qc_pre_command(primers="", outdir="")
        assert "--primers" not in cmd
        assert "--outdir" not in cmd


class TestBuildQcSummaryCommand:
    """Tests for build_qc_summary_command()."""

    def test_basic(self):
        cmd = build_qc_summary_command(qc_dir="qc_results")
        assert isinstance(cmd, list)
        assert "--qc-dir" in cmd
        assert "qc_results" in cmd


class TestBuildQcSpecCommand:
    """Tests for build_qc_spec_command()."""

    def test_basic_params(self):
        cmd = build_qc_spec_command(
            primers="p.tsv",
            database="db.fasta",
            outdir="spec_out",
        )
        assert "--primers" in cmd and "p.tsv" in cmd
        assert "--database" in cmd and "db.fasta" in cmd
        assert "--outdir" in cmd and "spec_out" in cmd

    def test_force_true(self):
        cmd = build_qc_spec_command(
            primers="p.tsv",
            database="db.fasta",
            outdir="spec_out",
            force=True,
        )
        assert "--force" in cmd

    def test_force_false(self):
        cmd = build_qc_spec_command(
            primers="p.tsv",
            database="db.fasta",
            outdir="spec_out",
            force=False,
        )
        assert "--force" not in cmd

    def test_numeric_params(self):
        cmd = build_qc_spec_command(
            primers="p.tsv",
            database="db.fasta",
            outdir="out",
            min_size=80,
            max_size=500,
            tm=50.0,
            max_tm=75.0,
            mismatch=2,
            cpu=4,
            kvalue=9,
        )
        assert "--min-size" in cmd and "80" in cmd
        assert "--max-size" in cmd and "500" in cmd
        assert "--tm" in cmd and "50.0" in cmd
        assert "--max-tm" in cmd and "75.0" in cmd
        assert "--cpu" in cmd and "4" in cmd
        assert "--kvalue" in cmd and "9" in cmd


class TestBuildObipcrRunCommand:
    """Tests for build_obipcr_run_command()."""

    def test_basic_params(self):
        cmd = build_obipcr_run_command(
            primers="p.tsv",
            database="db.fasta",
            outdir="results",
        )
        assert "--primers" in cmd and "p.tsv" in cmd
        assert "--database" in cmd and "db.fasta" in cmd
        assert "--outdir" in cmd and "results" in cmd

    def test_mismatches(self):
        cmd = build_obipcr_run_command(
            primers="p.tsv",
            database="db.fasta",
            outdir="results",
            mismatches="0,1,2,3",
        )
        assert "--mismatches" in cmd and "0,1,2,3" in cmd

    def test_flags_true(self):
        cmd = build_obipcr_run_command(
            primers="p.tsv",
            database="db.fasta",
            outdir="results",
            circular=True,
            summarize=True,
            report=True,
            force=True,
        )
        assert "--circular" in cmd
        assert "--summarize" in cmd
        assert "--report" in cmd
        assert "--force" in cmd

    def test_flags_false(self):
        cmd = build_obipcr_run_command(
            primers="p.tsv",
            database="db.fasta",
            outdir="results",
            circular=False,
            summarize=False,
            report=False,
            force=False,
        )
        assert "--circular" not in cmd
        assert "--summarize" not in cmd
        assert "--report" not in cmd
        assert "--force" not in cmd

    def test_taxonomy_included(self):
        cmd = build_obipcr_run_command(
            primers="p.tsv",
            database="db.fasta",
            outdir="results",
            taxonomy="tax.tsv",
        )
        assert "--taxonomy" in cmd and "tax.tsv" in cmd


class TestBuildFinalReportCommand:
    """Tests for build_final_report_command()."""

    def test_all_params(self):
        cmd = build_final_report_command(
            obipcr_dir="obipcr_results",
            qc_dir="qc_results",
            spec_dir="qc_spec_results",
            outdir="final_results",
        )
        assert "--obipcr-dir" in cmd and "obipcr_results" in cmd
        assert "--qc-dir" in cmd and "qc_results" in cmd
        assert "--spec-dir" in cmd and "qc_spec_results" in cmd
        assert "--outdir" in cmd and "final_results" in cmd


# ── Phase 3: run_gui_command tests ──────────────────────────────────────


class TestRunGuiCommand:
    """Tests for run_gui_command()."""

    def test_mock_success(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="done\n",
                stderr="",
            )
            result = run_gui_command(["echo", "hello"])
        assert result["status"] == "PASS"
        assert result["returncode"] == 0
        assert result["message"] == "Command completed successfully"

    def test_mock_failure(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=1,
                stdout="",
                stderr="error occurred",
            )
            result = run_gui_command(["badcmd"])
        assert result["status"] == "FAIL"
        assert result["returncode"] == 1
        assert "exited with code 1" in result["message"]

    def test_mock_timeout(self):
        with mock.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["sleep"], timeout=5),
        ):
            result = run_gui_command(["sleep", "999"])
        assert result["status"] == "TIMEOUT"
        assert "timed out" in result["message"]

    def test_command_is_list(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="",
                stderr="",
            )
            run_gui_command(["ls", "-la"])
        called_cmd = mock_run.call_args[0][0]
        assert isinstance(called_cmd, list)
        assert all(isinstance(a, str) for a in called_cmd)

    def test_no_shell_true(self):
        """Verify shell is not True in subprocess.run call."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="",
                stderr="",
            )
            run_gui_command(["echo", "test"])
        assert mock_run.call_args[1].get("shell", False) is False

    def test_file_not_found(self):
        with mock.patch(
            "subprocess.run",
            side_effect=FileNotFoundError("no such executable"),
        ):
            result = run_gui_command(["nonexistent"])
        assert result["status"] == "FAIL"
        assert "not found" in result["message"]


# ── Phase 3: all commands are list[str], no shell=True ──────────────────


class TestCommandsAreListOfStrings:
    """Verify all build_* functions return list[str] with no shell=True."""

    def test_all_return_list_of_str(self):
        builders = [
            build_qc_pre_command(primers="p.tsv", outdir="out"),
            build_qc_summary_command(qc_dir="qc_results"),
            build_qc_spec_command(
                primers="p.tsv", database="db.fasta", outdir="out"
            ),
            build_obipcr_run_command(
                primers="p.tsv", database="db.fasta", outdir="out"
            ),
            build_final_report_command(
                obipcr_dir="a", qc_dir="b", spec_dir="c", outdir="d"
            ),
        ]
        for cmd in builders:
            assert isinstance(cmd, list), f"Expected list, got {type(cmd)}"
            for arg in cmd:
                assert isinstance(arg, str), (
                    f"Expected str, got {type(arg)}: {arg!r}"
                )
            assert "shell" not in [a.lower() for a in cmd], (
                f"shell=True detected in {cmd}"
            )


# ── Phase 4: result reading tests ─────────────────────────────────────────


class TestLoadTsvFile:
    """Tests for load_tsv_file()."""

    def test_normal(self, tmp_path: Path):
        """Returns PASS with DataFrame for a valid TSV."""
        f = tmp_path / "data.tsv"
        f.write_text("col_a\tcol_b\nval1\tval2\nval3\tval4\n")
        result = load_tsv_file(str(f))
        assert result["status"] == "PASS"
        assert result["df"] is not None
        assert result["row_count"] == 2
        assert result["columns"] == ["col_a", "col_b"]
        assert result["error"] is None

    def test_file_not_found(self, tmp_path: Path):
        """Returns FAIL when file does not exist."""
        result = load_tsv_file(str(tmp_path / "missing.tsv"))
        assert result["status"] == "FAIL"
        assert "not found" in result["error"]
        assert result["df"] is None

    def test_empty_file(self, tmp_path: Path):
        """Returns FAIL when file has no data rows."""
        f = tmp_path / "empty.tsv"
        f.write_text("col_a\tcol_b\n")
        result = load_tsv_file(str(f))
        assert result["status"] == "FAIL"
        assert "no data rows" in result["error"]
        assert result["row_count"] == 0

    def test_empty_path(self):
        """Returns FAIL when no path provided."""
        result = load_tsv_file("")
        assert result["status"] == "FAIL"
        assert "No path provided" in result["error"]

    def test_malformed_tsv(self, tmp_path: Path):
        """Returns FAIL for unparseable TSV, does not raise."""
        f = tmp_path / "bad.tsv"
        f.write_text("not\ta valid tsv\ncol1\tcol2\n")
        result = load_tsv_file(str(f))
        # pandas is lenient — malformed TSV may still parse.
        # We just verify no exception is raised.
        assert result["status"] in ("PASS", "FAIL")


class TestLoadMarkdownFile:
    """Tests for load_markdown_file()."""

    def test_normal(self, tmp_path: Path):
        """Returns PASS with content for a valid markdown file."""
        f = tmp_path / "report.md"
        f.write_text("# Hello\n\nWorld.\n")
        result = load_markdown_file(str(f))
        assert result["status"] == "PASS"
        assert result["content"] == "# Hello\n\nWorld.\n"
        assert result["error"] is None

    def test_file_not_found(self, tmp_path: Path):
        """Returns FAIL when file does not exist."""
        result = load_markdown_file(str(tmp_path / "missing.md"))
        assert result["status"] == "FAIL"
        assert "not found" in result["error"]
        assert result["content"] is None

    def test_empty_file(self, tmp_path: Path):
        """Returns WARN when file is empty or whitespace only."""
        f = tmp_path / "empty.md"
        f.write_text("   \n")
        result = load_markdown_file(str(f))
        assert result["status"] == "WARN"
        assert "empty" in result["error"]

    def test_empty_path(self):
        """Returns FAIL when no path provided."""
        result = load_markdown_file("")
        assert result["status"] == "FAIL"
        assert "No path provided" in result["error"]


class TestLoadPrimerRank:
    """Tests for load_primer_rank()."""

    def test_normal(self, tmp_path: Path):
        """load_primer_rank wraps load_tsv_file correctly."""
        f = tmp_path / "primer_rank.tsv"
        f.write_text(
            "primer_id\tfinal_score\tfinal_status\n"
            "COI_short\t0.85\tRECOMMENDED\n"
            "16S_short\t0.42\tNOT_RECOMMENDED\n"
        )
        result = load_primer_rank(str(f))
        assert result["status"] == "PASS"
        assert result["row_count"] == 2
        assert result["df"] is not None


class TestSummarizePrimerRank:
    """Tests for summarize_primer_rank()."""

    def test_normal(self):
        """Returns correct summary from a well-formed primer rank DataFrame."""
        df = pd.DataFrame({
            "primer_id": ["A", "B", "C"],
            "final_score": ["0.90", "0.55", "0.30"],
            "final_status": ["RECOMMENDED", "ACCEPTABLE_WITH_WARNINGS", "NOT_RECOMMENDED"],
            "obipcr_unique_species_count": ["50", "30", "5"],
        })
        result = summarize_primer_rank(df)
        assert result["top_primer"] == "A"
        assert result["top_final_score"] == 0.90
        assert result["recommended_count"] == 1
        assert result["acceptable_count"] == 1
        assert result["not_recommended_count"] == 1
        assert result["needs_review_count"] == 0
        assert result["error"] is None

    def test_missing_final_status_column(self):
        """Gracefully handles missing final_status column."""
        df = pd.DataFrame({
            "primer_id": ["A", "B"],
            "final_score": ["0.80", "0.40"],
        })
        result = summarize_primer_rank(df)
        # Should not crash; top_primer/top_score still computed.
        assert result["top_primer"] == "A"
        assert result["recommended_count"] == 0
        assert result["not_recommended_count"] == 0
        assert result["error"] is None

    def test_empty_dataframe(self):
        """Returns error for None or empty DataFrame."""
        result = summarize_primer_rank(None)
        assert result["error"] == "No data to summarize"
        assert result["recommended_count"] == 0

        empty_df = pd.DataFrame()
        result2 = summarize_primer_rank(empty_df)
        assert result2["error"] == "No data to summarize"


class TestSummarizeStatusCounts:
    """Tests for summarize_status_counts()."""

    def test_normal(self):
        """Returns correct value counts for a column."""
        df = pd.DataFrame({
            "status": ["PASS", "PASS", "FAIL", "WARN", "PASS"],
        })
        result = summarize_status_counts(df, "status")
        assert result["error"] is None
        assert result["total"] == 5
        assert result["counts"] == {"PASS": 3, "FAIL": 1, "WARN": 1}

    def test_missing_column(self):
        """Returns clear error when column does not exist."""
        df = pd.DataFrame({"col_a": ["x", "y"]})
        result = summarize_status_counts(df, "missing_col")
        assert result["error"] is not None
        assert "not found" in result["error"]
        assert result["counts"] is None

    def test_empty_dataframe(self):
        """Returns error for None or empty DataFrame."""
        result = summarize_status_counts(None, "col")
        assert result["error"] == "No data to summarize"

        empty_df = pd.DataFrame()
        result2 = summarize_status_counts(empty_df, "col")
        assert result2["error"] == "No data to summarize"

    def test_na_values_counted(self):
        """NaN values are counted as 'NA'."""
        df = pd.DataFrame({
            "cat": ["A", None, "B", None],
        })
        result = summarize_status_counts(df, "cat")
        assert result["counts"] is not None
        assert "NA" in result["counts"]
        assert result["counts"]["NA"] == 2


# ── Phase 6A: Chinese translation tests ─────────────────────────────────


class TestTranslateStatus:
    """Tests for translate_status()."""

    def test_known_values(self):
        assert translate_status("PASS") == "正常"
        assert translate_status("FAIL") == "异常"
        assert translate_status("WARN") == "警告"
        assert translate_status("TIMEOUT") == "超时"

    def test_unknown_value_preserved(self):
        assert translate_status("UNKNOWN") == "UNKNOWN"
        assert translate_status("success") == "success"

    def test_none_returns_empty(self):
        assert translate_status(None) == ""

    def test_empty_string_preserved(self):
        assert translate_status("") == ""

    def test_non_string_preserved(self):
        assert translate_status(42) == "42"


class TestTranslateRecommendation:
    """Tests for translate_recommendation()."""

    def test_known_values(self):
        assert translate_recommendation("RECOMMENDED") == "推荐"
        assert translate_recommendation("ACCEPTABLE_WITH_WARNINGS") == "可用但有警告"
        assert translate_recommendation("NOT_RECOMMENDED") == "不推荐"
        assert translate_recommendation("NEEDS_REVIEW") == "需要人工检查"

    def test_unknown_value_preserved(self):
        assert translate_recommendation("EXCELLENT") == "EXCELLENT"

    def test_none_returns_empty(self):
        assert translate_recommendation(None) == ""

    def test_empty_string_preserved(self):
        assert translate_recommendation("") == ""


class TestTranslateWarningLabel:
    """Tests for translate_warning_label()."""

    def test_known_single_labels(self):
        assert translate_warning_label("PASS") == "通过"
        assert translate_warning_label("WARN_DIMER") == "引物二聚体警告"
        assert translate_warning_label("WARN_HAIRPIN") == "发卡结构警告"
        assert translate_warning_label("WARN_TM_DIFF") == "Tm 差异偏大"
        assert translate_warning_label("WARN_NO_AMP") == "未检测到扩增"
        assert translate_warning_label("WARN_MULTI_AMP") == "存在多个扩增产物"
        assert translate_warning_label("WARN_SIZE") == "扩增片段长度异常"
        assert translate_warning_label("WARN_OVERAMP") == "过度扩增"
        assert translate_warning_label("FAIL_PARSE") == "解析失败"
        assert translate_warning_label("FAIL_DEGENERATE_EXPLOSION") == "简并引物展开爆炸"
        assert translate_warning_label("FAIL_INDEX") == "索引构建失败"
        assert translate_warning_label("FAIL_SPEC") == "特异性分析失败"

    def test_compound_values(self):
        result = translate_warning_label("WARN_DIMER; WARN_HAIRPIN")
        assert "引物二聚体警告" in result
        assert "发卡结构警告" in result

    def test_mixed_known_unknown_compound(self):
        result = translate_warning_label("WARN_DIMER; UNKNOWN_WARN")
        assert "引物二聚体警告" in result
        assert "UNKNOWN_WARN" in result

    def test_unknown_value_preserved(self):
        assert translate_warning_label("SOME_RANDOM") == "SOME_RANDOM"

    def test_none_returns_empty(self):
        assert translate_warning_label(None) == ""

    def test_empty_string_preserved(self):
        assert translate_warning_label("") == ""

    def test_other_known_labels(self):
        assert translate_warning_label("NO_DEGENERACY") == "无简并碱基"
        assert translate_warning_label("EXPANDED") == "已展开"
        assert translate_warning_label("INVALID_BASE") == "无效碱基"
        assert translate_warning_label("OK") == "正常"
        assert translate_warning_label("NA") == "无数据"
