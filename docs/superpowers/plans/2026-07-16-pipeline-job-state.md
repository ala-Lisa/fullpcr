# Pipeline Job State Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current session. Repository rules prohibit commits unless the user separately authorizes them.

**Goal:** Prevent duplicate one-click analysis submissions, preserve truthful progress across Streamlit reruns, and terminate complete external-command process groups on timeout.

**Architecture:** A new `pipeline_jobs` module owns one daemon worker per project and persists atomic job state below `<project>/.fullpcr_jobs`. The Streamlit fragment reads that state every second and never owns execution. `run_gui_command` uses a new process session so timeout cleanup reaches wrapper commands and all descendants.

**Tech Stack:** Python 3.10+, standard-library threading/JSON/process signals, Streamlit fragments, pytest and Streamlit AppTest.

## Global Constraints

- A running project accepts exactly one complete-analysis submission.
- PASS, FAIL or TIMEOUT restores the ability to run again.
- Rerun, page navigation and ordinary widget interaction preserve `job_id`, completed-step count and current-step label.
- External timeout terminates the whole process group; no MFEprimer or obipcr descendant remains.
- Do not change analysis algorithms, command parameters, output formats or five-step order.
- Add no dependency and do not commit, push or modify Git history.
- Preserve all unrelated dirty-worktree changes.

---

### Task 1: Process-group-safe command execution

**Files:**
- Modify: `fullpcr/gui_helpers.py` (`run_gui_command`)
- Test: `tests/test_gui_helpers.py` (`TestRunGuiCommand`)

**Interfaces:**
- Consumes: `command: list[str]`, `timeout: int`.
- Produces: the existing result dictionary with `status`, `returncode`, `stdout`, `stderr`, `command`, and `message` unchanged.

- [ ] **Step 1: Add failing contract tests**

Add tests that mock `subprocess.Popen` and assert `start_new_session=True`, `shell=False`, text output capture, and existing PASS/FAIL/FileNotFoundError/OSError result shapes. Add a real Linux regression test that launches Python, which launches a long-lived child and writes the child PID to a temporary file; call `run_gui_command(..., timeout=1)` and assert both parent and child no longer exist after TIMEOUT.

The real child command must use argument lists, not a shell:

```python
parent_code = (
    "import pathlib, subprocess, sys, time; "
    "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
    "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); "
    "time.sleep(60)"
)
result = run_gui_command(
    [sys.executable, "-c", parent_code, str(pid_file)], timeout=1
)
assert result["status"] == "TIMEOUT"
```

- [ ] **Step 2: Run tests to prove the missing behavior**

Run:

```bash
pytest -q tests/test_gui_helpers.py -k "RunGuiCommand"
```

Expected before implementation: failures because `run_gui_command` uses `subprocess.run` and does not create/terminate a process group.

- [ ] **Step 3: Implement explicit process lifecycle**

Replace `subprocess.run` inside `run_gui_command` with:

```python
proc = subprocess.Popen(
    command,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    shell=False,
    start_new_session=True,
)
try:
    stdout, stderr = proc.communicate(timeout=timeout)
except subprocess.TimeoutExpired:
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        stdout, stderr = proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
    return the existing TIMEOUT result
```

Handle `ProcessLookupError` as “already exited”; always call `communicate()` to reap the wrapper. If group termination itself raises another `OSError`, record it in the timeout message without changing TIMEOUT to PASS.

- [ ] **Step 4: Re-run the Task 1 tests**

Run the same targeted command and require zero failures and no live test child PID.

---

### Task 2: Project-level background job manager

**Files:**
- Create: `fullpcr/pipeline_jobs.py`
- Create: `tests/test_pipeline_jobs.py`
- Modify: `fullpcr/gui_helpers.py` (`build_results_archive` exclusion)
- Test: `tests/test_gui_helpers.py` (`TestBuildResultsArchive`)

**Interfaces:**
- Consumes: canonical absolute project root and an existing five-step plan.
- Produces:

```python
def start_pipeline_job(
    project_root: str,
    plan: list[dict],
    *,
    runner: Callable | None = None,
) -> dict

def get_pipeline_job(project_root: str) -> dict | None
```

- [ ] **Step 1: Add failing task-manager tests**

Use `tmp_path` and runners controlled by `threading.Event` to test:

```python
first = start_pipeline_job(str(root), plan, runner=blocking_runner)
second = start_pipeline_job(str(root), plan, runner=blocking_runner)
assert first["started"] is True
assert second["started"] is False
assert second["job_id"] == first["job_id"]
assert runner_call_count == 1
```

Also test progress persistence (s3 running means `progress_current == 2` and `progress_total == 5`), stable reads, PASS/FAIL/TIMEOUT lock release, retry creating a new UUID, worker exception becoming FAIL, stale dead-owner lock recovery, corrupted JSON preservation, atomic temp cleanup, and separate projects running independently.

Add an archive test creating `.fullpcr_jobs/pipeline_state.json`, building a ZIP, and asserting no member starts with `.fullpcr_jobs/`.

- [ ] **Step 2: Run tests to prove APIs are absent**

```bash
pytest -q tests/test_pipeline_jobs.py tests/test_gui_helpers.py -k "PipelineJob or ResultsArchive"
```

Expected before implementation: import/API failures and archive-internal-file failure.

- [ ] **Step 3: Implement `pipeline_jobs.py`**

Use module globals:

```python
_REGISTRY_LOCK = threading.Lock()
_ACTIVE_THREADS: dict[str, threading.Thread] = {}
_JOB_DIR = ".fullpcr_jobs"
_LOCK_FILE = "pipeline.lock"
_STATE_FILE = "pipeline_state.json"
```

Normalize with `Path(project_root).resolve(strict=True)` and reject a non-directory root or symlinked `.fullpcr_jobs`. Acquire `pipeline.lock` using `os.open(..., os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)`. Write state through `tempfile.mkstemp` in the job directory, `os.fsync`, and `os.replace`.

The worker calls:

```python
outcome = run_full_pipeline(
    plan,
    runner=runner,
    on_progress=lambda event: _record_progress(root, job_id, event),
)
```

On each running event set `progress_current = index - 1`; on a PASS finished event set it to `index`. Terminal state stores the complete outcome. A `finally` block unlinks only the lock belonging to the same `job_id` and removes the thread from the registry.

`get_pipeline_job` must return a copy, never mutate a RUNNING record on ordinary reads, and recover only a lock whose recorded PID is no longer alive. Corrupt state is renamed with a `.corrupt-<timestamp>` suffix and returned as structured FAIL with `state_error=True`.

- [ ] **Step 4: Exclude internal job metadata from ZIP**

Extend the existing internal-directory exclusion set from `.fullpcr_downloads` to both `.fullpcr_downloads` and `.fullpcr_jobs`, without weakening symlink or special-file checks elsewhere.

- [ ] **Step 5: Run the Task 2 tests**

Require all task-manager and archive tests to pass and verify no `.tmp` job-state file remains.

---

### Task 3: Streamlit submission and stable progress UI

**Files:**
- Modify: `fullpcr/gui_app.py` (imports, quick-analysis job controls and status rendering)
- Test: `tests/test_gui_helpers.py` (`TestFullPipelineUi`)

**Interfaces:**
- Consumes: `project_output_root`, generated plan, `start_pipeline_job()` and `get_pipeline_job()`.
- Produces: disabled running button, stable progress, terminal outcome synchronization and unchanged dry-run behavior.

- [ ] **Step 1: Add failing AppTests**

Add tests with patched job APIs for:

- RUNNING renders button label “分析正在运行”, `disabled is True`, progress 40 for s3, and “正在进行：特异性分析”.
- A plain `at.run()` with the same job returns the same progress and job ID and never calls `start_pipeline_job`.
- A second submission while RUNNING cannot invoke `start_pipeline_job` again.
- Terminal PASS copies `outcome["results"]` into `wf_s1_result` through `wf_s5_result`, saves `full_pipeline_result`, and re-enables the run button.
- FAIL and TIMEOUT re-enable the run button and show the existing Chinese outcome.
- Dry-run creates only `full_pipeline_plan` and does not call the job manager.

- [ ] **Step 2: Run the tests to prove current UI is synchronous**

```bash
pytest -q tests/test_gui_helpers.py -k "FullPipelineUi"
```

Expected before implementation: new tests fail because the page calls `run_full_pipeline` synchronously and does not render persisted RUNNING state.

- [ ] **Step 3: Add job status rendering**

Create focused helpers in `gui_app.py`:

```python
def _sync_pipeline_job_outcome(job: dict) -> None
def _render_pipeline_job_progress(job: dict | None) -> None
```

For RUNNING, render `st.progress(progress_current / progress_total, text=...)` and an info message with `current_label`. For terminal states, synchronize the outcome once and call `_render_full_pipeline_outcome`.

- [ ] **Step 4: Move submission and polling into a fragment**

Use a fragment running every second:

```python
@st.fragment(run_every=1.0)
def _render_pipeline_job_controls(...):
    job = get_pipeline_job(project_root)
    running = bool(job and job.get("status") == "RUNNING")
    clicked = st.button(
        "分析正在运行" if running else "一键运行完整分析",
        disabled=base_disabled or running,
        key="full_pipeline_run_btn",
    )
```

On click, save `full_pipeline_plan`, clear only previous result/download state, call `start_pipeline_job`, and render the returned state. Do not call `run_full_pipeline` from the Streamlit script. The expander and dry-run path remain outside the background manager; dry-run retains the existing button key and behavior without creating a job directory.

- [ ] **Step 5: Run AppTests and adjacent state tests**

```bash
pytest -q tests/test_gui_helpers.py -k "FullPipelineUi or NoviceWorkbenchLayout or ResultDownloadsUi"
```

Require zero exceptions, stable widget keys and no changed result/download behavior.

---

### Task 4: Integrated regression and live UI verification

**Files:**
- Verify only; modify earlier files only if a failing requirement identifies a direct defect.

- [ ] **Step 1: Run focused suites**

```bash
pytest -q tests/test_pipeline_jobs.py tests/test_gui_helpers.py tests/test_cli.py
```

- [ ] **Step 2: Run all automated checks**

```bash
pytest -q
python3 -m compileall -q fullpcr
git diff --check
```

- [ ] **Step 3: Test the live Streamlit page**

Using the existing service on port 18503 and a temporary/lightweight test project, verify with headless Playwright:

1. Submit once and record the displayed job ID/state.
2. Interact with an expander or navigate away and back.
3. Confirm current step/progress did not reset and only one worker command exists.
4. Confirm the button remains disabled while RUNNING.
5. Confirm terminal state re-enables the button.

Do not run the user's expensive 18,000 bp MFEprimer analysis for this UI check.

- [ ] **Step 4: Verify timeout cleanup against the operating system**

Run the process-group regression again, then use `pgrep -af` with its unique test marker to confirm no parent or child remains. Confirm `curl -fsS http://127.0.0.1:18503/_stcore/health` still returns `ok` after restarting the service with the modified code.

- [ ] **Step 5: Review scope and working tree**

Inspect `git diff -- fullpcr/gui_helpers.py fullpcr/pipeline_jobs.py fullpcr/gui_app.py tests/test_pipeline_jobs.py tests/test_gui_helpers.py` and `git status --short`. Report unrelated pre-existing modifications separately; do not revert them.
