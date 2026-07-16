# Workbench Toggle Spacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the two redundant dividers around the advanced-parameter and advanced-workflow toggles so the existing compact workbench spacing can take effect.

**Architecture:** Delete one divider from the parameter renderer and one from the quick-analysis renderer. Preserve all controls, keys, state, and command behavior.

**Tech Stack:** Python 3.10+, Streamlit, pytest, Streamlit AppTest

## Global Constraints

- Remove only the two dividers named in the approved design.
- Keep the existing `0.72rem` workbench gap and all control dimensions.
- Do not change other pages, workflow dividers, parameters, state, or commands.
- Do not commit, push, or modify Git history.

---

### Task 1: Remove redundant toggle dividers

**Files:**
- Modify: `fullpcr/gui_app.py:991-996`
- Modify: `fullpcr/gui_app.py:2825-2832`
- Test: `tests/test_gui_helpers.py:2341-2410`

**Interfaces:**
- Consumes: `_render_analysis_parameter_controls()` and `_render_quick_analysis(common_params)`
- Produces: unchanged return values and widget behavior without the two visual separators

- [x] **Step 1: Add a failing source-contract test**

```python
source = self._app_path().read_text(encoding="utf-8")
quick_source = source.split("def _render_quick_analysis", 1)[1].split(
    "def _render_advanced_workflow_tabs", 1
)[0]
params_source = source.split("def _render_analysis_parameter_controls", 1)[1].split(
    "def _render_workflow_status_row", 1
)[0]
assert "st.divider()" not in quick_source
assert "st.divider()" not in params_source
```

- [x] **Step 2: Run the focused test and verify RED**

Run:

```bash
pytest -q tests/test_gui_helpers.py -k "AnalysisParameterPanel"
```

Expected: the new test fails because both function segments still contain `st.divider()`.

- [x] **Step 3: Delete exactly the two divider calls**

Remove the leading `st.divider()` from `_render_quick_analysis()` and the trailing `st.divider()` from `_render_analysis_parameter_controls()`. Make no other runtime changes.

- [x] **Step 4: Run focused and complete verification**

Run:

```bash
pytest -q tests/test_gui_helpers.py -k "AnalysisParameterPanel or NoviceWorkbenchLayout or QuickRecommendation or FullPipelineUi"
pytest -q tests/test_gui_helpers.py
pytest -q
python3 -m compileall -q fullpcr
git diff --check
```

Expected: all tests pass; compileall and diff check produce no errors.

- [x] **Step 5: Restart and smoke-test the service**

Run:

```bash
systemctl --user restart fullpcr.service
systemctl --user is-active fullpcr.service
curl -fsS --retry 15 --retry-connrefused --retry-delay 1 http://127.0.0.1:18503/_stcore/health
```

Expected: service is `active` and health response is `ok`.
