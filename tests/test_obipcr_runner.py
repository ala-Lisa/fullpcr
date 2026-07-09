"""Tests for obipcr_runner module."""

import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from fullpcr.obipcr_runner import (
    FAILED_JOBS_FIELDNAMES,
    ObiPCRConfig,
    build_obipcr_command,
    check_obipcr_available,
    run_obipcr_job,
)


# --- Shared test fixture values ---

FWD = "GGTCAACAAATCATAAAGATATTGG"
REV = "TAAACTTCAGGGTGACCAAAAAATCA"
DB = "/data/mitochondria.fasta"
OUT = "/results/amplicons.fasta"

# Valid obipcr FASTA output for mock
MOCK_FASTA_STDOUT = (
    '>NC_012920 {"taxid":9606,"scientific_name":"Homo sapiens",'
    '"forward_error":0,"reverse_error":0,"forward_match":"GGTCA",'
    '"reverse_match":"TAAAC","direction":"forward"}\n'
    "ATCGATCGATCG\n"
    '>NC_002083 {"taxid":9913,"scientific_name":"Bos taurus",'
    '"forward_error":1,"reverse_error":0,"forward_match":"GCTAG",'
    '"reverse_match":"CTAGC","direction":"forward"}\n'
    "GCTAGCTAGCTA\n"
)

MOCK_STDERR = "obipcr processing...\nDone.\n"


# ── helpers ────────────────────────────────────────────────────────────


def _mock_subprocess_run(*args, **kwargs):
    """Return a successful mock subprocess.CompletedProcess."""
    return subprocess.CompletedProcess(
        args=kwargs.get("args", []),
        returncode=0,
        stdout=MOCK_FASTA_STDOUT,
        stderr=MOCK_STDERR,
    )


def _mock_subprocess_run_failure(*args, **kwargs):
    """Return a failed mock subprocess.CompletedProcess."""
    return subprocess.CompletedProcess(
        args=kwargs.get("args", []),
        returncode=1,
        stdout="",
        stderr="obipcr: error: database not found\n",
    )


def _make_config(output: str | Path) -> ObiPCRConfig:
    return build_obipcr_command(
        forward=FWD,
        reverse=REV,
        min_length=100,
        max_length=400,
        allowed_mismatches=2,
        database=DB,
        output=output,
    )


# ── build_obipcr_command (existing tests) ──────────────────────────────


class TestBuildObipcrCommand:
    """Tests for build_obipcr_command()."""

    # ── basic command shape ────────────────────────────────────────────

    def test_builds_basic_command(self):
        """Should generate a correct minimal command as list[str]."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=2,
            database=DB,
            output=OUT,
        )

        cmd = config.command

        assert isinstance(cmd, list)
        assert all(isinstance(part, str) for part in cmd)
        assert cmd[0] == "obipcr"
        assert "--forward" in cmd
        assert FWD in cmd
        assert "--reverse" in cmd
        assert REV in cmd
        assert "--min-length" in cmd
        assert "100" in cmd
        assert "--max-length" in cmd
        assert "400" in cmd
        assert "--allowed-mismatches" in cmd
        assert "2" in cmd
        assert DB in cmd

    def test_returns_obi_pcr_config(self):
        """Should return an ObiPCRConfig with command and output."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=0,
            database=DB,
            output=OUT,
        )

        assert isinstance(config, ObiPCRConfig)
        assert isinstance(config.command, list)
        assert config.output == OUT

    # ── circular ───────────────────────────────────────────────────────

    def test_circular_true_includes_flag(self):
        """circular=True should add --circular to command."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=2,
            database=DB,
            output=OUT,
            circular=True,
        )

        assert "--circular" in config.command

    def test_circular_false_excludes_flag(self):
        """circular=False (default) should NOT add --circular."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=2,
            database=DB,
            output=OUT,
            circular=False,
        )

        assert "--circular" not in config.command

    def test_circular_default_is_false(self):
        """Default (no circular kwarg) should NOT include --circular."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=2,
            database=DB,
            output=OUT,
        )

        assert "--circular" not in config.command

    # ── no_progressbar ─────────────────────────────────────────────────

    def test_no_progressbar_true_includes_flag(self):
        """no_progressbar=True should add --no-progressbar (default)."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=2,
            database=DB,
            output=OUT,
            no_progressbar=True,
        )

        assert "--no-progressbar" in config.command

    def test_no_progressbar_false_excludes_flag(self):
        """no_progressbar=False should NOT add --no-progressbar."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=2,
            database=DB,
            output=OUT,
            no_progressbar=False,
        )

        assert "--no-progressbar" not in config.command

    # ── mismatches / length args ───────────────────────────────────────

    def test_allowed_mismatches_passed_correctly(self):
        """--allowed-mismatches should reflect the given int value."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=200,
            max_length=600,
            allowed_mismatches=3,
            database=DB,
            output=OUT,
        )

        idx = config.command.index("--allowed-mismatches")
        assert config.command[idx + 1] == "3"

    def test_min_max_length_passed_correctly(self):
        """--min-length and --max-length should reflect the given values."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=150,
            max_length=500,
            allowed_mismatches=1,
            database=DB,
            output=OUT,
        )

        idx_min = config.command.index("--min-length")
        assert config.command[idx_min + 1] == "150"
        idx_max = config.command.index("--max-length")
        assert config.command[idx_max + 1] == "500"

    # ── command is list, never string ───────────────────────────────────

    def test_command_is_list_not_string(self):
        """The command must be list[str], never a shell string."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=0,
            database=DB,
            output=OUT,
        )

        assert isinstance(config.command, list)
        assert not isinstance(config.command, str)

    # ── no shell redirect ">" for output ───────────────────────────────

    def test_output_not_in_command_as_redirect(self):
        """Output path must NOT appear in the command list as shell '>'."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=2,
            database=DB,
            output=OUT,
        )

        assert ">" not in config.command
        assert OUT not in config.command

    def test_output_path_preserved_in_config(self):
        """Output path must be preserved in config.output for later use."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=2,
            database=DB,
            output="/some/custom/output.fasta",
        )

        assert config.output == "/some/custom/output.fasta"

    # ── validation errors ──────────────────────────────────────────────

    def test_raises_on_empty_forward(self):
        """Should raise ValueError when forward is empty."""
        with pytest.raises(ValueError, match="forward"):
            build_obipcr_command(
                forward="",
                reverse=REV,
                min_length=100,
                max_length=400,
                allowed_mismatches=2,
                database=DB,
                output=OUT,
            )

    def test_raises_on_whitespace_forward(self):
        """Should raise ValueError when forward is whitespace only."""
        with pytest.raises(ValueError, match="forward"):
            build_obipcr_command(
                forward="   ",
                reverse=REV,
                min_length=100,
                max_length=400,
                allowed_mismatches=2,
                database=DB,
                output=OUT,
            )

    def test_raises_on_empty_reverse(self):
        """Should raise ValueError when reverse is empty."""
        with pytest.raises(ValueError, match="reverse"):
            build_obipcr_command(
                forward=FWD,
                reverse="",
                min_length=100,
                max_length=400,
                allowed_mismatches=2,
                database=DB,
                output=OUT,
            )

    def test_raises_on_empty_database(self):
        """Should raise ValueError when database is empty string."""
        with pytest.raises(ValueError, match="database"):
            build_obipcr_command(
                forward=FWD,
                reverse=REV,
                min_length=100,
                max_length=400,
                allowed_mismatches=2,
                database="",
                output=OUT,
            )

    def test_raises_on_empty_output(self):
        """Should raise ValueError when output is empty string."""
        with pytest.raises(ValueError, match="output"):
            build_obipcr_command(
                forward=FWD,
                reverse=REV,
                min_length=100,
                max_length=400,
                allowed_mismatches=2,
                database=DB,
                output="",
            )

    def test_raises_on_negative_min_length(self):
        """Should raise ValueError when min_length <= 0."""
        with pytest.raises(ValueError, match="min_length"):
            build_obipcr_command(
                forward=FWD,
                reverse=REV,
                min_length=0,
                max_length=400,
                allowed_mismatches=2,
                database=DB,
                output=OUT,
            )

    def test_raises_when_min_greater_than_max(self):
        """Should raise ValueError when min_length > max_length."""
        with pytest.raises(ValueError, match="不能大于"):
            build_obipcr_command(
                forward=FWD,
                reverse=REV,
                min_length=500,
                max_length=400,
                allowed_mismatches=2,
                database=DB,
                output=OUT,
            )

    def test_raises_on_negative_mismatches(self):
        """Should raise ValueError when allowed_mismatches < 0."""
        with pytest.raises(ValueError, match="allowed_mismatches"):
            build_obipcr_command(
                forward=FWD,
                reverse=REV,
                min_length=100,
                max_length=400,
                allowed_mismatches=-1,
                database=DB,
                output=OUT,
            )

    def test_error_message_includes_all_missing_params(self):
        """Error should include all missing parameters at once."""
        with pytest.raises(ValueError) as exc_info:
            build_obipcr_command(
                forward="",
                reverse="",
                min_length=0,
                max_length=0,
                allowed_mismatches=2,
                database="",
                output="",
            )

        msg = str(exc_info.value)
        assert "forward" in msg
        assert "reverse" in msg
        assert "database" in msg
        assert "output" in msg

    # ── command order sanity ───────────────────────────────────────────

    def test_database_is_last_positional_arg(self):
        """The database path should be the last arg (positional, not flag)."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=2,
            database=DB,
            output=OUT,
        )

        assert config.command[-1] == DB
        assert config.command[-2] != "--database"

    def test_command_starts_with_obipcr(self):
        """The first element must be the executable name."""
        config = build_obipcr_command(
            forward=FWD,
            reverse=REV,
            min_length=100,
            max_length=400,
            allowed_mismatches=2,
            database=DB,
            output=OUT,
        )

        assert config.command[0] == "obipcr"


# ── check_obipcr_available ─────────────────────────────────────────────


class TestCheckObipcrAvailable:
    def test_returns_true_when_obipcr_found(self, monkeypatch):
        """When obipcr is on PATH, returns True."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        assert check_obipcr_available() is True

    def test_returns_false_when_obipcr_not_found(self, monkeypatch):
        """When obipcr is not on PATH, returns False."""
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert check_obipcr_available() is False


# ── run_obipcr_job ─────────────────────────────────────────────────────


class TestRunObipcrJob:
    def test_successful_execution_writes_fasta(self, tmp_path, monkeypatch):
        """Successful run writes stdout to FASTA file."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        monkeypatch.setattr(subprocess, "run", _mock_subprocess_run)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config,
        )

        assert result["status"] == "success"
        assert result["primer_id"] == "COI"
        assert result["mismatch"] == 0
        assert output.is_file()
        assert MOCK_FASTA_STDOUT in output.read_text(encoding="utf-8")

    def test_successful_execution_writes_stderr_log(self, tmp_path, monkeypatch):
        """stderr is written to obipcr.stderr.log."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        monkeypatch.setattr(subprocess, "run", _mock_subprocess_run)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        run_obipcr_job(primer_id="COI", mismatch=0, config=config)

        stderr_path = output.with_name("obipcr.stderr.log")
        assert stderr_path.is_file()
        assert MOCK_STDERR in stderr_path.read_text(encoding="utf-8")

    def test_successful_execution_writes_amplicons_tsv(self, tmp_path, monkeypatch):
        """After successful run, amplicons.tsv is generated from FASTA."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        monkeypatch.setattr(subprocess, "run", _mock_subprocess_run)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        run_obipcr_job(primer_id="COI", mismatch=0, config=config)

        tsv_path = output.with_name("amplicons.tsv")
        assert tsv_path.is_file()

        content = tsv_path.read_text(encoding="utf-8")
        assert "record_id" in content
        assert "NC_012920" in content
        assert "Homo sapiens" in content

    def test_nonzero_returncode_marks_failed(self, tmp_path, monkeypatch):
        """When obipcr returns non-zero, status is 'failed'."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        monkeypatch.setattr(subprocess, "run", _mock_subprocess_run_failure)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config,
        )

        assert result["status"] == "failed"
        assert "database not found" in result["error_message"]

    def test_nonzero_still_writes_stderr_log(self, tmp_path, monkeypatch):
        """Even on failure, stderr is still written to log."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        monkeypatch.setattr(subprocess, "run", _mock_subprocess_run_failure)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        run_obipcr_job(primer_id="COI", mismatch=0, config=config)

        stderr_path = output.with_name("obipcr.stderr.log")
        assert stderr_path.is_file()

    def test_nonzero_uses_returncode_as_fallback_error(self, tmp_path, monkeypatch):
        """When stderr is empty and returncode != 0, uses returncode as error."""
        def _mock_empty_stderr(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=kwargs.get("args", []),
                returncode=2,
                stdout="",
                stderr="",
            )

        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        monkeypatch.setattr(subprocess, "run", _mock_empty_stderr)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config,
        )

        assert result["status"] == "failed"
        assert "返回非零退出码" in result["error_message"]
        assert "2" in result["error_message"]

    def test_obipcr_not_available_clear_error(self, tmp_path, monkeypatch):
        """When obipcr is not on PATH, returns clear error."""
        monkeypatch.setattr(shutil, "which", lambda name: None)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config,
        )

        assert result["status"] == "failed"
        assert "obipcr 未找到" in result["error_message"]
        assert "OBITools4" in result["error_message"]

    def test_resume_skips_existing_files(self, tmp_path, monkeypatch):
        """When --resume and output files exist, skip execution."""
        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        output.parent.mkdir(parents=True)
        output.write_text(">existing", encoding="utf-8")

        tsv_path = output.with_name("amplicons.tsv")
        tsv_path.write_text("record_id\n", encoding="utf-8")

        config = _make_config(str(output))

        # subprocess.run should NOT be called
        with mock.patch("subprocess.run") as mock_run:
            result = run_obipcr_job(
                primer_id="COI", mismatch=0, config=config, resume=True,
            )
            mock_run.assert_not_called()

        assert result["status"] == "skipped"
        assert "已有结果" in result["error_message"]

    def test_resume_does_not_skip_when_tsv_missing(self, tmp_path, monkeypatch):
        """When only FASTA exists but not TSV, still execute."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        monkeypatch.setattr(subprocess, "run", _mock_subprocess_run)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        output.parent.mkdir(parents=True)
        output.write_text(">existing", encoding="utf-8")
        # No amplicons.tsv

        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config, resume=True,
        )

        assert result["status"] == "success"

    def test_force_overrides_resume(self, tmp_path, monkeypatch):
        """--force re-runs even when --resume would skip."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        monkeypatch.setattr(subprocess, "run", _mock_subprocess_run)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        output.parent.mkdir(parents=True)
        output.write_text("old content", encoding="utf-8")

        tsv_path = output.with_name("amplicons.tsv")
        tsv_path.write_text("old", encoding="utf-8")

        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config,
            resume=True, force=True,
        )

        assert result["status"] == "success"
        # File should have been overwritten with new content
        assert MOCK_FASTA_STDOUT in output.read_text(encoding="utf-8")

    def test_result_has_all_required_keys(self, tmp_path, monkeypatch):
        """Each result dict must contain all FAILED_JOBS_FIELDNAMES keys."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        monkeypatch.setattr(subprocess, "run", _mock_subprocess_run)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config,
        )

        for key in FAILED_JOBS_FIELDNAMES:
            assert key in result, f"Missing key {key!r}"

    def test_command_in_result_is_string(self, tmp_path, monkeypatch):
        """command field is a space-joined string for readability."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        monkeypatch.setattr(subprocess, "run", _mock_subprocess_run)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config,
        )

        assert isinstance(result["command"], str)
        assert result["command"].startswith("obipcr")

    def test_creates_output_directory(self, tmp_path, monkeypatch):
        """Output directory should be created if it doesn't exist."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        monkeypatch.setattr(subprocess, "run", _mock_subprocess_run)

        output = tmp_path / "deep" / "nested" / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        assert not output.parent.exists()

        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config,
        )

        assert result["status"] == "success"
        assert output.is_file()

    def test_file_not_found_error_caught(self, tmp_path, monkeypatch):
        """When subprocess.run raises FileNotFoundError, report as failed."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")

        def _raise_fnf(*args, **kwargs):
            raise FileNotFoundError("No such file: obipcr")

        monkeypatch.setattr(subprocess, "run", _raise_fnf)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config,
        )

        assert result["status"] == "failed"
        assert "obipcr 未找到" in result["error_message"]

    def test_generic_exception_caught(self, tmp_path, monkeypatch):
        """Any unexpected exception is caught and reported."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")

        def _raise_generic(*args, **kwargs):
            raise RuntimeError("Something went wrong")

        monkeypatch.setattr(subprocess, "run", _raise_generic)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config,
        )

        assert result["status"] == "failed"
        assert "Something went wrong" in result["error_message"]

    def test_timeout_records_failure(self, tmp_path, monkeypatch):
        """When obipcr times out, status is 'failed' with timeout info."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")

        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="obipcr", timeout=30.0)

        monkeypatch.setattr(subprocess, "run", _raise_timeout)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config, timeout=30.0,
        )

        assert result["status"] == "failed"
        assert "超时" in result["error_message"]
        assert "30.0" in result["error_message"]

    def test_timeout_default_is_none(self, tmp_path, monkeypatch):
        """When called without timeout, subprocess.run gets timeout=None."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/obipcr")
        mock_run = mock.MagicMock(return_value=_mock_subprocess_run())

        monkeypatch.setattr(subprocess, "run", mock_run)

        output = tmp_path / "COI" / "mismatch_0" / "obipcr_amplicons.fasta"
        config = _make_config(str(output))
        result = run_obipcr_job(
            primer_id="COI", mismatch=0, config=config,
        )

        assert result["status"] == "success"
        # Verify timeout=None was passed
        assert mock_run.call_args[1].get("timeout") is None
