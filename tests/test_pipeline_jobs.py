"""Tests for project-scoped background pipeline jobs."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

import fullpcr.gui_helpers as gui_helpers
import fullpcr.pipeline_jobs as pipeline_jobs
from fullpcr.pipeline_jobs import (
    get_pipeline_job,
    request_pipeline_cancel,
    start_pipeline_job,
)


def _plan() -> list[dict]:
    return [
        {
            "key": "s1",
            "result_key": "wf_s1_result",
            "label": "基础质控",
            "command": ["cmd", "s1"],
            "timeout": 10,
        },
        {
            "key": "s2",
            "result_key": "wf_s2_result",
            "label": "质控汇总",
            "command": ["cmd", "s2"],
            "timeout": 10,
        },
        {
            "key": "s3",
            "result_key": "wf_s3_result",
            "label": "特异性分析",
            "command": ["cmd", "s3"],
            "timeout": 10,
        },
        {
            "key": "s4",
            "result_key": "wf_s4_result",
            "label": "obipcr 全库模拟 PCR",
            "command": ["cmd", "s4"],
            "timeout": 10,
        },
        {
            "key": "s5",
            "result_key": "wf_s5_result",
            "label": "最终综合报告",
            "command": ["cmd", "s5"],
            "timeout": 10,
        },
    ]


def _wait_terminal(root: Path, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = get_pipeline_job(str(root))
        if state is not None and state.get("status") != "RUNNING":
            return state
        time.sleep(0.01)
    raise AssertionError("pipeline job did not reach a terminal state")


def _wait_suspected_stuck(root: Path, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = get_pipeline_job(str(root))
        if state is not None and state.get("suspected_stuck") is True:
            return state
        time.sleep(0.01)
    raise AssertionError("pipeline job was not marked suspected stuck")


class TestPipelineJobManager:

    def test_activity_change_requires_cpu_or_output_delta(self):
        baseline = (10, 1, 100, 1_000)
        assert pipeline_jobs._activity_changed(baseline, (11, 1, 100, 1_000))
        assert pipeline_jobs._activity_changed(baseline, (10, 2, 100, 1_000))
        assert pipeline_jobs._activity_changed(baseline, (10, 1, 101, 1_000))
        assert pipeline_jobs._activity_changed(baseline, (10, 1, 100, 1_001))
        assert not pipeline_jobs._activity_changed(baseline, baseline)

    def test_output_signature_ignores_job_state_and_symlinks(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        result = root / "result.tsv"
        result.write_text("one", encoding="utf-8")
        job_dir = root / ".fullpcr_jobs"
        job_dir.mkdir()
        state = job_dir / "pipeline_state.json"
        state.write_text("first", encoding="utf-8")
        external = tmp_path / "external"
        external.write_text("outside", encoding="utf-8")
        (root / "external-link").symlink_to(external)

        before = pipeline_jobs._output_tree_signature(root)
        state.write_text("second and larger", encoding="utf-8")
        assert pipeline_jobs._output_tree_signature(root) == before
        result.write_text("changed output", encoding="utf-8")
        assert pipeline_jobs._output_tree_signature(root) != before

    @pytest.mark.skipif(
        not Path("/proc").is_dir() or not hasattr(os, "killpg"),
        reason="requires Linux process groups",
    )
    def test_suspected_stuck_can_be_cancelled_by_matching_job_id(
        self, monkeypatch, tmp_path
    ):
        root = tmp_path / "project"
        root.mkdir()
        marker = f"fullpcr-cancel-{os.getpid()}"
        plan = [
            {
                "key": "s1",
                "result_key": "wf_s1_result",
                "label": "基础质控",
                "command": [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                    marker,
                ],
                "timeout": None,
            },
            {
                "key": "s2",
                "result_key": "wf_s2_result",
                "label": "质控汇总",
                "command": [sys.executable, "-c", "raise SystemExit(99)"],
                "timeout": None,
            },
        ]
        monkeypatch.setattr(pipeline_jobs, "_HEALTH_CHECK_SECONDS", 0.05)
        monkeypatch.setattr(gui_helpers, "_COMMAND_POLL_SECONDS", 0.01)

        started = start_pipeline_job(str(root), plan)
        stuck = _wait_suspected_stuck(root)
        assert stuck["last_health_check_at"]
        assert stuck["last_activity_at"]
        assert stuck["current_process_group"] > 0

        wrong = request_pipeline_cancel(str(root), "wrong-job")
        assert wrong["cancelled"] is False
        accepted = request_pipeline_cancel(str(root), started["job_id"])
        assert accepted["cancelled"] is True

        terminal = _wait_terminal(root)
        assert terminal["status"] == "CANCELLED"
        assert terminal["outcome"]["status"] == "CANCELLED"
        assert terminal["outcome"]["failed_step"] == "s1"
        assert "wf_s2_result" not in terminal["outcome"]["results"]
        assert not (root / ".fullpcr_jobs" / "pipeline.lock").exists()
        pgid = stuck["current_process_group"]
        with pytest.raises(ProcessLookupError):
            os.killpg(pgid, 0)
    def test_duplicate_running_submission_executes_once(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        entered = threading.Event()
        release = threading.Event()
        calls = 0
        calls_lock = threading.Lock()

        def blocking_runner(command, *, timeout):
            nonlocal calls
            with calls_lock:
                calls += 1
            entered.set()
            assert release.wait(5)
            return {"status": "PASS", "command": command}

        first = start_pipeline_job(str(root), _plan(), runner=blocking_runner)
        assert first["started"] is True
        assert entered.wait(2)
        second = start_pipeline_job(str(root), _plan(), runner=blocking_runner)
        assert second["started"] is False
        assert second["job_id"] == first["job_id"]
        assert calls == 1

        release.set()
        terminal = _wait_terminal(root)
        assert terminal["status"] == "PASS"

    def test_running_progress_survives_repeated_reads(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        third_started = threading.Event()
        release = threading.Event()

        def runner(command, *, timeout):
            if command[-1] == "s3":
                third_started.set()
                assert release.wait(5)
            return {"status": "PASS"}

        started = start_pipeline_job(str(root), _plan(), runner=runner)
        assert started["started"] is True
        assert third_started.wait(2)

        first_read = get_pipeline_job(str(root))
        second_read = get_pipeline_job(str(root))
        assert first_read is not None and second_read is not None
        assert first_read["job_id"] == second_read["job_id"] == started["job_id"]
        assert first_read["status"] == "RUNNING"
        assert first_read["current_step"] == "s3"
        assert first_read["current_label"] == "特异性分析"
        assert first_read["progress_current"] == 2
        assert first_read["progress_total"] == 5

        release.set()
        _wait_terminal(root)

    def test_step_timings_persist_and_freeze(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        second_started = threading.Event()
        release = threading.Event()

        def runner(command, *, timeout):
            if command[-1] == "s2":
                second_started.set()
                assert release.wait(5)
            return {"status": "PASS"}

        start_pipeline_job(str(root), _plan(), runner=runner)
        assert second_started.wait(2)
        running = get_pipeline_job(str(root))
        assert running is not None
        assert running["step_started_at"]
        assert running["step_timings"]["s1"]["status"] == "PASS"
        assert running["step_timings"]["s1"]["finished_at"]
        assert running["step_timings"]["s1"]["elapsed_seconds"] >= 0
        assert running["step_timings"]["s2"]["status"] == "RUNNING"
        assert running["step_timings"]["s2"]["finished_at"] is None

        release.set()
        terminal = _wait_terminal(root)
        assert terminal["status"] == "PASS"
        assert list(terminal["step_timings"]) == ["s1", "s2", "s3", "s4", "s5"]
        assert all(
            timing["status"] == "PASS"
            and timing["finished_at"]
            and timing["elapsed_seconds"] >= 0
            for timing in terminal["step_timings"].values()
        )
        frozen = json.dumps(terminal["step_timings"], sort_keys=True)
        assert json.dumps(
            get_pipeline_job(str(root))["step_timings"], sort_keys=True
        ) == frozen

    def test_finished_job_can_be_submitted_again(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()

        def ok_runner(command, *, timeout):
            return {"status": "PASS"}

        first = start_pipeline_job(str(root), _plan(), runner=ok_runner)
        first_done = _wait_terminal(root)
        assert first_done["status"] == "PASS"

        second = start_pipeline_job(str(root), _plan(), runner=ok_runner)
        assert second["started"] is True
        assert second["job_id"] != first["job_id"]
        second_done = _wait_terminal(root)
        assert second_done["status"] == "PASS"

    def test_worker_exception_becomes_fail_and_releases_lock(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()

        def broken_runner(command, *, timeout):
            raise RuntimeError("worker exploded")

        started = start_pipeline_job(str(root), _plan(), runner=broken_runner)
        terminal = _wait_terminal(root)
        assert terminal["job_id"] == started["job_id"]
        assert terminal["status"] == "FAIL"
        assert "worker exploded" in terminal["error"]
        assert not (root / ".fullpcr_jobs" / "pipeline.lock").exists()

    @pytest.mark.parametrize("terminal_status", ["FAIL", "TIMEOUT"])
    def test_failed_or_timed_out_job_releases_lock(
        self, tmp_path, terminal_status
    ):
        root = tmp_path / "project"
        root.mkdir()

        def terminal_runner(command, *, timeout):
            return {"status": terminal_status}

        started = start_pipeline_job(str(root), _plan(), runner=terminal_runner)
        terminal = _wait_terminal(root)
        assert terminal["job_id"] == started["job_id"]
        assert terminal["status"] == terminal_status
        assert terminal["outcome"]["status"] == terminal_status
        assert not (root / ".fullpcr_jobs" / "pipeline.lock").exists()

    def test_stale_dead_owner_lock_is_recovered(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        job_dir = root / ".fullpcr_jobs"
        job_dir.mkdir()
        stale_job_id = "stale-job"
        (job_dir / "pipeline_state.json").write_text(
            json.dumps(
                {
                    "job_id": stale_job_id,
                    "status": "RUNNING",
                    "progress_current": 2,
                    "progress_total": 5,
                }
            ),
            encoding="utf-8",
        )
        (job_dir / "pipeline.lock").write_text(
            json.dumps({"job_id": stale_job_id, "owner_pid": 999_999_999}),
            encoding="utf-8",
        )

        def ok_runner(command, *, timeout):
            return {"status": "PASS"}

        restarted = start_pipeline_job(str(root), _plan(), runner=ok_runner)
        assert restarted["started"] is True
        assert restarted["job_id"] != stale_job_id
        assert _wait_terminal(root)["status"] == "PASS"

    def test_corrupt_state_blocks_once_then_allows_explicit_retry(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        job_dir = root / ".fullpcr_jobs"
        job_dir.mkdir()
        state_path = job_dir / "pipeline_state.json"
        state_path.write_text("{broken-json", encoding="utf-8")

        first = start_pipeline_job(str(root), _plan(), runner=lambda *_a, **_k: {})
        assert first["started"] is False
        assert first["status"] == "FAIL"
        assert first["state_error"] is True
        assert not state_path.exists()
        assert list(job_dir.glob("pipeline_state.json.corrupt-*"))

        def ok_runner(command, *, timeout):
            return {"status": "PASS"}

        second = start_pipeline_job(str(root), _plan(), runner=ok_runner)
        assert second["started"] is True
        assert _wait_terminal(root)["status"] == "PASS"

    def test_get_without_job_does_not_create_internal_directory(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        assert get_pipeline_job(str(root)) is None
        assert not (root / ".fullpcr_jobs").exists()

    def test_state_file_is_valid_json_and_no_temp_remains(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()

        def ok_runner(command, *, timeout):
            return {"status": "PASS"}

        start_pipeline_job(str(root), _plan(), runner=ok_runner)
        _wait_terminal(root)
        job_dir = root / ".fullpcr_jobs"
        state = json.loads((job_dir / "pipeline_state.json").read_text())
        assert state["status"] == "PASS"
        assert list(job_dir.glob(".pipeline-state-*")) == []


class TestPipelineJobTraceback:
    """Traceback is persisted on background exceptions."""

    def test_runner_exception_persists_traceback(self, tmp_path):
        """Runner raises: terminal state is FAIL with traceback field."""
        root = tmp_path / "project"
        root.mkdir()

        def failing_runner(command, *, timeout):
            raise RuntimeError("something broke")

        started = start_pipeline_job(str(root), _plan(), runner=failing_runner)
        assert started["started"] is True
        terminal = _wait_terminal(root)
        assert terminal["status"] == "FAIL"
        assert terminal["error"] != ""
        assert terminal["traceback"] != ""
        assert "RuntimeError" in terminal["traceback"]
        assert "something broke" in terminal["traceback"]
        assert "Traceback" in terminal["traceback"]

    def test_passed_steps_have_empty_traceback(self, tmp_path):
        """PASS result has empty traceback in final state."""
        root = tmp_path / "project"
        root.mkdir()

        def ok_runner(command, *, timeout):
            return {"status": "PASS"}

        started = start_pipeline_job(str(root), _plan(), runner=ok_runner)
        assert started["started"] is True
        terminal = _wait_terminal(root)
        assert terminal["status"] == "PASS"
        assert terminal["traceback"] == ""

    def test_legacy_state_without_traceback_still_readable(self, tmp_path):
        """Old state JSON without 'traceback' key can still be read."""
        root = tmp_path / "project"
        root.mkdir()
        job_dir = root / ".fullpcr_jobs"
        job_dir.mkdir()
        legacy_state = {
            "schema_version": 1,
            "job_id": "legacy-123",
            "status": "FAIL",
            "error": "old error",
        }
        (job_dir / "pipeline_state.json").write_text(
            json.dumps(legacy_state), encoding="utf-8"
        )
        got = get_pipeline_job(str(root))
        assert got is not None
        assert got["job_id"] == "legacy-123"
        assert got["status"] == "FAIL"
        # Missing traceback should NOT cause an error; treated as empty
        assert got.get("traceback", "") == ""
