# Pipeline Unlimited Runtime Monitoring Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with a review gate after each task. This repository does not authorize commits, subagents, or changes outside the listed files.

**Goal:** Run all five analysis steps without automatic time limits, persist total and per-step durations, detect ten minutes of CPU/output inactivity, and let the user terminate only a suspected-stuck task.

**Architecture:** Keep `pipeline_jobs.py` as the project-scoped state owner. Extend `run_gui_command()` with cancellation and observation callbacks while preserving process-group cleanup. The worker records timings and conservative activity snapshots; the Streamlit fragment only derives display durations from persisted timestamps and requests cancellation by `job_id`.

**Tech Stack:** Python 3.10+, `subprocess`, Linux `/proc`, `threading.Event`, Streamlit fragments, pytest, Streamlit AppTest.

## Global Constraints

- All five plan timeouts are `None`; no GUI-generated command contains `--timeout`.
- Health is sampled every 600 seconds and never stops a task automatically.
- A task is suspected stuck only when both process-group CPU ticks and output-tree signature are unchanged for 600 seconds.
- The terminate button appears only for `suspected_stuck=true`.
- Cancellation validates the active `job_id`, terminates the complete process group, records `CANCELLED`, and releases the project lock.
- Preserve existing input/output behavior, algorithm parameters, duplicate-submit protection, and old task-state compatibility.
- Do not commit, push, add dependencies, or modify unrelated dirty-worktree files.

---

### Task 1: Remove automatic timeouts without weakening explicit cleanup

**Files:**
- Modify: `fullpcr/gui_helpers.py`
- Modify: `fullpcr/gui_app.py`
- Test: `tests/test_gui_helpers.py`

**Interfaces:**
- `run_gui_command(command: list[str], timeout: int | float | None = None, ...) -> dict`
- `build_full_pipeline_plan(..., *_timeout: int | float | None = None) -> list[dict]`
- All builder `timeout` defaults become `None`; explicit finite timeout tests remain valid.

- [ ] **Step 1: Add failing tests for unlimited defaults**

Assert that the three GUI command builders omit `--timeout` by default, the five-step plan contains `[None, None, None, None, None]`, and `run_gui_command([python, -c, "print('ok')"], timeout=None)` returns `PASS`.

- [ ] **Step 2: Run focused tests and confirm the old defaults fail**

Run: `pytest -q tests/test_gui_helpers.py -k "BuildFullPipelinePlan or RunGuiCommand or timeout"`

- [ ] **Step 3: Implement unlimited defaults**

Change builder defaults and the five plan timeout annotations to optional values. In `_build_pipeline_plan_from_state()`, stop reading `_wf_s1_timeout`, `_wf_s3_timeout`, and `_wf_s4_timeout`; pass `timeout=None` to step command builders and all five plan entries. Remove the three advanced timeout widgets and explicit per-step timeout arguments. Remove the unused canonical timeout defaults while leaving old session keys harmless.

- [ ] **Step 4: Re-run focused tests**

Run: `pytest -q tests/test_gui_helpers.py -k "BuildFullPipelinePlan or RunGuiCommand or timeout"`

Expected: all selected tests pass; explicit finite timeout and descendant cleanup tests still pass.

---

### Task 2: Persist total and per-step timing

**Files:**
- Modify: `fullpcr/pipeline_jobs.py`
- Test: `tests/test_pipeline_jobs.py`

**Interfaces:**
- State adds `step_started_at: str | None`.
- State adds `step_timings: dict[str, {started_at, finished_at, elapsed_seconds, status}]`.
- `_record_progress()` freezes each completed/failed/cancelled step duration.

- [ ] **Step 1: Add failing state-timing tests**

Use a monkeypatched `_now()` sequence to verify that `running` creates the step entry, `finished` freezes `elapsed_seconds`, the next step gets a new start time, and terminal `finished_at` freezes total duration inputs.

- [ ] **Step 2: Run the timing tests and confirm failure**

Run: `pytest -q tests/test_pipeline_jobs.py -k "timing or progress"`

- [ ] **Step 3: Implement timing persistence**

Add strict ISO-8601 parsing with safe fallback. Initialize `step_started_at=None` and `step_timings={}` in `start_pipeline_job()`. On a `running` event, store the current timestamp and a fresh timing record. On `finished`, store status, finish timestamp, and non-negative elapsed seconds. Do not rewrite a frozen terminal duration during later reads.

- [ ] **Step 4: Re-run job-manager tests**

Run: `pytest -q tests/test_pipeline_jobs.py`

Expected: all job-manager tests pass, including duplicate submission and stale-lock recovery.

---

### Task 3: Add process activity observation and safe cancellation

**Files:**
- Modify: `fullpcr/gui_helpers.py`
- Modify: `fullpcr/pipeline_jobs.py`
- Test: `tests/test_gui_helpers.py`
- Test: `tests/test_pipeline_jobs.py`

**Interfaces:**
- `run_gui_command(..., cancel_requested: Callable[[], bool] | None = None, on_process_started: Callable[[int], None] | None = None, on_poll: Callable[[int], None] | None = None) -> dict`
- `request_pipeline_cancel(project_root: str, job_id: str) -> dict`
- Command cancellation result uses `status="CANCELLED"`.
- Health state adds `last_health_check_at`, `last_activity_at`, `suspected_stuck`, `stuck_since`, and `current_process_group`.

- [ ] **Step 1: Add failing callback and cancellation tests**

Cover process-start callback, periodic poll callback, a cancellation event that terminates a spawned child process group, and a `CANCELLED` result distinct from `FAIL` and `TIMEOUT`.

- [ ] **Step 2: Add failing activity-classification tests**

Test pure snapshots for CPU increase, output mtime/size change, no change before 600 seconds, and no change at 600 seconds. Test that `.fullpcr_jobs`, symlinks, and special files are ignored.

- [ ] **Step 3: Add failing job cancellation tests**

Start a real one-step sleeping command with test intervals shortened by monkeypatch. Wait until `suspected_stuck=true`, reject a wrong `job_id`, accept the current `job_id`, assert terminal `CANCELLED`, no child remains, the lock is removed, and no later plan step executes.

- [ ] **Step 4: Implement observable command execution**

Refactor the existing process-group termination sequence into one private helper shared by finite timeout and user cancellation. When observation callbacks are present, call `communicate()` in short bounded polls; check cancellation every poll and invoke the health callback without treating a poll timeout as a command timeout. Keep the existing direct `communicate(timeout=None)` path for unobserved commands.

- [ ] **Step 5: Implement conservative Linux activity snapshots**

Aggregate `utime + stime` for every `/proc/<pid>/stat` entry whose process group matches the current command. Build an output signature from ordinary non-symlink files under the project root while excluding `.fullpcr_jobs`. If either CPU ticks or output signature changes, record activity and clear suspicion. If neither changes for 600 seconds, persist suspicion without killing anything.

- [ ] **Step 6: Implement job-bound cancellation registry**

Register one `threading.Event` per active project and `job_id`. `request_pipeline_cancel()` must validate the normalized project root, current state, active registry entry, and exact `job_id` before setting the event. Clean the event and health runtime in the worker `finally` block.

- [ ] **Step 7: Teach the pipeline about `CANCELLED`**

Update `run_full_pipeline()` to stop after a cancelled step, retain the cancelled result, return overall `CANCELLED`, and use the message `分析已由用户终止。`.

- [ ] **Step 8: Run focused backend tests**

Run: `pytest -q tests/test_pipeline_jobs.py tests/test_gui_helpers.py -k "cancel or stuck or activity or RunGuiCommand or FullPipeline"`

Expected: callback, process cleanup, health detection, cancellation, and existing failure/timeout behavior all pass.

---

### Task 4: Render durable timings, stuck warning, and terminate action

**Files:**
- Modify: `fullpcr/gui_app.py`
- Test: `tests/test_gui_helpers.py`

**Interfaces:**
- `_format_pipeline_duration(seconds: float) -> str` produces `MM:SS` below one hour and `HH:MM:SS` at or above one hour.
- `_render_pipeline_job_progress()` uses persisted timestamps and `step_timings` only; it never mutates job state.
- UI calls `request_pipeline_cancel(project_root, job_id)` only when the current job is suspected stuck.

- [ ] **Step 1: Add failing AppTests**

Inject stable running state and assert progress text contains total and current-step durations, five compact step statuses are visible, plain rerun does not reset the values, and legacy state without timing fields renders safely. Inject suspected-stuck state and assert the Chinese warning and terminate button appear; assert the button is absent for active state.

- [ ] **Step 2: Add failing terminal rendering tests**

Cover frozen PASS duration and `CANCELLED` Chinese outcome text. Confirm legacy `TIMEOUT` results still render.

- [ ] **Step 3: Implement formatting and progress rendering**

Parse timezone-aware persisted timestamps defensively. Display `已完成 N/5 步 · 当前步骤 · 总用时 ... · 本步 ...` and one compact caption/list for all five steps. For malformed or absent old fields, omit only the unavailable duration.

- [ ] **Step 4: Implement warning and terminate button**

When `suspected_stuck` is true, show the last activity/check times and a `终止当前分析` button. On success, show a cancellation-requested message and let the fragment poll the terminal result. On registry or `job_id` failure, show the returned structured error and do not kill a process.

- [ ] **Step 5: Run UI-focused tests**

Run: `pytest -q tests/test_gui_helpers.py -k "FullPipelineUi or PipelineJob or duration or stuck or cancel"`

Expected: timing display, rerun persistence, warning, cancellation action, and existing one-click behavior pass.

---

### Task 5: Regression verification and live-service handoff

**Files:**
- No additional source files.

- [ ] **Step 1: Run relevant suites**

Run: `pytest -q tests/test_pipeline_jobs.py tests/test_gui_helpers.py`

- [ ] **Step 2: Run full verification**

Run: `pytest -q`

Run: `python3 -m compileall -q fullpcr`

Run: `git diff --check`

- [ ] **Step 3: Review scope**

Run: `git diff -- fullpcr/gui_helpers.py fullpcr/pipeline_jobs.py fullpcr/gui_app.py tests/test_pipeline_jobs.py tests/test_gui_helpers.py docs/superpowers/specs/2026-07-16-pipeline-timing-and-timeouts-design.md docs/superpowers/plans/2026-07-16-pipeline-unlimited-runtime-monitoring.md`

Verify no unrelated user changes were overwritten and no test was deleted or weakened merely to pass.

- [ ] **Step 4: Restart and smoke-test only after all tests pass**

Restart the existing user service, verify `http://127.0.0.1:18503/_stcore/health`, and inspect the service journal. Do not submit a real long analysis automatically; leave that action to the user.
