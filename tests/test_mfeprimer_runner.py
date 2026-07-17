"""Tests for mfeprimer_runner module — Phase 1 & 2."""

import subprocess
from unittest import mock

import pytest

from fullpcr.mfeprimer_runner import (
    MFEprimerConfig,
    QC_FAILED_JOBS_FIELDNAMES,
    build_mfeprimer_command,
    build_mfeprimer_dimer_command,
    build_mfeprimer_hairpin_command,
    build_mfeprimer_thermo_command,
    check_mfeprimer_available,
    run_mfeprimer_dimer,
    run_mfeprimer_hairpin,
    run_mfeprimer_qc_job,
    run_mfeprimer_thermo,
)


# ── helpers ────────────────────────────────────────────────────────────


def _make_config(module: str = "thermo") -> MFEprimerConfig:
    return MFEprimerConfig(
        command=["mfeprimer", module, "-i", "primers.fasta"],
        input_fasta="primers.fasta",
        output_dir="out",
    )


def _completed_process(
    stdout: str = "output",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["mfeprimer"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ── Phase 1: availability ──────────────────────────────────────────────


class TestCheckMfeprimerAvailable:
    def test_returns_bool(self):
        result = check_mfeprimer_available()
        assert isinstance(result, bool)

    @pytest.mark.skipif(
        check_mfeprimer_available(),
        reason="MFEprimer is installed — test only valid in CI without MFEprimer",
    )
    def test_is_false_in_ci(self):
        """MFEprimer is not installed in this environment."""
        assert check_mfeprimer_available() is False


# ── Phase 1: build_mfeprimer_command ────────────────────────────────────


class TestBuildMfeprimerCommand:
    def test_builds_basic_command(self):
        config = build_mfeprimer_command(
            primer_fasta="/tmp/test/primers.fasta",
            output_dir="/tmp/test/qc",
        )

        assert isinstance(config, MFEprimerConfig)
        assert config.input_fasta == "/tmp/test/primers.fasta"
        assert config.output_dir == "/tmp/test/qc"
        assert config.command == [
            "mfeprimer",
            "-i",
            "/tmp/test/primers.fasta",
            "-o",
            "/tmp/test/qc",
        ]

    def test_raises_on_empty_primer_fasta(self):
        with pytest.raises(ValueError, match="primer_fasta 不能为空"):
            build_mfeprimer_command(primer_fasta="", output_dir="out")

    def test_raises_on_empty_output_dir(self):
        with pytest.raises(ValueError, match="output_dir 不能为空"):
            build_mfeprimer_command(primer_fasta="f.fasta", output_dir="")


# ── Phase 2: build_mfeprimer_thermo_command ────────────────────────────


class TestBuildMfeprimerThermoCommand:
    def test_builds_correct_command(self):
        config = build_mfeprimer_thermo_command(
            primer_fasta="/data/primers.fasta",
        )

        assert config.command == [
            "mfeprimer",
            "thermo",
            "/data/primers.fasta",
        ]
        assert config.input_fasta == "/data/primers.fasta"

    def test_raises_on_empty_fasta(self):
        with pytest.raises(ValueError, match="primer_fasta 不能为空"):
            build_mfeprimer_thermo_command(primer_fasta="")

    def test_raises_on_whitespace_fasta(self):
        with pytest.raises(ValueError, match="primer_fasta 不能为空"):
            build_mfeprimer_thermo_command(primer_fasta="   ")


# ── Phase 2: build_mfeprimer_dimer_command ─────────────────────────────


class TestBuildMfeprimerDimerCommand:
    def test_default_params(self):
        config = build_mfeprimer_dimer_command(
            primer_fasta="/data/p.fasta",
        )

        assert config.command == [
            "mfeprimer",
            "dimer",
            "-i",
            "/data/p.fasta",
            "--score",
            "5",
            "--mismatch",
            "2",
            "--dg",
            "-5.0",
        ]

    def test_custom_params(self):
        config = build_mfeprimer_dimer_command(
            primer_fasta="p.fasta",
            score=8,
            mismatch=3,
            dg=-7.5,
        )

        assert "--score" in config.command
        assert "8" in config.command
        assert "--mismatch" in config.command
        assert "3" in config.command
        assert "--dg" in config.command
        assert "-7.5" in config.command

    def test_raises_on_empty_fasta(self):
        with pytest.raises(ValueError, match="primer_fasta 不能为空"):
            build_mfeprimer_dimer_command(primer_fasta="")


# ── Phase 2: build_mfeprimer_hairpin_command ───────────────────────────


class TestBuildMfeprimerHairpinCommand:
    def test_default_params(self):
        config = build_mfeprimer_hairpin_command(
            primer_fasta="/data/p.fasta",
        )

        assert config.command == [
            "mfeprimer",
            "hairpin",
            "-i",
            "/data/p.fasta",
            "--tm",
            "50.0",
            "--dg",
            "-5.0",
            "--score",
            "5",
        ]

    def test_custom_params(self):
        config = build_mfeprimer_hairpin_command(
            primer_fasta="p.fasta",
            tm=60.0,
            dg=-3.0,
            score=8,
        )

        assert "--tm" in config.command
        assert "60.0" in config.command
        assert "--dg" in config.command
        assert "-3.0" in config.command
        assert "--score" in config.command
        assert "8" in config.command

    def test_raises_on_empty_fasta(self):
        with pytest.raises(ValueError, match="primer_fasta 不能为空"):
            build_mfeprimer_hairpin_command(primer_fasta="")


# ── Phase 2: MFEprimerConfig ───────────────────────────────────────────


class TestMFEprimerConfig:
    def test_is_frozen(self):
        config = MFEprimerConfig(
            command=["mfeprimer"],
            input_fasta="f.fasta",
            output_dir="out",
        )
        with pytest.raises(Exception):
            config.command = ["other"]

    def test_repr_contains_key_info(self):
        config = MFEprimerConfig(
            command=["mfeprimer", "-i", "x.fasta"],
            input_fasta="x.fasta",
            output_dir="out",
        )
        rep = repr(config)
        assert "mfeprimer" in rep


# ── Phase 2: run_mfeprimer_qc_job (mocked subprocess) ──────────────────


class TestRunMfeprimerQcJob:
    # ── success ───────────────────────────────────────────────────────

    def test_success_writes_stdout_to_raw(self, tmp_path):
        config = _make_config("thermo")
        raw = tmp_path / "thermo" / "thermo_raw.txt"
        stderr_p = tmp_path / "thermo" / "thermo.stderr.log"

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(
                    stdout="Tm=60.5\n", stderr="log line\n"
                ),
            ):
                result = run_mfeprimer_qc_job(
                    module="thermo",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                )

        assert result["status"] == "success"
        assert raw.read_text(encoding="utf-8") == "Tm=60.5\n"
        assert stderr_p.read_text(encoding="utf-8") == "log line\n"

    def test_success_stderr_can_be_empty(self, tmp_path):
        config = _make_config("dimer")
        raw = tmp_path / "dimer" / "dimer_raw.txt"
        stderr_p = tmp_path / "dimer" / "dimer.stderr.log"

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(stdout="ok", stderr=""),
            ):
                result = run_mfeprimer_qc_job(
                    module="dimer",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                )

        assert result["status"] == "success"
        assert result["error_message"] == ""

    # ── failure: non-zero exit ────────────────────────────────────────

    def test_nonzero_exit_writes_failed_status(self, tmp_path):
        config = _make_config("hairpin")
        raw = tmp_path / "hairpin" / "hairpin_raw.txt"
        stderr_p = tmp_path / "hairpin" / "hairpin.stderr.log"

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(
                    stdout="", stderr="bad input", returncode=1
                ),
            ):
                result = run_mfeprimer_qc_job(
                    module="hairpin",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                )

        assert result["status"] == "failed"
        assert "bad input" in result["error_message"]
        assert stderr_p.read_text(encoding="utf-8") == "bad input"

    def test_nonzero_exit_no_stderr(self, tmp_path):
        config = _make_config("thermo")
        raw = tmp_path / "t" / "raw.txt"
        stderr_p = tmp_path / "t" / "log.txt"

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(
                    stdout="", stderr="", returncode=2
                ),
            ):
                result = run_mfeprimer_qc_job(
                    module="thermo",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                )

        assert result["status"] == "failed"
        assert "非零退出码" in result["error_message"]

    # ── mfeprimer not installed ───────────────────────────────────────

    def test_mfeprimer_not_available_fails_gracefully(self, tmp_path):
        config = _make_config("thermo")
        raw = tmp_path / "t" / "raw.txt"
        stderr_p = tmp_path / "t" / "log.txt"

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=False,
        ):
            result = run_mfeprimer_qc_job(
                module="thermo",
                config=config,
                raw_path=raw,
                stderr_path=stderr_p,
            )

        assert result["status"] == "failed"
        assert "未找到" in result["error_message"]

    # ── timeout ───────────────────────────────────────────────────────

    def test_timeout_records_failed(self, tmp_path):
        config = _make_config("thermo")
        raw = tmp_path / "t" / "raw.txt"
        stderr_p = tmp_path / "t" / "log.txt"

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5),
            ):
                result = run_mfeprimer_qc_job(
                    module="thermo",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                    timeout=5,
                )

        assert result["status"] == "failed"
        assert "超时" in result["error_message"]

    # ── resume / force ────────────────────────────────────────────────

    def test_resume_skips_existing(self, tmp_path):
        config = _make_config("thermo")
        raw = tmp_path / "t" / "raw.txt"
        stderr_p = tmp_path / "t" / "log.txt"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("old", encoding="utf-8")
        stderr_p.write_text("old", encoding="utf-8")

        # subprocess should NOT be called
        with mock.patch(
            "fullpcr.mfeprimer_runner.subprocess.run"
        ) as mock_run:
            result = run_mfeprimer_qc_job(
                module="thermo",
                config=config,
                raw_path=raw,
                stderr_path=stderr_p,
                resume=True,
                force=False,
            )
            mock_run.assert_not_called()

        assert result["status"] == "skipped"
        assert raw.read_text(encoding="utf-8") == "old"

    def test_force_overrides_resume(self, tmp_path):
        config = _make_config("thermo")
        raw = tmp_path / "t" / "raw.txt"
        stderr_p = tmp_path / "t" / "log.txt"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("old", encoding="utf-8")
        stderr_p.write_text("old", encoding="utf-8")

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(stdout="new"),
            ):
                result = run_mfeprimer_qc_job(
                    module="thermo",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                    resume=True,
                    force=True,
                )

        assert result["status"] == "success"
        assert raw.read_text(encoding="utf-8") == "new"

    def test_resume_requires_both_files(self, tmp_path):
        """If only raw exists but not stderr, should NOT skip."""
        config = _make_config("thermo")
        raw = tmp_path / "t" / "raw.txt"
        stderr_p = tmp_path / "t" / "log.txt"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("old", encoding="utf-8")
        # stderr_path NOT created

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(stdout="new"),
            ):
                result = run_mfeprimer_qc_job(
                    module="thermo",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                    resume=True,
                    force=False,
                )

        assert result["status"] == "success"
        assert raw.read_text(encoding="utf-8") == "new"

    # ── creates parent directories ────────────────────────────────────

    def test_creates_output_dir(self, tmp_path):
        config = _make_config("thermo")
        raw = tmp_path / "deep" / "nested" / "raw.txt"
        stderr_p = tmp_path / "deep" / "nested" / "log.txt"

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(),
            ):
                run_mfeprimer_qc_job(
                    module="thermo",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                )

        assert raw.is_file()
        assert stderr_p.is_file()

    # ── FileNotFoundError ─────────────────────────────────────────────

    def test_file_not_found_error(self, tmp_path):
        config = _make_config("thermo")
        raw = tmp_path / "t" / "raw.txt"
        stderr_p = tmp_path / "t" / "log.txt"

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                side_effect=FileNotFoundError("no mfeprimer"),
            ):
                result = run_mfeprimer_qc_job(
                    module="thermo",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                )

        assert result["status"] == "failed"
        assert "未找到" in result["error_message"]

    # ── generic exception ─────────────────────────────────────────────

    def test_generic_exception_caught(self, tmp_path):
        config = _make_config("thermo")
        raw = tmp_path / "t" / "raw.txt"
        stderr_p = tmp_path / "t" / "log.txt"

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                side_effect=RuntimeError("unexpected"),
            ):
                result = run_mfeprimer_qc_job(
                    module="thermo",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                )

        assert result["status"] == "failed"
        assert "unexpected" in result["error_message"]

    # ── generated_file mode ───────────────────────────────────────────

    def test_generated_file_copied_to_raw(self, tmp_path):
        """When generated_file is set and exists, copy its content to raw."""
        config = _make_config("thermo")
        raw = tmp_path / "thermo" / "thermo_raw.tsv"
        stderr_p = tmp_path / "thermo" / "thermo.stderr.log"
        generated = tmp_path / "p.thermo.tsv"
        generated.write_text("# Name\tSeq\nprimer\tATCG\n", encoding="utf-8")

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(stdout="stdout", stderr="log"),
            ):
                result = run_mfeprimer_qc_job(
                    module="thermo",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                    generated_file=str(generated),
                )

        assert result["status"] == "success"
        # raw should contain generated file content, NOT stdout
        assert raw.read_text(encoding="utf-8") == "# Name\tSeq\nprimer\tATCG\n"
        assert stderr_p.read_text(encoding="utf-8") == "log"

    def test_generated_file_missing_fails(self, tmp_path):
        """When generated_file is set but doesn't exist, mark failed."""
        config = _make_config("thermo")
        raw = tmp_path / "t" / "raw.tsv"
        stderr_p = tmp_path / "t" / "log.txt"

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(stdout="ok", stderr=""),
            ):
                result = run_mfeprimer_qc_job(
                    module="thermo",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                    generated_file="/nonexistent/path/file.tsv",
                )

        assert result["status"] == "failed"
        assert "未生成" in result["error_message"]


# ── Phase 2: run_mfeprimer_thermo (thin wrapper) ───────────────────────


class TestRunMfeprimerThermo:
    def test_copies_generated_file_to_raw_tsv(self, tmp_path):
        """Thermo writes <input>.thermo.tsv; it must be copied to raw output."""
        fasta = str(tmp_path / "p.fasta")
        generated = tmp_path / "p.thermo.tsv"
        generated.write_text("# Name\tSeq\nprimer1\tATCG\n", encoding="utf-8")

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(stdout="", stderr="log"),
            ):
                result = run_mfeprimer_thermo(
                    primer_fasta=fasta,
                    outdir=str(tmp_path),
                )

        assert result["status"] == "success"
        assert result["module"] == "thermo"

        raw = tmp_path / "thermo" / "thermo_raw.tsv"
        assert raw.is_file()
        assert raw.read_text(encoding="utf-8") == "# Name\tSeq\nprimer1\tATCG\n"

        stderr_log = tmp_path / "thermo" / "thermo.stderr.log"
        assert stderr_log.is_file()
        assert stderr_log.read_text(encoding="utf-8") == "log"

    def test_fails_when_generated_file_missing(self, tmp_path):
        """If .thermo.tsv is not generated, mark status failed."""
        fasta = str(tmp_path / "p.fasta")
        # Do NOT create the .thermo.tsv file

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(stdout="", stderr=""),
            ):
                result = run_mfeprimer_thermo(
                    primer_fasta=fasta,
                    outdir=str(tmp_path),
                )

        assert result["status"] == "failed"
        assert "未生成" in result["error_message"]

    def test_writes_to_expected_path(self, tmp_path):
        fasta = str(tmp_path / "p.fasta")
        generated = tmp_path / "p.thermo.tsv"
        generated.write_text("data", encoding="utf-8")

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(),
            ):
                run_mfeprimer_thermo(
                    primer_fasta=fasta,
                    outdir=str(tmp_path),
                )

        assert (tmp_path / "thermo" / "thermo_raw.tsv").is_file()
        assert (tmp_path / "thermo" / "thermo.stderr.log").is_file()

    def test_passes_positional_arg_in_command(self, tmp_path):
        """Verify thermo uses positional arg, not -i flag."""
        fasta = str(tmp_path / "p.fasta")
        generated = tmp_path / "p.thermo.tsv"
        generated.write_text("data", encoding="utf-8")

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(),
            ) as mock_run:
                run_mfeprimer_thermo(
                    primer_fasta=fasta,
                    outdir=str(tmp_path),
                )

        call_args = mock_run.call_args[0][0]
        assert call_args == ["mfeprimer", "thermo", fasta]
        assert "-i" not in call_args


# ── Phase 2: run_mfeprimer_dimer (thin wrapper) ────────────────────────


class TestRunMfeprimerDimer:
    def test_passes_params_through(self, tmp_path):
        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(stdout="dimer ok"),
            ):
                result = run_mfeprimer_dimer(
                    primer_fasta="p.fasta",
                    outdir=str(tmp_path),
                    score=7,
                    mismatch=3,
                    dg=-4.5,
                )

        assert result["status"] == "success"
        assert result["module"] == "dimer"
        raw = tmp_path / "dimer" / "dimer_raw.txt"
        assert raw.read_text(encoding="utf-8") == "dimer ok"

    def test_uses_default_params(self, tmp_path):
        """Default params should be passed to build function."""
        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(),
            ) as mock_run:
                run_mfeprimer_dimer(
                    primer_fasta="p.fasta",
                    outdir=str(tmp_path),
                )

        # Verify command includes default values
        call_args = mock_run.call_args[0][0]
        assert "--score" in call_args
        assert "5" in call_args


# ── Phase 2: run_mfeprimer_hairpin (thin wrapper) ──────────────────────


class TestRunMfeprimerHairpin:
    def test_passes_params_through(self, tmp_path):
        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(stdout="hairpin ok"),
            ):
                result = run_mfeprimer_hairpin(
                    primer_fasta="p.fasta",
                    outdir=str(tmp_path),
                    tm=55.0,
                    dg=-4.0,
                    score=6,
                )

        assert result["status"] == "success"
        assert result["module"] == "hairpin"
        raw = tmp_path / "hairpin" / "hairpin_raw.txt"
        assert raw.read_text(encoding="utf-8") == "hairpin ok"


# ── QC_FAILED_JOBS_FIELDNAMES ──────────────────────────────────────────


class TestQcFailedJobsFieldnames:
    def test_contains_required_keys(self):
        required = {"module", "command", "output", "status", "error_message"}
        assert set(QC_FAILED_JOBS_FIELDNAMES) == required


class TestLongStderrNotTruncated:
    """Regression: >500 char stderr is NOT truncated after the [:500] removal."""

    def test_long_stderr_preserved_in_full(self, tmp_path):
        """mfeprimer stderr longer than 500 chars is preserved in full."""
        long_stderr = "START-" + ("y" * 600) + "-END"
        config = _make_config("spec")
        raw = tmp_path / "spec_raw.txt"
        stderr_p = tmp_path / "spec.stderr.log"

        with mock.patch(
            "fullpcr.mfeprimer_runner.check_mfeprimer_available",
            return_value=True,
        ):
            with mock.patch(
                "fullpcr.mfeprimer_runner.subprocess.run",
                return_value=_completed_process(
                    stdout="", stderr=long_stderr, returncode=1
                ),
            ):
                result = run_mfeprimer_qc_job(
                    module="spec",
                    config=config,
                    raw_path=raw,
                    stderr_path=stderr_p,
                )

        assert result["status"] == "failed"
        error_msg = result["error_message"]
        assert error_msg.startswith("START-")
        assert error_msg.endswith("-END")
        assert len(error_msg) > 500
