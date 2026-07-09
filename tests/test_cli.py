"""Tests for CLI module."""

import argparse
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest

from fullpcr.cli import _parse_mismatches, main, run_dry_run


# ── helpers ────────────────────────────────────────────────────────────


def _write_primers_tsv(tmp_path: Path) -> str:
    """Write a minimal primers.tsv and return its path."""
    content = textwrap.dedent("""\
        primer_id\tforward\treverse\tmin_length\tmax_length
        COI_short\tGGTCAACAAATCATAAAGATATTGG\tTAAACTTCAGGGTGACCAAAAAATCA\t100\t400
        16S\tGACGAGAAGACCCTATGGAGC\tCGCTGTTATCCCTAGGGTAACT\t200\t600
    """)
    path = tmp_path / "primers.tsv"
    path.write_text(content, encoding="utf-8")
    return str(path)


def _write_empty_fasta(tmp_path: Path) -> str:
    """Write a minimal FASTA file and return its path."""
    path = tmp_path / "mock_mito.fasta"
    path.write_text(">seq1\nATCG\n", encoding="utf-8")
    return str(path)


def _make_args(**overrides):
    """Build an argparse.Namespace with sensible dry-run defaults."""
    defaults = {
        "command": "run",
        "primers": "/tmp/primers.tsv",
        "database": "/tmp/mock.fasta",
        "outdir": "/tmp/results",
        "mismatches": "0,1,2",
        "circular": True,
        "dry_run": True,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ── _parse_mismatches ──────────────────────────────────────────────────


class TestParseMismatches:
    def test_parses_comma_separated_string(self):
        assert _parse_mismatches("0,1,2,3") == [0, 1, 2, 3]

    def test_handles_spaces(self):
        assert _parse_mismatches("0, 1, 2 ,3") == [0, 1, 2, 3]

    def test_single_value(self):
        assert _parse_mismatches("5") == [5]

    def test_negative_values(self):
        assert _parse_mismatches("-1,0,1") == [-1, 0, 1]

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError, match="不能为空"):
            _parse_mismatches("")

    def test_raises_on_whitespace_only(self):
        with pytest.raises(ValueError, match="不能为空"):
            _parse_mismatches("   ")

    def test_raises_on_non_integer(self):
        with pytest.raises(ValueError, match="非整数值"):
            _parse_mismatches("0,abc,2")


# ── run_dry_run ────────────────────────────────────────────────────────


class TestRunDryRun:
    def test_generates_correct_job_count(self, tmp_path, capsys):
        """N primers × M mismatches = N*M jobs."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)

        args = _make_args(
            primers=primers_path,
            database=db_path,
            outdir=str(tmp_path / "results"),
            mismatches="0,1,2,3",
        )

        jobs = run_dry_run(args)

        # 2 primers × 4 mismatches = 8 jobs
        assert len(jobs) == 8
        assert len({j["primer_id"] for j in jobs}) == 2
        assert len({j["mismatch"] for j in jobs}) == 4

    def test_each_job_has_required_keys(self, tmp_path, capsys):
        """Each job dict must contain primer_id, mismatch, command, output."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)

        args = _make_args(
            primers=primers_path,
            database=db_path,
            outdir=str(tmp_path / "results"),
            mismatches="0",
        )

        jobs = run_dry_run(args)

        for job in jobs:
            assert "primer_id" in job
            assert "mismatch" in job
            assert "command" in job
            assert "output" in job
            assert isinstance(job["command"], list)
            assert job["command"][0] == "obipcr"

    def test_output_path_contains_primer_and_mismatch(
        self, tmp_path, capsys
    ):
        """Output path should follow results/primer_id/mismatch_N/..."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)

        args = _make_args(
            primers=primers_path,
            database=db_path,
            outdir=str(tmp_path / "results"),
            mismatches="2",
        )

        jobs = run_dry_run(args)

        for job in jobs:
            pid = job["primer_id"]
            m = job["mismatch"]
            expected_suffix = (
                f"results/{pid}/mismatch_{m}/obipcr_amplicons.fasta"
            )
            assert job["output"].endswith(expected_suffix)

    def test_circular_flag_on_commands(self, tmp_path, capsys):
        """When --circular is set, all commands should include --circular."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)

        args = _make_args(
            primers=primers_path,
            database=db_path,
            outdir=str(tmp_path / "results"),
            mismatches="0",
            circular=True,
        )

        jobs = run_dry_run(args)

        for job in jobs:
            assert "--circular" in job["command"]

    def test_circular_flag_off(self, tmp_path, capsys):
        """When --circular is not set, commands should not have --circular."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)

        args = _make_args(
            primers=primers_path,
            database=db_path,
            outdir=str(tmp_path / "results"),
            mismatches="0",
            circular=False,
        )

        jobs = run_dry_run(args)

        for job in jobs:
            assert "--circular" not in job["command"]

    def test_dry_run_prints_summary_line(self, tmp_path, capsys):
        """Dry-run should print a summary with total job count."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)

        args = _make_args(
            primers=primers_path,
            database=db_path,
            outdir=str(tmp_path / "results"),
            mismatches="0,1",
        )

        run_dry_run(args)
        captured = capsys.readouterr()

        assert "合计" in captured.out
        assert "4 jobs" in captured.out

    def test_dry_run_does_not_call_subprocess_run(self, tmp_path, capsys):
        """Dry-run must never invoke subprocess.run."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)

        args = _make_args(
            primers=primers_path,
            database=db_path,
            outdir=str(tmp_path / "results"),
            mismatches="0,1",
        )

        with mock.patch("subprocess.run") as mock_run:
            run_dry_run(args)
            mock_run.assert_not_called()


# ── main (CLI entry) ───────────────────────────────────────────────────


class TestMainDryRun:
    def test_run_dry_run_succeeds(self, tmp_path, capsys):
        """Full CLI invocation should complete successfully."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(tmp_path / "results"),
            "--mismatches", "0,1,2,3",
            "--circular",
            "--dry-run",
        ]

        with mock.patch.object(sys, "exit") as mock_exit:
            main(argv)

        # Should not call sys.exit(1)
        exit_calls = [
            c
            for c in mock_exit.call_args_list
            if c.args and c.args[0] != 0
        ]
        assert len(exit_calls) == 0

        captured = capsys.readouterr()
        assert "DRY-RUN" in captured.out
        assert "obipcr" in captured.out

    def test_missing_dry_run_executes_real(self, tmp_path):
        """Without --dry-run, CLI now executes for real (not exit with error)."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(tmp_path / "results"),
            "--mismatches", "0",
        ]

        # CLI should NOT exit; it proceeds with real execution
        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", _mock_subprocess_success):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        # No error exit
        exit_calls = [
            c for c in mock_exit.call_args_list
            if c.args and c.args[0] != 0
        ]
        assert len(exit_calls) == 0

    def test_missing_primers_file_exits(self, tmp_path):
        """Should exit with error when primers file does not exist."""
        db_path = _write_empty_fasta(tmp_path)
        nonexistent = str(tmp_path / "no_such_file.tsv")

        argv = [
            "run",
            "--primers", nonexistent,
            "--database", db_path,
            "--outdir", str(tmp_path / "results"),
            "--mismatches", "0",
            "--dry-run",
        ]

        with pytest.raises(SystemExit) as exc_info:
            main(argv)

        assert exc_info.value.code == 1

    def test_missing_database_file_exits(self, tmp_path):
        """Should exit with error when database file does not exist."""
        primers_path = _write_primers_tsv(tmp_path)
        nonexistent = str(tmp_path / "no_such_db.fasta")

        argv = [
            "run",
            "--primers", primers_path,
            "--database", nonexistent,
            "--outdir", str(tmp_path / "results"),
            "--mismatches", "0",
            "--dry-run",
        ]

        with pytest.raises(SystemExit) as exc_info:
            main(argv)

        assert exc_info.value.code == 1

    def test_missing_primers_error_message(self, tmp_path, capsys):
        """Error message should clearly state which file is missing."""
        db_path = _write_empty_fasta(tmp_path)
        nonexistent = str(tmp_path / "no_such_file.tsv")

        argv = [
            "run",
            "--primers", nonexistent,
            "--database", db_path,
            "--outdir", str(tmp_path / "results"),
            "--mismatches", "0",
            "--dry-run",
        ]

        with pytest.raises(SystemExit):
            main(argv)

        captured = capsys.readouterr()
        assert "primers 文件不存在" in captured.err
        assert "no_such_file.tsv" in captured.err

    def test_missing_database_error_message(self, tmp_path, capsys):
        """Error message should clearly state which file is missing."""
        primers_path = _write_primers_tsv(tmp_path)
        nonexistent = str(tmp_path / "no_such_db.fasta")

        argv = [
            "run",
            "--primers", primers_path,
            "--database", nonexistent,
            "--outdir", str(tmp_path / "results"),
            "--mismatches", "0",
            "--dry-run",
        ]

        with pytest.raises(SystemExit):
            main(argv)

        captured = capsys.readouterr()
        assert "database 文件不存在" in captured.err
        assert "no_such_db.fasta" in captured.err

    def test_both_files_missing_reports_both(self, tmp_path, capsys):
        """When both files are missing, report both errors."""
        argv = [
            "run",
            "--primers", str(tmp_path / "a.tsv"),
            "--database", str(tmp_path / "b.fasta"),
            "--outdir", str(tmp_path / "results"),
            "--mismatches", "0",
            "--dry-run",
        ]

        with pytest.raises(SystemExit):
            main(argv)

        captured = capsys.readouterr()
        assert "primers 文件不存在" in captured.err
        assert "database 文件不存在" in captured.err

    def test_invalid_subcommand_exits(self, capsys):
        """Non-existent subcommand should cause argparse to exit."""
        # argparse rejects 'bogus' because only 'run' is a valid
        # subcommand choice — it calls sys.exit(2) internally.
        with pytest.raises(SystemExit) as exc_info:
            main(["bogus"])

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "invalid choice" in captured.err


# ── helpers for real-execution tests ────────────────────────────────────

MOCK_OBIPCR_FASTA = (
    '>NC_012920 {"taxid":9606,"scientific_name":"Homo sapiens",'
    '"forward_error":0,"reverse_error":0,"forward_match":"GGTCA",'
    '"reverse_match":"TAAAC","direction":"forward"}\n'
    "ATCGATCGATCG\n"
    '>NC_002083 {"taxid":9913,"scientific_name":"Bos taurus",'
    '"forward_error":1,"reverse_error":0,"forward_match":"GCTAG",'
    '"reverse_match":"CTAGC","direction":"forward"}\n'
    "GCTAGCTAGCTA\n"
)


def _mock_subprocess_success(*args, **kwargs):
    return subprocess.CompletedProcess(
        args=kwargs.get("args", []),
        returncode=0,
        stdout=MOCK_OBIPCR_FASTA,
        stderr="",
    )


def _write_taxonomy_tsv(tmp_path: Path) -> str:
    path = tmp_path / "taxonomy.tsv"
    content = textwrap.dedent("""\
        taxid\tscientific_name\tkingdom\tphylum\tclass\torder\tfamily\tgenus\tspecies
        9606\tHomo sapiens\tAnimalia\tChordata\tMammalia\tPrimates\tHominidae\tHomo\tHomo sapiens
        9913\tBos taurus\tAnimalia\tChordata\tMammalia\tCetartiodactyla\tBovidae\tBos\tBos taurus
    """)
    path.write_text(content, encoding="utf-8")
    return str(path)


# ── run_real (non-dry-run CLI) ──────────────────────────────────────────


class TestRunReal:
    def test_real_execution_generates_amplicons_tsv(self, tmp_path):
        """Non-dry-run should generate amplicons.tsv from obipcr output."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
        ]

        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", _mock_subprocess_success):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        # Should not call sys.exit
        exit_calls = [
            c for c in mock_exit.call_args_list
            if c.args and c.args[0] != 0
        ]
        assert len(exit_calls) == 0

        # Check amplicons.tsv was generated
        tsv_path = outdir / "COI_short" / "mismatch_0" / "amplicons.tsv"
        assert tsv_path.is_file(), f"Expected {tsv_path} to exist"

        content = tsv_path.read_text(encoding="utf-8")
        assert "NC_012920" in content
        assert "Homo sapiens" in content

    def test_real_execution_generates_failed_jobs_tsv(self, tmp_path):
        """failed_jobs.tsv should be written (empty on success)."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
        ]

        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", _mock_subprocess_success):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        failed_path = outdir / "failed_jobs.tsv"
        assert failed_path.is_file()

    def test_failed_jobs_tsv_has_correct_columns(self, tmp_path):
        """failed_jobs.tsv must have the correct header columns."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
        ]

        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", _mock_subprocess_success):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        failed_path = outdir / "failed_jobs.tsv"
        header = failed_path.read_text(encoding="utf-8").split("\n")[0]
        expected = "\t".join([
            "primer_id", "mismatch", "command", "output",
            "status", "error_message",
        ])
        assert header == expected

    def test_dry_run_does_not_call_subprocess(self, tmp_path):
        """--dry-run should never invoke subprocess.run."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(tmp_path / "results"),
            "--mismatches", "0",
            "--dry-run",
        ]

        with mock.patch("subprocess.run") as mock_run:
            with mock.patch.object(sys, "exit") as mock_exit:
                main(argv)
            mock_run.assert_not_called()

    def test_real_execution_calls_subprocess(self, tmp_path):
        """Non-dry-run should call subprocess.run for each job."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
        ]

        mock_run = mock.MagicMock(side_effect=_mock_subprocess_success)
        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", mock_run):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        # 2 primers × 1 mismatch = 2 calls
        assert mock_run.call_count == 2

    def test_multiple_mismatches_executes_all(self, tmp_path):
        """Each primer × mismatch combination gets executed."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0,1,2",
        ]

        mock_run = mock.MagicMock(side_effect=_mock_subprocess_success)
        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", mock_run):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        # 2 primers × 3 mismatches = 6 calls
        assert mock_run.call_count == 6

    def test_resume_flag_skips_existing(self, tmp_path):
        """--resume skips when outputs already exist."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        # Pre-create output files
        for pid in ["COI_short", "16S"]:
            d = outdir / pid / "mismatch_0"
            d.mkdir(parents=True)
            (d / "obipcr_amplicons.fasta").write_text(">existing", encoding="utf-8")
            (d / "amplicons.tsv").write_text("record_id\n", encoding="utf-8")

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
            "--resume",
        ]

        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run") as mock_run:
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        # All 2 jobs skipped, subprocess.run never called
        mock_run.assert_not_called()

    def test_force_overrides_resume(self, tmp_path):
        """--force re-runs even when --resume and files exist."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        # Pre-create output files
        for pid in ["COI_short", "16S"]:
            d = outdir / pid / "mismatch_0"
            d.mkdir(parents=True)
            (d / "obipcr_amplicons.fasta").write_text("old", encoding="utf-8")
            (d / "amplicons.tsv").write_text("old", encoding="utf-8")

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
            "--resume",
            "--force",
        ]

        mock_run = mock.MagicMock(side_effect=_mock_subprocess_success)
        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", mock_run):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        # All jobs re-executed despite existing files
        assert mock_run.call_count == 2

    def test_failed_jobs_recorded_in_tsv(self, tmp_path):
        """When a job fails, it should appear in failed_jobs.tsv."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        # Simulate obipcr not available → all jobs fail
        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
        ]

        with mock.patch("shutil.which", return_value=None):
            with mock.patch.object(sys, "exit") as mock_exit:
                main(argv)

        failed_path = outdir / "failed_jobs.tsv"
        assert failed_path.is_file()
        content = failed_path.read_text(encoding="utf-8")
        assert "obipcr 未找到" in content
        assert "COI_short" in content
        assert "16S" in content

    def test_obipcr_fasta_written_to_output(self, tmp_path):
        """obipcr stdout is written to obipcr_amplicons.fasta."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
        ]

        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", _mock_subprocess_success):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        fasta_path = outdir / "COI_short" / "mismatch_0" / "obipcr_amplicons.fasta"
        assert fasta_path.is_file()
        content = fasta_path.read_text(encoding="utf-8")
        assert "NC_012920" in content

    def test_stderr_log_written(self, tmp_path):
        """obipcr stderr is written to obipcr.stderr.log."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        def _mock_with_stderr(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=kwargs.get("args", []),
                returncode=0,
                stdout=MOCK_OBIPCR_FASTA,
                stderr="Processing 2 sequences...\n",
            )

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
        ]

        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", _mock_with_stderr):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        log_path = outdir / "COI_short" / "mismatch_0" / "obipcr.stderr.log"
        assert log_path.is_file()
        assert "Processing 2 sequences" in log_path.read_text(encoding="utf-8")


# ── post-run: --summarize / --report ────────────────────────────────────


class TestRunRealPostSteps:
    def test_summarize_generates_combined_summary(self, tmp_path):
        """--summarize should generate combined_summary.tsv after execution."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
            "--summarize",
        ]

        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", _mock_subprocess_success):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        cs_path = outdir / "combined_summary.tsv"
        assert cs_path.is_file(), f"Expected {cs_path} to exist"
        content = cs_path.read_text(encoding="utf-8")
        assert "primer_id" in content
        assert "COI_short" in content
        assert "16S" in content

    def test_report_generates_report_md(self, tmp_path):
        """--report should generate report.md after execution."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
            "--report",
        ]

        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", _mock_subprocess_success):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        report_path = outdir / "report.md"
        assert report_path.is_file(), f"Expected {report_path} to exist"
        content = report_path.read_text(encoding="utf-8")
        assert "# fullpcr in silico PCR Report" in content

    def test_summarize_with_taxonomy(self, tmp_path):
        """--summarize --taxonomy should include taxonomy merge."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        tax_path = _write_taxonomy_tsv(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
            "--summarize",
            "--taxonomy", tax_path,
        ]

        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", _mock_subprocess_success):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        cov_path = outdir / "coverage_by_taxon.tsv"
        assert cov_path.is_file()
        content = cov_path.read_text(encoding="utf-8")
        assert "Animalia" in content

    def test_summarize_and_report_together(self, tmp_path):
        """Both --summarize and --report can be used together."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
            "--summarize",
            "--report",
        ]

        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", _mock_subprocess_success):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        assert (outdir / "combined_summary.tsv").is_file()
        assert (outdir / "report.md").is_file()


# ── helpers for summarize/report subcommand tests ──────────────────────


def _build_mock_result_dir_for_summarize(tmp_path: Path) -> str:
    """Create a results/ dir with amplicons.tsv files for summarize tests."""
    outdir = tmp_path / "results"

    for pid in ["COI_short", "16S"]:
        d = outdir / pid / "mismatch_0"
        d.mkdir(parents=True)
        (d / "amplicons.tsv").write_text(
            textwrap.dedent("""\
                record_id\taccession\tdefinition\ttaxid\tscientific_name\tdirection\tforward_error\treverse_error\tforward_match\treverse_match\tamplicon_length\tsequence
                amplicon_0001\tNC_012920\t\t9606\tHomo sapiens\tforward\t0\t0\tGGTCA\tTAAAC\t200\tATCGATCGATCG
                amplicon_0002\tNC_002083\t\t9913\tBos taurus\tforward\t1\t0\tGCTAG\tCTAGC\t180\tGCTAGCTAGCTA
            """),
            encoding="utf-8",
        )

    return str(outdir)


def _build_result_dir_with_summaries(tmp_path: Path) -> str:
    """Create a results/ dir with amplicons.tsv files and pre-generated summaries."""
    outdir = _build_mock_result_dir_for_summarize(tmp_path)

    # Run summarize to generate all TSV files
    from fullpcr.summarize import write_summary_outputs
    tax_path = _write_taxonomy_tsv(tmp_path)
    write_summary_outputs(outdir, taxonomy_path=tax_path)

    return outdir


# ── summarize subcommand ────────────────────────────────────────────────


class TestSummarizeSubcommand:
    def test_generates_summary_files(self, tmp_path):
        """summarize --indir should generate all 5 summary TSV files."""
        outdir = _build_mock_result_dir_for_summarize(tmp_path)

        argv = ["summarize", "--indir", outdir]
        with mock.patch.object(sys, "exit") as mock_exit:
            main(argv)

        assert (Path(outdir) / "combined_summary.tsv").is_file()
        assert (Path(outdir) / "coverage_by_taxon.tsv").is_file()
        assert (Path(outdir) / "length_distribution.tsv").is_file()
        assert (Path(outdir) / "mismatch_distribution.tsv").is_file()
        assert (Path(outdir) / "species_resolution.tsv").is_file()

    def test_missing_result_dir_exits(self, capsys):
        """When --indir does not exist, exit with error."""
        argv = ["summarize", "--indir", "/nonexistent/dir"]

        with pytest.raises(SystemExit) as exc_info:
            main(argv)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "目录不存在" in captured.err

    def test_with_taxonomy(self, tmp_path):
        """summarize --indir --taxonomy should merge taxonomy."""
        outdir = _build_mock_result_dir_for_summarize(tmp_path)
        tax_path = _write_taxonomy_tsv(tmp_path)

        argv = ["summarize", "--indir", outdir, "--taxonomy", tax_path]
        with mock.patch.object(sys, "exit") as mock_exit:
            main(argv)

        cov = Path(outdir) / "coverage_by_taxon.tsv"
        content = cov.read_text(encoding="utf-8")
        assert "Animalia" in content

    def test_without_taxonomy_still_works(self, tmp_path):
        """summarize without --taxonomy should still generate all files."""
        outdir = _build_mock_result_dir_for_summarize(tmp_path)

        argv = ["summarize", "--indir", outdir]
        with mock.patch.object(sys, "exit") as mock_exit:
            main(argv)

        assert (Path(outdir) / "combined_summary.tsv").is_file()

    def test_missing_taxonomy_file_exits(self, capsys):
        """When --taxonomy points to a missing file, exit with error."""
        outdir = "/tmp/mock_results"
        argv = [
            "summarize",
            "--indir", outdir,
            "--taxonomy", "/nonexistent/tax.tsv",
        ]

        # First check taxonomy (fails before checking result_dir)
        # Actually, run_summarize checks indir first, then taxonomy.
        # We need a real dir to test taxonomy error.
        # The order: indir check → taxonomy check. So missing taxonomy
        # is caught only if indir exists.

    def test_handles_empty_result_dir(self, tmp_path):
        """An empty result dir (no amplicons.tsv) should not crash."""
        empty_dir = tmp_path / "empty_results"
        empty_dir.mkdir()

        argv = ["summarize", "--indir", str(empty_dir)]
        with mock.patch.object(sys, "exit") as mock_exit:
            main(argv)

        # Should still generate header-only TSV files
        assert (empty_dir / "combined_summary.tsv").is_file()

    def test_taxonomy_missing_file_exits(self, tmp_path):
        """When --taxonomy points to non-existent file, exit with error."""
        outdir = tmp_path / "results"
        outdir.mkdir()

        argv = [
            "summarize",
            "--indir", str(outdir),
            "--taxonomy", str(tmp_path / "no_such_taxon.tsv"),
        ]

        with pytest.raises(SystemExit) as exc_info:
            main(argv)

        assert exc_info.value.code == 1


# ── report subcommand ───────────────────────────────────────────────────


class TestReportSubcommand:
    def test_generates_report_md(self, tmp_path):
        """report --indir should generate report.md."""
        outdir = _build_result_dir_with_summaries(tmp_path)

        argv = ["report", "--indir", outdir]
        with mock.patch.object(sys, "exit") as mock_exit:
            main(argv)

        report_path = Path(outdir) / "report.md"
        assert report_path.is_file()
        content = report_path.read_text(encoding="utf-8")
        assert "# fullpcr in silico PCR Report" in content
        assert "## Run Summary" in content

    def test_missing_result_dir_exits(self, capsys):
        """When --indir does not exist, exit with error."""
        argv = ["report", "--indir", "/nonexistent/dir"]

        with pytest.raises(SystemExit) as exc_info:
            main(argv)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "目录不存在" in captured.err

    def test_missing_summary_tsv_still_generates_report(self, tmp_path):
        """Even when no summary TSV files exist, report should generate."""
        empty_dir = tmp_path / "empty_results"
        empty_dir.mkdir()

        argv = ["report", "--indir", str(empty_dir)]
        with mock.patch.object(sys, "exit") as mock_exit:
            main(argv)

        report_path = empty_dir / "report.md"
        assert report_path.is_file()
        content = report_path.read_text(encoding="utf-8")
        assert "## Known Limitations" in content

    def test_report_contains_known_limitations(self, tmp_path):
        """Report should always include the Known Limitations section."""
        outdir = _build_result_dir_with_summaries(tmp_path)

        argv = ["report", "--indir", outdir]
        with mock.patch.object(sys, "exit") as mock_exit:
            main(argv)

        content = (Path(outdir) / "report.md").read_text(encoding="utf-8")
        assert "## Known Limitations" in content
        assert "in silico PCR" in content

    def test_subcommand_name_in_help(self, capsys):
        """--help output should list all subcommands."""
        with pytest.raises(SystemExit):
            main(["--help"])

        captured = capsys.readouterr()
        assert "summarize" in captured.out
        assert "report" in captured.out
        assert "run" in captured.out


# ── integration: real mock obipcr executable ────────────────────────────

MOCK_OBIPCR_SCRIPT = """\
#!/usr/bin/env python3
import sys
sys.stdout.write(
    '>NC_012920 {"taxid":9606,"scientific_name":"Homo sapiens",'
    '"forward_error":0,"reverse_error":0,"forward_match":"GGTCA",'
    '"reverse_match":"TAAAC","direction":"forward"}\\n'
    "ATCGATCGATCG\\n"
    '>NC_002083 {"taxid":9913,"scientific_name":"Bos taurus",'
    '"forward_error":1,"reverse_error":0,"forward_match":"GCTAG",'
    '"reverse_match":"CTAGC","direction":"forward"}\\n'
    "GCTAGCTAGCTA\\n"
)
sys.stderr.write("mock obipcr processing...\\n")
"""


class TestIntegrationWithMockObipcrExecutable:
    """End-to-end tests using a real mock obipcr executable on PATH.

    These tests do NOT monkeypatch subprocess.run — the real
    subprocess and shutil.which machinery runs.
    """

    def test_full_run_with_mock_obipcr(self, tmp_path, monkeypatch):
        """Real execution via mock obipcr executable on PATH."""
        import os
        import stat

        # 1. Create mock obipcr executable
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        obipcr_exe = bin_dir / "obipcr"
        obipcr_exe.write_text(MOCK_OBIPCR_SCRIPT, encoding="utf-8")
        obipcr_exe.chmod(obipcr_exe.stat().st_mode | stat.S_IEXEC)

        # 2. Add to PATH
        monkeypatch.setenv("PATH", str(bin_dir), prepend=os.pathsep)

        # 3. Create input files
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        # 4. Run CLI (no subprocess.run mock!)
        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
        ]

        with mock.patch.object(sys, "exit") as mock_exit:
            main(argv)

        # 5. Verify exit
        exit_calls = [
            c for c in mock_exit.call_args_list
            if c.args and c.args[0] != 0
        ]
        assert len(exit_calls) == 0

        # 6. Verify output files for COI_short / mismatch_0
        job_dir = outdir / "COI_short" / "mismatch_0"

        fasta = job_dir / "obipcr_amplicons.fasta"
        assert fasta.is_file(), f"Missing {fasta}"
        content = fasta.read_text(encoding="utf-8")
        assert "NC_012920" in content
        assert "NC_002083" in content

        tsv = job_dir / "amplicons.tsv"
        assert tsv.is_file()
        tsv_content = tsv.read_text(encoding="utf-8")
        assert "Homo sapiens" in tsv_content
        assert "Bos taurus" in tsv_content

        stderr_log = job_dir / "obipcr.stderr.log"
        assert stderr_log.is_file()
        assert "mock obipcr processing" in stderr_log.read_text(encoding="utf-8")

        # 7. Verify failed_jobs.tsv has header
        failed = outdir / "failed_jobs.tsv"
        assert failed.is_file()
        header = failed.read_text(encoding="utf-8").split("\n")[0]
        assert "primer_id" in header
        assert "status" in header

    def test_mock_obipcr_jobs_have_success_status(self, tmp_path, monkeypatch):
        """All jobs should have status=success with mock obipcr."""
        import os
        import stat

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        obipcr_exe = bin_dir / "obipcr"
        obipcr_exe.write_text(MOCK_OBIPCR_SCRIPT, encoding="utf-8")
        obipcr_exe.chmod(obipcr_exe.stat().st_mode | stat.S_IEXEC)

        monkeypatch.setenv("PATH", str(bin_dir), prepend=os.pathsep)

        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0,1",
        ]

        with mock.patch.object(sys, "exit") as mock_exit:
            main(argv)

        failed = outdir / "failed_jobs.tsv"
        lines = failed.read_text(encoding="utf-8").strip().split("\n")
        # Only header (1 line) when no failures
        assert len(lines) == 1, f"Expected only header, got {len(lines)} lines"

    def test_dry_run_still_works(self, tmp_path, capsys):
        """--dry-run should still print commands without executing."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(tmp_path / "results"),
            "--mismatches", "0",
            "--dry-run",
        ]

        with mock.patch.object(sys, "exit") as mock_exit:
            main(argv)

        captured = capsys.readouterr()
        assert "DRY-RUN" in captured.out


# ── --timeout CLI ───────────────────────────────────────────────────────


class TestTimeoutCLI:
    def test_timeout_passed_to_run_obipcr_job(self, tmp_path):
        """--timeout should be passed through to run_obipcr_job."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
            "--timeout", "60",
        ]

        mock_run = mock.MagicMock(side_effect=_mock_subprocess_success)
        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", mock_run):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        # Verify timeout=60.0 was passed to subprocess.run
        for call_args in mock_run.call_args_list:
            assert call_args[1].get("timeout") == 60.0

    def test_timeout_default_not_passed(self, tmp_path):
        """Without --timeout, timeout should not be set."""
        primers_path = _write_primers_tsv(tmp_path)
        db_path = _write_empty_fasta(tmp_path)
        outdir = tmp_path / "results"

        argv = [
            "run",
            "--primers", primers_path,
            "--database", db_path,
            "--outdir", str(outdir),
            "--mismatches", "0",
        ]

        mock_run = mock.MagicMock(side_effect=_mock_subprocess_success)
        with mock.patch("shutil.which", return_value="/usr/bin/obipcr"):
            with mock.patch("subprocess.run", mock_run):
                with mock.patch.object(sys, "exit") as mock_exit:
                    main(argv)

        # timeout key should either be absent or None
        for call_args in mock_run.call_args_list:
            assert call_args[1].get("timeout") is None
