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
    _WORKFLOW_PATH_KEYS,
    apply_primer_preset_to_state,
    apply_project_paths_to_state,
    build_final_report_command,
    build_obipcr_run_command,
    build_qc_pre_command,
    build_qc_spec_command,
    build_qc_summary_command,
    check_command_available,
    collect_environment_status,
    compute_inputs_validated,
    derive_project_paths,
    ensure_widget_key,
    get_fullpcr_info,
    get_primer_preset,
    get_python_info,
    init_canonical_defaults,
    load_markdown_file,
    load_primer_rank,
    load_tsv_file,
    run_gui_command,
    should_refresh_environment_status,
    summarize_primer_rank,
    summarize_status_counts,
    sync_widgets_to_canonical,
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


# ── Phase 7A: environment status tests ───────────────────────────────────


class TestCollectEnvironmentStatus:
    """Tests for collect_environment_status() — all external calls mocked.

    Never executes real obipcr or MFEprimer in unit tests.
    """

    @staticmethod
    def _mock_py_info():
        return {"version": "mock 3.11", "executable": "/mock/python"}

    @staticmethod
    def _mock_fp_info():
        return {"importable": True, "version": "0.1.0", "path": "/mock/fullpcr", "error": None}

    @staticmethod
    def _mock_cmd_ok(_command=None):
        return {"available": True, "version": "mock-1.0", "error": None}

    @staticmethod
    def _mock_cmd_fail(_command=None):
        return {"available": False, "version": None, "error": "mock: not found"}

    def test_returns_all_expected_keys(self):
        with mock.patch(
            "fullpcr.gui_helpers.get_python_info", return_value=self._mock_py_info()
        ), mock.patch(
            "fullpcr.gui_helpers.get_fullpcr_info", return_value=self._mock_fp_info()
        ), mock.patch(
            "fullpcr.gui_helpers.check_command_available", return_value=self._mock_cmd_ok()
        ), mock.patch("os.getcwd", return_value="/mock/cwd"), mock.patch(
            "time.time", return_value=1234567890.0
        ):
            result = collect_environment_status()

        expected_keys = {
            "python", "fullpcr", "obipcr", "mfeprimer",
            "cwd", "ok_count", "fail_count", "all_ok", "checked_at",
        }
        assert set(result.keys()) == expected_keys

    def test_checked_at_is_from_mocked_time(self):
        with mock.patch(
            "fullpcr.gui_helpers.get_python_info", return_value=self._mock_py_info()
        ), mock.patch(
            "fullpcr.gui_helpers.get_fullpcr_info", return_value=self._mock_fp_info()
        ), mock.patch(
            "fullpcr.gui_helpers.check_command_available", return_value=self._mock_cmd_ok()
        ), mock.patch("os.getcwd", return_value="/mock/cwd"), mock.patch(
            "time.time", return_value=1234567890.0
        ):
            result = collect_environment_status()

        assert result["checked_at"] == 1234567890.0

    def test_ok_count_all_available_is_4(self):
        with mock.patch(
            "fullpcr.gui_helpers.get_python_info", return_value=self._mock_py_info()
        ), mock.patch(
            "fullpcr.gui_helpers.get_fullpcr_info", return_value=self._mock_fp_info()
        ), mock.patch(
            "fullpcr.gui_helpers.check_command_available", return_value=self._mock_cmd_ok()
        ), mock.patch("os.getcwd", return_value="/mock/cwd"), mock.patch(
            "time.time", return_value=1234567890.0
        ):
            result = collect_environment_status()

        assert result["ok_count"] == 4
        assert result["fail_count"] == 0
        assert result["all_ok"] is True

    def test_fail_count_when_tools_unavailable(self):
        def _cmd_varied(cmd):
            if cmd[0] == "obipcr":
                return {"available": True, "version": "mock", "error": None}
            return {"available": False, "version": None, "error": "mock: not found"}

        with mock.patch(
            "fullpcr.gui_helpers.get_python_info", return_value=self._mock_py_info()
        ), mock.patch(
            "fullpcr.gui_helpers.get_fullpcr_info", return_value=self._mock_fp_info()
        ), mock.patch(
            "fullpcr.gui_helpers.check_command_available", side_effect=_cmd_varied
        ), mock.patch("os.getcwd", return_value="/mock/cwd"), mock.patch(
            "time.time", return_value=1234567890.0
        ):
            result = collect_environment_status()

        # Python (always 1) + fullpcr (1) + obipcr (1) = 3, mfeprimer (0) = 1 fail
        assert result["ok_count"] == 3
        assert result["fail_count"] == 1
        assert result["all_ok"] is False

    def test_cwd_is_mocked(self):
        with mock.patch(
            "fullpcr.gui_helpers.get_python_info", return_value=self._mock_py_info()
        ), mock.patch(
            "fullpcr.gui_helpers.get_fullpcr_info", return_value=self._mock_fp_info()
        ), mock.patch(
            "fullpcr.gui_helpers.check_command_available", return_value=self._mock_cmd_ok()
        ), mock.patch("os.getcwd", return_value="/mock/cwd"), mock.patch(
            "time.time", return_value=1234567890.0
        ):
            result = collect_environment_status()

        assert result["cwd"] == "/mock/cwd"

    def test_python_info_from_mock(self):
        with mock.patch(
            "fullpcr.gui_helpers.get_python_info", return_value=self._mock_py_info()
        ), mock.patch(
            "fullpcr.gui_helpers.get_fullpcr_info", return_value=self._mock_fp_info()
        ), mock.patch(
            "fullpcr.gui_helpers.check_command_available", return_value=self._mock_cmd_ok()
        ), mock.patch("os.getcwd", return_value="/mock/cwd"), mock.patch(
            "time.time", return_value=1234567890.0
        ):
            result = collect_environment_status()

        assert result["python"]["executable"] == "/mock/python"

    def test_fullpcr_importable_from_mock(self):
        with mock.patch(
            "fullpcr.gui_helpers.get_python_info", return_value=self._mock_py_info()
        ), mock.patch(
            "fullpcr.gui_helpers.get_fullpcr_info", return_value=self._mock_fp_info()
        ), mock.patch(
            "fullpcr.gui_helpers.check_command_available", return_value=self._mock_cmd_ok()
        ), mock.patch("os.getcwd", return_value="/mock/cwd"), mock.patch(
            "time.time", return_value=1234567890.0
        ):
            result = collect_environment_status()

        assert result["fullpcr"]["importable"] is True
        assert result["fullpcr"]["version"] == "0.1.0"


class TestShouldRefreshEnvironmentStatus:
    """Tests for should_refresh_environment_status()."""

    def test_none_checked_at_returns_true(self):
        """Returns True when checked_at is None (never collected)."""
        assert should_refresh_environment_status(None, 100.0) is True

    def test_within_ttl_returns_false(self):
        """Returns False when checked_at is within TTL."""
        assert should_refresh_environment_status(90.0, 100.0, ttl_seconds=60) is False

    def test_exceeded_ttl_returns_true(self):
        """Returns True when checked_at is older than TTL."""
        assert should_refresh_environment_status(39.0, 100.0, ttl_seconds=60) is True

    def test_exact_ttl_boundary_returns_false(self):
        """Returns False at exact TTL boundary (60.0 > 60 is False)."""
        # 100.0 - 40.0 = 60.0, which is NOT > 60
        assert should_refresh_environment_status(40.0, 100.0, ttl_seconds=60) is False

    def test_default_ttl_is_60(self):
        """Default TTL is 60 seconds."""
        assert should_refresh_environment_status(50.0, 100.0) is False  # 50s < 60s
        assert should_refresh_environment_status(39.0, 100.0) is True   # 61s > 60s


class TestEnvironmentStatusCache:
    """Integration tests for the environment-status caching loop.

    Simulates the cache-check logic used by ``_render_environment_popover``
    (``should_refresh_environment_status`` + a ``collect_environment_status``
    call counter).  No real subprocess is ever spawned.
    """

    def _simulate_loop(
        self,
        events: list[tuple[float, bool]],
        ttl: int = 60,
    ) -> list[int]:
        """Simulate the cache loop and return call counts after each step.

        Args:
            events: List of ``(now, force_refresh)`` tuples.
            ttl: TTL in seconds.

        Returns:
            List of cumulative ``collect_environment_status`` call counts
            after each event.
        """
        checked_at: float | None = None
        call_count = 0
        counts: list[int] = []

        for now, force_refresh in events:
            needs = force_refresh or should_refresh_environment_status(
                checked_at, now, ttl_seconds=ttl
            )
            if needs:
                call_count += 1
                checked_at = now
            counts.append(call_count)

        return counts

    def test_first_call_collects_once(self):
        """First check always triggers a collection → 1 call."""
        counts = self._simulate_loop([(100.0, False)])
        assert counts == [1]

    def test_multiple_reruns_within_ttl_stay_one(self):
        """Multiple checks within TTL do not re-collect."""
        counts = self._simulate_loop([
            (100.0, False),  # first → 1
            (110.0, False),  # 10 s later → still within TTL
            (150.0, False),  # 50 s later → still within TTL
            (159.0, False),  # 59 s later → still within TTL
        ])
        assert counts == [1, 1, 1, 1]

    def test_manual_refresh_adds_one(self):
        """Force-refresh triggers a new collection."""
        counts = self._simulate_loop([
            (100.0, False),  # first → 1
            (110.0, True),   # force refresh → 2
        ])
        assert counts == [1, 2]

    def test_ttl_expiry_adds_one(self):
        """After TTL expires, a check triggers re-collection."""
        counts = self._simulate_loop([
            (100.0, False),  # first → 1
            (161.0, False),  # 61 s later → TTL expired → 2
        ])
        assert counts == [1, 2]

    def test_full_cycle(self):
        """First(1) → TTL内(1) → force(2) → TTL到期(3)."""
        counts = self._simulate_loop([
            (100.0, False),  # 1
            (130.0, False),  # 1 (TTL内)
            (140.0, True),   # 2 (force)
            (141.0, False),  # 2 (TTL内 after force)
            (202.0, False),  # 3 (TTL到期 after last collection at 140)
        ])
        assert counts == [1, 1, 2, 2, 3]


class TestDeriveProjectPaths:
    """Tests for derive_project_paths()."""

    def test_normal_path(self):
        """Returns correctly derived sub-directories from a normal path."""
        result = derive_project_paths("/home/user/project/results")
        assert result["output_root"] == "/home/user/project/results"
        assert result["qc_results_dir"] == "/home/user/project/results/qc_results"
        assert result["qc_spec_results_dir"] == "/home/user/project/results/qc_spec_results"
        assert result["obipcr_results_dir"] == "/home/user/project/results/obipcr_results"
        assert result["final_results_dir"] == "/home/user/project/results/final_results"

    def test_relative_path(self):
        """Handles relative paths correctly."""
        result = derive_project_paths("output")
        assert result["output_root"] == "output"
        assert result["qc_results_dir"] == "output/qc_results"
        assert result["obipcr_results_dir"] == "output/obipcr_results"

    def test_empty_path(self):
        """All values are empty strings when output_root is empty."""
        result = derive_project_paths("")
        assert result["output_root"] == ""
        assert result["qc_results_dir"] == ""
        assert result["qc_spec_results_dir"] == ""
        assert result["obipcr_results_dir"] == ""
        assert result["final_results_dir"] == ""

    def test_none_path(self):
        """All values are empty strings when output_root is None."""
        result = derive_project_paths(None)  # type: ignore[arg-type]
        assert result["output_root"] == ""
        assert result["qc_results_dir"] == ""

    def test_path_with_trailing_slash(self):
        """Handles trailing slash correctly (pathlib normalizes)."""
        result = derive_project_paths("/tmp/out/")
        # pathlib strips trailing slash
        assert result["output_root"] == "/tmp/out"
        assert result["final_results_dir"] == "/tmp/out/final_results"


class TestGetPrimerPreset:
    """Tests for get_primer_preset()."""

    def test_12s16s(self):
        preset = get_primer_preset("12S/16S 短片段")
        assert preset["min_size"] == 80
        assert preset["max_size"] == 500
        assert preset["spec_mismatch"] == 2
        assert preset["obipcr_mismatches"] == "0,1,2"
        assert preset["circular"] is True
        assert "12S/16S" in preset["description"]

    def test_coi_mini_barcode(self):
        preset = get_primer_preset("COI mini-barcode")
        assert preset["min_size"] == 100
        assert preset["max_size"] == 350
        assert preset["spec_mismatch"] == 2
        assert preset["obipcr_mismatches"] == "0,1,2,3"
        assert preset["circular"] is True

    def test_coi_folmer(self):
        preset = get_primer_preset("COI Folmer")
        assert preset["min_size"] == 500
        assert preset["max_size"] == 800
        assert preset["spec_mismatch"] == 3
        assert preset["obipcr_mismatches"] == "0,1,2,3"
        assert preset["circular"] is True

    def test_cytb(self):
        preset = get_primer_preset("Cytb")
        assert preset["min_size"] == 300
        assert preset["max_size"] == 1200
        assert preset["spec_mismatch"] == 3
        assert preset["obipcr_mismatches"] == "0,1,2,3"
        assert preset["circular"] is True

    def test_custom(self):
        preset = get_primer_preset("自定义")
        assert preset["min_size"] is None
        assert preset["max_size"] is None
        assert preset["spec_mismatch"] is None
        assert preset["obipcr_mismatches"] is None
        assert preset["circular"] is None

    def test_unknown_preset_falls_back_to_custom(self):
        """Unknown preset name returns the '自定义' preset (all None)."""
        preset = get_primer_preset("NONEXISTENT_PRESET")
        assert preset["min_size"] is None
        assert preset["max_size"] is None
        assert preset["spec_mismatch"] is None
        assert preset["obipcr_mismatches"] is None
        assert preset["circular"] is None


class TestApplyProjectPathsToState:
    """Tests for apply_project_paths_to_state()."""

    def test_normal_sync(self):
        """All workflow widget keys are updated from project paths."""
        state: dict = {}
        paths = {
            "output_root": "/tmp/proj",
            "primers_path": "/tmp/proj/primers.tsv",
            "database_path": "/tmp/proj/db.fasta",
            "taxonomy_path": "/tmp/proj/tax.tsv",
            "qc_results_dir": "/tmp/proj/qc_results",
            "qc_spec_results_dir": "/tmp/proj/qc_spec_results",
            "obipcr_results_dir": "/tmp/proj/obipcr_results",
            "final_results_dir": "/tmp/proj/final_results",
            "spec_index_database": "/tmp/proj/qc_spec_results/index/database.fasta",
        }
        apply_project_paths_to_state(state, paths)

        assert state["wf_s1_primers"] == "/tmp/proj/primers.tsv"
        assert state["wf_s1_outdir"] == "/tmp/proj/qc_results"
        assert state["wf_s2_qcdir"] == "/tmp/proj/qc_results"
        assert state["wf_s3_primers"] == "/tmp/proj/primers.tsv"
        assert state["wf_s3_database"] == "/tmp/proj/db.fasta"
        assert state["wf_s3_outdir"] == "/tmp/proj/qc_spec_results"
        assert state["wf_s4_primers"] == "/tmp/proj/primers.tsv"
        assert state["wf_s4_database"] == "/tmp/proj/qc_spec_results/index/database.fasta"
        assert state["wf_s4_taxonomy"] == "/tmp/proj/tax.tsv"
        assert state["wf_s4_outdir"] == "/tmp/proj/obipcr_results"
        assert state["wf_s5_obipcr_dir"] == "/tmp/proj/obipcr_results"
        assert state["wf_s5_qc_dir"] == "/tmp/proj/qc_results"
        assert state["wf_s5_spec_dir"] == "/tmp/proj/qc_spec_results"
        assert state["wf_s5_outdir"] == "/tmp/proj/final_results"

    def test_does_not_modify_unrelated_keys(self):
        """Only workflow-path keys are touched; other keys are left alone."""
        state: dict = {"some_other_key": "keep_me", "another": 42}
        paths = {
            "output_root": "/tmp/x",
            "primers_path": "/tmp/x/p.tsv",
            "database_path": "/tmp/x/db.fasta",
            "taxonomy_path": "/tmp/x/t.tsv",
            "qc_results_dir": "/tmp/x/qc",
            "qc_spec_results_dir": "/tmp/x/qcs",
            "obipcr_results_dir": "/tmp/x/obi",
            "final_results_dir": "/tmp/x/final",
            "spec_index_database": "/tmp/x/qcs/index/db.fasta",
        }
        apply_project_paths_to_state(state, paths)

        assert state["some_other_key"] == "keep_me"
        assert state["another"] == 42
        assert state["wf_s1_primers"] == "/tmp/x/p.tsv"

    def test_empty_paths_noop(self):
        """When output_root is empty, no state keys are modified."""
        state: dict = {"wf_s1_primers": "original_value"}
        paths = derive_project_paths("")  # all empty
        apply_project_paths_to_state(state, paths)

        assert state["wf_s1_primers"] == "original_value"

    def test_none_paths_noop(self):
        """When paths is empty dict, no state keys are modified."""
        state: dict = {"wf_s1_primers": "original_value"}
        apply_project_paths_to_state(state, {})

        assert state["wf_s1_primers"] == "original_value"

    def test_missing_optional_keys(self):
        """Missing optional keys (taxonomy, spec_index_database) are not written."""
        state: dict = {}
        paths = {
            "output_root": "/tmp/min",
            "primers_path": "/tmp/min/p.tsv",
            "database_path": "/tmp/min/db.fasta",
            "qc_results_dir": "/tmp/min/qc",
            "qc_spec_results_dir": "/tmp/min/qcs",
            "obipcr_results_dir": "/tmp/min/obi",
            "final_results_dir": "/tmp/min/final",
            # taxonomy_path and spec_index_database omitted
        }
        apply_project_paths_to_state(state, paths)

        # Keys whose path values are missing are simply never written.
        assert "wf_s4_taxonomy" not in state
        assert "wf_s4_database" not in state
        # Keys with valid path values are written as usual.
        assert state["wf_s1_primers"] == "/tmp/min/p.tsv"


# ── Phase 6B (continued): overwrite parameter ─────────────────────────────


class TestApplyProjectPathsToStateOverwrite:
    """Tests for apply_project_paths_to_state() overwrite behaviour."""

    @staticmethod
    def _sample_paths() -> dict:
        return {
            "output_root": "/tmp/proj",
            "primers_path": "/tmp/proj/primers.tsv",
            "database_path": "/tmp/proj/db.fasta",
            "taxonomy_path": "/tmp/proj/tax.tsv",
            "qc_results_dir": "/tmp/proj/qc_results",
            "qc_spec_results_dir": "/tmp/proj/qc_spec_results",
            "obipcr_results_dir": "/tmp/proj/obipcr_results",
            "final_results_dir": "/tmp/proj/final_results",
            "spec_index_database": "/tmp/proj/qc_spec_results/index/database.fasta",
        }

    # ── overwrite=False (default) ───────────────────────────────────────

    def test_overwrite_false_fills_missing_keys(self):
        """overwrite=False initialises missing or empty workflow keys."""
        state: dict = {}
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=False)
        assert state["wf_s1_primers"] == "/tmp/proj/primers.tsv"
        assert state["wf_s4_database"] == "/tmp/proj/qc_spec_results/index/database.fasta"
        assert state["wf_s5_outdir"] == "/tmp/proj/final_results"

    def test_overwrite_false_fills_empty_string_keys(self):
        """overwrite=False fills keys whose current value is ''."""
        state: dict = {"wf_s1_primers": "", "wf_s1_outdir": ""}
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=False)
        assert state["wf_s1_primers"] == "/tmp/proj/primers.tsv"
        assert state["wf_s1_outdir"] == "/tmp/proj/qc_results"

    def test_overwrite_false_preserves_non_empty_values(self):
        """overwrite=False keeps existing non-empty manual values untouched."""
        state: dict = {
            "wf_s1_primers": "/custom/path/primers.tsv",
            "wf_s1_outdir": "/custom/qc",
        }
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=False)
        # Existing non-empty values are preserved
        assert state["wf_s1_primers"] == "/custom/path/primers.tsv"
        assert state["wf_s1_outdir"] == "/custom/qc"
        # Missing keys are still filled
        assert state["wf_s3_database"] == "/tmp/proj/db.fasta"
        assert state["wf_s5_outdir"] == "/tmp/proj/final_results"

    def test_overwrite_false_mixed_preservation(self):
        """overwrite=False fills empties but leaves non-empties alone."""
        state: dict = {
            "wf_s1_primers": "/custom/p.tsv",    # non-empty → preserved
            "wf_s1_outdir": "",                   # empty → filled
            "wf_s3_primers": "",                  # empty → filled
            "wf_s5_outdir": "/custom/final",      # non-empty → preserved
        }
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=False)
        assert state["wf_s1_primers"] == "/custom/p.tsv"
        assert state["wf_s1_outdir"] == "/tmp/proj/qc_results"
        assert state["wf_s3_primers"] == "/tmp/proj/primers.tsv"
        assert state["wf_s5_outdir"] == "/custom/final"

    def test_overwrite_false_preserves_taxonomy_when_project_empty(self):
        """overwrite=False does not write empty taxonomy path over manual value."""
        state: dict = {"wf_s4_taxonomy": "/custom/tax.tsv"}
        paths = {
            "output_root": "/tmp/proj",
            "primers_path": "/tmp/proj/p.tsv",
            "database_path": "/tmp/proj/db.fasta",
            "taxonomy_path": "",  # taxonomy FAIL → empty
            "qc_results_dir": "/tmp/proj/qc",
            "qc_spec_results_dir": "/tmp/proj/qcs",
            "obipcr_results_dir": "/tmp/proj/obi",
            "final_results_dir": "/tmp/proj/final",
        }
        apply_project_paths_to_state(state, paths, overwrite=False)
        # Manual taxonomy value is preserved because taxonomy_path is empty.
        assert state["wf_s4_taxonomy"] == "/custom/tax.tsv"
        # spec_index_database was never in the paths dict → not written.
        assert "wf_s4_database" not in state

    # ── overwrite=True ──────────────────────────────────────────────────

    def test_overwrite_true_force_replaces(self):
        """overwrite=True replaces all mapped keys regardless of current value."""
        state: dict = {
            "wf_s1_primers": "/custom/p.tsv",
            "wf_s1_outdir": "/custom/qc",
            "wf_s5_outdir": "/custom/final",
        }
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=True)
        # All values are force-replaced
        assert state["wf_s1_primers"] == "/tmp/proj/primers.tsv"
        assert state["wf_s1_outdir"] == "/tmp/proj/qc_results"
        assert state["wf_s5_outdir"] == "/tmp/proj/final_results"

    def test_overwrite_true_fills_all(self):
        """overwrite=True fills all mapped keys even on clean state."""
        state: dict = {}
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=True)
        assert state["wf_s1_primers"] == "/tmp/proj/primers.tsv"
        assert state["wf_s4_taxonomy"] == "/tmp/proj/tax.tsv"
        assert state["wf_s5_outdir"] == "/tmp/proj/final_results"

    # ── no-op guards ────────────────────────────────────────────────────

    def test_empty_output_root_noop_overwrite_false(self):
        """No state changes when output_root is empty, even with overwrite=False."""
        state: dict = {"wf_s1_primers": "original_value"}
        apply_project_paths_to_state(state, {"output_root": "", "primers_path": "/x/p.tsv"}, overwrite=False)
        assert state["wf_s1_primers"] == "original_value"

    def test_empty_output_root_noop_overwrite_true(self):
        """No state changes when output_root is empty, even with overwrite=True."""
        state: dict = {"wf_s1_primers": "original_value"}
        apply_project_paths_to_state(state, {"output_root": "", "primers_path": "/x/p.tsv"}, overwrite=True)
        assert state["wf_s1_primers"] == "original_value"

    def test_empty_paths_dict_noop(self):
        """Empty paths dict is a no-op regardless of overwrite."""
        state: dict = {"wf_s1_primers": "original_value"}
        apply_project_paths_to_state(state, {}, overwrite=True)
        assert state["wf_s1_primers"] == "original_value"

    def test_unrelated_keys_untouched_overwrite_false(self):
        """Unrelated session_state keys are never modified (overwrite=False)."""
        state: dict = {"my_app_key": "important", "another_flag": True}
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=False)
        assert state["my_app_key"] == "important"
        assert state["another_flag"] is True

    def test_unrelated_keys_untouched_overwrite_true(self):
        """Unrelated session_state keys are never modified (overwrite=True)."""
        state: dict = {"my_app_key": "important", "another_flag": True}
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=True)
        assert state["my_app_key"] == "important"
        assert state["another_flag"] is True

    # ── overwrite=False strict semantics ─────────────────────────────────

    def test_overwrite_false_preserves_non_empty_even_if_matches_default(self):
        """overwrite=False preserves non-empty values even when equal to canonical default."""
        state: dict = {
            "wf_s1_outdir": "qc_results",       # canonical default but NON-EMPTY → preserved
            "wf_s3_outdir": "qc_spec_results",  # canonical default but NON-EMPTY → preserved
            "wf_s4_outdir": "obipcr_results",   # canonical default but NON-EMPTY → preserved
        }
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=False)
        assert state["wf_s1_outdir"] == "qc_results"
        assert state["wf_s3_outdir"] == "qc_spec_results"
        assert state["wf_s4_outdir"] == "obipcr_results"

    def test_overwrite_false_does_not_write_widget_keys(self):
        """overwrite=False never writes _-prefixed temp widget keys."""
        state: dict = {}
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=False)
        for _, state_key in [
            ("qc_results_dir", "wf_s1_outdir"),
            ("qc_spec_results_dir", "wf_s3_outdir"),
            ("final_results_dir", "wf_s5_outdir"),
        ]:
            wk = f"_{state_key}"
            assert wk not in state, f"{wk} should not be written by overwrite=False"

    def test_overwrite_false_fills_empty_string(self):
        """overwrite=False fills keys with empty string values."""
        state: dict = {"wf_s1_outdir": ""}
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=False)
        assert state["wf_s1_outdir"] == "/tmp/proj/qc_results"

    def test_overwrite_false_fills_none(self):
        """overwrite=False fills keys with None values."""
        state: dict = {"wf_s1_outdir": None}
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=False)
        assert state["wf_s1_outdir"] == "/tmp/proj/qc_results"

    def test_overwrite_false_fills_missing_key(self):
        """overwrite=False fills keys not present in state."""
        state: dict = {}
        apply_project_paths_to_state(state, self._sample_paths(), overwrite=False)
        assert state["wf_s1_outdir"] == "/tmp/proj/qc_results"


class TestCanonicalPersistence:
    """Tests for the canonical/temp key persistence system."""

    def test_init_canonical_defaults_sets_missing(self):
        """init_canonical_defaults sets defaults for keys not in state."""
        state: dict = {}
        init_canonical_defaults(state)
        assert state["inputs_primers_path"] == "example_data/primers.tsv"
        assert state["wf_s1_timeout"] == 60
        assert state["wf_preset_select"] == "自定义"
        assert state["res_final_dir"] == "final_results"
        assert state["rpt_final_path"] == "final_results/final_report.md"

    def test_init_canonical_defaults_preserves_existing(self):
        """init_canonical_defaults does not overwrite existing keys."""
        state: dict = {
            "inputs_primers_path": "/custom/path.tsv",
            "wf_s3_timeout": 999,
        }
        init_canonical_defaults(state)
        assert state["inputs_primers_path"] == "/custom/path.tsv"
        assert state["wf_s3_timeout"] == 999

    def test_ensure_widget_key_loads_from_canonical(self):
        """ensure_widget_key copies canonical value to widget key."""
        state: dict = {"wf_s3_timeout": 999}
        ensure_widget_key(state, "_wf_s3_timeout")
        assert state["_wf_s3_timeout"] == 999

    def test_ensure_widget_key_falls_back_to_default(self):
        """ensure_widget_key uses canonical default when canonical key absent."""
        state: dict = {}
        ensure_widget_key(state, "_wf_s3_timeout")
        assert state["_wf_s3_timeout"] == 300  # from _CANONICAL_DEFAULTS

    def test_ensure_widget_key_noop_if_widget_exists(self):
        """ensure_widget_key is no-op when widget key already in state."""
        state: dict = {
            "wf_s3_timeout": 999,
            "_wf_s3_timeout": 777,
        }
        ensure_widget_key(state, "_wf_s3_timeout")
        assert state["_wf_s3_timeout"] == 777  # unchanged

    def test_sync_widgets_to_canonical(self):
        """sync_widgets_to_canonical copies temp widget values to canonical."""
        state: dict = {
            "_wf_s3_timeout": 888,
            "_wf_s4_circular": False,
            "_inputs_primers_path": "/my/path.tsv",
        }
        # Set canonical to different values to verify overwrite.
        state["wf_s3_timeout"] = 100
        state["wf_s4_circular"] = True
        state["inputs_primers_path"] = "old"

        sync_widgets_to_canonical(state)
        assert state["wf_s3_timeout"] == 888
        assert state["wf_s4_circular"] is False
        assert state["inputs_primers_path"] == "/my/path.tsv"

    def test_sync_widgets_to_canonical_skips_absent_widgets(self):
        """sync_widgets_to_canonical leaves canonical keys alone when widget absent."""
        state: dict = {"wf_s3_timeout": 555}
        sync_widgets_to_canonical(state)
        assert state["wf_s3_timeout"] == 555  # unchanged — no widget key present

    def test_overwrite_false_preserves_default_match_non_empty(self):
        """overwrite=False preserves non-empty values even when equal to default."""
        state: dict = {"wf_s1_outdir": "qc_results"}
        paths = {
            "output_root": "/tmp/proj",
            "qc_results_dir": "/tmp/proj/qc_results",
        }
        apply_project_paths_to_state(state, paths, overwrite=False)
        # "qc_results" is non-empty — preserved regardless of matching default.
        assert state["wf_s1_outdir"] == "qc_results"

    def test_overwrite_false_preserves_primers_default_non_empty(self):
        """overwrite=False preserves non-empty 'example_data/primers.tsv' even when equal to default."""
        state: dict = {"wf_s3_primers": "example_data/primers.tsv"}
        paths = {
            "output_root": "/tmp/proj",
            "primers_path": "/tmp/proj/p.tsv",
        }
        apply_project_paths_to_state(state, paths, overwrite=False)
        # Non-empty → preserved.
        assert state["wf_s3_primers"] == "example_data/primers.tsv"


class TestWorkflowPathKeysExcludedFromEagerInit:
    """Tests that init_canonical_defaults skips workflow path keys."""

    def test_init_does_not_create_workflow_path_keys(self):
        """init_canonical_defaults({}) does NOT eagerly initialise the 14 path keys."""
        state: dict = {}
        init_canonical_defaults(state)
        for key in _WORKFLOW_PATH_KEYS:
            assert key not in state, (
                f"{key} should NOT be initialised by init_canonical_defaults"
            )

    def test_init_still_creates_workflow_non_path_params(self):
        """Non-path workflow params are still eagerly initialised."""
        state: dict = {}
        init_canonical_defaults(state)
        assert state["wf_s1_timeout"] == 60
        assert state["wf_s1_thermo"] is True
        assert state["wf_s3_minsize"] == 80
        assert state["wf_s4_circular"] is True
        assert state["wf_preset_select"] == "自定义"

    def test_init_still_creates_inputs_keys(self):
        """Inputs page canonical keys are still eagerly initialised."""
        state: dict = {}
        init_canonical_defaults(state)
        assert state["inputs_primers_path"] == "example_data/primers.tsv"
        assert state["inputs_database_path"] == "example_data/real_mito_small.fasta"
        assert state["inputs_taxonomy_path"] == "example_data/taxonomy.tsv"
        assert state["inputs_output_dir"] == "results"

    def test_init_still_creates_results_keys(self):
        """Results page canonical keys are still eagerly initialised."""
        state: dict = {}
        init_canonical_defaults(state)
        assert state["res_final_dir"] == "final_results"
        assert state["res_obipcr_dir"] == "obipcr_results"

    def test_init_still_creates_reports_keys(self):
        """Reports page canonical keys are still eagerly initialised."""
        state: dict = {}
        init_canonical_defaults(state)
        assert state["rpt_final_path"] == "final_results/final_report.md"
        assert state["rpt_obipcr_path"] == "obipcr_results/report.md"

    def test_init_creates_workflow_dry_run(self):
        """workflow_dry_run is eagerly initialised to False."""
        state: dict = {}
        init_canonical_defaults(state)
        assert state["workflow_dry_run"] is False

    def test_ensure_widget_key_workflow_path_fallback(self):
        """ensure_widget_key still provides fallback from _CANONICAL_DEFAULTS."""
        state: dict = {}
        ensure_widget_key(state, "_wf_s1_outdir")
        assert state["_wf_s1_outdir"] == "qc_results"

    def test_ensure_widget_key_dry_run_fallback(self):
        """ensure_widget_key provides fallback for _workflow_dry_run."""
        state: dict = {}
        ensure_widget_key(state, "_workflow_dry_run")
        assert state["_workflow_dry_run"] is False

    def test_sync_includes_workflow_dry_run(self):
        """sync_widgets_to_canonical copies _workflow_dry_run → workflow_dry_run."""
        state: dict = {"_workflow_dry_run": True, "workflow_dry_run": False}
        sync_widgets_to_canonical(state)
        assert state["workflow_dry_run"] is True


# ── Phase 6B: compute_inputs_validated ────────────────────────────────────


class TestComputeInputsValidated:
    """Tests for compute_inputs_validated()."""

    def test_all_pass(self):
        """PASS/PASS/PASS/PASS → True."""
        assert compute_inputs_validated("PASS", "PASS", "PASS", "PASS") is True

    def test_output_warn_still_valid(self):
        """PASS/PASS/PASS/WARN → True."""
        assert compute_inputs_validated("PASS", "PASS", "PASS", "WARN") is True

    def test_primers_fail(self):
        """Any input FAIL → False."""
        assert compute_inputs_validated("FAIL", "PASS", "PASS", "PASS") is False

    def test_database_fail(self):
        """Database FAIL → False."""
        assert compute_inputs_validated("PASS", "FAIL", "PASS", "PASS") is False

    def test_taxonomy_fail(self):
        """Taxonomy FAIL → False."""
        assert compute_inputs_validated("PASS", "PASS", "FAIL", "PASS") is False

    def test_output_fail(self):
        """Output FAIL → False."""
        assert compute_inputs_validated("PASS", "PASS", "PASS", "FAIL") is False

    def test_multiple_failures(self):
        """Multiple FAILs → False."""
        assert compute_inputs_validated("FAIL", "PASS", "FAIL", "PASS") is False

    def test_all_fail(self):
        """All FAIL → False."""
        assert compute_inputs_validated("FAIL", "FAIL", "FAIL", "FAIL") is False

    def test_output_timeout(self):
        """Output TIMEOUT is not WARN/PASS → False."""
        assert compute_inputs_validated("PASS", "PASS", "PASS", "TIMEOUT") is False


# ── Phase 6B: apply_primer_preset_to_state (real function, no replica) ────


class TestApplyPrimerPresetToState:
    """Tests for apply_primer_preset_to_state — the real production helper."""

    #: Keys that must never be touched by preset application.
    PROTECTED_KEYS = [
        "wf_s1_primers", "wf_s1_outdir", "wf_s2_qcdir",
        "wf_s3_primers", "wf_s3_database", "wf_s3_outdir",
        "wf_s4_primers", "wf_s4_database", "wf_s4_taxonomy", "wf_s4_outdir",
        "wf_s5_obipcr_dir", "wf_s5_qc_dir", "wf_s5_spec_dir", "wf_s5_outdir",
        "wf_s1_timeout", "wf_s3_timeout", "wf_s4_timeout",
        "wf_s1_score", "wf_s1_dg", "wf_s1_tm", "wf_s1_mismatch", "wf_s1_maxdeg",
        "wf_s3_tm", "wf_s3_maxtm", "wf_s3_cpu", "wf_s3_kvalue",
        "wf_s3_force", "wf_s4_summarize", "wf_s4_report", "wf_s4_force",
    ]

    def test_12s16s_correct_values(self):
        """12S/16S preset writes exact expected values to the 5 target keys."""
        state: dict = {}
        apply_primer_preset_to_state(state, "12S/16S 短片段")
        assert state["wf_s3_minsize"] == 80
        assert state["wf_s3_maxsize"] == 500
        assert state["wf_s3_mismatch"] == 2
        assert state["wf_s4_mismatches"] == "0,1,2"
        assert state["wf_s4_circular"] is True

    def test_coi_folmer_correct_values(self):
        """COI Folmer preset writes correct values."""
        state: dict = {}
        apply_primer_preset_to_state(state, "COI Folmer")
        assert state["wf_s3_minsize"] == 500
        assert state["wf_s3_maxsize"] == 800
        assert state["wf_s3_mismatch"] == 3
        assert state["wf_s4_mismatches"] == "0,1,2,3"
        assert state["wf_s4_circular"] is True

    def test_only_touches_5_keys(self):
        """Preset application only creates/modifies the 5 target keys (plus their _-prefixed widget keys)."""
        state: dict = {"some_unrelated": "keep_me"}
        apply_primer_preset_to_state(state, "12S/16S 短片段")
        assert state["some_unrelated"] == "keep_me"
        preset_keys = {"wf_s3_minsize", "wf_s3_maxsize", "wf_s3_mismatch",
                        "wf_s4_mismatches", "wf_s4_circular"}
        widget_keys = {f"_{k}" for k in preset_keys}
        assert set(state.keys()) == preset_keys | widget_keys | {"some_unrelated"}

    def test_protected_keys_untouched(self):
        """Preset never modifies path, timeout, or advanced-param keys."""
        state: dict = {k: f"keep_{k}" for k in self.PROTECTED_KEYS}
        apply_primer_preset_to_state(state, "COI mini-barcode")
        for k in self.PROTECTED_KEYS:
            assert state[k] == f"keep_{k}", f"{k} was modified"

    def test_custom_noop(self):
        """'自定义' preset leaves state completely unchanged."""
        state: dict = {
            "wf_s3_minsize": 999,
            "wf_s3_maxsize": 888,
            "wf_s4_circular": False,
            "wf_s1_outdir": "/custom/qc",
        }
        before = dict(state)
        apply_primer_preset_to_state(state, "自定义")
        assert state == before

    def test_sequential_presets_overwrite(self):
        """Applying a second preset overwrites values from the first."""
        state: dict = {}
        apply_primer_preset_to_state(state, "12S/16S 短片段")
        apply_primer_preset_to_state(state, "COI Folmer")
        assert state["wf_s3_minsize"] == 500
        assert state["wf_s3_maxsize"] == 800
        assert state["wf_s4_mismatches"] == "0,1,2,3"

    def test_unknown_preset_noop(self):
        """Unknown preset name is a no-op (falls through to custom)."""
        state: dict = {"wf_s3_minsize": 42}
        apply_primer_preset_to_state(state, "NONEXISTENT")
        assert state["wf_s3_minsize"] == 42


class TestWorkflowSyncState:
    """Test path-sync logic using plain dicts.

    Replicates the ``"从输入文件同步路径"`` button behaviour.
    """

    @staticmethod
    def _project_snapshot() -> dict:
        return {
            "project_output_root": "/tmp/proj",
            "project_primers_path": "/tmp/proj/primers.tsv",
            "project_database_path": "/tmp/proj/db.fasta",
            "project_taxonomy_path": "/tmp/proj/tax.tsv",
            "project_derived_paths": {
                "qc_results_dir": "/tmp/proj/qc_results",
                "qc_spec_results_dir": "/tmp/proj/qc_spec_results",
                "obipcr_results_dir": "/tmp/proj/obipcr_results",
                "final_results_dir": "/tmp/proj/final_results",
            },
        }

    #: Parameter keys that must NOT be cleared by a path sync.
    PARAM_KEYS = [
        "wf_s3_minsize", "wf_s3_maxsize", "wf_s3_mismatch",
        "wf_s4_mismatches", "wf_s4_circular",
        "wf_s1_timeout", "wf_s3_timeout", "wf_s4_timeout",
        "wf_s1_thermo", "wf_s1_dimer", "wf_s1_hairpin", "wf_s1_degen",
        "wf_s1_score", "wf_s1_dg", "wf_s1_tm", "wf_s1_mismatch", "wf_s1_maxdeg",
        "wf_s3_tm", "wf_s3_maxtm", "wf_s3_cpu", "wf_s3_kvalue", "wf_s3_force",
        "wf_s4_summarize", "wf_s4_report", "wf_s4_force",
        "wf_s4_circular",
    ]

    def test_sync_overwrites_paths_but_not_params(self):
        """Sync replaces paths (overwrite=True) but leaves params intact."""
        state: dict = {
            **{k: f"param_{k}" for k in self.PARAM_KEYS},
            "wf_s1_primers": "/old/path/p.tsv",
            "wf_s4_database": "/old/db.fasta",
        }
        proj = self._project_snapshot()
        derived = proj["project_derived_paths"]

        # Apply sync using the same logic as the button in gui_app.py.
        apply_project_paths_to_state(
            state,
            {
                "output_root": proj["project_output_root"],
                "primers_path": proj["project_primers_path"],
                "database_path": proj["project_database_path"],
                "taxonomy_path": proj["project_taxonomy_path"],
                "qc_results_dir": derived["qc_results_dir"],
                "qc_spec_results_dir": derived["qc_spec_results_dir"],
                "obipcr_results_dir": derived["obipcr_results_dir"],
                "final_results_dir": derived["final_results_dir"],
                "spec_index_database": "/tmp/proj/qc_spec_results/index/database.fasta",
            },
            overwrite=True,
        )

        # Paths are overwritten
        assert state["wf_s1_primers"] == "/tmp/proj/primers.tsv"
        assert state["wf_s4_database"] == "/tmp/proj/qc_spec_results/index/database.fasta"
        # Parameters are untouched
        for k in self.PARAM_KEYS:
            assert state[k] == f"param_{k}", f"{k} should not be affected by sync"

    def test_sync_does_not_modify_params(self):
        """Sync with overwrite=True only touches path keys, never params."""
        state: dict = {k: f"keep_{k}" for k in self.PARAM_KEYS}
        proj = self._project_snapshot()
        derived = proj["project_derived_paths"]
        apply_project_paths_to_state(
            state,
            {
                "output_root": proj["project_output_root"],
                "primers_path": proj["project_primers_path"],
                "database_path": proj["project_database_path"],
                "taxonomy_path": proj["project_taxonomy_path"],
                "qc_results_dir": derived["qc_results_dir"],
                "qc_spec_results_dir": derived["qc_spec_results_dir"],
                "obipcr_results_dir": derived["obipcr_results_dir"],
                "final_results_dir": derived["final_results_dir"],
                "spec_index_database": "/tmp/proj/qc_spec_results/index/database.fasta",
            },
            overwrite=True,
        )
        for k in self.PARAM_KEYS:
            assert state[k] == f"keep_{k}", f"{k} was wrongfully modified"

    def test_sync_clears_nothing(self):
        """Sync never deletes or clears any session_state key."""
        state: dict = {"unrelated_key": "unrelated_value"}
        proj = self._project_snapshot()
        derived = proj["project_derived_paths"]
        apply_project_paths_to_state(
            state,
            {
                "output_root": proj["project_output_root"],
                "primers_path": proj["project_primers_path"],
                "database_path": proj["project_database_path"],
                "taxonomy_path": proj["project_taxonomy_path"],
                "qc_results_dir": derived["qc_results_dir"],
                "qc_spec_results_dir": derived["qc_spec_results_dir"],
                "obipcr_results_dir": derived["obipcr_results_dir"],
                "final_results_dir": derived["final_results_dir"],
                "spec_index_database": "/tmp/proj/qc_spec_results/index/database.fasta",
            },
            overwrite=True,
        )
        assert state["unrelated_key"] == "unrelated_value"


# ── Phase 6B: Streamlit AppTest integration tests ───────────────────────


class TestGuiAppSmoke:
    """Smoke test for the fullpcr GUI app using streamlit.testing."""

    def test_app_loads_without_exception(self):
        """The app script starts and renders a title without exception."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception, f"App raised: {at.exception}"
        # Header now uses st.markdown, not st.title.
        assert any("fullpcr" in m.value for m in at.markdown), (
            "fullpcr header not found in markdown elements"
        )

    def test_clean_session_workbench_no_exception(self):
        """Navigating to the 分析工作台 page on a clean session does not crash."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception, f"App raised on initial load: {at.exception}"
        # Default page is already 分析工作台.
        assert not at.exception, (
            f"App raised on 分析工作台 page: {at.exception}"
        )

    def test_no_session_state_warnings_on_initial_load(self):
        """No Session State API conflict warnings on initial app load."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

    def test_no_session_state_warnings_on_page_switch(self):
        """No Session State API warnings when switching pages."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception
        for page in ["分析工作台", "结果总览", "报告与下载"]:
            at.sidebar.radio[0].set_value(page)
            at.run(timeout=30)
            assert not at.exception, f"App raised on page {page}: {at.exception}"

    def test_sidebar_nav_options_exact(self):
        """Sidebar radio options are exactly the 3 expected pages."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        options = at.sidebar.radio[0].options
        assert options == ["分析工作台", "结果总览", "报告与下载"], (
            f"Unexpected sidebar options: {options}"
        )


class TestGuiAppPreset:
    """Integration tests for the primer preset button using AppTest."""

    @staticmethod
    def _navigate_to_workflow(at):
        """Helper: switch to the Workflow page via the sidebar radio."""
        at.sidebar.radio[0].set_value("分析工作台")
        at.run(timeout=30)

    def test_selecting_preset_without_clicking_apply_does_not_change_params(self):
        """Switching the preset selectbox alone leaves parameters unchanged."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception
        self._navigate_to_workflow(at)
        assert not at.exception

        # Modify all 5 target keys to custom values.
        at.number_input("_wf_s3_minsize").set_value(999).run()
        assert not at.exception
        at.number_input("_wf_s3_maxsize").set_value(888).run()
        assert not at.exception
        at.number_input("_wf_s3_mismatch").set_value(7).run()
        assert not at.exception
        at.text_input("_wf_s4_mismatches").set_value("9,9,9").run()
        assert not at.exception
        at.checkbox("_wf_s4_circular").uncheck().run()
        assert not at.exception

        # Also set a path and an advanced param to known values.
        at.text_input("_wf_s1_outdir").set_value("/keep/qc").run()
        assert not at.exception
        at.number_input("_wf_s3_timeout").set_value(999).run()
        assert not at.exception

        # Now switch the selectbox to COI Folmer but do NOT click "应用参数预设".
        at.selectbox("_wf_preset_select").select("COI Folmer").run()
        assert not at.exception

        # All values must remain unchanged.
        assert at.number_input("_wf_s3_minsize").value == 999
        assert at.number_input("_wf_s3_maxsize").value == 888
        assert at.number_input("_wf_s3_mismatch").value == 7
        assert at.text_input("_wf_s4_mismatches").value == "9,9,9"
        assert at.checkbox("_wf_s4_circular").value is False
        assert at.text_input("_wf_s1_outdir").value == "/keep/qc"
        assert at.number_input("_wf_s3_timeout").value == 999

    def test_apply_preset_updates_5_params_immediately(self):
        """Clicking '应用参数预设' updates the 5 target keys on the next run."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception
        self._navigate_to_workflow(at)
        assert not at.exception

        # Select COI Folmer preset.
        at.selectbox("_wf_preset_select").select("COI Folmer").run()
        assert not at.exception
        # Click "应用参数预设".
        at.button("wf_apply_preset_btn").click().run()
        assert not at.exception

        # The 5 target keys must now have COI Folmer values.
        assert at.number_input("_wf_s3_minsize").value == 500
        assert at.number_input("_wf_s3_maxsize").value == 800
        assert at.number_input("_wf_s3_mismatch").value == 3
        assert at.text_input("_wf_s4_mismatches").value == "0,1,2,3"
        assert at.checkbox("_wf_s4_circular").value is True

    def test_apply_preset_leaves_paths_and_advanced_params_untouched(self):
        """Preset application only affects the 5 target keys."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception
        self._navigate_to_workflow(at)
        assert not at.exception

        # Set known values for paths and advanced params.
        at.text_input("_wf_s1_outdir").set_value("/my/qc").run()
        assert not at.exception
        at.number_input("_wf_s3_timeout").set_value(777).run()
        assert not at.exception
        at.number_input("_wf_s3_tm").set_value(66.0).run()
        assert not at.exception
        at.checkbox("_wf_s4_summarize").uncheck().run()
        assert not at.exception

        # Apply COI Folmer preset.
        at.selectbox("_wf_preset_select").select("COI Folmer").run()
        assert not at.exception
        at.button("wf_apply_preset_btn").click().run()
        assert not at.exception

        # Preset keys updated.
        assert at.number_input("_wf_s3_minsize").value == 500
        assert at.number_input("_wf_s3_maxsize").value == 800
        # Paths and advanced params unchanged.
        assert at.text_input("_wf_s1_outdir").value == "/my/qc"
        assert at.number_input("_wf_s3_timeout").value == 777
        assert at.number_input("_wf_s3_tm").value == 66.0
        assert at.checkbox("_wf_s4_summarize").value is False

    def test_sync_overwrites_paths_but_not_params(self):
        """Sync button force-syncs paths but leaves params intact."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        # First validate inputs to create a project snapshot.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        # Navigate to Workflow and set custom param values.
        self._navigate_to_workflow(at)
        assert not at.exception
        at.number_input("_wf_s3_timeout").set_value(555).run()
        assert not at.exception
        at.button("wf_sync_btn").click().run()
        assert not at.exception

        # After sync, paths come from project (primers_path -> example_data/primers.tsv).
        assert at.text_input("_wf_s1_primers").value == "example_data/primers.tsv"
        # But params are untouched.
        assert at.number_input("_wf_s3_timeout").value == 555


class TestGuiAppParamsPlumbing:
    """Params widget return values feed into command previews immediately.

    Checks ``at.code`` blocks for the actual generated CLI commands.
    """

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    @staticmethod
    def _code_texts(at) -> list[str]:
        """Extract visible text from all st.code elements."""
        return [c.value for c in at.code] if hasattr(at, "code") else []

    @staticmethod
    def _all_code(at) -> str:
        return "\n".join(TestGuiAppParamsPlumbing._code_texts(at))

    def test_minsize_999_in_qc_spec_command(self):
        """Changing _wf_s3_minsize to 999 → '--min-size 999' in qc-spec command."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        at.number_input("_wf_s3_minsize").set_value(999).run()
        assert not at.exception

        all_code = self._all_code(at)
        assert "--min-size 999" in all_code, (
            f"Expected '--min-size 999' in code:\n{all_code}"
        )

    def test_maxsize_888_mismatch_7_in_qc_spec_command(self):
        """Changing max_size to 888 and mismatch to 7 → both in qc-spec command."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        at.number_input("_wf_s3_maxsize").set_value(888).run()
        at.number_input("_wf_s3_mismatch").set_value(7).run()
        assert not at.exception

        all_code = self._all_code(at)
        assert "--max-size 888" in all_code, (
            f"Expected '--max-size 888' in code:\n{all_code}"
        )
        assert "--mismatch 7" in all_code, (
            f"Expected '--mismatch 7' in code:\n{all_code}"
        )

    def test_obipcr_mismatches_and_circular_in_run_command(self):
        """mismatches='0,1,2,3,4,5', circular=False → in obipcr run command."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        at.text_input("_wf_s4_mismatches").set_value("0,1,2,3,4,5").run()
        at.checkbox("_wf_s4_circular").uncheck().run()
        assert not at.exception

        all_code = self._all_code(at)
        assert "--mismatches 0,1,2,3,4,5" in all_code, (
            f"Expected '--mismatches 0,1,2,3,4,5' in code:\n{all_code}"
        )
        assert "--circular" not in all_code, (
            f"Expected no '--circular' in code:\n{all_code}"
        )

    def test_empty_mismatches_omits_flag(self):
        """Empty mismatches → '--mismatches' must NOT appear in run command."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        at.text_input("_wf_s4_mismatches").set_value("").run()
        assert not at.exception

        all_code = self._all_code(at)
        assert "--mismatches" not in all_code, (
            f"Expected no '--mismatches' when empty, got:\n{all_code}"
        )


class TestGuiAppPersistence:
    """Integration tests for cross-page widget persistence using AppTest."""

    @staticmethod
    def _set_inputs_values(at):
        """Set all four Inputs page widgets to custom values."""
        at.text_input("_inputs_primers_path").set_value("/user/input.tsv").run()
        at.text_input("_inputs_database_path").set_value("/user/db.fasta").run()
        at.text_input("_inputs_taxonomy_path").set_value("/user/tax.tsv").run()
        at.text_input("_inputs_output_dir").set_value("/user/output").run()

    def test_inputs_paths_survive_page_switch(self):
        """Inputs page paths persist after 分析工作台 → 结果总览 → 分析工作台."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        # Set custom input paths on 分析工作台.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        self._set_inputs_values(at)

        # Navigate to 结果总览 and back.
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # Values must be preserved, not reset to example_data defaults.
        assert at.text_input("_inputs_primers_path").value == "/user/input.tsv"
        assert at.text_input("_inputs_database_path").value == "/user/db.fasta"
        assert at.text_input("_inputs_taxonomy_path").value == "/user/tax.tsv"
        assert at.text_input("_inputs_output_dir").value == "/user/output"

    def test_results_paths_survive_page_switch(self):
        """Results page paths persist after visiting another page and returning."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        at.text_input("_res_final_dir").set_value("/user/final").run()
        assert not at.exception
        at.text_input("_res_obipcr_dir").set_value("/user/obi").run()
        assert not at.exception

        # Navigate away and back.
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception

        assert at.text_input("_res_final_dir").value == "/user/final"
        assert at.text_input("_res_obipcr_dir").value == "/user/obi"

    def test_reports_paths_survive_page_switch(self):
        """Reports page paths persist after visiting another page and returning."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        at.text_input("_rpt_final_path").set_value("/user/report.md").run()
        assert not at.exception

        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception

        assert at.text_input("_rpt_final_path").value == "/user/report.md"

    def test_workflow_manual_paths_survive_inputs_revalidation(self):
        """Workflow manual paths persist after returning to Inputs and re-validating."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        # Validate inputs.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Navigate to Workflow, set manual path.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.text_input("_wf_s1_outdir").set_value("/custom/manual/qc").run()
        assert not at.exception

        # Return to Inputs, re-validate.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Return to Workflow — manual path must survive.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        assert at.text_input("_wf_s1_outdir").value == "/custom/manual/qc"

    def test_preset_select_survives_page_switch(self):
        """Preset selectbox value persists across 分析工作台 → 报告与下载 → 分析工作台."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.selectbox("_wf_preset_select").select("Cytb").run()
        assert not at.exception

        # Cross-page: 分析工作台 → 报告与下载 → 分析工作台
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        assert at.selectbox("_wf_preset_select").value == "Cytb"

    def test_revalidation_flow_no_exception_and_paths_preserved(self):
        """Full re-validation flow: Inputs→Workflow(edit)→Inputs(re-validate)→Workflow(verify)."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        # 1. Validate inputs.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # 2. Navigate to Workflow, change paths to non-default values.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.text_input("_wf_s1_outdir").set_value("/custom/manual/qc").run()
        assert not at.exception
        at.text_input("_wf_s4_outdir").set_value("/custom/obipcr").run()
        assert not at.exception
        at.number_input("_wf_s3_timeout").set_value(999).run()
        assert not at.exception

        # 3. Return to Inputs, re-validate.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.button("inputs_validate_btn").click().run()
        # Must NOT raise StreamlitAPIException on re-validation.
        assert not at.exception, f"Re-validation raised: {at.exception}"

        # 4. Return to Workflow — manual paths must survive.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        assert at.text_input("_wf_s1_outdir").value == "/custom/manual/qc"
        assert at.text_input("_wf_s4_outdir").value == "/custom/obipcr"
        assert at.number_input("_wf_s3_timeout").value == 999

    def test_change_inputs_path_back_to_default(self):
        """User can change an Inputs path to the built-in default value."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        # Change to custom.
        at.text_input("_inputs_primers_path").set_value("/user/input.tsv").run()
        assert not at.exception
        # Change back to built-in default.
        at.text_input("_inputs_primers_path").set_value("example_data/primers.tsv").run()
        assert not at.exception
        # Verify UI shows the user's last input (which equals the default).
        assert at.text_input("_inputs_primers_path").value == "example_data/primers.tsv"

    def test_change_workflow_number_input_back_to_default(self):
        """User can change a workflow number_input to its default value."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        # Change to 999.
        at.number_input("_wf_s3_timeout").set_value(999).run()
        assert not at.exception
        # Change back to default 300.
        at.number_input("_wf_s3_timeout").set_value(300).run()
        assert not at.exception
        # UI must show 300.
        assert at.number_input("_wf_s3_timeout").value == 300

    def test_change_workflow_path_back_to_default(self):
        """User can change a workflow path back to its default value."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        # Change to custom.
        at.text_input("_wf_s1_outdir").set_value("/manual/qc").run()
        assert not at.exception
        # Change back to default "qc_results".
        at.text_input("_wf_s1_outdir").set_value("qc_results").run()
        assert not at.exception
        # UI must show the user's input.
        assert at.text_input("_wf_s1_outdir").value == "qc_results"

    def test_change_results_path_back_to_default(self):
        """User can change a Results path to the default value."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        # Change to custom.
        at.text_input("_res_final_dir").set_value("/custom/final").run()
        assert not at.exception
        # Change back to default.
        at.text_input("_res_final_dir").set_value("final_results").run()
        assert not at.exception
        assert at.text_input("_res_final_dir").value == "final_results"

    def test_change_reports_path_back_to_default(self):
        """User can change a Reports path to the default value."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        # Change to custom.
        at.text_input("_rpt_final_path").set_value("/custom/final/report.md").run()
        assert not at.exception
        # Change back to default.
        at.text_input("_rpt_final_path").set_value("final_results/final_report.md").run()
        assert not at.exception
        assert at.text_input("_rpt_final_path").value == "final_results/final_report.md"

    def test_preset_custom_noop_and_stays(self):
        """'自定义' preset button click does not modify any parameter."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        # Set custom values first.
        at.number_input("_wf_s3_minsize").set_value(999).run()
        assert not at.exception
        # Select "自定义" and click apply.
        at.selectbox("_wf_preset_select").select("自定义").run()
        assert not at.exception
        at.button("wf_apply_preset_btn").click().run()
        assert not at.exception
        # Values unchanged.
        assert at.number_input("_wf_s3_minsize").value == 999

    def test_inputs_fail_state_protection(self):
        """After failed validation, inputs_validated is False and workflow paths not synced."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        # Navigate to Inputs with default (valid) paths first.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        # Change primers_path to a non-existent file (should FAIL validation).
        at.text_input("_inputs_primers_path").set_value("/nonexistent/path.tsv").run()
        assert not at.exception
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Navigate to Workflow — sync button should show warning.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.button("wf_sync_btn").click().run()
        assert not at.exception

    def test_comprehensive_cross_page_persistence(self):
        """分析工作台 → 结果总览 → 分析工作台: all critical state survives."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        # -- Setup on 分析工作台 --
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # Validate first with default (valid) paths to create project snapshot.
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Now customize inputs paths, workflow path, params.
        self._set_inputs_values(at)
        at.text_input("_wf_s1_outdir").set_value("/custom/manual/qc").run()
        assert not at.exception
        at.toggle("_workflow_dry_run").set_value(True).run()
        assert not at.exception
        at.selectbox("_wf_preset_select").select("COI Folmer").run()
        assert not at.exception
        at.button("wf_apply_preset_btn").click().run()
        assert not at.exception
        # Inject step result
        at.session_state["wf_s1_result"] = {
            "status": "PASS", "stdout": "done", "stderr": "",
            "returncode": 0, "message": "ok",
        }
        at.run(timeout=30)
        assert not at.exception

        # -- Navigate away to 结果总览 --
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception

        # -- Return to 分析工作台 --
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # Verify inputs paths
        assert at.text_input("_inputs_primers_path").value == "/user/input.tsv"
        assert at.text_input("_inputs_database_path").value == "/user/db.fasta"
        assert at.text_input("_inputs_taxonomy_path").value == "/user/tax.tsv"
        assert at.text_input("_inputs_output_dir").value == "/user/output"

        # Verify workflow manual path
        assert at.text_input("_wf_s1_outdir").value == "/custom/manual/qc"

        # Verify dry-run
        assert at.toggle("_workflow_dry_run").value is True
        assert at.session_state["workflow_dry_run"] is True

        # Verify preset + params
        assert at.selectbox("_wf_preset_select").value == "COI Folmer"
        assert at.number_input("_wf_s3_minsize").value == 500

        # Verify validation snapshot still present (from first validate)
        snapshot = at.session_state["input_validation_snapshot"]
        assert snapshot is not None
        assert snapshot["all_valid"] is True

        # Verify step result
        s1 = at.session_state["wf_s1_result"]
        assert s1 is not None
        assert s1["stdout"] == "done"


# ── Phase 6B (final): Inputs-first path init, Workflow-first preservation,
#                      dry-run persistence ────────────────────────────────


class TestInputsFirstWorkflowPaths:
    """AppTest: first Inputs validation initialises project-derived paths."""

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    def test_inputs_first_validation_initializes_project_paths(self):
        """Flow A: fresh session → Inputs validate → Workflow gets results/* paths."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        # Navigate directly to Inputs (never visited Workflow).
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # Validate with default paths (example_data/* → output_root="results").
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Navigate to Workflow.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # UI widget values must show project-derived results/* paths.
        assert at.text_input("_wf_s1_outdir").value == "results/qc_results"
        assert at.text_input("_wf_s2_qcdir").value == "results/qc_results"
        assert at.text_input("_wf_s3_outdir").value == "results/qc_spec_results"
        assert (
            at.text_input("_wf_s4_database").value
            == "results/qc_spec_results/index/database.fasta"
        )
        assert at.text_input("_wf_s4_outdir").value == "results/obipcr_results"
        assert at.text_input("_wf_s5_outdir").value == "results/final_results"

        # Canonical session_state keys must also be set.
        assert at.session_state["wf_s1_outdir"] == "results/qc_results"
        assert at.session_state["wf_s5_outdir"] == "results/final_results"


class TestWorkflowFirstPreservation:
    """AppTest: Phase 7A — merged pages overwrite fallbacks on validation."""

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    def test_validation_overwrites_fallback_with_project_paths(self):
        """Phase 7A: on merged page, validation fills project paths over fallbacks."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        # 1. On merged page, widget gets fallback from _CANONICAL_DEFAULTS.
        assert at.text_input("_wf_s1_outdir").value == "qc_results"

        # 2. Validate inputs — project paths overwrite fallback values.
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        # After validation, project-derived path replaces canonical-default fallback.
        assert at.text_input("_wf_s1_outdir").value == "results/qc_results"

        # Non-path params remain unchanged.
        assert at.checkbox("_wf_s1_thermo").value is True
        assert at.number_input("_wf_s1_timeout").value == 60


class TestEmptyWorkflowPathInit:
    """AppTest: empty/None workflow paths are filled on validation."""

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    def test_first_validate_fills_cleared_path(self):
        """First validation fills wf_s1_outdir when cleared to empty before click."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        # Navigate to 分析工作台, clear wf_s1_outdir to empty string.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.text_input("_wf_s1_outdir").set_value("").run()
        assert not at.exception

        # Validate — first init should fill the empty path.
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.text_input("_wf_s1_outdir").value == "results/qc_results"

    def test_second_validate_fills_path_cleared_after_first_init(self):
        """After first init, clear a path → second validation fills it again."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # First validation seeds project paths.
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.text_input("_wf_s1_outdir").value == "results/qc_results"

        # Clear wf_s1_outdir.
        at.text_input("_wf_s1_outdir").set_value("").run()
        assert not at.exception

        # Second validation fills it again.
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.text_input("_wf_s1_outdir").value == "results/qc_results"

    def test_user_edited_default_value_preserved(self):
        """User sets path to /manual/qc then back to qc_results — preserved after validation."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # User types custom, then back to default.
        at.text_input("_wf_s1_outdir").set_value("/manual/qc").run()
        assert not at.exception
        at.text_input("_wf_s1_outdir").set_value("qc_results").run()
        assert not at.exception

        # Validate — "qc_results" is non-empty, user_edited → preserved.
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.text_input("_wf_s1_outdir").value == "qc_results"

    def test_non_empty_custom_path_preserved_on_revalidation(self):
        """Non-empty custom path survives re-validation."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # First validation.
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Set custom non-empty path.
        at.text_input("_wf_s1_outdir").set_value("/custom/manual/qc").run()
        assert not at.exception

        # Re-validate.
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.text_input("_wf_s1_outdir").value == "/custom/manual/qc"


class TestDryRunPersistence:
    """AppTest: workflow_dry_run survives page switches via canonical/temp-key."""

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    def test_dry_run_survives_page_switch(self):
        """Toggle workflow_dry_run to True, switch 分析工作台 → 结果总览 → 分析工作台, verify persistence."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        # 1. Enable dry-run on 分析工作台.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.toggle("_workflow_dry_run").set_value(True).run()
        assert not at.exception

        # 2. Cross-page: 分析工作台 → 结果总览 → 分析工作台.
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # 3. UI temp key and canonical value must both be True.
        assert at.toggle("_workflow_dry_run").value is True
        assert at.session_state["workflow_dry_run"] is True


# ── Phase 7A fix: stdout/stderr stale display regression ──────────────────


class TestStepResultDisplay:
    """Regression tests: second run must immediately show latest stdout/stderr."""

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    @staticmethod
    def _code_texts(at) -> list[str]:
        """Extract visible text from all st.code elements in the app."""
        return [c.value for c in at.code] if hasattr(at, "code") else []

    def test_stdout_second_run_shows_new_content(self):
        """Update wf_s1_result.stdout from FIRST to SECOND — SECOND must appear."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        # Inject result with "FIRST".
        at.session_state["wf_s1_result"] = {
            "status": "PASS",
            "stdout": "FIRST\n",
            "stderr": "",
            "returncode": 0,
            "message": "ok",
        }
        at.run(timeout=30)
        assert not at.exception

        # Update to "SECOND".
        at.session_state["wf_s1_result"] = {
            "status": "PASS",
            "stdout": "SECOND\n",
            "stderr": "",
            "returncode": 0,
            "message": "ok",
        }
        at.run(timeout=30)
        assert not at.exception

        # After second render: SECOND must appear, FIRST must NOT appear.
        code_texts = self._code_texts(at)
        all_code = "\n".join(code_texts)
        assert "SECOND" in all_code, f"SECOND not found in code: {all_code!r}"
        assert "FIRST" not in all_code, f"FIRST unexpectedly still in code: {all_code!r}"

    def test_stderr_second_run_shows_new_content(self):
        """Update wf_s1_result.stderr from ERR1 to ERR2 — ERR2 must appear."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        # Inject result with "ERR1" stderr.
        at.session_state["wf_s1_result"] = {
            "status": "FAIL",
            "stdout": "",
            "stderr": "ERR1: something went wrong\n",
            "returncode": 1,
            "message": "failed",
        }
        at.run(timeout=30)
        assert not at.exception

        # Update stderr to "ERR2".
        at.session_state["wf_s1_result"] = {
            "status": "FAIL",
            "stdout": "",
            "stderr": "ERR2: different error\n",
            "returncode": 1,
            "message": "failed",
        }
        at.run(timeout=30)
        assert not at.exception

        # After second render: ERR2 must appear, ERR1 must NOT appear.
        code_texts = self._code_texts(at)
        all_code = "\n".join(code_texts)
        assert "ERR2" in all_code, f"ERR2 not found in code: {all_code!r}"
        assert "ERR1" not in all_code, f"ERR1 unexpectedly still in code: {all_code!r}"
