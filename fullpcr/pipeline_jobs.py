"""Project-scoped background execution for the Streamlit full pipeline."""

from __future__ import annotations

import copy
import json
import os
import stat
import tempfile
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fullpcr.gui_helpers import run_full_pipeline, run_gui_command


_REGISTRY_LOCK = threading.Lock()
_ACTIVE_THREADS: dict[str, threading.Thread] = {}
_ACTIVE_CANCEL_EVENTS: dict[str, tuple[str, threading.Event]] = {}
_JOB_DIR = ".fullpcr_jobs"
_LOCK_FILE = "pipeline.lock"
_STATE_FILE = "pipeline_state.json"
_HEALTH_CHECK_SECONDS = 600.0


ActivitySnapshot = tuple[int, int, int, int]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elapsed_seconds(started_at: object, finished_at: object) -> float:
    """Return a non-negative duration for two persisted ISO timestamps."""
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return 0.0
    try:
        started = datetime.fromisoformat(started_at)
        finished = datetime.fromisoformat(finished_at)
        if started.tzinfo is None or finished.tzinfo is None:
            return 0.0
    except ValueError:
        return 0.0
    return max(0.0, (finished - started).total_seconds())


def _process_group_cpu_ticks(process_group: int) -> int:
    """Return aggregate Linux CPU ticks for the given process group."""
    total = 0
    proc_root = Path("/proc")
    if process_group <= 0 or not proc_root.is_dir():
        return total
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            value = (entry / "stat").read_text(encoding="utf-8")
            tail = value[value.rindex(")") + 2 :].split()
            if int(tail[2]) != process_group:
                continue
            total += int(tail[11]) + int(tail[12])
        except (OSError, ValueError, IndexError):
            continue
    return total


def _output_tree_signature(root: Path) -> tuple[int, int, int]:
    """Return count, bytes and latest mtime for ordinary project outputs."""
    file_count = 0
    total_bytes = 0
    latest_mtime_ns = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if name != _JOB_DIR and not (current / name).is_symlink()
        ]
        for name in filenames:
            path = current / name
            if path.is_symlink():
                continue
            try:
                info = path.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            file_count += 1
            total_bytes += info.st_size
            latest_mtime_ns = max(latest_mtime_ns, info.st_mtime_ns)
    return file_count, total_bytes, latest_mtime_ns


def _activity_snapshot(root: Path, process_group: int) -> ActivitySnapshot:
    count, total_bytes, latest_mtime_ns = _output_tree_signature(root)
    return (
        _process_group_cpu_ticks(process_group),
        count,
        total_bytes,
        latest_mtime_ns,
    )


def _activity_changed(
    previous: ActivitySnapshot, current: ActivitySnapshot
) -> bool:
    """Return whether CPU or output-tree activity changed between samples."""
    return previous != current


def _normalise_project_root(project_root: str) -> Path:
    raw = Path(project_root)
    if raw.is_symlink():
        raise ValueError(f"项目根目录不能是符号链接: {raw}")
    try:
        root = raw.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"项目根目录不可用: {raw}: {exc}") from exc
    if not root.is_dir():
        raise ValueError(f"项目根路径不是目录: {root}")
    return root


def _job_paths(root: Path, *, create: bool = False) -> tuple[Path, Path, Path]:
    job_dir = root / _JOB_DIR
    if job_dir.is_symlink():
        raise ValueError(f"任务状态目录不能是符号链接: {job_dir}")
    if job_dir.exists() and not job_dir.is_dir():
        raise ValueError(f"任务状态路径不是目录: {job_dir}")
    if create:
        job_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
    return job_dir, job_dir / _LOCK_FILE, job_dir / _STATE_FILE


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root is not an object")
    return value


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    fd = -1
    tmp_path = ""
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=".pipeline-state-", suffix=".tmp", dir=str(path.parent)
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        tmp_path = ""
    finally:
        if fd >= 0:
            os.close(fd)
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _release_lock(lock_path: Path, job_id: str) -> None:
    try:
        lock = _read_json(lock_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return
    if lock.get("job_id") != job_id:
        return
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _unlink_lock(lock_path: Path) -> None:
    """Remove a lock already proven stale or invalid."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _lock_owner_active(root: Path, lock: dict[str, Any]) -> bool:
    """Return whether a lock still has a live owner.

    For this process, the registry is authoritative: a live server PID alone
    must not keep a lock forever after its worker thread has ended.  A lock
    owned by another live process is treated as active.
    """
    owner_pid = lock.get("owner_pid")
    if not _pid_alive(owner_pid):
        return False
    if owner_pid != os.getpid():
        return True
    worker = _ACTIVE_THREADS.get(str(root))
    return bool(worker is not None and worker.is_alive())


def _load_state(state_path: Path) -> dict[str, Any] | None:
    if not state_path.exists():
        return None
    try:
        return _read_json(state_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        corrupt_path = state_path.with_name(
            f"{state_path.name}.corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        try:
            os.replace(state_path, corrupt_path)
        except OSError:
            corrupt_path = state_path
        return {
            "schema_version": 1,
            "status": "FAIL",
            "state_error": True,
            "error": f"任务状态文件损坏: {exc}",
            "corrupt_path": str(corrupt_path),
        }


def _record_progress(root: Path, job_id: str, event: dict) -> None:
    _, _, state_path = _job_paths(root)
    with _REGISTRY_LOCK:
        state = _load_state(state_path)
        if state is None or state.get("job_id") != job_id:
            return
        timestamp = _now()
        index = int(event["index"])
        total = int(event["total"])
        phase = str(event["phase"])
        status = event.get("status")
        key = str(event["key"])
        completed = list(state.get("completed_steps", []))
        if phase == "finished" and status == "PASS":
            if key not in completed:
                completed.append(key)
        timings = dict(state.get("step_timings") or {})
        if phase == "running":
            state["step_started_at"] = timestamp
            timings[key] = {
                "started_at": timestamp,
                "finished_at": None,
                "elapsed_seconds": None,
                "status": "RUNNING",
            }
        elif phase == "finished":
            timing = dict(timings.get(key) or {})
            started_at = timing.get("started_at") or state.get("step_started_at")
            timing.update(
                {
                    "started_at": started_at,
                    "finished_at": timestamp,
                    "elapsed_seconds": _elapsed_seconds(started_at, timestamp),
                    "status": str(status or "FAIL"),
                }
            )
            timings[key] = timing
        state.update(
            {
                "current_step": key,
                "current_label": str(event["label"]),
                "phase": phase,
                "completed_steps": completed,
                "progress_current": index if status == "PASS" else index - 1,
                "progress_total": total,
                "step_timings": timings,
                "updated_at": timestamp,
            }
        )
        _atomic_write_json(state_path, state)


def _record_process_started(root: Path, job_id: str, process_group: int) -> None:
    """Persist a fresh health baseline for the command that just started."""
    _, _, state_path = _job_paths(root)
    timestamp = _now()
    with _REGISTRY_LOCK:
        state = _load_state(state_path)
        if state is None or state.get("job_id") != job_id:
            return
        state.update(
            {
                "current_process_group": process_group,
                "last_health_check_at": timestamp,
                "last_activity_at": timestamp,
                "suspected_stuck": False,
                "stuck_since": None,
                "updated_at": timestamp,
            }
        )
        _atomic_write_json(state_path, state)


def _record_health_check(
    root: Path,
    job_id: str,
    *,
    active: bool,
    suspected_stuck: bool,
) -> None:
    """Persist one ten-minute health decision without stopping the job."""
    _, _, state_path = _job_paths(root)
    timestamp = _now()
    with _REGISTRY_LOCK:
        state = _load_state(state_path)
        if state is None or state.get("job_id") != job_id:
            return
        state["last_health_check_at"] = timestamp
        if active:
            state["last_activity_at"] = timestamp
            state["suspected_stuck"] = False
            state["stuck_since"] = None
        elif suspected_stuck:
            state["suspected_stuck"] = True
            state["stuck_since"] = state.get("stuck_since") or timestamp
        state["updated_at"] = timestamp
        _atomic_write_json(state_path, state)


def request_pipeline_cancel(project_root: str, job_id: str) -> dict:
    """Request cancellation only for the matching in-process active job."""
    try:
        root = _normalise_project_root(project_root)
        _, _, state_path = _job_paths(root)
    except ValueError as exc:
        return {"cancelled": False, "status": "FAIL", "error": str(exc)}

    with _REGISTRY_LOCK:
        state = _load_state(state_path)
        if state is None or state.get("status") != "RUNNING":
            return {
                "cancelled": False,
                "status": "FAIL",
                "error": "当前项目没有正在运行的分析任务。",
            }
        if state.get("job_id") != job_id:
            return {
                "cancelled": False,
                "status": "FAIL",
                "error": "任务标识不匹配，未执行终止操作。",
            }
        registered = _ACTIVE_CANCEL_EVENTS.get(str(root))
        if registered is None or registered[0] != job_id:
            return {
                "cancelled": False,
                "status": "FAIL",
                "error": "无法确认任务归属，未执行终止操作。",
            }
        registered[1].set()
        timestamp = _now()
        state["cancel_requested_at"] = timestamp
        state["updated_at"] = timestamp
        _atomic_write_json(state_path, state)
        return {"cancelled": True, "status": "RUNNING", "job_id": job_id}


def _run_job(
    root: Path,
    job_id: str,
    plan: list[dict],
    runner: Callable | None,
    cancel_event: threading.Event,
) -> None:
    _, lock_path, state_path = _job_paths(root)
    terminal: dict[str, Any]
    previous_snapshot: ActivitySnapshot | None = None
    last_check = time.monotonic()
    last_activity = last_check

    def process_started(process_group: int) -> None:
        nonlocal previous_snapshot, last_check, last_activity
        now = time.monotonic()
        previous_snapshot = _activity_snapshot(root, process_group)
        last_check = now
        last_activity = now
        _record_process_started(root, job_id, process_group)

    def poll_health(process_group: int) -> None:
        nonlocal previous_snapshot, last_check, last_activity
        now = time.monotonic()
        if now - last_check < _HEALTH_CHECK_SECONDS:
            return
        current = _activity_snapshot(root, process_group)
        active = (
            previous_snapshot is None
            or _activity_changed(previous_snapshot, current)
        )
        if active:
            last_activity = now
        suspected = not active and now - last_activity >= _HEALTH_CHECK_SECONDS
        previous_snapshot = current
        last_check = now
        _record_health_check(
            root,
            job_id,
            active=active,
            suspected_stuck=suspected,
        )

    effective_runner = runner
    if effective_runner is None:
        def monitored_runner(command, *, timeout):
            return run_gui_command(
                command,
                timeout=None,
                cancel_requested=cancel_event.is_set,
                on_process_started=process_started,
                on_poll=poll_health,
            )

        effective_runner = monitored_runner
    try:
        outcome = run_full_pipeline(
            plan,
            runner=effective_runner,
            on_progress=lambda event: _record_progress(root, job_id, event),
        )
        terminal = {
            "status": str(outcome.get("status", "FAIL")),
            "outcome": outcome,
            "error": "",
        }
    except Exception as exc:
        terminal = {
            "status": "FAIL",
            "outcome": None,
            "error": f"后台分析任务异常: {exc}",
            "traceback": traceback.format_exc(),
        }
    finally:
        with _REGISTRY_LOCK:
            state = _load_state(state_path) or {}
            if state.get("job_id") == job_id:
                state.update(terminal)
                state["phase"] = "finished"
                state["finished_at"] = _now()
                state["updated_at"] = state["finished_at"]
                if terminal["status"] == "PASS":
                    state["progress_current"] = state.get("progress_total", 5)
                _atomic_write_json(state_path, state)
            _release_lock(lock_path, job_id)
            _ACTIVE_THREADS.pop(str(root), None)
            registered = _ACTIVE_CANCEL_EVENTS.get(str(root))
            if registered is not None and registered[0] == job_id:
                _ACTIVE_CANCEL_EVENTS.pop(str(root), None)


def get_pipeline_job(project_root: str) -> dict | None:
    """Return the persisted pipeline state for *project_root*."""
    try:
        root = _normalise_project_root(project_root)
        _, lock_path, state_path = _job_paths(root)
    except ValueError as exc:
        return {"status": "FAIL", "state_error": True, "error": str(exc)}

    state = _load_state(state_path)
    if state is None:
        return None
    if state.get("status") != "RUNNING":
        return copy.deepcopy(state)

    try:
        lock = _read_json(lock_path)
    except (OSError, ValueError, json.JSONDecodeError):
        lock = {}
    if (
        lock.get("job_id") == state.get("job_id")
        and _lock_owner_active(root, lock)
    ):
        return copy.deepcopy(state)

    with _REGISTRY_LOCK:
        current = _load_state(state_path) or state
        if current.get("status") == "RUNNING":
            current.update(
                {
                    "status": "FAIL",
                    "phase": "finished",
                    "error": "后台任务已中断，运行锁已失效。",
                    "finished_at": _now(),
                    "updated_at": _now(),
                }
            )
            _atomic_write_json(state_path, current)
        _unlink_lock(lock_path)
        return copy.deepcopy(current)


def start_pipeline_job(
    project_root: str,
    plan: list[dict],
    *,
    runner: Callable | None = None,
) -> dict:
    """Start one background pipeline for a project, or return the active one."""
    try:
        root = _normalise_project_root(project_root)
        _, lock_path, state_path = _job_paths(root, create=True)
    except ValueError as exc:
        return {
            "started": False,
            "status": "FAIL",
            "state_error": True,
            "error": str(exc),
        }

    with _REGISTRY_LOCK:
        current = _load_state(state_path)
        if current is not None and current.get("state_error"):
            answer = copy.deepcopy(current)
            answer["started"] = False
            return answer

        if current is not None and current.get("status") == "RUNNING":
            try:
                lock = _read_json(lock_path)
            except (OSError, ValueError, json.JSONDecodeError):
                lock = {}
            if (
                lock.get("job_id") == current.get("job_id")
                and _lock_owner_active(root, lock)
            ):
                answer = copy.deepcopy(current)
                answer["started"] = False
                return answer
            _unlink_lock(lock_path)

        # A lock can outlive its terminal state if the service or worker was
        # interrupted between the final state write and normal lock cleanup.
        # Do not remove a lock owned by another live process: it may be in the
        # brief interval between exclusive lock creation and state creation.
        if lock_path.exists():
            try:
                lock = _read_json(lock_path)
            except (OSError, ValueError, json.JSONDecodeError):
                try:
                    lock_age = max(
                        0.0,
                        datetime.now().timestamp() - lock_path.stat().st_mtime,
                    )
                except OSError:
                    lock_age = 0.0
                if lock_age < 2.0:
                    return {
                        "started": False,
                        "status": "RUNNING",
                        "error": "该项目的分析任务正在初始化，请稍后重试。",
                    }
                _unlink_lock(lock_path)
            else:
                same_terminal_job = bool(
                    current is not None
                    and current.get("status") != "RUNNING"
                    and lock.get("job_id") == current.get("job_id")
                )
                if same_terminal_job or not _lock_owner_active(root, lock):
                    _unlink_lock(lock_path)
                else:
                    return {
                        "started": False,
                        "status": "RUNNING",
                        "job_id": lock.get("job_id"),
                        "error": "该项目的分析已在运行。",
                    }

        job_id = uuid.uuid4().hex
        lock_value = {"job_id": job_id, "owner_pid": os.getpid()}
        try:
            fd = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            active = _load_state(state_path) or {
                "status": "RUNNING",
                "error": "该项目的分析已在运行。",
            }
            answer = copy.deepcopy(active)
            answer["started"] = False
            return answer
        except OSError as exc:
            return {
                "started": False,
                "status": "FAIL",
                "state_error": True,
                "error": f"无法创建任务运行锁: {exc}",
            }
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(lock_value, handle)
            handle.flush()
            os.fsync(handle.fileno())

        started_at = _now()
        state: dict[str, Any] = {
            "schema_version": 1,
            "job_id": job_id,
            "project_root": str(root),
            "status": "RUNNING",
            "current_step": None,
            "current_label": "准备开始五步分析",
            "phase": "starting",
            "completed_steps": [],
            "progress_current": 0,
            "progress_total": len(plan),
            "outcome": None,
            "error": "",
            "traceback": "",
            "started_at": started_at,
            "step_started_at": None,
            "step_timings": {},
            "last_health_check_at": None,
            "last_activity_at": None,
            "suspected_stuck": False,
            "stuck_since": None,
            "current_process_group": None,
            "updated_at": started_at,
            "finished_at": None,
            "owner_pid": os.getpid(),
        }
        try:
            _atomic_write_json(state_path, state)
            cancel_event = threading.Event()
            worker = threading.Thread(
                target=_run_job,
                args=(root, job_id, copy.deepcopy(plan), runner, cancel_event),
                name=f"fullpcr-pipeline-{job_id[:8]}",
                daemon=True,
            )
            _ACTIVE_THREADS[str(root)] = worker
            _ACTIVE_CANCEL_EVENTS[str(root)] = (job_id, cancel_event)
            worker.start()
        except Exception as exc:
            _ACTIVE_THREADS.pop(str(root), None)
            _ACTIVE_CANCEL_EVENTS.pop(str(root), None)
            _release_lock(lock_path, job_id)
            state.update(
                {
                    "status": "FAIL",
                    "phase": "finished",
                    "error": f"无法启动后台分析任务: {exc}",
                    "traceback": "",
                    "finished_at": _now(),
                    "updated_at": _now(),
                }
            )
            try:
                _atomic_write_json(state_path, state)
            except OSError:
                pass
            answer = copy.deepcopy(state)
            answer["started"] = False
            return answer

        answer = copy.deepcopy(state)
        answer["started"] = True
        return answer
