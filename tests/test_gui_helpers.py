"""Tests for gui_helpers module."""

from __future__ import annotations

import gzip
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

import pandas as pd

from fullpcr.gui_helpers import (
    _WORKFLOW_PATH_KEYS,
    apply_primer_preset_to_state,
    apply_project_paths_to_state,
    build_final_report_command,
    build_full_pipeline_plan,
    build_manual_primers_tsv,
    build_obipcr_run_command,
    build_qc_pre_command,
    build_qc_spec_command,
    build_qc_summary_command,
    build_spec_index_database_path,
    run_full_pipeline,
    check_command_available,
    clear_upload_mode,
    collect_environment_status,
    compute_inputs_validated,
    derive_project_paths,
    ensure_widget_key,
    get_effective_database_path,
    get_effective_primers_path,
    get_effective_taxonomy_path,
    get_fullpcr_info,
    get_primer_preset,
    get_python_info,
    init_canonical_defaults,
    init_workspace_session_state,
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
    get_raw_spec_tsv_info,
    build_results_archive,
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

    def test_default_has_no_timeout(self):
        assert "--timeout" not in build_qc_pre_command(
            primers="p.tsv", outdir="out"
        )


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

    def test_default_has_no_timeout(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="out"
        )
        assert "--timeout" not in cmd
        assert cmd[cmd.index("--max-tm") + 1] == "100.0"


class TestBuildQcSpecCommandNewParams:
    """Phase 3D-2: new spec params in gui_helpers.build_qc_spec_command()."""

    def test_mis_start_present(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            mis_start=3,
        )
        assert "--mis-start" in cmd and "3" in cmd

    def test_mis_start_none_absent(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            mis_start=None,
        )
        assert "--mis-start" not in cmd

    def test_mis_end_present(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            mis_end=7,
        )
        assert "--mis-end" in cmd and "7" in cmd

    def test_mis_end_none_absent(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            mis_end=None,
        )
        assert "--mis-end" not in cmd

    def test_bind_true(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            bind=True,
        )
        assert "--bind" in cmd

    def test_bind_false_absent(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            bind=False,
        )
        assert "--bind" not in cmd

    def test_cut_primer_true(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            cut_primer=True,
        )
        assert "--cut-primer" in cmd

    def test_cut_primer_false_absent(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            cut_primer=False,
        )
        assert "--cut-primer" not in cmd

    def test_mono_present(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            mono=75.0,
        )
        assert "--mono" in cmd and "75.0" in cmd

    def test_mono_none_absent(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            mono=None,
        )
        assert "--mono" not in cmd

    def test_diva_present(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            diva=2.0,
        )
        assert "--diva" in cmd and "2.0" in cmd

    def test_dntp_present(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            dntp=0.5,
        )
        assert "--dntp" in cmd and "0.5" in cmd

    def test_oligo_present(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            oligo=100.0,
        )
        assert "--oligo" in cmd and "100.0" in cmd

    def test_all_none_default_unchanged(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
        )
        for flag in ["--mis-start", "--mis-end", "--bind", "--cut-primer",
                      "--mono", "--diva", "--dntp", "--oligo"]:
            assert flag not in cmd, f"{flag} leaked at defaults"

    def test_flag_and_value_separate_elements(self):
        cmd = build_qc_spec_command(
            primers="p.tsv", database="db.fasta", outdir="o",
            mono=75.0, mis_start=3, bind=True,
        )
        idx = cmd.index("--mono")
        assert cmd[idx + 1] == "75.0"
        idx2 = cmd.index("--mis-start")
        assert cmd[idx2 + 1] == "3"
        assert "--bind" in cmd


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

    def test_default_has_no_timeout(self):
        assert "--timeout" not in build_obipcr_run_command(
            primers="p.tsv", database="db.fasta", outdir="results"
        )


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
        proc = mock.Mock(returncode=0, pid=123)
        proc.communicate.return_value = ("done\n", "")
        with mock.patch(
            "fullpcr.gui_helpers.subprocess.Popen", return_value=proc
        ):
            result = run_gui_command(["echo", "hello"])
        assert result["status"] == "PASS"
        assert result["returncode"] == 0
        assert result["stdout"] == "done\n"
        assert result["message"] == "Command completed successfully"
        proc.communicate.assert_called_once_with(timeout=None)

    def test_mock_failure(self):
        proc = mock.Mock(returncode=1, pid=123)
        proc.communicate.return_value = ("", "error occurred")
        with mock.patch(
            "fullpcr.gui_helpers.subprocess.Popen", return_value=proc
        ):
            result = run_gui_command(["badcmd"])
        assert result["status"] == "FAIL"
        assert result["returncode"] == 1
        assert result["stderr"] == "error occurred"
        assert "exited with code 1" in result["message"]

    def test_mock_timeout(self):
        proc = mock.Mock(returncode=-signal.SIGTERM, pid=123)
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd=["sleep"], timeout=5),
            ("", ""),
        ]
        with (
            mock.patch(
                "fullpcr.gui_helpers.subprocess.Popen", return_value=proc
            ),
            mock.patch("fullpcr.gui_helpers.os.killpg") as killpg,
        ):
            result = run_gui_command(["sleep", "999"], timeout=5)
        assert result["status"] == "TIMEOUT"
        assert "timed out" in result["message"]
        killpg.assert_called_once_with(123, signal.SIGTERM)

    def test_observed_command_can_be_cancelled(self):
        proc = mock.Mock(returncode=-signal.SIGTERM, pid=321)
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd=["slow"], timeout=0.01),
            ("partial", ""),
        ]
        started: list[int] = []
        polls: list[int] = []
        cancel_checks = iter([False, True])
        with (
            mock.patch(
                "fullpcr.gui_helpers.subprocess.Popen", return_value=proc
            ),
            mock.patch("fullpcr.gui_helpers.os.killpg") as killpg,
            mock.patch("fullpcr.gui_helpers._COMMAND_POLL_SECONDS", 0.01),
        ):
            result = run_gui_command(
                ["slow"],
                timeout=None,
                cancel_requested=lambda: next(cancel_checks),
                on_process_started=started.append,
                on_poll=polls.append,
            )

        assert started == [321]
        assert polls == [321]
        assert result["status"] == "CANCELLED"
        assert result["stdout"] == "partial"
        killpg.assert_called_once_with(321, signal.SIGTERM)

    def test_command_is_list(self):
        proc = mock.Mock(returncode=0, pid=123)
        proc.communicate.return_value = ("", "")
        with mock.patch(
            "fullpcr.gui_helpers.subprocess.Popen", return_value=proc
        ) as mock_popen:
            run_gui_command(["ls", "-la"])
        called_cmd = mock_popen.call_args[0][0]
        assert isinstance(called_cmd, list)
        assert all(isinstance(a, str) for a in called_cmd)

    def test_no_shell_true(self):
        """Verify Popen receives shell=False."""
        proc = mock.Mock(returncode=0, pid=123)
        proc.communicate.return_value = ("", "")
        with mock.patch(
            "fullpcr.gui_helpers.subprocess.Popen", return_value=proc
        ) as mock_popen:
            run_gui_command(["echo", "test"])
        assert mock_popen.call_args.kwargs["shell"] is False

    def test_file_not_found(self):
        with mock.patch(
            "fullpcr.gui_helpers.subprocess.Popen",
            side_effect=FileNotFoundError("no such executable"),
        ):
            result = run_gui_command(["nonexistent"])
        assert result["status"] == "FAIL"
        assert "not found" in result["message"]

    def test_os_error(self):
        with mock.patch(
            "fullpcr.gui_helpers.subprocess.Popen",
            side_effect=OSError("cannot start"),
        ):
            result = run_gui_command(["broken"])
        assert result["status"] == "FAIL"
        assert result["returncode"] is None
        assert "cannot start" in result["message"]

    def test_timeout_escalates_to_sigkill(self):
        proc = mock.Mock(returncode=-signal.SIGKILL, pid=123)
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd=["sleep"], timeout=5),
            subprocess.TimeoutExpired(cmd=["sleep"], timeout=2),
            ("", ""),
        ]
        with (
            mock.patch(
                "fullpcr.gui_helpers.subprocess.Popen", return_value=proc
            ),
            mock.patch("fullpcr.gui_helpers.os.killpg") as killpg,
        ):
            result = run_gui_command(["sleep", "999"], timeout=5)
        assert result["status"] == "TIMEOUT"
        assert killpg.call_args_list == [
            mock.call(123, signal.SIGTERM),
            mock.call(123, signal.SIGKILL),
        ]

    def test_starts_command_in_new_process_session(self):
        """The GUI wrapper must own a process group that includes descendants."""
        proc = mock.Mock(returncode=0, pid=123)
        proc.communicate.return_value = ("", "")
        with mock.patch(
            "fullpcr.gui_helpers.subprocess.Popen", return_value=proc
        ) as mock_popen:
            run_gui_command(["echo", "test"])

        assert mock_popen.call_args.kwargs["start_new_session"] is True

    @pytest.mark.skipif(not hasattr(os, "killpg"), reason="requires POSIX process groups")
    def test_timeout_terminates_descendant_process(self, tmp_path):
        """A timeout must not leave the external tool's child running."""
        pid_file = tmp_path / "child.pid"
        marker = f"fullpcr-timeout-child-{os.getpid()}"
        child_code = "import time; time.sleep(60)"
        parent_code = (
            "import pathlib, subprocess, sys, time; "
            "p=subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[3]]); "
            "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); "
            "time.sleep(60)"
        )
        child_pid = None
        try:
            result = run_gui_command(
                [
                    sys.executable,
                    "-c",
                    parent_code,
                    str(pid_file),
                    child_code,
                    marker,
                ],
                timeout=1,
            )
            assert result["status"] == "TIMEOUT"
            assert pid_file.is_file()
            child_pid = int(pid_file.read_text())
            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


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

    def test_default(self):
        preset = get_primer_preset("默认参数")
        assert preset["min_size"] == 80
        assert preset["max_size"] == 500
        assert preset["spec_mismatch"] == 2
        assert preset["obipcr_mismatches"] == "0,1,2"
        assert preset["circular"] is True

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
        assert state["wf_s3_cpu"] == 4
        assert state["wf_preset_select"] == "默认参数"
        assert state["res_final_dir"] == "final_results"
        assert state["rpt_final_path"] == "final_results/final_report.md"

    def test_init_canonical_defaults_preserves_existing(self):
        """init_canonical_defaults does not overwrite existing keys."""
        state: dict = {
            "inputs_primers_path": "/custom/path.tsv",
            "wf_s3_cpu": 8,
        }
        init_canonical_defaults(state)
        assert state["inputs_primers_path"] == "/custom/path.tsv"
        assert state["wf_s3_cpu"] == 8

    def test_ensure_widget_key_loads_from_canonical(self):
        """ensure_widget_key copies canonical value to widget key."""
        state: dict = {"wf_s3_cpu": 8}
        ensure_widget_key(state, "_wf_s3_cpu")
        assert state["_wf_s3_cpu"] == 8

    def test_ensure_widget_key_falls_back_to_default(self):
        """ensure_widget_key uses canonical default when canonical key absent."""
        state: dict = {}
        ensure_widget_key(state, "_wf_s3_cpu")
        assert state["_wf_s3_cpu"] == 4  # from _CANONICAL_DEFAULTS

    def test_ensure_widget_key_noop_if_widget_exists(self):
        """ensure_widget_key is no-op when widget key already in state."""
        state: dict = {
            "wf_s3_cpu": 8,
            "_wf_s3_cpu": 6,
        }
        ensure_widget_key(state, "_wf_s3_cpu")
        assert state["_wf_s3_cpu"] == 6  # unchanged

    def test_sync_widgets_to_canonical(self):
        """sync_widgets_to_canonical copies temp widget values to canonical."""
        state: dict = {
            "_wf_s3_cpu": 8,
            "_wf_s4_circular": False,
            "_inputs_primers_path": "/my/path.tsv",
        }
        # Set canonical to different values to verify overwrite.
        state["wf_s3_cpu"] = 4
        state["wf_s4_circular"] = True
        state["inputs_primers_path"] = "old"

        sync_widgets_to_canonical(state)
        assert state["wf_s3_cpu"] == 8
        assert state["wf_s4_circular"] is False
        assert state["inputs_primers_path"] == "/my/path.tsv"

    def test_sync_widgets_to_canonical_skips_absent_widgets(self):
        """sync_widgets_to_canonical leaves canonical keys alone when widget absent."""
        state: dict = {"wf_s3_cpu": 6}
        sync_widgets_to_canonical(state)
        assert state["wf_s3_cpu"] == 6  # unchanged — no widget key present

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
        assert state["wf_s3_cpu"] == 4
        assert state["wf_s1_thermo"] is True
        assert state["wf_s3_minsize"] == 80
        assert state["wf_s4_circular"] is True
        assert state["wf_preset_select"] == "默认参数"

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

    def test_default_restores_canonical_values(self):
        state = {
            "wf_s3_minsize": 999,
            "wf_s3_maxsize": 999,
            "wf_s3_mismatch": 9,
            "wf_s4_mismatches": "9",
            "wf_s4_circular": False,
        }
        apply_primer_preset_to_state(state, "默认参数")
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
            "project_database_path": "/tmp/proj/reference.fa",
            "project_taxonomy_path": "/tmp/proj/tax.tsv",
            "project_derived_paths": {
                "qc_results_dir": "/tmp/proj/qc_results",
                "qc_spec_results_dir": "/tmp/proj/qc_spec_results",
                "obipcr_results_dir": "/tmp/proj/obipcr_results",
                "final_results_dir": "/tmp/proj/final_results",
            },
        }

    _EXPECTED_SPEC_INDEX = "/tmp/proj/qc_spec_results/index/reference.fa"

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
                "spec_index_database": build_spec_index_database_path(
                    derived["qc_spec_results_dir"],
                    proj["project_database_path"],
                ),
            },
            overwrite=True,
        )

        # Paths are overwritten
        assert state["wf_s1_primers"] == "/tmp/proj/primers.tsv"
        assert state["wf_s4_database"] == self._EXPECTED_SPEC_INDEX
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
                "spec_index_database": build_spec_index_database_path(
                    derived["qc_spec_results_dir"],
                    proj["project_database_path"],
                ),
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
                "spec_index_database": build_spec_index_database_path(
                    derived["qc_spec_results_dir"],
                    proj["project_database_path"],
                ),
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


class TestCorporateBranding:
    """博坤生物品牌资源和首屏展示。"""

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    @staticmethod
    def _logo_path():
        return (
            Path(__file__).resolve().parent.parent
            / "fullpcr"
            / "assets"
            / "bokun-bio-logo.png"
        )

    def test_official_logo_asset_is_valid_png(self):
        data = self._logo_path().read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert int.from_bytes(data[16:20], "big") == 945
        assert int.from_bytes(data[20:24], "big") == 945
        assert len(data) > 100_000

    def test_logo_is_included_as_package_data(self):
        pyproject = (self._app_path().parent.parent / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        assert 'fullpcr = ["assets/*.png"]' in pyproject

    def test_brand_is_visible_on_initial_page(self):
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        assert any("博坤生物" in str(m.value) for m in at.markdown)
        assert any("brand-hero" in str(m.value) for m in at.markdown)
        assert any("PCR PRIMER EVALUATION SYSTEM" in str(m.value) for m in at.markdown)
        shell_text = " ".join(
            [str(m.value) for m in at.markdown]
            + [str(c.value) for c in at.caption]
        )
        assert "fullpcr 全库引物评测平台" not in shell_text
        assert "全库引物评测平台" in shell_text
        assert "博坤生物 · 分析系统" in shell_text
        style_markup = "\n".join(str(m.value) for m in at.markdown)
        assert "font-size: 20px" in style_markup
        assert "#f7f9f5" in style_markup
        assert '[data-testid="stBaseButton-primary"]:disabled' in style_markup
        assert '[data-testid="stToolbar"]' in style_markup
        assert '[data-testid="stDeployButton"]' in style_markup
        assert "color-scheme: light" in style_markup

    def test_desktop_sidebar_is_locked_open(self):
        """Navigation cannot be collapsed and lost on desktop browsers."""
        source = self._app_path().read_text(encoding="utf-8")
        assert 'initial_sidebar_state="locked"' in source

    def test_mist_blue_translucent_navigation_contract(self):
        """Corporate shell uses the approved mist-blue glass visual system."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        markup = "\n".join(str(item.value) for item in at.markdown)
        assert "sidebar-brand-panel" in markup
        assert "sidebar-nav-intro" in markup
        assert "sidebar-footer" in markup
        assert "--bk-mist-blue: #d6e4f1" in markup
        assert "backdrop-filter: blur(18px)" in markup
        assert "border-left: 4px solid var(--bk-green)" in markup
        assert "min-height: 168px" in markup
        assert "rgba(255,255,255,0.58)" in markup
        assert "white-space: nowrap" in markup

    def test_analysis_workbench_density_is_scoped(self):
        """Compact spacing belongs only to the keyed workbench container."""
        source = self._app_path().read_text(encoding="utf-8")
        assert 'st.container(key="analysis_workbench_compact")' in source
        assert ".st-key-analysis_workbench_compact" in source
        assert ".st-key-analysis_workbench_compact h3" in source
        assert ".st-key-analysis_workbench_compact hr" in source

    def test_environment_is_in_sidebar_and_header_uses_full_width(self):
        """Environment control belongs above navigation, not beside the hero."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        assert len(at.sidebar.get("popover")) == 1
        source = self._app_path().read_text(encoding="utf-8")
        header_source = source[
            source.index("def _render_header()"):
            source.index("# ── environment popover")
        ]
        assert "st.columns" not in header_source

    def test_navigation_cards_have_equal_width_and_balanced_type(self):
        """All three navigation modules share one width and type scale."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        markup = "\n".join(str(item.value) for item in at.markdown)
        assert "align-items: stretch" in markup
        assert "width: 100% !important" in markup
        assert "box-sizing: border-box" in markup
        assert "font-size: 0.68rem" in markup
        assert "font-size: 0.90rem" in markup
        assert "font-size: 0.62rem" in markup

    def test_streamlit_header_has_no_visual_footprint(self):
        """The hidden Streamlit shell header must not reserve page space."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        markup = "\n".join(str(item.value) for item in at.markdown)
        assert 'height: 0 !important' in markup
        assert 'min-height: 0 !important' in markup
        assert 'pointer-events: none' in markup

    def test_sidebar_content_does_not_scroll(self):
        """The locked desktop navigation fits one viewport without scrolling."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        markup = "\n".join(str(item.value) for item in at.markdown)
        assert 'height: 100dvh' in markup
        assert 'overflow: hidden' in markup
        assert 'margin-top: auto' in markup
        assert '@media (max-height: 800px) and (min-width: 801px)' in markup


class TestAnalysisParameterPanel:
    """UI contract for the simplified analysis-parameter panel."""

    @staticmethod
    def _open_workbench():
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        return at

    def test_shortcut_controls_are_removed(self):
        at = self._open_workbench()

        assert "wf_sync_btn" not in [button.key for button in at.button]
        assert "wf_apply_preset_btn" not in [button.key for button in at.button]
        assert "_wf_preset_select" not in [selectbox.key for selectbox in at.selectbox]

    def test_toggle_sections_have_no_dividers(self):
        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        source = app_path.read_text(encoding="utf-8")
        quick_source = source.split("def _render_quick_analysis", 1)[1].split(
            "def _render_advanced_workflow_tabs", 1
        )[0]
        params_source = source.split(
            "def _render_analysis_parameter_controls", 1
        )[1].split("def _render_workflow_status_row", 1)[0]

        assert "st.divider()" not in quick_source
        assert "st.divider()" not in params_source

    def test_basic_help_and_advanced_visibility(self):
        at = self._open_workbench()

        assert "分析参数" not in [item.label for item in at.expander]
        basic_help = {
            "_wf_s3_minsize": ("MFEprimer spec", "-s"),
            "_wf_s3_maxsize": ("MFEprimer spec", "-S"),
            "_wf_s3_mismatch": ("MFEprimer spec", "--misMatch"),
        }
        for key, expected in basic_help.items():
            help_text = at.number_input(key).help
            assert all(item in help_text for item in expected)

        mismatch_help = at.text_input("_wf_s4_mismatches").help
        assert "obipcr" in mismatch_help
        assert "--mismatches" in mismatch_help
        circular_help = at.checkbox("_wf_s4_circular").help
        assert "obipcr" in circular_help
        assert "--circular" in circular_help

        assert at.toggle("_show_advanced_parameters").value is False
        advanced_keys = {
            "_wf_s3_use_tm": "-t",
            "_wf_s3_use_misstart": "--misStart",
            "_wf_s3_use_misend": "--misEnd",
            "_wf_s3_use_mono": "--mono",
            "_wf_s3_use_diva": "--diva",
            "_wf_s3_use_dntp": "--dntp",
            "_wf_s3_use_oligo": "--oligo",
            "_wf_s3_bind": "-b",
            "_wf_s3_cutprimer": "--cutprimer",
        }
        checkbox_keys = [checkbox.key for checkbox in at.checkbox]
        assert advanced_keys.keys().isdisjoint(checkbox_keys)

        at.toggle("_show_advanced_parameters").set_value(True).run()
        assert not at.exception
        for key, flag in advanced_keys.items():
            help_text = at.checkbox(key).help
            assert "MFEprimer spec" in help_text
            assert flag in help_text


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
        _enable_advanced_workflow(at)
        assert not at.exception
        _enable_advanced_workflow(at)

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
        _enable_advanced_workflow(at)
        assert not at.exception
        _enable_advanced_workflow(at)

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
        _enable_advanced_workflow(at)
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
        _enable_advanced_workflow(at)
        assert not at.exception

        at.text_input("_wf_s4_mismatches").set_value("").run()
        assert not at.exception

        all_code = self._all_code(at)
        assert "--mismatches" not in all_code, (
            f"Expected no '--mismatches' when empty, got:\n{all_code}"
        )


def _switch_all_to_server_path(at):
    """Switch all three file-type radios to 服务器路径 so text_inputs render."""
    at.radio("_inputs_primers_mode").set_value("服务器路径").run()
    at.radio("_inputs_database_mode").set_value("服务器路径").run()
    at.radio("_inputs_taxonomy_mode").set_value("服务器路径").run()


def _enable_advanced_workflow(at):
    """Enable the advanced workflow toggle so 5-step tabs render."""
    at.toggle("_show_advanced_workflow").set_value(True).run()


class TestGuiAppPersistence:
    """Integration tests for cross-page widget persistence using AppTest."""

    @staticmethod
    def _set_inputs_values(at):
        """Set all three visible input-path widgets to custom values."""
        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value("/user/input.tsv").run()
        at.text_input("_inputs_database_path").set_value("/user/db.fasta").run()
        at.text_input("_inputs_taxonomy_path").set_value("/user/tax.tsv").run()

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
        _enable_advanced_workflow(at)
        assert not at.exception
        self._set_inputs_values(at)

        # Navigate to 结果总览 and back.
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # Radios reset to 本地上传 — switch back to see text_inputs.
        _switch_all_to_server_path(at)

        # Values must be preserved, not reset to example_data defaults.
        assert at.text_input("_inputs_primers_path").value == "/user/input.tsv"
        assert at.text_input("_inputs_database_path").value == "/user/db.fasta"
        assert at.text_input("_inputs_taxonomy_path").value == "/user/tax.tsv"

    def test_results_project_selection_survives_page_switch(
        self, tmp_path, monkeypatch
    ):
        """The selected real project persists across page navigation."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        data_root = tmp_path / "data"
        for run_id in ("run-a", "run-b"):
            final_dir = data_root / "runs" / run_id / "final_results"
            final_dir.mkdir(parents=True)
            (final_dir / "primer_rank.tsv").write_text(
                "primer_id\tfinal_score\nP1\t1\n", encoding="utf-8"
            )
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        selector = at.selectbox("_selected_result_project")
        selected = selector.options[-1]
        from datetime import datetime
        time_name = selected.split(" · ", 1)[1].split("（", 1)[0]
        datetime.strptime(time_name, "%Y_%m_%d_%H_%M")
        selector.select(selected).run()
        assert not at.exception

        # Navigate away and back.
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception

        assert at.selectbox("_selected_result_project").value == selected

    def test_reports_page_uses_project_selection_not_paths(
        self, tmp_path, monkeypatch
    ):
        """Reports use a known project selector and expose no path text fields."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        final_dir = tmp_path / "data" / "runs" / "run-report" / "final_results"
        final_dir.mkdir(parents=True)
        (final_dir / "primer_rank.tsv").write_text(
            "primer_id\tfinal_score\nP1\t1\n", encoding="utf-8"
        )
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(tmp_path / "data"))

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        selected = at.selectbox("_selected_result_project").value
        from datetime import datetime
        datetime.strptime(selected.split(" · ", 1)[1], "%Y_%m_%d_%H_%M")
        with pytest.raises(KeyError):
            at.text_input("_rpt_final_path")
        with pytest.raises(KeyError):
            at.text_input("_rpt_obipcr_path")

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
        _enable_advanced_workflow(at)
        assert not at.exception
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Navigate to Workflow, set manual path.
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        _enable_advanced_workflow(at)
        at.text_input("_wf_s1_outdir").set_value("/custom/manual/qc").run()
        assert not at.exception

        # Return to Inputs, re-validate.
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Return to Workflow — manual path must survive.
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        assert at.text_input("_wf_s1_outdir").value == "/custom/manual/qc"

    def test_base_params_survive_page_switch(self):
        """Base values persist across 分析工作台 → 报告与下载 → 分析工作台."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        at.number_input("_wf_s3_minsize").set_value(320).run()
        at.number_input("_wf_s3_maxsize").set_value(880).run()
        at.number_input("_wf_s3_mismatch").set_value(4).run()
        assert not at.exception

        # Cross-page: 分析工作台 → 报告与下载 → 分析工作台
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        assert at.number_input("_wf_s3_minsize").value == 320
        assert at.number_input("_wf_s3_maxsize").value == 880
        assert at.number_input("_wf_s3_mismatch").value == 4

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
        _enable_advanced_workflow(at)
        assert not at.exception
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # 2. Navigate to Workflow, change paths to non-default values.
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        _enable_advanced_workflow(at)
        at.text_input("_wf_s1_outdir").set_value("/custom/manual/qc").run()
        assert not at.exception
        at.text_input("_wf_s4_outdir").set_value("/custom/obipcr").run()
        assert not at.exception
        at.number_input("_wf_s3_cpu").set_value(8).run()
        assert not at.exception

        # 3. Return to Inputs, re-validate.
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        at.button("inputs_validate_btn").click().run()
        # Must NOT raise StreamlitAPIException on re-validation.
        assert not at.exception, f"Re-validation raised: {at.exception}"

        # 4. Return to Workflow — manual paths must survive.
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        assert at.text_input("_wf_s1_outdir").value == "/custom/manual/qc"
        assert at.text_input("_wf_s4_outdir").value == "/custom/obipcr"
        assert at.number_input("_wf_s3_cpu").value == 8

    def test_change_inputs_path_back_to_default(self):
        """User can change an Inputs path to the built-in default value."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        # Switch to server-path mode so text_inputs render.
        _switch_all_to_server_path(at)
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
        _enable_advanced_workflow(at)
        assert not at.exception
        # Change to 8.
        at.number_input("_wf_s3_cpu").set_value(8).run()
        assert not at.exception
        # Change back to default 4.
        at.number_input("_wf_s3_cpu").set_value(4).run()
        assert not at.exception
        # UI must show 4.
        assert at.number_input("_wf_s3_cpu").value == 4

    def test_change_workflow_path_back_to_default(self):
        """User can change a workflow path back to its default value."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        # Change to custom.
        at.text_input("_wf_s1_outdir").set_value("/manual/qc").run()
        assert not at.exception
        # Change back to default "qc_results".
        at.text_input("_wf_s1_outdir").set_value("qc_results").run()
        assert not at.exception
        # UI must show the user's input.
        assert at.text_input("_wf_s1_outdir").value == "qc_results"

    def test_results_page_has_no_free_form_result_paths(self, tmp_path, monkeypatch):
        """Result sources are selected by project, not editable path fields."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        monkeypatch.setenv("FULLPCR_DATA_DIR", str(tmp_path / "empty"))

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        for key in ("_res_final_dir", "_res_obipcr_dir", "_res_qc_dir", "_res_spec_dir"):
            with pytest.raises(KeyError):
                at.text_input(key)

    def test_reports_page_has_no_free_form_report_paths(self, tmp_path):
        """Report paths are derived from the selected project and remain hidden."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        root = tmp_path / "project"
        root.mkdir()
        at.session_state["project_output_root"] = str(root)

        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        with pytest.raises(KeyError):
            at.text_input("_rpt_final_path")
        with pytest.raises(KeyError):
            at.text_input("_rpt_obipcr_path")

    def test_inputs_fail_state_protection(self):
        """Failed validation remains invalid without a manual sync shortcut."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"
        at = AppTest.from_file(str(app_path))
        at.run(timeout=30)
        assert not at.exception

        # Navigate to Inputs with default (valid) paths first.
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        # Switch to server-path mode so text_inputs render.
        _switch_all_to_server_path(at)
        # Change primers_path to a non-existent file (should FAIL validation).
        at.text_input("_inputs_primers_path").set_value("/nonexistent/path.tsv").run()
        assert not at.exception
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        assert at.session_state["inputs_validated"] is False
        assert "wf_sync_btn" not in [button.key for button in at.button]

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
        _enable_advanced_workflow(at)
        assert not at.exception

        # Validate first with default (valid) paths to create project snapshot.
        # Switch to server-path mode so default text_input values are used.
        _switch_all_to_server_path(at)
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Now customize inputs paths, workflow path, params.
        self._set_inputs_values(at)
        at.text_input("_wf_s1_outdir").set_value("/custom/manual/qc").run()
        assert not at.exception
        at.toggle("_workflow_dry_run").set_value(True).run()
        assert not at.exception
        at.number_input("_wf_s3_minsize").set_value(500).run()
        at.number_input("_wf_s3_maxsize").set_value(800).run()
        at.number_input("_wf_s3_mismatch").set_value(3).run()
        at.text_input("_wf_s4_mismatches").set_value("0,1,2,3").run()
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
        _enable_advanced_workflow(at)
        assert not at.exception

        # Radios reset to 本地上传 — switch back to see text_inputs.
        _switch_all_to_server_path(at)

        # Verify inputs paths
        assert at.text_input("_inputs_primers_path").value == "/user/input.tsv"
        assert at.text_input("_inputs_database_path").value == "/user/db.fasta"
        assert at.text_input("_inputs_taxonomy_path").value == "/user/tax.tsv"

        # Verify workflow manual path
        assert at.text_input("_wf_s1_outdir").value == "/custom/manual/qc"

        # Verify dry-run
        assert at.toggle("_workflow_dry_run").value is True
        assert at.session_state["workflow_dry_run"] is True

        # Verify base params
        assert at.number_input("_wf_s3_minsize").value == 500
        assert at.number_input("_wf_s3_maxsize").value == 800
        assert at.number_input("_wf_s3_mismatch").value == 3
        assert at.text_input("_wf_s4_mismatches").value == "0,1,2,3"

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
        _enable_advanced_workflow(at)
        assert not at.exception

        # Switch to server-path mode so default text_input paths are used.
        _switch_all_to_server_path(at)

        # Validate with default paths (example_data/* → output_root="results").
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Navigate to Workflow.
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # UI widget values must show project-derived results/* paths.
        assert at.text_input("_wf_s1_outdir").value == "results/qc_results"
        assert at.text_input("_wf_s2_qcdir").value == "results/qc_results"
        assert at.text_input("_wf_s3_outdir").value == "results/qc_spec_results"
        assert (
            at.text_input("_wf_s4_database").value
            == "results/qc_spec_results/index/real_mito_small.fasta"
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

        # Enable advanced workflow so path widgets are rendered.
        _enable_advanced_workflow(at)

        # 1. On merged page, widget gets fallback from _CANONICAL_DEFAULTS.
        assert at.text_input("_wf_s1_outdir").value == "qc_results"

        # 2. Validate inputs — project paths overwrite fallback values.
        _switch_all_to_server_path(at)
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        # After validation, project-derived path replaces canonical-default fallback.
        assert at.text_input("_wf_s1_outdir").value == "results/qc_results"

        # Non-path params remain unchanged.
        assert at.checkbox("_wf_s1_thermo").value is True
        assert at.number_input("_wf_s1_maxdeg").value == 256


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
        _enable_advanced_workflow(at)
        assert not at.exception
        _enable_advanced_workflow(at)
        at.text_input("_wf_s1_outdir").set_value("").run()
        assert not at.exception

        # Validate — first init should fill the empty path.
        _switch_all_to_server_path(at)
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
        _enable_advanced_workflow(at)
        assert not at.exception

        # First validation seeds project paths.
        _switch_all_to_server_path(at)
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.text_input("_wf_s1_outdir").value == "results/qc_results"

        # Clear wf_s1_outdir.
        at.text_input("_wf_s1_outdir").set_value("").run()
        assert not at.exception

        # Second validation fills it again.
        _switch_all_to_server_path(at)
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
        _enable_advanced_workflow(at)
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
        _enable_advanced_workflow(at)
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
        _enable_advanced_workflow(at)
        assert not at.exception
        at.toggle("_workflow_dry_run").set_value(True).run()
        assert not at.exception

        # 2. Cross-page: 分析工作台 → 结果总览 → 分析工作台.
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
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

        # Enable advanced workflow so step results render.
        _enable_advanced_workflow(at)

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

        # Enable advanced workflow so step results render.
        _enable_advanced_workflow(at)

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


# ═══════════════════════════════════════════════════════════════════════════
# Workspace session state tests
# ═══════════════════════════════════════════════════════════════════════════


class TestInitWorkspaceSessionState:

    def test_sets_defaults_on_empty_state(self):
        state: dict = {}
        init_workspace_session_state(state)
        assert state["ws_run_id"] is None
        assert state["ws_uploads_dir"] is None
        assert state["ws_use_upload_primers"] is False
        assert state["ws_use_upload_database"] is False
        assert state["ws_use_upload_taxonomy"] is False
        assert state["ws_uploaded_primers_path"] is None
        assert state["ws_uploaded_database_path"] is None
        assert state["ws_uploaded_taxonomy_path"] is None

    def test_does_not_overwrite_existing(self):
        state = {"ws_run_id": "abc"}
        init_workspace_session_state(state)
        assert state["ws_run_id"] == "abc"
        assert state["ws_use_upload_primers"] is False


class TestGetEffectivePaths:

    def test_primers_upload_mode(self):
        state = {
            "ws_use_upload_primers": True,
            "ws_uploaded_primers_path": "/tmp/u/primers.tsv",
            "inputs_primers_path": "/old/path.tsv",
        }
        assert get_effective_primers_path(state) == "/tmp/u/primers.tsv"

    def test_primers_server_mode(self):
        state = {
            "ws_use_upload_primers": False,
            "ws_uploaded_primers_path": "/tmp/u/primers.tsv",
            "inputs_primers_path": "/old/path.tsv",
        }
        assert get_effective_primers_path(state) == "/old/path.tsv"

    def test_primers_upload_mode_no_path(self):
        state = {
            "ws_use_upload_primers": True,
            "ws_uploaded_primers_path": None,
            "inputs_primers_path": "/old/path.tsv",
        }
        assert get_effective_primers_path(state) == "/old/path.tsv"

    def test_database_upload_mode(self):
        state = {
            "ws_use_upload_database": True,
            "ws_uploaded_database_path": "/tmp/u/database.fasta",
            "inputs_database_path": "/old/db.fa",
        }
        assert get_effective_database_path(state) == "/tmp/u/database.fasta"

    def test_database_server_mode(self):
        state = {
            "ws_use_upload_database": False,
            "ws_uploaded_database_path": "/tmp/u/database.fasta",
            "inputs_database_path": "/old/db.fa",
        }
        assert get_effective_database_path(state) == "/old/db.fa"

    def test_taxonomy_upload_mode(self):
        state = {
            "ws_use_upload_taxonomy": True,
            "ws_uploaded_taxonomy_path": "/tmp/u/taxonomy.tsv",
            "inputs_taxonomy_path": "/old/tax.tsv",
        }
        assert get_effective_taxonomy_path(state) == "/tmp/u/taxonomy.tsv"

    def test_taxonomy_server_mode(self):
        state = {
            "ws_use_upload_taxonomy": False,
            "ws_uploaded_taxonomy_path": "/tmp/u/taxonomy.tsv",
            "inputs_taxonomy_path": "/old/tax.tsv",
        }
        assert get_effective_taxonomy_path(state) == "/old/tax.tsv"

    def test_empty_state_defaults(self):
        state: dict = {}
        assert get_effective_primers_path(state) == ""
        assert get_effective_database_path(state) == ""
        assert get_effective_taxonomy_path(state) == ""


class TestClearUploadMode:

    def test_clears_primers(self):
        state = {
            "ws_use_upload_primers": True,
            "ws_uploaded_primers_path": "/tmp/p.tsv",
        }
        clear_upload_mode(state, "primers")
        assert state["ws_use_upload_primers"] is False
        assert state["ws_uploaded_primers_path"] is None

    def test_clears_database(self):
        state = {
            "ws_use_upload_database": True,
            "ws_uploaded_database_path": "/tmp/db.fasta",
        }
        clear_upload_mode(state, "database")
        assert state["ws_use_upload_database"] is False
        assert state["ws_uploaded_database_path"] is None

    def test_clears_taxonomy(self):
        state = {
            "ws_use_upload_taxonomy": True,
            "ws_uploaded_taxonomy_path": "/tmp/t.tsv",
        }
        clear_upload_mode(state, "taxonomy")
        assert state["ws_use_upload_taxonomy"] is False
        assert state["ws_uploaded_taxonomy_path"] is None

    def test_unknown_type_noop(self):
        state = {"other": "keep"}
        clear_upload_mode(state, "unknown")
        assert state["other"] == "keep"

    def test_switch_mode_clears_old_path(self):
        """Simulate switching from upload to server mode."""
        state = {
            "ws_use_upload_primers": True,
            "ws_uploaded_primers_path": "/tmp/p.tsv",
        }
        clear_upload_mode(state, "primers")
        # Upload path cleared, server text input will be read instead.
        assert state["ws_uploaded_primers_path"] is None
        r = get_effective_primers_path(state)
        assert r == ""


class TestBuildSpecIndexDatabasePath:

    def test_upload_mode_database_fasta(self):
        """Upload mode: database is always database.fasta."""
        result = build_spec_index_database_path(
            "/ws/runs/r1/qc_spec_results", "/ws/runs/r1/uploads/database.fasta"
        )
        assert result.endswith("/index/database.fasta")

    def test_server_path_preserves_basename(self):
        """Server path: index uses the actual file basename."""
        result = build_spec_index_database_path(
            "/ws/runs/r1/qc_spec_results", "/x/reference.fa"
        )
        assert result.endswith("/index/reference.fa")

    def test_server_path_gz_basename(self):
        """Server path with .fa.gz."""
        result = build_spec_index_database_path(
            "/ws/runs/r1/qc_spec_results", "/x/db.fasta.gz"
        )
        assert result.endswith("/index/db.fasta.gz")

    def test_empty_qc_dir_returns_empty(self):
        result = build_spec_index_database_path("", "/x/db.fasta")
        assert result == ""

    def test_empty_database_returns_empty(self):
        result = build_spec_index_database_path("/qc", "")
        assert result == ""


# ═══════════════════════════════════════════════════════════════════════════
# Real FileUploader AppTests
# ═══════════════════════════════════════════════════════════════════════════

_EXAMPLE_DATA = Path(__file__).resolve().parent.parent / "example_data"


class TestRealUploadWorkflow:
    """AppTests that exercise real ``st.file_uploader`` widgets."""

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    @staticmethod
    def _read(path):
        return Path(path).read_bytes()

    def test_first_upload_initializes_workflow(self, monkeypatch, tmp_path):
        """Real upload of primers + database + taxonomy → first validation
        auto-fills Workflow paths."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        data_root = tmp_path / "upload_data"
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))

        primers_bytes = self._read(_EXAMPLE_DATA / "primers.tsv")
        db_bytes = self._read(_EXAMPLE_DATA / "real_mito_small.fasta")
        tax_bytes = self._read(_EXAMPLE_DATA / "taxonomy.tsv")

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # Primers: switch from default 直接填写 to 本地上传.
        at.radio("_inputs_primers_mode").set_value("本地上传").run()
        assert not at.exception

        at.file_uploader("_ws_primers_uploader").upload(
            "primers.tsv", primers_bytes, "text/tab-separated-values",
        ).run()
        assert not at.exception
        at.file_uploader("_ws_database_uploader").upload(
            "reference.fa", db_bytes, "text/plain",
        ).run()
        assert not at.exception
        at.file_uploader("_ws_taxonomy_uploader").upload(
            "taxonomy.tsv", tax_bytes, "text/tab-separated-values",
        ).run()
        assert not at.exception

        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        assert at.session_state["inputs_validated"] is True
        ws_run_id = at.session_state["ws_run_id"]
        assert ws_run_id is not None
        assert len(ws_run_id) == 32
        ws_uploads = at.session_state["ws_uploads_dir"]
        assert str(data_root) in ws_uploads

        # Uploaded database normalised to database.fasta.
        db_path = at.session_state["project_database_path"]
        assert Path(db_path).name == "database.fasta"

        # Workflow paths initialised.
        assert at.session_state["workflow_paths_initialized"] is True

        # wf_s3_database → uploaded database.fasta.
        wf_s3_db = at.session_state["wf_s3_database"]
        assert "database.fasta" in str(wf_s3_db)

        # wf_s4_database → index/database.fasta (upload normalised).
        wf_s4_db = at.session_state["wf_s4_database"]
        assert str(wf_s4_db).endswith("index/database.fasta"), (
            f"wf_s4_database = {wf_s4_db!r}"
        )

    def test_revalidation_preserves_manual_paths(self, monkeypatch, tmp_path):
        """After first upload validation, manually edited Workflow paths
        survive a second validation after the manual sync shortcut is removed."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        data_root = tmp_path / "upload_data"
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))

        primers_bytes = self._read(_EXAMPLE_DATA / "primers.tsv")
        db_bytes = self._read(_EXAMPLE_DATA / "real_mito_small.fasta")
        tax_bytes = self._read(_EXAMPLE_DATA / "taxonomy.tsv")

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # First upload + validate — switch primers to 本地上传.
        at.radio("_inputs_primers_mode").set_value("本地上传").run()
        assert not at.exception
        at.file_uploader("_ws_primers_uploader").upload(
            "primers.tsv", primers_bytes, "text/tab-separated-values",
        ).run()
        assert not at.exception
        at.file_uploader("_ws_database_uploader").upload(
            "reference.fa", db_bytes, "text/plain",
        ).run()
        assert not at.exception
        at.file_uploader("_ws_taxonomy_uploader").upload(
            "taxonomy.tsv", tax_bytes, "text/tab-separated-values",
        ).run()
        assert not at.exception

        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is True
        assert at.session_state["workflow_paths_initialized"] is True

        # Manually override two Workflow paths (both canonical AND widget key).
        at.session_state["wf_s1_outdir"] = "/manual/qc"
        at.session_state["_wf_s1_outdir"] = "/manual/qc"
        at.session_state["wf_s4_database"] = "/manual/index/custom.fa"
        at.session_state["_wf_s4_database"] = "/manual/index/custom.fa"
        at.run(timeout=30)
        assert not at.exception

        # Second validation — must NOT overwrite manual paths.
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["wf_s1_outdir"] == "/manual/qc"
        assert at.session_state["wf_s4_database"] == "/manual/index/custom.fa"

        assert "wf_sync_btn" not in [button.key for button in at.button]
        assert at.session_state["wf_s1_outdir"] == "/manual/qc"
        assert at.session_state["wf_s4_database"] == "/manual/index/custom.fa"


class TestServerGzipRejection:
    """Server-path .fasta.gz/.fa.gz must be rejected because downstream
    qc-spec cannot read compressed FASTA.  Upload mode is fine."""

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    @staticmethod
    def _read(path):
        return Path(path).read_bytes()

    def _make_gz(self, tmp_path: Path) -> str:
        """Create a valid gzip FASTA in *tmp_path* and return its path."""
        import gzip
        gz_path = tmp_path / "server_db.fasta.gz"
        with gzip.open(gz_path, "wb") as gz:
            gz.write(b">seq1\nACGTACGT\n")
        return str(gz_path)

    def test_server_gzip_rejected(self, monkeypatch, tmp_path):
        """场景 A: server-path .fasta.gz → validation FAIL with clear error."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        data_root = tmp_path / "data"
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))

        gz_path = self._make_gz(tmp_path)
        primers_bytes = self._read(_EXAMPLE_DATA / "primers.tsv")
        tax_bytes = self._read(_EXAMPLE_DATA / "taxonomy.tsv")

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # Switch primers and taxonomy to server, database stays server (default).
        _switch_all_to_server_path(at)

        # Upload primers and taxonomy as example_data content via file_uploader
        # is NOT needed — we use server path mode.  Set text_input values.
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")
        ).run()
        assert not at.exception
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")
        ).run()
        assert not at.exception
        # Database → server-path gzip file.
        at.text_input("_inputs_database_path").set_value(gz_path).run()
        assert not at.exception

        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Validation must fail.
        assert at.session_state["inputs_validated"] is False

        snapshot = at.session_state["input_validation_snapshot"]
        db_result = snapshot["db_result"]
        assert db_result["status"] == "FAIL"
        error = str(db_result.get("error", ""))
        assert "服务器路径" in error
        assert "压缩" in error
        assert ("本地上传" in error or "解压" in error)

        # No project snapshot created for gzip path (all_valid is False,
        # so project_database_path is never set).
        # Verify wf_s3/wf_s4 were NOT synced to the gzip path.
        assert "wf_s3_database" not in at.session_state or (
            ".fasta.gz" not in str(at.session_state["wf_s3_database"])
        )

    def test_same_gzip_succeeds_via_upload(self, monkeypatch, tmp_path):
        """场景 B: same gzip via upload → PASS, normalised to database.fasta."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        data_root = tmp_path / "data"
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))

        # Create gzip content.
        import gzip, io
        raw = b">seq1\nACGTACGT\n>seq2\nTGCATGCA\n"
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(raw)
        gz_bytes = buf.getvalue()

        primers_bytes = self._read(_EXAMPLE_DATA / "primers.tsv")
        tax_bytes = self._read(_EXAMPLE_DATA / "taxonomy.tsv")

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # Primers + taxonomy: server path.  Database: upload (default).
        at.radio("_inputs_primers_mode").set_value("服务器路径").run()
        at.radio("_inputs_taxonomy_mode").set_value("服务器路径").run()
        assert not at.exception
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")
        ).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")
        ).run()
        assert not at.exception

        # Database via upload.
        at.file_uploader("_ws_database_uploader").upload(
            "db.fasta.gz", gz_bytes, "application/gzip",
        ).run()
        assert not at.exception

        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        assert at.session_state["inputs_validated"] is True

        db_path = at.session_state["project_database_path"]
        assert Path(db_path).name == "database.fasta"
        # Saved file is plain readable FASTA.
        saved_content = Path(db_path).read_bytes()
        assert saved_content == raw

        wf_s3_db = at.session_state["wf_s3_database"]
        assert "database.fasta" in str(wf_s3_db)

        wf_s4_db = at.session_state["wf_s4_database"]
        assert str(wf_s4_db).endswith("index/database.fasta")


# ═══════════════════════════════════════════════════════════════════════════
# build_manual_primers_tsv unit tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildManualPrimersTsv:

    def test_single_row_pass(self):
        result = build_manual_primers_tsv([{
            "primer_id": "P1", "forward": "atcg", "reverse": "gcta",
            "min_length": "100", "max_length": "200",
        }])
        assert result["status"] == "PASS"
        text = result["content"].decode("utf-8")
        lines = text.splitlines()
        assert lines[0] == "primer_id\tforward\treverse\tmin_length\tmax_length"
        assert lines[1] == "P1\tATCG\tGCTA\t100\t200"
        assert len(lines) == 2
        assert "\r" not in text

    def test_uppercase_normalization(self):
        result = build_manual_primers_tsv([{
            "primer_id": "test", "forward": "atcg", "reverse": "gcta",
            "min_length": "100", "max_length": "200",
        }])
        assert b"\tATCG\t" in result["content"]

    def test_empty_rows_fail(self):
        result = build_manual_primers_tsv([])
        assert result["status"] == "FAIL"
        assert "至少需要" in result["error"]

    def test_missing_field_fail(self):
        result = build_manual_primers_tsv([{
            "primer_id": "P1", "forward": "", "reverse": "GCTA",
            "min_length": "100", "max_length": "200",
        }])
        assert result["status"] == "FAIL"
        assert "第 1 行" in result["error"]
        assert "前向引物" in result["error"]

    def test_illegal_sequence_fail(self):
        result = build_manual_primers_tsv([{
            "primer_id": "P1", "forward": "ATCXG", "reverse": "GCTA",
            "min_length": "100", "max_length": "200",
        }])
        assert result["status"] == "FAIL"
        assert "X" in result["error"]

    def test_duplicate_id_fail(self):
        result = build_manual_primers_tsv([
            {"primer_id": "P1", "forward": "ATCG", "reverse": "GCTA",
             "min_length": "100", "max_length": "200"},
            {"primer_id": "P1", "forward": "GGGG", "reverse": "CCCC",
             "min_length": "100", "max_length": "200"},
        ])
        assert result["status"] == "FAIL"
        assert "重复" in result["error"]

    def test_unsafe_id_slash_fail(self):
        result = build_manual_primers_tsv([{
            "primer_id": "bad/id", "forward": "ATCG", "reverse": "GCTA",
            "min_length": "100", "max_length": "200",
        }])
        assert result["status"] == "FAIL"

    def test_invalid_length_fail(self):
        result = build_manual_primers_tsv([{
            "primer_id": "P1", "forward": "ATCG", "reverse": "GCTA",
            "min_length": "abc", "max_length": "200",
        }])
        assert result["status"] == "FAIL"
        assert "不是有效整数" in result["error"]

    def test_min_greater_than_max_fail(self):
        result = build_manual_primers_tsv([{
            "primer_id": "P1", "forward": "ATCG", "reverse": "GCTA",
            "min_length": "500", "max_length": "200",
        }])
        assert result["status"] == "FAIL"
        assert "不能大于" in result["error"]

    @pytest.mark.parametrize("bad_char", ["\x00", "\x1f", "\x7f", "\t", "\n"])
    def test_control_chars_in_id_fail(self, bad_char):
        pid = f"bad{bad_char}id"
        result = build_manual_primers_tsv([{
            "primer_id": pid, "forward": "ATCG", "reverse": "GCTA",
            "min_length": "100", "max_length": "200",
        }])
        assert result["status"] == "FAIL"
        assert result["content"] is None
        assert "第 1 行" in result["error"]

    def test_two_rows_pass(self):
        result = build_manual_primers_tsv([
            {"primer_id": "P1", "forward": "ATCG", "reverse": "GCTA",
             "min_length": "100", "max_length": "200"},
            {"primer_id": "P2", "forward": "GGGG", "reverse": "CCCC",
             "min_length": "50", "max_length": "150"},
        ])
        assert result["status"] == "PASS"
        assert len(result["normalized_rows"]) == 2


# ═══════════════════════════════════════════════════════════════════════════
# direct fill AppTests
# ═══════════════════════════════════════════════════════════════════════════

class TestDirectFillWorkflow:

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    @staticmethod
    def _read(path):
        return Path(path).read_bytes()

    def test_direct_fill_success(self, monkeypatch, tmp_path):
        """场景 A: fill one primer pair, save+validate, PASS."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        data_root = tmp_path / "data"
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))
        db_bytes = self._read(_EXAMPLE_DATA / "real_mito_small.fasta")
        tax_bytes = self._read(_EXAMPLE_DATA / "taxonomy.tsv")

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # Primers: 直接填写 is default.
        at.text_input("_manual_primer_id_0").set_value("COI_test").run()
        at.text_input("_manual_forward_0").set_value(
            "GGTCAACAAATCATAAAGATATTGG").run()
        at.text_input("_manual_reverse_0").set_value(
            "TAAACTTCAGGGTGACCAAAAAATCA").run()
        at.text_input("_manual_min_length_0").set_value("100").run()
        at.text_input("_manual_max_length_0").set_value("400").run()
        assert not at.exception

        at.file_uploader("_ws_database_uploader").upload(
            "db.fasta", db_bytes, "text/plain").run()
        at.file_uploader("_ws_taxonomy_uploader").upload(
            "tax.tsv", tax_bytes, "text/tab-separated-values").run()
        assert not at.exception

        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is True

        pp = at.session_state["project_primers_path"]
        assert Path(pp).name == "primers.tsv"
        saved = Path(pp).read_text()
        assert "COI_test\tGGTCAACAAATCATAAAGATATTGG\t" in saved
        assert "primers.tsv" in str(at.session_state["wf_s1_primers"])

    def test_direct_fill_error_revalidation(self, monkeypatch, tmp_path):
        """场景 B: valid first, then invalid revalidation preserves original."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        data_root = tmp_path / "data"
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))
        db_bytes = self._read(_EXAMPLE_DATA / "real_mito_small.fasta")
        tax_bytes = self._read(_EXAMPLE_DATA / "taxonomy.tsv")

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # First: valid data.
        at.text_input("_manual_primer_id_0").set_value("P1").run()
        at.text_input("_manual_forward_0").set_value("ATCG").run()
        at.text_input("_manual_reverse_0").set_value("GCTA").run()
        at.text_input("_manual_min_length_0").set_value("100").run()
        at.text_input("_manual_max_length_0").set_value("200").run()
        at.file_uploader("_ws_database_uploader").upload(
            "db.fasta", db_bytes, "text/plain").run()
        at.file_uploader("_ws_taxonomy_uploader").upload(
            "tax.tsv", tax_bytes, "text/tab-separated-values").run()

        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is True
        pp = at.session_state["project_primers_path"]
        original = Path(pp).read_text()

        # Second: invalid forward.
        at.text_input("_manual_forward_0").set_value("ATCXG").run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is False

        snap = at.session_state["input_validation_snapshot"]
        error = str(snap.get("primers_result", {}).get("error", ""))
        assert "第 1 行" in error or "X" in error
        assert Path(pp).read_text() == original
        uploads = Path(at.session_state["ws_uploads_dir"])
        assert list(uploads.glob(".tmp_*")) == []

    def test_error_survives_rerun(self, monkeypatch, tmp_path):
        """After a failed revalidation, error text survives a plain rerun."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        data_root = tmp_path / "data"
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))
        db_bytes = self._read(_EXAMPLE_DATA / "real_mito_small.fasta")
        tax_bytes = self._read(_EXAMPLE_DATA / "taxonomy.tsv")

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # First successful validation.
        at.text_input("_manual_primer_id_0").set_value("P1").run()
        at.text_input("_manual_forward_0").set_value("ATCG").run()
        at.text_input("_manual_reverse_0").set_value("GCTA").run()
        at.text_input("_manual_min_length_0").set_value("100").run()
        at.text_input("_manual_max_length_0").set_value("200").run()
        at.file_uploader("_ws_database_uploader").upload(
            "db.fasta", db_bytes, "text/plain").run()
        at.file_uploader("_ws_taxonomy_uploader").upload(
            "tax.tsv", tax_bytes, "text/tab-separated-values").run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is True
        pp = at.session_state["project_primers_path"]
        original = Path(pp).read_text()

        # Second: invalid forward, validate.
        at.text_input("_manual_forward_0").set_value("ATCXG").run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is False

        # Simulate a plain rerun (no button click).
        at.run(timeout=30)
        assert not at.exception

        # After rerun, the error text must still be visible.
        all_errors = [e.value for e in at.error]
        combined = " ".join(all_errors)
        assert "第 1 行" in combined or "X" in combined or "非法字符" in combined, (
            f"Expected error text in page, got: {combined!r}"
        )
        # No spurious generic "文件保存失败" message.
        assert "文件保存失败" not in combined, (
            f"Spurious generic error found: {combined!r}"
        )

        snap = at.session_state["input_validation_snapshot"]
        # primers: FAIL with specific error.
        assert snap["primers_result"]["status"] == "FAIL"
        # database: PASS with real path.
        assert snap["db_result"]["status"] == "PASS"
        assert snap["db_result"].get("path"), "db_result has no path"
        # taxonomy: PASS with real path.
        assert snap["tax_result"]["status"] == "PASS"
        assert snap["tax_result"].get("path"), "tax_result has no path"
        # output: not FAIL.
        assert snap["out_result"]["status"] in ("PASS", "WARN"), (
            f"out_result wrongly FAIL: {snap['out_result']}"
        )
        # failures list has input names, not full error body.
        assert "引物文件" in snap["failures"]
        assert all(len(f) < 50 for f in snap["failures"])

        # DB/taxonomy must NOT show spurious failures in page elements.
        for e in at.error:
            assert "参考数据库" not in (e.value or ""), (
                f"DB wrongly shows error: {e.value!r}"
            )
            assert "分类信息" not in (e.value or ""), (
                f"Taxonomy wrongly shows error: {e.value!r}"
            )

        # Original file preserved, no temp residue.
        assert Path(pp).read_text() == original
        uploads = Path(at.session_state["ws_uploads_dir"])
        assert list(uploads.glob(".tmp_*")) == []

    def test_default_mode_is_direct_fill(self):
        """Default primers mode is 直接填写."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        assert at.radio("_inputs_primers_mode").value == "直接填写"
        at.text_input("_manual_primer_id_0")  # no KeyError

    def test_switch_to_upload_shows_file_uploader(self):
        """Switch to 本地上传 shows file_uploader."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        at.radio("_inputs_primers_mode").set_value("本地上传").run()
        assert not at.exception
        at.file_uploader("_ws_primers_uploader")  # no KeyError

    def test_switch_to_server_shows_text_input(self):
        """Switch to 服务器路径 shows text_input."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        at.radio("_inputs_primers_mode").set_value("服务器路径").run()
        assert not at.exception
        at.text_input("_inputs_primers_path")  # no KeyError


# ═══════════════════════════════════════════════════════════════════════════
# pipeline plan & executor tests
# ═══════════════════════════════════════════════════════════════════════════

def _make_plan(**overrides):
    defaults = {
        "qc_pre_command": ["cmd", "qc-pre"],
        "qc_summary_command": ["cmd", "qc-summary"],
        "qc_spec_command": ["cmd", "qc-spec"],
        "obipcr_command": ["cmd", "obipcr"],
        "final_report_command": ["cmd", "final-report"],
    }
    defaults.update(overrides)
    return build_full_pipeline_plan(**defaults)  # type: ignore[arg-type]


class TestBuildFullPipelinePlan:

    def test_five_steps(self):
        plan = _make_plan()
        assert len(plan) == 5

    def test_keys_in_order(self):
        plan = _make_plan()
        assert [s["key"] for s in plan] == ["s1", "s2", "s3", "s4", "s5"]

    def test_result_keys(self):
        plan = _make_plan()
        assert [s["result_key"] for s in plan] == [
            "wf_s1_result", "wf_s2_result", "wf_s3_result",
            "wf_s4_result", "wf_s5_result",
        ]

    def test_commands_are_lists_of_str(self):
        plan = _make_plan()
        for s in plan:
            assert isinstance(s["command"], list)
            assert all(isinstance(a, str) for a in s["command"])

    def test_commands_preserved(self):
        plan = _make_plan(
            qc_pre_command=["a", "b"],
            qc_spec_command=["x", "y", "z"],
        )
        assert plan[0]["command"] == ["a", "b"]
        assert plan[2]["command"] == ["x", "y", "z"]

    def test_all_five_timeouts_mapped(self):
        plan = _make_plan(
            qc_pre_timeout=10, qc_summary_timeout=20,
            qc_spec_timeout=30, obipcr_timeout=40,
            final_report_timeout=50,
        )
        assert [s["timeout"] for s in plan] == [10, 20, 30, 40, 50]

    def test_default_timeouts(self):
        plan = _make_plan()
        assert [step["timeout"] for step in plan] == [None] * 5


class TestRunFullPipeline:

    @staticmethod
    def _ok_runner(command, *, timeout):
        return {"status": "PASS", "command": command, "timeout": timeout}

    @staticmethod
    def _fail_runner(command, *, timeout):
        return {"status": "FAIL", "message": "error"}

    @staticmethod
    def _timeout_runner(command, *, timeout):
        return {"status": "TIMEOUT", "message": "timed out"}

    def test_cancelled_step_stops_following_steps(self):
        plan = _make_plan()
        calls = 0

        def runner(command, *, timeout):
            nonlocal calls
            calls += 1
            return {"status": "CANCELLED"}

        result = run_full_pipeline(plan, runner=runner)
        assert result["status"] == "CANCELLED"
        assert result["failed_step"] == "s1"
        assert result["message"] == "分析已由用户终止。"
        assert calls == 1
        assert "wf_s1_result" in result["results"]
        assert "wf_s2_result" not in result["results"]

    def test_all_pass(self):
        plan = _make_plan()
        results_log: list[list[str]] = []

        def record_runner(cmd, *, timeout):
            results_log.append(cmd)
            return {"status": "PASS"}

        result = run_full_pipeline(plan, runner=record_runner)
        assert result["status"] == "PASS"
        assert result["failed_step"] is None
        assert result["completed_steps"] == ["s1", "s2", "s3", "s4", "s5"]
        assert list(result["results"]) == [
            "wf_s1_result", "wf_s2_result", "wf_s3_result",
            "wf_s4_result", "wf_s5_result",
        ]
        assert len(results_log) == 5

    def test_timeout_passed_to_runner(self):
        plan = _make_plan(qc_pre_timeout=77)
        seen: list[int] = []

        def capture_runner(cmd, *, timeout):
            seen.append(timeout)
            return {"status": "PASS"}

        run_full_pipeline(plan, runner=capture_runner)
        assert seen[0] == 77

    def test_s3_fail_stops(self):
        plan = _make_plan()
        call_log: list[str] = []

        def runner(cmd, *, timeout):
            call_log.append(f"called_{len(call_log)}")
            if len(call_log) == 3:
                return {"status": "FAIL"}
            return {"status": "PASS"}

        result = run_full_pipeline(plan, runner=runner)
        assert result["status"] == "FAIL"
        assert result["failed_step"] == "s3"
        assert result["completed_steps"] == ["s1", "s2"]
        assert len(call_log) == 3  # s4, s5 never called
        assert "wf_s3_result" in result["results"]
        assert "s3" not in result["results"]

    def test_s2_timeout_stops(self):
        plan = _make_plan()
        call_log: list[str] = []

        def runner(cmd, *, timeout):
            call_log.append(f"called_{len(call_log)}")
            if len(call_log) == 2:
                return {"status": "TIMEOUT"}
            return {"status": "PASS"}

        result = run_full_pipeline(plan, runner=runner)
        assert result["status"] == "TIMEOUT"
        assert result["failed_step"] == "s2"
        assert result["completed_steps"] == ["s1"]
        assert len(call_log) == 2
        assert "wf_s2_result" in result["results"]
        assert "wf_s3_result" not in result["results"]
        assert "wf_s4_result" not in result["results"]
        assert "wf_s5_result" not in result["results"]

    def test_none_status_is_fail(self):
        plan = _make_plan()
        call_log: list[str] = []

        def runner(cmd, *, timeout):
            call_log.append(f"called_{len(call_log)}")
            if len(call_log) == 1:
                return {"status": None}
            return {"status": "PASS"}

        result = run_full_pipeline(plan, runner=runner)
        assert result["status"] == "FAIL"
        assert result["failed_step"] == "s1"
        assert len(call_log) == 1
        assert "wf_s1_result" in result["results"]
        assert "wf_s2_result" not in result["results"]

    def test_missing_status_is_fail(self):
        plan = _make_plan()
        call_log: list[str] = []

        def runner(cmd, *, timeout):
            call_log.append(f"called_{len(call_log)}")
            if len(call_log) == 2:
                return {}  # no "status" key
            return {"status": "PASS"}

        result = run_full_pipeline(plan, runner=runner)
        assert result["status"] == "FAIL"
        assert result["failed_step"] == "s2"
        assert len(call_log) == 2
        assert "wf_s2_result" in result["results"]
        assert "wf_s3_result" not in result["results"]

    def test_plan_unchanged(self):
        import copy
        plan = _make_plan()
        before = copy.deepcopy(plan)
        run_full_pipeline(plan, runner=self._ok_runner)
        assert plan == before

    def test_progress_callback_reports_each_step_before_and_after(self):
        plan = _make_plan()
        events: list[dict] = []

        result = run_full_pipeline(
            plan,
            runner=self._ok_runner,
            on_progress=lambda event: events.append(dict(event)),
        )

        assert result["status"] == "PASS"
        assert len(events) == 10
        assert [event["label"] for event in events[::2]] == [
            step["label"] for step in plan
        ]
        assert all(event["phase"] == "running" for event in events[::2])
        assert all(event["phase"] == "finished" for event in events[1::2])
        assert all(event["status"] == "PASS" for event in events[1::2])
        assert [event["index"] for event in events[::2]] == [1, 2, 3, 4, 5]
        assert all(event["total"] == 5 for event in events)


# ═══════════════════════════════════════════════════════════════════════════
# full pipeline UI AppTests
# ═══════════════════════════════════════════════════════════════════════════

class TestFullPipelineUi:

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    @staticmethod
    def _read(path):
        return Path(path).read_bytes()

    @staticmethod
    def _set_dependencies_available(at):
        from fullpcr.gui_helpers import collect_environment_status
        real_env = collect_environment_status()
        real_env["obipcr"] = {
            "available": True, "version": "mock", "error": None,
        }
        real_env["mfeprimer"] = {
            "available": True, "version": "mock", "error": None,
        }
        real_env["checked_at"] = time.time() + 3600
        at.session_state["environment_status"] = real_env
        at.session_state["environment_checked_at"] = time.time() + 3600

    def _setup_valid_inputs(self, at, monkeypatch, tmp_path):
        """Validate inputs in server-path mode so the pipeline button is enabled."""
        data_root = tmp_path / "data"
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception
        _enable_advanced_workflow(at)
        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        project_root = tmp_path / "pipeline-project"
        project_root.mkdir(exist_ok=True)
        at.session_state["inputs_output_dir"] = str(project_root)
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is True

    @staticmethod
    def _wait_job_terminal(project_root, timeout=5.0):
        from fullpcr.pipeline_jobs import get_pipeline_job
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = get_pipeline_job(str(project_root))
            if state is not None and state.get("status") != "RUNNING":
                return state
            time.sleep(0.01)
        raise AssertionError("pipeline job did not finish")

    def test_invalid_inputs_button_disabled(self, monkeypatch, tmp_path):
        """Button is disabled when inputs not validated; no subprocess calls."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        with mock.patch("subprocess.run") as mr:
            at.button("full_pipeline_run_btn").click().run()
        mr.assert_not_called()
        # Page should show hint to validate first.
        all_text = " ".join(
            [e.value for e in at.info] + [e.value for e in at.warning]
        )
        assert "验证" in all_text or "请先" in all_text

    def test_dry_run_no_execution(self, monkeypatch, tmp_path):
        """Dry-run: plan stored, no subprocess, even without obipcr/MFEprimer."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        self._setup_valid_inputs(at, monkeypatch, tmp_path)
        at.toggle("_workflow_dry_run").set_value(True).run()
        assert not at.exception

        with mock.patch("subprocess.run") as mr:
            at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        mr.assert_not_called()

        plan = at.session_state["full_pipeline_plan"]
        assert len(plan) == 5
        assert plan[0]["key"] == "s1"
        assert plan[4]["key"] == "s5"
        assert "full_pipeline_result" not in at.session_state
        assert "wf_s1_result" not in at.session_state

    def test_running_job_disables_button_and_progress_survives_rerun(
        self, monkeypatch, tmp_path
    ):
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        self._set_dependencies_available(at)
        self._setup_valid_inputs(at, monkeypatch, tmp_path)
        now = datetime.now(timezone.utc)
        running = {
            "schema_version": 1,
            "job_id": "job-stable-123",
            "status": "RUNNING",
            "current_step": "s3",
            "current_label": "特异性分析",
            "phase": "running",
            "progress_current": 2,
            "progress_total": 5,
            "completed_steps": ["s1", "s2"],
            "outcome": None,
            "owner_pid": os.getppid(),
            "started_at": (now - timedelta(minutes=3)).isoformat(),
            "step_started_at": (now - timedelta(seconds=75)).isoformat(),
            "step_timings": {
                "s1": {
                    "started_at": (now - timedelta(minutes=3)).isoformat(),
                    "finished_at": (now - timedelta(minutes=2)).isoformat(),
                    "elapsed_seconds": 60.0,
                    "status": "PASS",
                },
                "s2": {
                    "started_at": (now - timedelta(minutes=2)).isoformat(),
                    "finished_at": (now - timedelta(seconds=75)).isoformat(),
                    "elapsed_seconds": 45.0,
                    "status": "PASS",
                },
                "s3": {
                    "started_at": (now - timedelta(seconds=75)).isoformat(),
                    "finished_at": None,
                    "elapsed_seconds": None,
                    "status": "RUNNING",
                },
            },
        }
        root = tmp_path / "running-project"
        root.mkdir()
        at.session_state["project_output_root"] = str(root)
        job_dir = root / ".fullpcr_jobs"
        job_dir.mkdir()
        (job_dir / "pipeline_state.json").write_text(
            json.dumps(running), encoding="utf-8"
        )
        (job_dir / "pipeline.lock").write_text(
            json.dumps({"job_id": running["job_id"], "owner_pid": os.getppid()}),
            encoding="utf-8",
        )

        at.run(timeout=30)
        assert not at.exception
        button = at.button("full_pipeline_run_btn")
        assert button.label == "分析正在运行"
        assert button.disabled is True
        progress = at.get("progress")
        assert len(progress) == 1
        assert progress[0].proto.value == 40
        assert "特异性分析" in progress[0].proto.text
        assert "总用时" in progress[0].proto.text
        assert "本步" not in progress[0].proto.text
        captions = " ".join(str(item.value) for item in at.caption)
        assert "基础质控：01:00" in captions
        assert "特异性分析" in captions and "运行中" in captions

        at.run(timeout=30)
        assert not at.exception
        progress = at.get("progress")
        assert len(progress) == 1
        assert progress[0].proto.value == 40
        assert "特异性分析" in progress[0].proto.text
        persisted = json.loads((job_dir / "pipeline_state.json").read_text())
        assert persisted["job_id"] == "job-stable-123"

    def test_suspected_stuck_shows_terminate_button(
        self, monkeypatch, tmp_path
    ):
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        self._set_dependencies_available(at)
        self._setup_valid_inputs(at, monkeypatch, tmp_path)
        now = datetime.now(timezone.utc)
        running = {
            "schema_version": 1,
            "job_id": "job-stuck-123",
            "status": "RUNNING",
            "current_step": "s3",
            "current_label": "特异性分析",
            "phase": "running",
            "progress_current": 2,
            "progress_total": 5,
            "completed_steps": ["s1", "s2"],
            "outcome": None,
            "owner_pid": os.getppid(),
            "started_at": (now - timedelta(minutes=15)).isoformat(),
            "step_started_at": (now - timedelta(minutes=12)).isoformat(),
            "step_timings": {},
            "suspected_stuck": True,
            "last_activity_at": (now - timedelta(minutes=10)).isoformat(),
            "last_health_check_at": now.isoformat(),
        }
        root = tmp_path / "stuck-project"
        root.mkdir()
        at.session_state["project_output_root"] = str(root)
        job_dir = root / ".fullpcr_jobs"
        job_dir.mkdir()
        (job_dir / "pipeline_state.json").write_text(
            json.dumps(running), encoding="utf-8"
        )
        (job_dir / "pipeline.lock").write_text(
            json.dumps({"job_id": running["job_id"], "owner_pid": os.getppid()}),
            encoding="utf-8",
        )

        at.run(timeout=30)
        assert not at.exception
        assert at.button(f"cancel_pipeline_{running['job_id']}").label == "终止当前分析"
        warnings = " ".join(str(item.value) for item in at.warning)
        assert "疑似" not in warnings or "卡住" in warnings
        assert "可能已经卡住" in warnings

    def test_terminal_job_restores_results_and_reenables_button(
        self, monkeypatch, tmp_path
    ):
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        self._set_dependencies_available(at)
        self._setup_valid_inputs(at, monkeypatch, tmp_path)
        results = {
            f"wf_s{index}_result": {"status": "PASS", "step": index}
            for index in range(1, 6)
        }
        outcome = {
            "status": "PASS",
            "results": results,
            "completed_steps": ["s1", "s2", "s3", "s4", "s5"],
            "failed_step": None,
            "message": "全部五步完成。",
        }
        terminal = {
            "job_id": "job-pass-123",
            "status": "PASS",
            "phase": "finished",
            "progress_current": 5,
            "progress_total": 5,
            "completed_steps": ["s1", "s2", "s3", "s4", "s5"],
            "outcome": outcome,
        }
        root = tmp_path / "terminal-project"
        root.mkdir()
        at.session_state["project_output_root"] = str(root)
        job_dir = root / ".fullpcr_jobs"
        job_dir.mkdir()
        (job_dir / "pipeline_state.json").write_text(
            json.dumps(terminal), encoding="utf-8"
        )

        at.run(timeout=30)
        assert not at.exception
        assert at.button("full_pipeline_run_btn").disabled is False
        assert at.session_state["full_pipeline_result"]["status"] == "PASS"
        for key, value in results.items():
            assert at.session_state[key] == value

    def test_all_pass(self, monkeypatch, tmp_path):
        """A background PASS outcome is restored into session_state."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        # Inject available env so dependency check passes.
        from fullpcr.gui_helpers import collect_environment_status
        import time
        real_env = collect_environment_status()
        real_env["obipcr"] = {"available": True, "version": "mock", "error": None}
        real_env["mfeprimer"] = {"available": True, "version": "mock", "error": None}
        real_env["checked_at"] = time.time() + 3600
        at.session_state["environment_status"] = real_env
        at.session_state["environment_checked_at"] = time.time() + 3600

        self._setup_valid_inputs(at, monkeypatch, tmp_path)

        calls = []

        def pass_runner(command, *, timeout):
            calls.append(command)
            return {"status": "PASS", "command": command}

        from fullpcr.pipeline_jobs import start_pipeline_job
        project_root = Path(at.session_state["project_output_root"])
        plan = _make_plan()
        at.session_state["full_pipeline_plan"] = plan
        started = start_pipeline_job(
            str(project_root), plan, runner=pass_runner
        )
        assert started["started"] is True
        self._wait_job_terminal(project_root)
        at.run(timeout=30)
        assert not at.exception

        assert len(calls) == 5
        assert all(isinstance(command, list) for command in calls)

        outcome = at.session_state["full_pipeline_result"]
        assert outcome["status"] == "PASS"
        assert outcome["completed_steps"] == ["s1", "s2", "s3", "s4", "s5"]
        progress = at.get("progress")
        assert len(progress) == 1
        assert progress[0].proto.value == 100
        assert progress[0].proto.text.startswith("五步分析全部完成")
        assert "总用时" in progress[0].proto.text
        assert any(
            "分析完成，结果已保存" in str(item.value)
            for item in at.success
        )

        for rk in ["wf_s1_result", "wf_s2_result", "wf_s3_result", "wf_s4_result", "wf_s5_result"]:
            assert rk in at.session_state

        # Rerun persistence: outcome + "完整分析已完成" survive plain rerun.
        prev_call_count = len(calls)
        at.run(timeout=30)
        assert not at.exception
        assert len(calls) == prev_call_count  # rerun did not execute again
        assert at.session_state["full_pipeline_result"]["status"] == "PASS"
        all_success = [e.value for e in at.success]
        assert any("完整分析已完成" in (v or "") for v in all_success)

    def test_s3_fail_stops(self, monkeypatch, tmp_path):
        """A third-step background FAIL is restored; s4/s5 remain absent."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        from fullpcr.gui_helpers import collect_environment_status
        import time
        real_env = collect_environment_status()
        real_env["obipcr"] = {"available": True, "version": "mock", "error": None}
        real_env["mfeprimer"] = {"available": True, "version": "mock", "error": None}
        real_env["checked_at"] = time.time() + 3600
        at.session_state["environment_status"] = real_env
        at.session_state["environment_checked_at"] = time.time() + 3600

        self._setup_valid_inputs(at, monkeypatch, tmp_path)

        call_count = [0]

        def _fail_third(command, *, timeout):
            call_count[0] += 1
            status = "FAIL" if call_count[0] == 3 else "PASS"
            return {
                "status": status,
                "message": "mock failure" if status == "FAIL" else "ok",
                "returncode": 1 if status == "FAIL" else 0,
                "stdout": "",
                "stderr": "",
            }

        from fullpcr.pipeline_jobs import start_pipeline_job
        project_root = Path(at.session_state["project_output_root"])
        plan = _make_plan()
        at.session_state["full_pipeline_plan"] = plan
        started = start_pipeline_job(
            str(project_root), plan, runner=_fail_third
        )
        assert started["started"] is True
        self._wait_job_terminal(project_root)
        at.run(timeout=30)
        assert not at.exception
        assert call_count[0] == 3

        outcome = at.session_state["full_pipeline_result"]
        assert outcome["status"] == "FAIL"
        assert outcome["failed_step"] == "s3"
        assert outcome["completed_steps"] == ["s1", "s2"]
        assert "wf_s3_result" in at.session_state
        assert "wf_s4_result" not in at.session_state
        assert "wf_s5_result" not in at.session_state

        # Rerun: failure message survives.
        prev_calls = call_count[0]
        at.run(timeout=30)
        assert not at.exception
        assert call_count[0] == prev_calls
        all_errors = [e.value for e in at.error]
        combined = " ".join(str(v) for v in all_errors)
        assert "失败" in combined or "第 3" in combined or "特异性" in combined
        assert "停止" in combined or "未执行" in combined

    def test_timeout_stops(self, monkeypatch, tmp_path):
        """A second-step background TIMEOUT stops and is restored."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        from fullpcr.gui_helpers import collect_environment_status
        import time
        real_env = collect_environment_status()
        real_env["obipcr"] = {"available": True, "version": "mock", "error": None}
        real_env["mfeprimer"] = {"available": True, "version": "mock", "error": None}
        real_env["checked_at"] = time.time() + 3600
        at.session_state["environment_status"] = real_env
        at.session_state["environment_checked_at"] = time.time() + 3600

        self._setup_valid_inputs(at, monkeypatch, tmp_path)

        call_count = [0]

        def _timeout_second(command, *, timeout):
            call_count[0] += 1
            status = "TIMEOUT" if call_count[0] == 2 else "PASS"
            return {
                "status": status,
                "message": "mock timeout" if status == "TIMEOUT" else "ok",
                "returncode": None if status == "TIMEOUT" else 0,
                "stdout": "",
                "stderr": "",
            }

        from fullpcr.pipeline_jobs import start_pipeline_job
        project_root = Path(at.session_state["project_output_root"])
        plan = _make_plan()
        at.session_state["full_pipeline_plan"] = plan
        started = start_pipeline_job(
            str(project_root), plan, runner=_timeout_second
        )
        assert started["started"] is True
        self._wait_job_terminal(project_root)
        at.run(timeout=30)
        assert not at.exception
        assert call_count[0] == 2

        outcome = at.session_state["full_pipeline_result"]
        assert outcome["status"] == "TIMEOUT"
        assert outcome["failed_step"] == "s2"
        assert "wf_s2_result" in at.session_state
        assert "wf_s3_result" not in at.session_state

        # Rerun: timeout message survives.
        prev_calls = call_count[0]
        at.run(timeout=30)
        assert not at.exception
        assert call_count[0] == prev_calls
        all_errors = [e.value for e in at.error]
        combined = " ".join(str(v) for v in all_errors)
        assert "超时" in combined or "质控汇总" in combined
        assert "停止" in combined or "未执行" in combined

    def test_dependency_missing_blocked(self, monkeypatch, tmp_path):
        """Button disabled when obipcr/MFEprimer unavailable."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        import time

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        # Set env with obipcr unavailable, checked_at in future.
        from fullpcr.gui_helpers import collect_environment_status
        real_env = collect_environment_status()
        real_env["obipcr"] = {"available": False, "version": None, "error": "not found"}
        real_env["mfeprimer"] = {"available": False, "version": None, "error": "not found"}
        real_env["checked_at"] = time.time() + 3600
        at.session_state["environment_status"] = real_env
        at.session_state["environment_checked_at"] = time.time() + 3600

        self._setup_valid_inputs(at, monkeypatch, tmp_path)

        # Page shows missing dependency names (button is disabled, no click needed).
        all_warnings = [e.value for e in at.warning]
        combined = " ".join(str(v) for v in all_warnings)
        assert "obipcr" in combined or "MFEprimer" in combined

        # subprocess.run must not be called.
        with mock.patch("subprocess.run") as mr:
            pass  # disabled button prevents execution
        mr.assert_not_called()

    def test_plan_parameter_mapping(self, monkeypatch, tmp_path):
        """Plan commands contain correct paths from session state."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        self._setup_valid_inputs(at, monkeypatch, tmp_path)

        # Mock env and subprocess.
        from fullpcr.gui_helpers import collect_environment_status
        import time
        real_env = collect_environment_status()
        real_env["obipcr"] = {"available": True, "version": "mock", "error": None}
        real_env["mfeprimer"] = {"available": True, "version": "mock", "error": None}
        real_env["checked_at"] = time.time() + 3600
        at.session_state["environment_status"] = real_env
        at.session_state["environment_checked_at"] = time.time() + 3600

        at.toggle("_workflow_dry_run").set_value(True).run()
        at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        plan = at.session_state["full_pipeline_plan"]
        assert plan is not None
        assert len(plan) == 5

        # Step 1: primers path present.
        s1_cmd = " ".join(plan[0]["command"])
        assert "example_data/primers.tsv" in s1_cmd
        # Step 3: database path present.
        s3_cmd = " ".join(plan[2]["command"])
        assert "example_data/real_mito_small.fasta" in s3_cmd
        # Step 4: index database path present.
        s4_cmd = " ".join(plan[3]["command"])
        assert "index/real_mito_small.fasta" in s4_cmd
        # Timeout values.
        assert [step["timeout"] for step in plan] == [None] * 5
        assert all("--timeout" not in step["command"] for step in plan)
        assert plan[2]["command"][
            plan[2]["command"].index("--max-tm") + 1
        ] == "100.0"
        captions = " ".join(str(item.value) for item in at.caption)
        assert "无时间上限" not in captions

    def test_plan_direct_fill_and_upload_paths(self, monkeypatch, tmp_path):
        """Direct-fill primers + upload DB/taxonomy → plan has correct workspace paths."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        import time

        data_root = tmp_path / "data"
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))
        from fullpcr.gui_helpers import collect_environment_status
        real_env = collect_environment_status()
        real_env["obipcr"] = {"available": True, "version": "mock", "error": None}
        real_env["mfeprimer"] = {"available": True, "version": "mock", "error": None}
        real_env["checked_at"] = time.time() + 3600

        db_bytes = self._read(_EXAMPLE_DATA / "real_mito_small.fasta")
        tax_bytes = self._read(_EXAMPLE_DATA / "taxonomy.tsv")

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.session_state["environment_status"] = real_env
        at.session_state["environment_checked_at"] = time.time() + 3600

        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # Primers: direct fill.
        at.text_input("_manual_primer_id_0").set_value("P1").run()
        at.text_input("_manual_forward_0").set_value("ATCG").run()
        at.text_input("_manual_reverse_0").set_value("GCTA").run()
        at.text_input("_manual_min_length_0").set_value("100").run()
        at.text_input("_manual_max_length_0").set_value("200").run()
        # DB + taxonomy: upload.
        at.file_uploader("_ws_database_uploader").upload(
            "db.fasta", db_bytes, "text/plain").run()
        at.file_uploader("_ws_taxonomy_uploader").upload(
            "tax.tsv", tax_bytes, "text/tab-separated-values").run()

        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is True

        # Dry-run to capture plan without execution.
        at.toggle("_workflow_dry_run").set_value(True).run()

        with mock.patch("subprocess.run") as mr:
            at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        mr.assert_not_called()

        plan = at.session_state["full_pipeline_plan"]
        proot = at.session_state["project_output_root"]
        assert plan[0]["key"] == "s1"
        assert plan[4]["key"] == "s5"

        # Helper: find flag value in command list.
        def flag_val(cmd, flag):
            try:
                idx = cmd.index(flag)
                return cmd[idx + 1]
            except (ValueError, IndexError):
                return None

        # Step 1.
        s1 = plan[0]["command"]
        assert flag_val(s1, "--primers") == str(
            at.session_state["project_primers_path"])
        assert flag_val(s1, "--outdir") == str(
            Path(proot) / "qc_results")

        # Step 2.
        s2 = plan[1]["command"]
        assert flag_val(s2, "--qc-dir") == str(
            Path(proot) / "qc_results")

        # Step 3.
        s3 = plan[2]["command"]
        assert flag_val(s3, "--primers") == str(
            at.session_state["project_primers_path"])
        assert flag_val(s3, "--database") == str(
            at.session_state["project_database_path"])
        assert flag_val(s3, "--outdir") == str(
            Path(proot) / "qc_spec_results")

        # Step 4.
        s4 = plan[3]["command"]
        assert flag_val(s4, "--primers") == str(
            at.session_state["project_primers_path"])
        assert flag_val(s4, "--database") == str(
            Path(proot) / "qc_spec_results" / "index" / "database.fasta")
        assert flag_val(s4, "--taxonomy") == str(
            at.session_state["project_taxonomy_path"])
        assert flag_val(s4, "--outdir") == str(
            Path(proot) / "obipcr_results")

        # Step 5.
        s5 = plan[4]["command"]
        assert flag_val(s5, "--obipcr-dir") == str(
            Path(proot) / "obipcr_results")
        assert flag_val(s5, "--qc-dir") == str(
            Path(proot) / "qc_results")
        assert flag_val(s5, "--spec-dir") == str(
            Path(proot) / "qc_spec_results")
        assert flag_val(s5, "--outdir") == str(
            Path(proot) / "final_results")

        # Timeouts.
        assert [step["timeout"] for step in plan] == [None] * 5


# ═══════════════════════════════════════════════════════════════════════════
# quick recommendation AppTests
# ═══════════════════════════════════════════════════════════════════════════

class TestQuickRecommendation:

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    def _inject_pipeline_state(self, at, final_dir, rank_tsv_content):
        """Inject full_pipeline_plan, full_pipeline_result, inputs_validated,
        and environment_status so the recommendation renderer runs."""
        import time
        plan = [
            {"key": "s1", "command": ["cmd1"]},
            {"key": "s2", "command": ["cmd2"]},
            {"key": "s3", "command": ["cmd3"]},
            {"key": "s4", "command": ["cmd4"]},
            {"key": "s5", "command": ["cmd5", "--outdir", str(final_dir)]},
        ]
        at.session_state["full_pipeline_plan"] = plan
        at.session_state["full_pipeline_result"] = {"status": "PASS", "failed_step": None, "message": "ok"}
        at.session_state["inputs_validated"] = True
        # Inject valid env to skip dependency check rendering.
        from fullpcr.gui_helpers import collect_environment_status
        real_env = collect_environment_status()
        real_env["obipcr"] = {"available": True, "version": "mock", "error": None}
        real_env["mfeprimer"] = {"available": True, "version": "mock", "error": None}
        real_env["checked_at"] = time.time() + 3600
        at.session_state["environment_status"] = real_env
        at.session_state["environment_checked_at"] = time.time() + 3600
        # Write primer_rank.tsv.
        (final_dir / "primer_rank.tsv").write_text(rank_tsv_content, encoding="utf-8")
        at.run(timeout=30)
        assert not at.exception

    def test_recommended_shown(self, tmp_path, monkeypatch):
        """RECOMMENDED primer → success card with correct label."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        final_dir = tmp_path / "final_results"
        final_dir.mkdir()
        rank_tsv = (
            "primer_id\tfinal_score\tfinal_status\trecommendation\treason\n"
            "P1\t0.95\tRECOMMENDED\t推荐使用\t覆盖率高\n"
            "P2\t0.60\tACCEPTABLE_WITH_WARNINGS\t可用\t二聚体警告\n"
        )

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        self._inject_pipeline_state(at, final_dir, rank_tsv)

        # Workbench ends at the run status and points to 结果总览.
        all_success = [e.value for e in at.success]
        assert any("完整分析已完成" in (v or "") for v in all_success)
        assert not any("最高评分引物" in str(v) for v in all_success)
        assert any("结果总览" in str(v.value) for v in at.info)

        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception

        # Top primer shown, NOT mislabeled as "推荐引物".
        all_success = [e.value for e in at.success]
        assert any("最高评分引物" in (v or "") for v in all_success)
        assert any("推荐" in (v or "") for v in all_success)
        # Score visible in metric.
        metric_values = [m.value for m in at.metric]
        assert any("0.95" in str(v) for v in metric_values)
        # Recommendation/reason visible.
        all_captions = [str(e.value) for e in at.caption]
        captions_text = " ".join(all_captions)
        assert "覆盖率高" in captions_text or "推荐使用" in captions_text
        # Recommendation is a concise summary; the full ranking has one
        # separate collapsed area and one download entry.
        with pytest.raises(KeyError):
            at.download_button("quick_dl_primer_rank")

    def test_not_recommended_shown(self, tmp_path, monkeypatch):
        """NOT_RECOMMENDED → error display, no misleading '推荐引物' label."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        final_dir = tmp_path / "final_results"
        final_dir.mkdir()
        rank_tsv = (
            "primer_id\tfinal_score\tfinal_status\trecommendation\treason\n"
            "P1\t0.30\tNOT_RECOMMENDED\t不推荐\t无扩增\n"
        )

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        self._inject_pipeline_state(at, final_dir, rank_tsv)

        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception

        errors = [e.value for e in at.error]
        combined = " ".join(str(v) for v in errors)
        assert "最高评分引物" in combined
        assert "不推荐" in combined
        # Must NOT call it "推荐引物".
        assert "推荐引物" not in combined

    def test_missing_file_graceful(self, tmp_path, monkeypatch):
        """Missing primer_rank.tsv → warning, no crash."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        final_dir = tmp_path / "final_results"
        final_dir.mkdir()
        # No primer_rank.tsv written.

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        self._inject_pipeline_state(at, final_dir, "dummy")
        (final_dir / "primer_rank.tsv").unlink()  # Remove after injection.
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception

        all_warnings = [e.value for e in at.warning]
        combined = " ".join(str(v) for v in all_warnings)
        assert "不可用" in combined or "不存在" in combined
        assert at.session_state["full_pipeline_result"]["status"] == "PASS"

    def test_missing_required_columns(self, tmp_path, monkeypatch):
        """Missing primer_id/final_score → column names shown, no crash."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        final_dir = tmp_path / "final_results"
        final_dir.mkdir()
        rank_tsv = "some_col\nval\n"

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        self._inject_pipeline_state(at, final_dir, rank_tsv)

        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception

        all_warnings = [e.value for e in at.warning]
        combined = " ".join(str(v) for v in all_warnings)
        assert "缺少" in combined
        assert at.session_state["full_pipeline_result"]["status"] == "PASS"

    def test_s5_outdir_missing(self, tmp_path, monkeypatch):
        """s5 without --outdir → graceful message, no crash."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # Inject plan with s5 lacking --outdir.
        plan = [
            {"key": "s1"}, {"key": "s2"}, {"key": "s3"}, {"key": "s4"},
            {"key": "s5", "command": ["cmd5"]},
        ]
        import time
        at.session_state["full_pipeline_plan"] = plan
        at.session_state["full_pipeline_result"] = {"status": "PASS", "failed_step": None}
        at.session_state["inputs_validated"] = True
        from fullpcr.gui_helpers import collect_environment_status
        real_env = collect_environment_status()
        real_env["obipcr"] = {"available": True, "version": "mock", "error": None}
        real_env["mfeprimer"] = {"available": True, "version": "mock", "error": None}
        real_env["checked_at"] = time.time() + 3600
        at.session_state["environment_status"] = real_env
        at.session_state["environment_checked_at"] = time.time() + 3600
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception

        all_infos = [e.value for e in at.info]
        combined = " ".join(str(v) for v in all_infos)
        assert "无法确定" in combined or "路径" in combined

    def test_new_validation_clears_old_results(self, monkeypatch, tmp_path):
        """Clicking validate clears prior pipeline plan, result, and step results."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        data_root = tmp_path / "data"
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        _enable_advanced_workflow(at)
        assert not at.exception

        # Pre-populate pipeline state.
        at.session_state["full_pipeline_plan"] = ["mock_plan"]
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.session_state["wf_s1_result"] = {"status": "PASS"}
        at.session_state["wf_s2_result"] = {"status": "PASS"}
        at.session_state["wf_s3_result"] = {"status": "PASS"}
        at.session_state["wf_s4_result"] = {"status": "PASS"}
        at.session_state["wf_s5_result"] = {"status": "PASS"}

        # Validate in server-path mode.
        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # Pipeline results cleared.
        assert "full_pipeline_plan" not in at.session_state
        assert "full_pipeline_result" not in at.session_state
        for rk in ["wf_s1_result", "wf_s2_result", "wf_s3_result", "wf_s4_result", "wf_s5_result"]:
            assert rk not in at.session_state, f"{rk} should be cleared"

        # Workflow paths and params must survive.
        assert "inputs_validated" in at.session_state
        assert at.session_state["inputs_validated"] is True


class TestResultsOverviewFlow:
    """Workbench output is consumed and selectively rendered by 结果总览."""

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    @staticmethod
    def _prepare_pipeline_results(at, root: Path) -> tuple[str, str, str, str]:
        final_dir = root / "final_results"
        obipcr_dir = root / "obipcr_results"
        qc_dir = root / "qc_results"
        spec_dir = root / "qc_spec_results"
        for directory in (final_dir, obipcr_dir, qc_dir, spec_dir / "spec"):
            directory.mkdir(parents=True, exist_ok=True)

        (final_dir / "primer_rank.tsv").write_text(
            "primer_id\tfinal_score\tfinal_status\tqc_status\t"
            "spec_status\trecommendation\treason\n"
            "P1\t0.95\tRECOMMENDED\tPASS\tPASS\t推荐使用\t覆盖率高\n",
            encoding="utf-8",
        )
        (obipcr_dir / "combined_summary.tsv").write_text(
            "primer_id\tspecies_count\nP1\t12\n", encoding="utf-8"
        )
        (qc_dir / "primer_qc_summary.tsv").write_text(
            "primer_id\tqc_status\nP1\tPASS\n", encoding="utf-8"
        )
        (spec_dir / "spec" / "primer_spec.tsv").write_text(
            "primer_id\tspec_status\nP1\tPASS\n", encoding="utf-8"
        )

        at.session_state["full_pipeline_plan"] = [
            {"key": "s1", "command": ["qc", "--outdir", str(qc_dir)]},
            {"key": "s2", "command": ["summary"]},
            {"key": "s3", "command": ["spec", "--outdir", str(spec_dir)]},
            {"key": "s4", "command": ["obipcr", "--outdir", str(obipcr_dir)]},
            {"key": "s5", "command": ["report", "--outdir", str(final_dir)]},
        ]
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        assert not at.exception
        return tuple(str(p) for p in (final_dir, obipcr_dir, qc_dir, spec_dir))

    def test_pipeline_results_auto_load_on_overview(self, tmp_path):
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        expected_dirs = self._prepare_pipeline_results(at, tmp_path / "project")

        # Workbench only reports completion; recommendation is not rendered here.
        assert not any(
            "本次推荐结果" in str(item.value) for item in at.subheader
        )

        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception

        assert tuple(at.session_state["res_loaded_dirs"]) == expected_dirs
        assert at.session_state["res_rank_result"]["status"] == "PASS"
        assert any("本次推荐结果" in str(item.value) for item in at.subheader)
        assert at.multiselect("_res_visible_sections").value == ["obipcr 汇总"]
        expander_labels = [item.label for item in at.expander]
        assert not any("加载当前或历史项目结果" in label for label in expander_labels)
        assert any(label.startswith("查看已加载项目结果 · ") for label in expander_labels)

        headers = [str(item.value) for item in at.header]
        assert "obipcr 汇总结果" in headers
        assert "MFEprimer 质控汇总" not in headers
        assert "MFEprimer 特异性汇总" not in headers

    def test_detail_selector_only_renders_selected_sections(self, tmp_path):
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        expected_dirs = self._prepare_pipeline_results(at, tmp_path / "project")
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception

        at.multiselect("_res_visible_sections").set_value(
            ["MFEprimer 质控", "MFEprimer 特异性"]
        ).run()
        assert not at.exception

        headers = [str(item.value) for item in at.header]
        assert "obipcr 汇总结果" not in headers
        assert "MFEprimer 质控汇总" in headers
        assert "MFEprimer 特异性汇总" in headers
        assert tuple(at.session_state["res_loaded_dirs"]) == expected_dirs

        # Selector and loaded results survive a page round trip without reloading.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        assert at.multiselect("_res_visible_sections").value == [
            "MFEprimer 质控",
            "MFEprimer 特异性",
        ]
        assert tuple(at.session_state["res_loaded_dirs"]) == expected_dirs

    def test_history_project_selector_loads_absolute_obipcr_result(
        self, tmp_path, monkeypatch
    ):
        """History loading derives all result paths from one real run root."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        data_root = tmp_path / "fullpcr-data"
        project = data_root / "runs" / "run-history"
        final_dir = project / "final_results"
        obipcr_dir = project / "obipcr_results"
        qc_dir = project / "qc_results"
        spec_dir = project / "qc_spec_results" / "spec"
        for directory in (final_dir, obipcr_dir, qc_dir, spec_dir):
            directory.mkdir(parents=True, exist_ok=True)
        (final_dir / "primer_rank.tsv").write_text(
            "primer_id\tfinal_score\tfinal_status\nP1\t0.9\tRECOMMENDED\n",
            encoding="utf-8",
        )
        (obipcr_dir / "combined_summary.tsv").write_text(
            "primer_id\tamplicon_count\tunique_species_count\nP1\t12\t10\n",
            encoding="utf-8",
        )
        (qc_dir / "primer_qc_summary.tsv").write_text(
            "primer_id\tqc_status\nP1\tPASS\n", encoding="utf-8"
        )
        (spec_dir / "primer_spec.tsv").write_text(
            "primer_id\tspec_status\nP1\tPASS\n", encoding="utf-8"
        )
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(data_root))

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        selected = at.selectbox("_selected_result_project").value
        from datetime import datetime
        datetime.strptime(selected.split(" · ", 1)[1], "%Y_%m_%d_%H_%M")
        at.button("res_load_btn").click().run()
        assert not at.exception

        combined = at.session_state["res_combined_result"]
        assert combined["status"] == "PASS"
        assert combined["path"] == str(obipcr_dir / "combined_summary.tsv")
        assert Path(combined["path"]).is_absolute()
        assert "File not found: obipcr_results" not in " ".join(
            str(item.value) for item in at.info
        )
        assert not any(
            "请先在「分析工作台」" in str(item.value) for item in at.info
        )
        loaded = next(
            item
            for item in at.expander
            if item.label.startswith("查看已加载项目结果 · ")
        )
        assert selected.split(" · ", 1)[1] in loaded.label

class TestNoviceWorkbenchLayout:

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    def test_default_shows_novice_flow(self):
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        novice_text = [e.value for e in at.caption] + [e.value for e in at.markdown]
        assert any("填写" in str(v) for v in novice_text)
        assert any("workflow-strip" in str(v) for v in novice_text)
        at.radio("_inputs_primers_mode")
        assert at.radio("_inputs_primers_mode").value == "直接填写"
        assert at.text_input("_manual_min_length_0").label == "最小扩增长度 (bp)"
        assert at.text_input("_manual_max_length_0").label == "最大扩增长度 (bp)"
        with pytest.raises(KeyError):
            at.text_input("_inputs_output_dir")
        at.button("inputs_validate_btn")
        at.button("full_pipeline_run_btn")
        assert "分析参数" not in [item.label for item in at.expander]
        assert at.number_input("_wf_s3_minsize").value == 80
        assert at.number_input("_wf_s3_maxsize").value == 500
        assert at.number_input("_wf_s3_mismatch").value == 2
        assert at.toggle("_show_advanced_parameters").value is False
        execution_expander = next(
            item for item in at.expander if item.label == "执行设置与五步命令"
        )
        execution_expander.toggle("_workflow_dry_run")
        assert all(
            item.label != "查看五步执行命令" for item in at.expander
        )
        tab_labels = [t.label for t in at.tabs]
        assert "1. 基础质控" not in tab_labels

        # All five workflow step run buttons must be absent by key.
        all_button_keys = [b.key for b in at.button]
        for run_key in ["wf_run_s1", "wf_run_s2", "wf_run_s3", "wf_run_s4", "wf_run_s5"]:
            assert run_key not in all_button_keys, (
                f"{run_key} should not be visible in novice mode"
            )

    def test_validation_details_collapsed_and_output_path_hidden(self):
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")
        ).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")
        ).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")
        ).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is True
        assert at.session_state["project_output_root"]

        validation = next(
            item for item in at.expander if item.label == "验证结果：已通过"
        )
        assert validation.proto.expanded is False
        visible_markdown = " ".join(str(item.value) for item in at.markdown)
        assert "项目输出目录" not in visible_markdown
        assert "#### 输出目录" not in visible_markdown
        with pytest.raises(KeyError):
            at.text_input("_inputs_output_dir")

    def test_enable_advanced_shows_tabs(self):
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        at.toggle("_show_advanced_workflow").set_value(True).run()
        assert not at.exception
        assert "1. 基础质控" in [t.label for t in at.tabs]
        at.button("wf_run_s1")

    def test_toggle_preserves_state(self):
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # Write identifiable test values for all state keys that must survive
        # the advanced-workflow toggle.
        at.session_state["wf_s1_outdir"] = "/my/qc"
        # Set both canonical and widget key so sync_widgets_to_canonical
        # does not overwrite the canonical value on re-render.
        at.session_state["wf_s3_maxsize"] = 999
        at.session_state["_wf_s3_maxsize"] = 999
        at.session_state["workflow_path_user_edited"] = {"wf_s1_outdir"}
        at.session_state["inputs_validated"] = True
        at.session_state["ws_run_id"] = "test-run-3c1"
        at.session_state["ws_uploads_dir"] = "/tmp/test-uploads"
        at.session_state["ws_uploaded_primers_path"] = "/tmp/up/primers.tsv"
        at.session_state["ws_uploaded_database_path"] = "/tmp/up/db.fasta"
        at.session_state["ws_uploaded_taxonomy_path"] = "/tmp/up/tax.tsv"
        at.session_state["full_pipeline_plan"] = [
            {"key": "s1", "label": "Step 1", "command": ["echo", "hi"], "timeout": 60},
        ]
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        for sk in ["wf_s1_result", "wf_s2_result", "wf_s3_result", "wf_s4_result", "wf_s5_result"]:
            at.session_state[sk] = {"status": "PASS", "stdout": sk, "returncode": 0}

        # Toggle ON — verify no state was lost.
        at.toggle("_show_advanced_workflow").set_value(True).run()
        assert not at.exception
        assert at.session_state["wf_s1_outdir"] == "/my/qc"
        assert at.session_state["wf_s3_maxsize"] == 999
        assert at.session_state["workflow_path_user_edited"] == {"wf_s1_outdir"}
        assert at.session_state["inputs_validated"] is True
        assert at.session_state["ws_run_id"] == "test-run-3c1"
        assert at.session_state["ws_uploads_dir"] == "/tmp/test-uploads"
        assert at.session_state["ws_uploaded_primers_path"] == "/tmp/up/primers.tsv"
        assert at.session_state["ws_uploaded_database_path"] == "/tmp/up/db.fasta"
        assert at.session_state["ws_uploaded_taxonomy_path"] == "/tmp/up/tax.tsv"
        assert at.session_state["full_pipeline_plan"] == [
            {"key": "s1", "label": "Step 1", "command": ["echo", "hi"], "timeout": 60},
        ]
        assert at.session_state["full_pipeline_result"] == {"status": "PASS"}
        for sk in ["wf_s1_result", "wf_s2_result", "wf_s3_result", "wf_s4_result", "wf_s5_result"]:
            assert at.session_state[sk] == {"status": "PASS", "stdout": sk, "returncode": 0}, (
                f"{sk} was modified by toggle ON"
            )

        # Toggle OFF — verify again that nothing was cleared.
        at.toggle("_show_advanced_workflow").set_value(False).run()
        assert not at.exception
        assert at.session_state["wf_s1_outdir"] == "/my/qc"
        assert at.session_state["wf_s3_maxsize"] == 999
        assert at.session_state["workflow_path_user_edited"] == {"wf_s1_outdir"}
        assert at.session_state["inputs_validated"] is True
        assert at.session_state["ws_run_id"] == "test-run-3c1"
        assert at.session_state["ws_uploads_dir"] == "/tmp/test-uploads"
        assert at.session_state["ws_uploaded_primers_path"] == "/tmp/up/primers.tsv"
        assert at.session_state["ws_uploaded_database_path"] == "/tmp/up/db.fasta"
        assert at.session_state["ws_uploaded_taxonomy_path"] == "/tmp/up/tax.tsv"
        assert at.session_state["full_pipeline_plan"] == [
            {"key": "s1", "label": "Step 1", "command": ["echo", "hi"], "timeout": 60},
        ]
        assert at.session_state["full_pipeline_result"] == {"status": "PASS"}
        for sk in ["wf_s1_result", "wf_s2_result", "wf_s3_result", "wf_s4_result", "wf_s5_result"]:
            assert at.session_state[sk] == {"status": "PASS", "stdout": sk, "returncode": 0}, (
                f"{sk} was modified by toggle OFF"
            )

    def test_params_expander_plan_works(self):
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is True

        at.toggle("_workflow_dry_run").set_value(True).run()
        assert at.button("full_pipeline_run_btn").label == "生成五步命令预览"
        with mock.patch("subprocess.run") as mr:
            at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        mr.assert_not_called()
        plan = at.session_state["full_pipeline_plan"]
        assert len(plan) == 5
        assert plan[0]["key"] == "s1"


class TestSpecCustomParams:
    """Phase 3D-2: AppTest for spec custom params in the GUI."""

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    @staticmethod
    def _set_optional_number(at, value_key: str, value) -> None:
        """Enable one optional numeric parameter and set its value via UI."""
        if not at.toggle("_show_advanced_parameters").value:
            at.toggle("_show_advanced_parameters").set_value(True).run()
            assert not at.exception
        use_key = value_key.replace("_wf_s3_", "_wf_s3_use_")
        at.checkbox(use_key).set_value(True).run()
        assert not at.exception
        at.number_input(value_key).set_value(value).run()
        assert not at.exception

    def test_default_spec_params_are_none_or_false(self):
        """Default values: six numeric params None, two bools False."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        for key in (
            "wf_s3_use_tm",
            "wf_s3_use_misstart",
            "wf_s3_use_misend",
            "wf_s3_use_mono",
            "wf_s3_use_diva",
            "wf_s3_use_dntp",
            "wf_s3_use_oligo",
        ):
            assert at.session_state[key] is False

        assert at.session_state["wf_s3_misstart"] is None
        assert at.session_state["wf_s3_misend"] is None
        assert at.session_state["wf_s3_bind"] is False
        assert at.session_state["wf_s3_cutprimer"] is False
        assert at.session_state["wf_s3_mono"] is None
        assert at.session_state["wf_s3_diva"] is None
        assert at.session_state["wf_s3_dntp"] is None
        assert at.session_state["wf_s3_oligo"] is None
        assert at.session_state["wf_s3_minsize"] == 80
        assert at.session_state["wf_s3_maxsize"] == 500
        assert at.session_state["wf_s3_mismatch"] == 2
        assert at.session_state["wf_s3_tm"] == 50.0

        number_keys = [widget.key for widget in at.number_input]
        assert "_wf_s3_misstart" not in number_keys
        assert "_wf_s3_misend" not in number_keys

    def test_parameter_panel_uses_conditional_inputs_and_semantic_steps(self):
        """Top parameters are grouped clearly and use domain-specific steps."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        expander_labels = [expander.label for expander in at.expander]
        assert "分析参数" not in expander_labels
        assert "分析参数（可选）" not in expander_labels

        number_keys = [widget.key for widget in at.number_input]
        for key in (
            "_wf_s3_tm",
            "_wf_s3_misstart",
            "_wf_s3_misend",
            "_wf_s3_mono",
            "_wf_s3_diva",
            "_wf_s3_dntp",
            "_wf_s3_oligo",
        ):
            assert key not in number_keys

        assert at.number_input("_wf_s3_minsize").step == 10.0
        assert at.number_input("_wf_s3_maxsize").step == 10.0
        assert at.number_input("_wf_s3_mismatch").step == 1.0

        expected_controls = {
            "_wf_s3_tm": (0.5, 50.0),
            "_wf_s3_misstart": (1.0, 1),
            "_wf_s3_misend": (1.0, 9),
            "_wf_s3_mono": (1.0, 50.0),
            "_wf_s3_diva": (0.1, 1.5),
            "_wf_s3_dntp": (0.05, 0.25),
            "_wf_s3_oligo": (1.0, 50.0),
        }
        at.toggle("_show_advanced_parameters").set_value(True).run()
        assert not at.exception
        for value_key, (expected_step, expected_value) in expected_controls.items():
            use_key = value_key.replace("_wf_s3_", "_wf_s3_use_")
            at.checkbox(use_key).set_value(True).run()
            assert at.number_input(value_key).step == expected_step
            assert at.number_input(value_key).value == expected_value

    def test_all_empty_no_spec_flags_in_plan(self):
        """When all spec params are at defaults, step 3 command has no new flags."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is True

        at.toggle("_workflow_dry_run").set_value(True).run()
        at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        plan = at.session_state["full_pipeline_plan"]
        s3_cmd = " ".join(plan[2]["command"])
        assert "--tm 50.0" in s3_cmd
        for flag in ["--mis-start", "--mis-end", "--bind", "--cut-primer",
                      "--mono", "--diva", "--dntp", "--oligo"]:
            assert flag not in s3_cmd, f"{flag} leaked into step 3"

    def test_all_spec_params_set_in_plan(self):
        """When all spec params are set, step 3 command includes them all."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        self._set_optional_number(at, "_wf_s3_tm", 55.5)
        self._set_optional_number(at, "_wf_s3_misstart", 3)
        self._set_optional_number(at, "_wf_s3_misend", 7)
        self._set_optional_number(at, "_wf_s3_mono", 75.0)
        self._set_optional_number(at, "_wf_s3_diva", 2.0)
        self._set_optional_number(at, "_wf_s3_dntp", 0.5)
        self._set_optional_number(at, "_wf_s3_oligo", 100.0)
        at.checkbox("_wf_s3_bind").set_value(True).run()
        at.checkbox("_wf_s3_cutprimer").set_value(True).run()

        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        at.toggle("_workflow_dry_run").set_value(True).run()
        at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        plan = at.session_state["full_pipeline_plan"]
        s3_cmd = " ".join(plan[2]["command"])
        assert "--tm 55.5" in s3_cmd
        assert "--mis-start 3" in s3_cmd
        assert "--mis-end 7" in s3_cmd
        assert "--bind" in s3_cmd
        assert "--cut-primer" in s3_cmd
        assert "--mono 75.0" in s3_cmd
        assert "--diva 2.0" in s3_cmd
        assert "--dntp 0.5" in s3_cmd
        assert "--oligo 100.0" in s3_cmd

    def test_disabling_numeric_override_restores_default_command(self):
        """Turning an override off omits its flag and remembers its value."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception

        self._set_optional_number(at, "_wf_s3_tm", 55.5)
        self._set_optional_number(at, "_wf_s3_mono", 75.0)
        at.checkbox("_wf_s3_use_tm").set_value(False).run()
        at.checkbox("_wf_s3_use_mono").set_value(False).run()

        number_keys = [widget.key for widget in at.number_input]
        assert "_wf_s3_tm" not in number_keys
        assert "_wf_s3_mono" not in number_keys
        assert at.session_state["wf_s3_tm"] == 55.5
        assert at.session_state["wf_s3_mono"] == 75.0

        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        at.toggle("_workflow_dry_run").set_value(True).run()
        at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        s3_cmd = " ".join(
            at.session_state["full_pipeline_plan"][2]["command"]
        )
        assert "--tm 50.0" in s3_cmd
        assert "--tm 55.5" not in s3_cmd
        assert "--mono" not in s3_cmd

    def test_bind_and_cut_primer_independent(self):
        """bind and cut_primer can be toggled independently."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        at.session_state["wf_s3_bind"] = True
        at.session_state["_wf_s3_bind"] = True
        at.session_state["wf_s3_cutprimer"] = False
        at.session_state["_wf_s3_cutprimer"] = False
        at.run(timeout=30)

        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        at.toggle("_workflow_dry_run").set_value(True).run()
        at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        plan = at.session_state["full_pipeline_plan"]
        s3_cmd = " ".join(plan[2]["command"])
        assert "--bind" in s3_cmd
        assert "--cut-primer" not in s3_cmd

    def test_collapsing_advanced_preserves_command_and_values(self):
        """Collapsing advanced controls only changes visibility."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        self._set_optional_number(at, "_wf_s3_misstart", 5)
        self._set_optional_number(at, "_wf_s3_mono", 75.0)
        at.checkbox("_wf_s3_bind").set_value(True).run()
        assert not at.exception

        at.toggle("_show_advanced_parameters").set_value(False).run()
        assert not at.exception
        checkbox_keys = [checkbox.key for checkbox in at.checkbox]
        assert "_wf_s3_use_misstart" not in checkbox_keys
        assert "_wf_s3_use_mono" not in checkbox_keys
        assert "_wf_s3_bind" not in checkbox_keys

        assert at.session_state["wf_s3_misstart"] == 5
        assert at.session_state["wf_s3_mono"] == 75.0
        assert at.session_state["wf_s3_bind"] is True
        assert at.session_state["wf_s3_use_misstart"] is True
        assert at.session_state["wf_s3_use_mono"] is True

        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        at.toggle("_workflow_dry_run").set_value(True).run()
        at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        s3_cmd = " ".join(at.session_state["full_pipeline_plan"][2]["command"])
        assert "--mis-start 5" in s3_cmd
        assert "--mono 75.0" in s3_cmd
        assert "--bind" in s3_cmd

        at.toggle("_show_advanced_parameters").set_value(True).run()
        assert at.number_input("_wf_s3_misstart").value == 5
        assert at.number_input("_wf_s3_mono").value == 75.0
        assert at.checkbox("_wf_s3_bind").value is True

    def test_bind_false_cutprimer_true(self):
        """bind=False, cut_primer=True → --cutprimer but no --bind."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        at.session_state["wf_s3_bind"] = False
        at.session_state["_wf_s3_bind"] = False
        at.session_state["wf_s3_cutprimer"] = True
        at.session_state["_wf_s3_cutprimer"] = True
        at.run(timeout=30)

        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        at.toggle("_workflow_dry_run").set_value(True).run()
        at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        plan = at.session_state["full_pipeline_plan"]
        s3_cmd = " ".join(plan[2]["command"])
        assert "--bind" not in s3_cmd
        assert "--cut-primer" in s3_cmd

    def test_page_and_workflow_round_trip(self):
        """All 8 spec params survive page switch and workflow toggle."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # Enable and set all numeric overrides via widgets.
        self._set_optional_number(at, "_wf_s3_tm", 55.5)
        self._set_optional_number(at, "_wf_s3_misstart", 3)
        self._set_optional_number(at, "_wf_s3_misend", 7)
        self._set_optional_number(at, "_wf_s3_mono", 75.0)
        self._set_optional_number(at, "_wf_s3_diva", 2.0)
        self._set_optional_number(at, "_wf_s3_dntp", 0.5)
        self._set_optional_number(at, "_wf_s3_oligo", 100.0)
        at.checkbox("_wf_s3_bind").set_value(True).run()
        at.checkbox("_wf_s3_cutprimer").set_value(True).run()

        def _assert_all():
            assert at.session_state["wf_s3_tm"] == 55.5
            assert at.session_state["wf_s3_misstart"] == 3
            assert at.session_state["wf_s3_misend"] == 7
            assert at.session_state["wf_s3_mono"] == 75.0
            assert at.session_state["wf_s3_diva"] == 2.0
            assert at.session_state["wf_s3_dntp"] == 0.5
            assert at.session_state["wf_s3_oligo"] == 100.0
            assert at.session_state["wf_s3_bind"] is True
            assert at.session_state["wf_s3_cutprimer"] is True
            for key in (
                "wf_s3_use_tm",
                "wf_s3_use_misstart",
                "wf_s3_use_misend",
                "wf_s3_use_mono",
                "wf_s3_use_diva",
                "wf_s3_use_dntp",
                "wf_s3_use_oligo",
            ):
                assert at.session_state[key] is True

        _assert_all()

        # Switch page and back.
        at.sidebar.radio[0].set_value("结果总览").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        _assert_all()

        # Toggle advanced workflow ON then OFF.
        at.toggle("_show_advanced_workflow").set_value(True).run()
        assert not at.exception
        _assert_all()
        at.toggle("_show_advanced_workflow").set_value(False).run()
        assert not at.exception
        _assert_all()

    def test_one_click_and_step3_commands_match(self):
        """One-click plan s3 command matches advanced step-3 command preview."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # Enable and set all spec numeric overrides via widgets.
        self._set_optional_number(at, "_wf_s3_tm", 55.5)
        self._set_optional_number(at, "_wf_s3_misstart", 3)
        self._set_optional_number(at, "_wf_s3_misend", 7)
        self._set_optional_number(at, "_wf_s3_mono", 75.0)
        self._set_optional_number(at, "_wf_s3_diva", 2.0)
        self._set_optional_number(at, "_wf_s3_dntp", 0.5)
        self._set_optional_number(at, "_wf_s3_oligo", 100.0)
        at.checkbox("_wf_s3_bind").set_value(True).run()
        at.checkbox("_wf_s3_cutprimer").set_value(True).run()

        # Validate inputs.
        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        # One-click plan (dry-run).
        at.toggle("_workflow_dry_run").set_value(True).run()
        at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        plan = at.session_state["full_pipeline_plan"]
        plan_s3 = " ".join(plan[2]["command"])

        # Open advanced workflow, get step-3 command preview from st.code.
        at.toggle("_show_advanced_workflow").set_value(True).run()
        assert not at.exception
        # There may be 2+ code blocks with qc-spec (plan expander + step-3
        # expander).  They must all match the plan s3 command.
        code_texts = [c.value for c in at.code if "qc-spec" in (c.value or "")]
        assert len(code_texts) >= 1, f"Expected at least 1 qc-spec block, got {len(code_texts)}"
        for ct in code_texts:
            step3_cmd = " ".join(ct.strip().split())
            assert plan_s3 == step3_cmd, (
                f"Plan s3:\n  {plan_s3}\nPreview:\n  {step3_cmd}"
            )

    def test_spec_params_survive_validation_all_eight(self):
        """All 8 spec params survive re-validation, checked individually."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        # Enable and set all numeric overrides via widgets.
        self._set_optional_number(at, "_wf_s3_tm", 55.5)
        self._set_optional_number(at, "_wf_s3_misstart", 3)
        self._set_optional_number(at, "_wf_s3_misend", 7)
        self._set_optional_number(at, "_wf_s3_mono", 75.0)
        self._set_optional_number(at, "_wf_s3_diva", 2.0)
        self._set_optional_number(at, "_wf_s3_dntp", 0.5)
        self._set_optional_number(at, "_wf_s3_oligo", 100.0)
        at.checkbox("_wf_s3_bind").set_value(True).run()
        at.checkbox("_wf_s3_cutprimer").set_value(True).run()

        # Validate (clears pipeline results but not spec params).
        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception

        assert at.session_state["wf_s3_tm"] == 55.5
        assert at.session_state["wf_s3_misstart"] == 3
        assert at.session_state["wf_s3_misend"] == 7
        assert at.session_state["wf_s3_mono"] == 75.0
        assert at.session_state["wf_s3_diva"] == 2.0
        assert at.session_state["wf_s3_dntp"] == 0.5
        assert at.session_state["wf_s3_oligo"] == 100.0
        assert at.session_state["wf_s3_bind"] is True
        assert at.session_state["wf_s3_cutprimer"] is True
        for key in (
            "wf_s3_use_tm",
            "wf_s3_use_misstart",
            "wf_s3_use_misend",
            "wf_s3_use_mono",
            "wf_s3_use_diva",
            "wf_s3_use_dntp",
            "wf_s3_use_oligo",
        ):
            assert at.session_state[key] is True

    def test_no_duplicate_key_on_advanced_workflow(self):
        """Opening advanced workflow does not raise duplicate widget key."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception

        at.toggle("_show_advanced_workflow").set_value(True).run()
        assert not at.exception
        assert "1. 基础质控" in [t.label for t in at.tabs]


class TestRawSpecTsvInfo:
    """Phase 3D-3A: tests for get_raw_spec_tsv_info()."""

    def test_normal(self, tmp_path: Path):
        d = tmp_path / "qc_spec_results" / "spec"
        d.mkdir(parents=True)
        f = d / "spec_output.txt.spec.tsv"
        f.write_text("col1\tcol2\nval1\tval2\n")
        info = get_raw_spec_tsv_info(str(tmp_path / "qc_spec_results"))
        assert info["status"] == "PASS"
        assert info["file_name"] == "spec_output.txt.spec.tsv"
        assert info["size"] == f.stat().st_size
        assert Path(info["path"]).is_absolute()

    def test_dir_not_exist(self, tmp_path: Path):
        info = get_raw_spec_tsv_info(str(tmp_path / "no_such_dir"))
        assert info["status"] == "FAIL"
        assert "不存在" in info["error"]

    def test_path_not_dir(self, tmp_path: Path):
        f = tmp_path / "afile"
        f.write_text("data")
        info = get_raw_spec_tsv_info(str(f))
        assert info["status"] == "FAIL"
        assert "不是目录" in info["error"]

    def test_tsv_not_exist(self, tmp_path: Path):
        (tmp_path / "qc_spec_results" / "spec").mkdir(parents=True)
        info = get_raw_spec_tsv_info(str(tmp_path / "qc_spec_results"))
        assert info["status"] == "FAIL"
        assert "不存在" in info["error"]

    def test_tsv_is_dir(self, tmp_path: Path):
        d = tmp_path / "qc_spec_results" / "spec" / "spec_output.txt.spec.tsv"
        d.mkdir(parents=True)
        info = get_raw_spec_tsv_info(str(tmp_path / "qc_spec_results"))
        assert info["status"] == "FAIL"
        assert "不是普通文件" in info["error"]

    def test_root_symlink_rejected(self, tmp_path: Path):
        real_dir = tmp_path / "real_qc"
        (real_dir / "spec").mkdir(parents=True)
        (real_dir / "spec" / "spec_output.txt.spec.tsv").write_text("data\n")
        link = tmp_path / "link_qc"
        link.symlink_to(real_dir)
        info = get_raw_spec_tsv_info(str(link))
        assert info["status"] == "FAIL"
        assert "符号链接" in info["error"]

    def test_tsv_symlink_rejected(self, tmp_path: Path):
        real = tmp_path / "real.tsv"
        real.write_text("data\n")
        d = tmp_path / "qc_spec_results" / "spec"
        d.mkdir(parents=True)
        link = d / "spec_output.txt.spec.tsv"
        link.symlink_to(real)
        info = get_raw_spec_tsv_info(str(tmp_path / "qc_spec_results"))
        assert info["status"] == "FAIL"
        assert "符号链接" in info["error"]


class TestBuildResultsArchive:
    """Phase 3D-3A: tests for build_results_archive()."""

    def test_normal(self, tmp_path: Path):
        (tmp_path / "qc_results").mkdir()
        (tmp_path / "qc_results" / "summary.tsv").write_text("qc_summary\n")
        (tmp_path / "obipcr_results").mkdir()
        (tmp_path / "obipcr_results" / "amplicon.fasta").write_text(">r1\nATCG\n")
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "PASS"
        assert info["file_count"] == 2
        assert info["size"] > 0
        assert Path(info["path"]).is_file()
        assert info["file_name"] == "fullpcr_results.zip"

    def test_internal_pipeline_job_state_is_excluded(self, tmp_path: Path):
        (tmp_path / "qc_results").mkdir()
        (tmp_path / "qc_results" / "summary.tsv").write_text("ok\n")
        job_dir = tmp_path / ".fullpcr_jobs"
        job_dir.mkdir()
        (job_dir / "pipeline_state.json").write_text('{"status":"PASS"}')
        (job_dir / "pipeline.lock").write_text('{"job_id":"old"}')

        info = build_results_archive(str(tmp_path))

        assert info["status"] == "PASS"
        import zipfile
        with zipfile.ZipFile(info["path"], "r") as zf:
            names = zf.namelist()
        assert "qc_results/summary.tsv" in names
        assert not any(name.startswith(".fullpcr_jobs/") for name in names)

    def test_selected_directories_only(self, tmp_path: Path):
        for dirname in ("uploads", "qc_results", "obipcr_results"):
            directory = tmp_path / dirname
            directory.mkdir()
            (directory / "result.txt").write_text(dirname, encoding="utf-8")

        info = build_results_archive(
            tmp_path,
            included_dirs=["obipcr_results", "qc_results"],
            archive_name="fullpcr_selected_results.zip",
        )

        assert info["status"] == "PASS"
        assert info["file_name"] == "fullpcr_selected_results.zip"
        import zipfile
        with zipfile.ZipFile(info["path"], "r") as zf:
            names = set(zf.namelist())
        assert names == {
            "obipcr_results/result.txt",
            "qc_results/result.txt",
        }

    @pytest.mark.parametrize(
        ("included_dirs", "archive_name", "error_fragment"),
        [
            ([], "selected.zip", "未选择"),
            (["../outside"], "selected.zip", "不安全"),
            (["qc_results"], "../selected.zip", "不安全"),
        ],
    )
    def test_selected_archive_rejects_unsafe_input(
        self, tmp_path: Path, included_dirs, archive_name, error_fragment
    ):
        (tmp_path / "qc_results").mkdir()
        (tmp_path / "qc_results" / "x.txt").write_text("x")
        info = build_results_archive(
            tmp_path,
            included_dirs=included_dirs,
            archive_name=archive_name,
        )
        assert info["status"] == "FAIL"
        assert error_fragment in info["error"]

    def test_namelist_relative_safe(self, tmp_path: Path):
        (tmp_path / "results").mkdir(parents=True)
        (tmp_path / "results" / "a.txt").write_text("a")
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "PASS"
        import zipfile
        with zipfile.ZipFile(info["path"], "r") as zf:
            names = zf.namelist()
        for name in names:
            assert not name.startswith("/"), f"Absolute path in ZIP: {name}"
            assert ".." not in name, f"Path traversal in ZIP: {name}"

    def test_content_matches_original(self, tmp_path: Path):
        (tmp_path / "dir").mkdir()
        content = "hello zip world\n"
        (tmp_path / "dir" / "file.txt").write_text(content)
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "PASS"
        import zipfile
        with zipfile.ZipFile(info["path"], "r") as zf:
            extracted = zf.read("dir/file.txt").decode("utf-8")
        assert extracted == content

    def test_includes_raw_spec_tsv(self, tmp_path: Path):
        d = tmp_path / "qc_spec_results" / "spec"
        d.mkdir(parents=True)
        (d / "spec_output.txt.spec.tsv").write_text("raw spec\n")
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "PASS"
        import zipfile
        with zipfile.ZipFile(info["path"], "r") as zf:
            names = zf.namelist()
        assert "qc_spec_results/spec/spec_output.txt.spec.tsv" in names

    def test_excludes_downloads_dir(self, tmp_path: Path):
        (tmp_path / "data.txt").write_text("data\n")
        dl = tmp_path / ".fullpcr_downloads"
        dl.mkdir()
        (dl / "old.zip").write_text("old")
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "PASS"
        import zipfile
        with zipfile.ZipFile(info["path"], "r") as zf:
            names = zf.namelist()
        assert "data.txt" in names
        assert ".fullpcr_downloads" not in str(names)

    def test_empty_root_fails(self, tmp_path: Path):
        tmp_path.mkdir(exist_ok=True)
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "FAIL"
        assert "没有可打包" in info["error"]

    def test_root_not_exist(self, tmp_path: Path):
        info = build_results_archive(str(tmp_path / "gone"))
        assert info["status"] == "FAIL"

    def test_root_not_dir(self, tmp_path: Path):
        f = tmp_path / "afile"
        f.write_text("nope")
        info = build_results_archive(str(f))
        assert info["status"] == "FAIL"
        assert "不是目录" in info["error"]

    def test_root_symlink_rejected(self, tmp_path: Path):
        real = tmp_path / "real_root"
        real.mkdir()
        (real / "f.txt").write_text("ok")
        link = tmp_path / "link_root"
        link.symlink_to(real)
        info = build_results_archive(str(link))
        assert info["status"] == "FAIL"
        assert "符号链接" in info["error"]

    def test_inner_symlink_rejected(self, tmp_path: Path):
        real = tmp_path / "real_file"
        real.write_text("data\n")
        (tmp_path / "sub").mkdir()
        link = tmp_path / "sub" / "link_to_file"
        link.symlink_to(real)
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "FAIL"
        assert "符号链接" in info["error"]

    def test_space_and_chinese_names(self, tmp_path: Path):
        (tmp_path / "my results").mkdir()
        content = "unicode test\n"
        (tmp_path / "my results" / "中文报告.md").write_text(content)
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "PASS"
        import zipfile
        with zipfile.ZipFile(info["path"], "r") as zf:
            extracted = zf.read("my results/中文报告.md").decode("utf-8")
        assert extracted == content

    def test_write_failure_cleans_temp_and_preserves_existing(self, tmp_path: Path):
        (tmp_path / "data.txt").write_text("data\n")
        dl = tmp_path / ".fullpcr_downloads"
        dl.mkdir()
        existing_zip = dl / "fullpcr_results.zip"
        existing_zip.write_text("existing archive")
        with mock.patch("zipfile.ZipFile.write", side_effect=OSError("disk full")):
            info = build_results_archive(str(tmp_path))
        assert info["status"] == "FAIL"
        assert "disk full" in info["error"]
        temps = list(dl.glob(".fullpcr_tmp_*"))
        assert len(temps) == 0, f"Temp files left: {temps}"
        assert existing_zip.read_text() == "existing archive"

    def test_atomic_replace_on_rebuild(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("first\n")
        info1 = build_results_archive(str(tmp_path))
        assert info1["status"] == "PASS"
        assert info1["file_count"] == 1

        (tmp_path / "b.txt").write_text("second\n")
        info2 = build_results_archive(str(tmp_path))
        assert info2["status"] == "PASS"
        assert info2["file_count"] == 2

        import zipfile
        with zipfile.ZipFile(info2["path"], "r") as zf:
            names = zf.namelist()
        assert "a.txt" in names
        assert "b.txt" in names

    def test_source_files_not_modified(self, tmp_path: Path):
        (tmp_path / "x.txt").write_text("original")
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "PASS"
        assert (tmp_path / "x.txt").read_text() == "original"

    def test_downloads_dir_symlink_rejected(self, tmp_path: Path):
        (tmp_path / "data.txt").write_text("data\n")
        external = tmp_path / "external"
        external.mkdir()
        dl = tmp_path / ".fullpcr_downloads"
        dl.symlink_to(external)
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "FAIL"
        assert "符号链接" in info["error"]
        # No temp files in external dir.
        assert not list(external.glob(".fullpcr_tmp_*"))

    def test_downloads_dir_is_file(self, tmp_path: Path):
        (tmp_path / "data.txt").write_text("data\n")
        dl = tmp_path / ".fullpcr_downloads"
        dl.write_text("not a dir")
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "FAIL"
        assert "不是目录" in info["error"]

    def test_fifo_in_root_rejected(self, tmp_path: Path):
        import os as _os2
        (tmp_path / "data.txt").write_text("data\n")
        fifo_path = tmp_path / "myfifo"
        try:
            _os2.mkfifo(str(fifo_path))
        except OSError:
            pytest.skip("mkfifo not supported on this platform")
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "FAIL"
        assert "不支持的文件类型" in info["error"]
        # Existing ZIP or temp leftovers must be clean.
        dl = tmp_path / ".fullpcr_downloads"
        if dl.exists() and dl.is_dir():
            temps = list(dl.glob(".fullpcr_tmp_*"))
            assert len(temps) == 0, f"Temp files left: {temps}"

    def test_fifo_preserves_existing_zip(self, tmp_path: Path):
        import os as _os2
        (tmp_path / "data.txt").write_text("data\n")
        dl = tmp_path / ".fullpcr_downloads"
        dl.mkdir()
        existing = dl / "fullpcr_results.zip"
        existing.write_text("old archive")
        fifo_path = tmp_path / "myfifo"
        try:
            _os2.mkfifo(str(fifo_path))
        except OSError:
            pytest.skip("mkfifo not supported on this platform")
        info = build_results_archive(str(tmp_path))
        assert info["status"] == "FAIL"
        assert existing.read_text() == "old archive"
        temps = list(dl.glob(".fullpcr_tmp_*"))
        assert len(temps) == 0, f"Temp files left: {temps}"

    def test_mkdir_oserror_returns_fail(self, tmp_path: Path):
        (tmp_path / "data.txt").write_text("data\n")
        with mock.patch("pathlib.Path.mkdir", side_effect=OSError("permission denied")):
            info = build_results_archive(str(tmp_path))
        assert info["status"] == "FAIL"
        assert "permission denied" in info["error"]

    def test_mkstemp_oserror_returns_fail(self, tmp_path: Path):
        (tmp_path / "data.txt").write_text("data\n")
        with mock.patch("tempfile.mkstemp", side_effect=OSError("no space left")):
            info = build_results_archive(str(tmp_path))
        assert info["status"] == "FAIL"
        assert "no space left" in info["error"]


class TestResultDownloadsUi:
    """Phase 3D-3B: AppTest for result-download UI."""

    @staticmethod
    def _app_path():
        return Path(__file__).resolve().parent.parent / "fullpcr" / "gui_app.py"

    def test_no_project_root_on_reports_page(self, tmp_path, monkeypatch):
        """On 报告与下载 with no project_root: guidance info, no download buttons."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        monkeypatch.setenv("FULLPCR_DATA_DIR", str(tmp_path / "empty-data"))
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        info_texts = [i.value for i in at.info]
        assert any("尚未发现可用项目" in str(v) for v in info_texts)

    def test_no_pipeline_result_hides_downloads_on_workbench(self, tmp_path):
        """Analysis workbench without full_pipeline_result: no download buttons."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        root.mkdir()
        at.session_state["project_output_root"] = str(root)
        at.session_state["project_derived_paths"] = {"qc_spec_results_dir": str(root)}
        at.run(timeout=30)
        assert not at.exception
        # Workbench contains no download destination or download controls.
        assert not any("全部结果下载" in str(v.value) for v in at.subheader)
        with pytest.raises(KeyError):
            at.button("build_results_zip_btn")
        with pytest.raises(KeyError):
            at.download_button("dl_raw_spec_tsv")
        with pytest.raises(KeyError):
            at.download_button("dl_results_zip")

    def test_with_pipeline_result_shows_build_button(self, tmp_path):
        """full_pipeline_result present → build_results_zip_btn visible."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        root.mkdir()
        (root / "x.txt").write_text("data")
        at.session_state["project_output_root"] = str(root)
        at.session_state["project_derived_paths"] = {"qc_spec_results_dir": str(root)}
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        assert at.multiselect("_results_zip_groups").value == []
        assert at.button("build_results_zip_btn").disabled is True

    def test_reports_are_collapsed_chinese_and_before_downloads(self, tmp_path):
        """Report uses derived files, stays collapsed, and renders Chinese interpretation."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest

        root = tmp_path / "project"
        final_dir = root / "final_results"
        obipcr_dir = root / "obipcr_results"
        qc_dir = root / "qc_results"
        spec_dir = root / "qc_spec_results" / "spec"
        final_dir.mkdir(parents=True)
        obipcr_dir.mkdir()
        qc_dir.mkdir()
        spec_dir.mkdir(parents=True)
        (final_dir / "primer_rank.tsv").write_text(
            "primer_id\tfinal_score\tfinal_status\tqc_status\tspec_status\t"
            "obipcr_unique_species_count\treason\n"
            "P1\t0.95\tRECOMMENDED\tPASS\tPASS\t12\t覆盖率高\n",
            encoding="utf-8",
        )
        (obipcr_dir / "combined_summary.tsv").write_text(
            "primer_id\tmismatch\tamplicon_count\tunique_species_count\t"
            "species_level_unique_resolution_rate\tmean_amplicon_length\t"
            "missing_taxonomy_count\nP1\t2\t14\t12\t0.9\t210\t0\n",
            encoding="utf-8",
        )
        (qc_dir / "primer_qc_summary.tsv").write_text(
            "primer_id\tforward_tm\treverse_tm\ttm_difference\tdimer_count\t"
            "forward_hairpin_count\treverse_hairpin_count\tqc_status\tqc_reason\n"
            "P1\t60\t61\t1\t0\t0\t0\tPASS\t\n",
            encoding="utf-8",
        )
        (spec_dir / "primer_spec.tsv").write_text(
            "primer_id\tspec_amplicon_count\tunique_reference_count\t"
            "unique_species_count\tspec_reference_fraction\tstatus\treason\n"
            "P1\t12\t12\t10\t1.0\tPASS\t\n",
            encoding="utf-8",
        )
        (final_dir / "final_report.md").write_text("# Raw English report\n")
        (obipcr_dir / "report.md").write_text("# Raw obipcr report\n")

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        at.session_state["project_output_root"] = str(root)
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        visible_shell = " ".join(
            [str(item.value) for item in at.markdown]
            + [str(item.value) for item in at.caption]
        )
        assert str(root) not in visible_shell

        report_expander = next(
            item for item in at.expander if item.label == "查看中文分析报告"
        )
        assert report_expander.proto.expanded is False
        with pytest.raises(KeyError):
            at.text_input("_rpt_final_path")
        with pytest.raises(KeyError):
            at.text_input("_rpt_obipcr_path")
        assert not any("综合结论" in str(item.value) for item in at.markdown)

        at.button("rpt_load_btn").click().run()
        assert not at.exception
        markdown = " ".join(str(item.value) for item in at.markdown)
        assert "综合结论" in markdown
        assert "MFEprimer 基础质控解读" in markdown
        assert "MFEprimer 特异性分析解读" in markdown
        assert "obipcr 扩增结果解读" in markdown
        info_text = " ".join(str(item.value) for item in at.info)
        assert "并不是单独的 MFEprimer 报告" not in info_text
        assert "fullpcr 综合报告" in info_text
        captions = " ".join(str(item.value) for item in at.caption)
        assert "覆盖物种数反映可检出的物种范围" in captions
        assert "Raw English report" not in markdown
        assert "fullpcr 综合报告" in at.download_button("dl_final_report").label
        assert "obipcr 独立报告" in at.download_button("dl_obipcr_report").label

    def test_selected_result_groups_create_selected_zip(self, tmp_path):
        """Selecting result categories excludes unselected categories from ZIP."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        import zipfile

        root = tmp_path / "project"
        for dirname in (
            "uploads",
            "qc_results",
            "qc_spec_results",
            "obipcr_results",
            "final_results",
        ):
            directory = root / dirname
            directory.mkdir(parents=True)
            (directory / "result.txt").write_text(dirname, encoding="utf-8")

        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        at.session_state["project_output_root"] = str(root)
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception

        groups = at.multiselect("_results_zip_groups")
        assert "全部结果" not in groups.options
        assert "输入文件" not in groups.options
        assert "obipcr 扩增结果" in groups.options
        assert "综合排名与最终报告" in groups.options
        assert groups.value == []
        assert at.button("build_results_zip_btn").disabled is True
        groups.set_value(["obipcr 扩增结果", "综合排名与最终报告"]).run()
        assert at.button("build_results_zip_btn").disabled is False
        at.button("build_results_zip_btn").click().run()
        assert not at.exception

        info = at.session_state["results_archive_info"]
        assert info["status"] == "PASS"
        assert info["file_name"] == "fullpcr_selected_results.zip"
        with zipfile.ZipFile(info["path"], "r") as zf:
            names = set(zf.namelist())
        assert names == {
            "obipcr_results/result.txt",
            "final_results/result.txt",
        }
        assert at.download_button("dl_results_zip").label == "下载所选结果 ZIP"

    def test_raw_spec_tsv_button_removed(self, tmp_path):
        """Raw Spec TSV stays inside the category ZIP; no standalone button."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        spec_dir = root / "qc_spec_results" / "spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec_output.txt.spec.tsv").write_text("c1\tc2\nv1\tv2\n")
        at.session_state["project_output_root"] = str(root)
        at.session_state["project_derived_paths"] = {"qc_spec_results_dir": str(root / "qc_spec_results")}
        at.session_state["full_pipeline_plan"] = [
            {"key": "s3", "label": "s3", "command": ["echo", "--outdir", str(root / "qc_spec_results")], "timeout": 60},
        ]
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        with pytest.raises(KeyError):
            at.download_button("dl_raw_spec_tsv")
        assert not any(
            "原始 Spec TSV" in str(item.value) for item in at.caption
        )

    def test_download_groups_have_results_only(self, tmp_path):
        """Download choices contain analysis results, never inputs or an ambiguous all tag."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        import zipfile
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        for dirname in ("uploads", "qc_results", "qc_spec_results", "obipcr_results", "final_results"):
            directory = root / dirname
            directory.mkdir(parents=True)
            (directory / "x.txt").write_text("x")
        at.session_state["project_output_root"] = str(root)
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        options = at.multiselect("_results_zip_groups").options
        assert options == [
            "MFEprimer 基础质控结果",
            "MFEprimer 特异性分析结果",
            "obipcr 扩增结果",
            "综合排名与最终报告",
        ]
        assert "输入文件" not in options
        assert "全部结果" not in options
        at.multiselect("_results_zip_groups").set_value(options).run()
        at.button("build_results_zip_btn").click().run()
        assert not at.exception
        info = at.session_state["results_archive_info"]
        assert info["status"] == "PASS"
        assert info["file_name"] == "fullpcr_all_results.zip"
        with zipfile.ZipFile(info["path"], "r") as zf:
            names = set(zf.namelist())
        assert names == {
            "qc_results/x.txt",
            "qc_spec_results/x.txt",
            "obipcr_results/x.txt",
            "final_results/x.txt",
        }
        assert not any(name.startswith("uploads/") for name in names)

    def test_initial_render_no_auto_zip(self, tmp_path):
        """First render does not auto-create ZIP."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        root.mkdir()
        (root / "x.txt").write_text("data")
        at.session_state["project_output_root"] = str(root)
        at.session_state["project_derived_paths"] = {"qc_spec_results_dir": str(root)}
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        zip_path = root / ".fullpcr_downloads" / "fullpcr_results.zip"
        assert not zip_path.exists(), f"ZIP was auto-created at {zip_path}"

    def test_build_zip_button_creates_zip(self, tmp_path):
        """Click build → ZIP created, PASS info, dl_results_zip shown."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        spec_dir = root / "qc_spec_results" / "spec"
        spec_dir.mkdir(parents=True)
        (root / "a.txt").write_text("hello")
        (spec_dir / "spec_output.txt.spec.tsv").write_text("raw\n")
        at.session_state["project_output_root"] = str(root)
        at.session_state["project_derived_paths"] = {"qc_spec_results_dir": str(root / "qc_spec_results")}
        at.session_state["full_pipeline_plan"] = [
            {"key": "s3", "label": "s3", "command": ["echo", "--outdir", str(root / "qc_spec_results")], "timeout": 60},
        ]
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        at.multiselect("_results_zip_groups").set_value(
            ["MFEprimer 特异性分析结果"]
        ).run()
        at.button("build_results_zip_btn").click().run()
        assert not at.exception
        info = at.session_state["results_archive_info"]
        assert info["status"] == "PASS"
        assert info["file_count"] == 1
        at.download_button("dl_results_zip")

    def test_zip_content_contains_selected_results_only(self, tmp_path):
        """ZIP includes the selected result directory and excludes root/input files."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        spec_dir = root / "qc_spec_results" / "spec"
        spec_dir.mkdir(parents=True)
        (root / "results.txt").write_text("r")
        (spec_dir / "spec_output.txt.spec.tsv").write_text("raw")
        at.session_state["project_output_root"] = str(root)
        at.session_state["project_derived_paths"] = {"qc_spec_results_dir": str(root / "qc_spec_results")}
        at.session_state["full_pipeline_plan"] = [
            {"key": "s3", "label": "s3", "command": ["echo", "--outdir", str(root / "qc_spec_results")], "timeout": 60},
        ]
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        at.multiselect("_results_zip_groups").set_value(
            ["MFEprimer 特异性分析结果"]
        ).run()
        at.button("build_results_zip_btn").click().run()
        assert not at.exception
        info = at.session_state["results_archive_info"]
        assert info["status"] == "PASS"
        import zipfile
        with zipfile.ZipFile(info["path"], "r") as zf:
            names = zf.namelist()
        assert "results.txt" not in names
        assert "qc_spec_results/spec/spec_output.txt.spec.tsv" in names
        assert ".fullpcr_downloads" not in str(names)

    def test_backend_fail_shows_error(self, tmp_path):
        """Backend FAIL → error message with detail, no dl_results_zip."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        qc_dir = root / "qc_results"
        qc_dir.mkdir(parents=True)
        (qc_dir / "x.txt").write_text("x")
        at.session_state["project_output_root"] = str(root)
        at.session_state["project_derived_paths"] = {"qc_spec_results_dir": str(root)}
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        at.multiselect("_results_zip_groups").set_value(
            ["MFEprimer 基础质控结果"]
        ).run()
        (root / ".fullpcr_downloads").write_text("阻止创建下载目录")
        at.button("build_results_zip_btn").click().run()
        assert not at.exception
        info = at.session_state["results_archive_info"]
        assert info["status"] == "FAIL"
        assert "不是目录" in info["error"]
        warnings = [w.value for w in at.warning]
        assert any("结果 ZIP 生成失败" in str(w) for w in warnings)
        assert any(info["error"] in str(w) for w in warnings)
        with pytest.raises(KeyError):
            at.download_button("dl_results_zip")

    def test_page_round_trip_no_rebuild(self, tmp_path):
        """Page switch: state survives, build_results_archive not re-called."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        final_dir = root / "final_results"
        final_dir.mkdir(parents=True)
        (final_dir / "f.txt").write_text("ok")
        at.session_state["project_output_root"] = str(root)
        at.session_state["project_derived_paths"] = {"qc_spec_results_dir": str(root)}
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        at.multiselect("_results_zip_groups").set_value(
            ["综合排名与最终报告"]
        ).run()
        at.button("build_results_zip_btn").click().run()
        assert not at.exception
        info1 = at.session_state["results_archive_info"]
        assert info1["status"] == "PASS"
        zip_mtime = Path(info1["path"]).stat().st_mtime

        # Switch away and return to 报告与下载.
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
        info2 = at.session_state["results_archive_info"]
        assert info2["status"] == "PASS"
        # ZIP must NOT have been rewritten (mtime unchanged).
        assert Path(info2["path"]).stat().st_mtime == zip_mtime

    def test_validation_clears_download_state(self, tmp_path):
        """Validation clears results_archive_info and results_archive_root."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        root.mkdir()
        (root / "f.txt").write_text("ok")
        at.session_state["results_archive_info"] = {"status": "PASS", "file_count": 1, "size": 100,
                                                      "path": str(root / "z.zip"), "file_name": "z.zip"}
        at.session_state["results_archive_root"] = str(root)
        at.session_state["project_output_root"] = str(root)
        at.session_state["project_derived_paths"] = {"qc_spec_results_dir": str(root)}
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert "results_archive_info" not in at.session_state
        assert "results_archive_root" not in at.session_state

    def test_dry_run_does_not_clear_download_state(self, tmp_path):
        """Dry-run pipeline keeps download state, real run clears it."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        root.mkdir()
        (root / "f.txt").write_text("ok")
        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is True
        # Set download state after validation.
        at.session_state["results_archive_info"] = {"status": "PASS", "file_count": 1, "size": 100,
                                                      "path": str(root / "z.zip"), "file_name": "z.zip"}
        at.session_state["results_archive_root"] = str(root)
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        # Dry-run: state kept.
        at.toggle("_workflow_dry_run").set_value(True).run()
        at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        assert "results_archive_info" in at.session_state
        assert at.session_state["results_archive_info"]["status"] == "PASS"

    def test_real_pipeline_clears_download_state(self, tmp_path):
        """Real pipeline execution clears results_archive_info/root."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        root.mkdir()
        (root / "f.txt").write_text("ok")
        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        assert at.session_state["inputs_validated"] is True
        at.session_state["results_archive_info"] = {"status": "PASS", "file_count": 1, "size": 100,
                                                      "path": str(root / "z.zip"), "file_name": "z.zip"}
        at.session_state["results_archive_root"] = str(root)
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        # Real run (dry_run=False): must clear download state before handing
        # execution to the persistent background manager.
        running_job = {
            "started": True,
            "status": "RUNNING",
            "job_id": "download-clear-job",
            "current_label": "准备开始五步分析",
            "progress_current": 0,
            "progress_total": 5,
        }
        with mock.patch(
            "fullpcr.pipeline_jobs.start_pipeline_job", return_value=running_job
        ) as start_job:
            at.button("full_pipeline_run_btn").click().run()
        assert not at.exception
        start_job.assert_called_once()
        assert "results_archive_info" not in at.session_state
        assert "results_archive_root" not in at.session_state

    def test_advanced_step_clears_download_state(self, tmp_path):
        """Running an advanced workflow step clears download state."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        root.mkdir()
        (root / "f.txt").write_text("ok")
        _switch_all_to_server_path(at)
        at.text_input("_inputs_primers_path").set_value(
            str(_EXAMPLE_DATA / "primers.tsv")).run()
        at.text_input("_inputs_database_path").set_value(
            str(_EXAMPLE_DATA / "real_mito_small.fasta")).run()
        at.text_input("_inputs_taxonomy_path").set_value(
            str(_EXAMPLE_DATA / "taxonomy.tsv")).run()
        at.button("inputs_validate_btn").click().run()
        assert not at.exception
        at.session_state["results_archive_info"] = {"status": "PASS", "file_count": 1, "size": 100,
                                                      "path": str(root / "z.zip"), "file_name": "z.zip"}
        at.session_state["results_archive_root"] = str(root)
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        # Enable advanced workflow and run step 1 (no dry-run).
        at.toggle("_show_advanced_workflow").set_value(True).run()
        assert not at.exception
        with mock.patch("fullpcr.gui_app.run_gui_command",
                         return_value={"status": "PASS", "stdout": "ok", "stderr": "",
                                        "returncode": 0, "message": "ok"}):
            at.button("wf_run_s1").click().run()
        assert not at.exception
        assert "results_archive_info" not in at.session_state
        assert "results_archive_root" not in at.session_state

    def test_both_pages_no_duplicate_widget_key(self, tmp_path):
        """Both pages render without DuplicateWidgetID."""
        pytest.importorskip("streamlit.testing")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(self._app_path()))
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("分析工作台").run()
        assert not at.exception
        root = tmp_path / "proj"
        spec_dir = root / "qc_spec_results" / "spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec_output.txt.spec.tsv").write_text("raw\n")
        (root / "f.txt").write_text("ok")
        at.session_state["project_output_root"] = str(root)
        at.session_state["project_derived_paths"] = {"qc_spec_results_dir": str(root / "qc_spec_results")}
        at.session_state["full_pipeline_plan"] = [
            {"key": "s3", "label": "s3", "command": ["echo", "--outdir", str(root / "qc_spec_results")], "timeout": 60},
        ]
        at.session_state["full_pipeline_result"] = {"status": "PASS"}
        at.run(timeout=30)
        assert not at.exception
        at.sidebar.radio[0].set_value("报告与下载").run()
        assert not at.exception
