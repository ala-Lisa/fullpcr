# Analysis Parameters Always Visible Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the outer analysis-parameter expander so the base controls are always visible while retaining the independent advanced-parameter toggle.

**Architecture:** Change only the analysis-workbench layout wrapper around `_render_analysis_parameter_controls()`. Preserve the parameter renderer, widget keys, session state, and command construction exactly as they are.

**Tech Stack:** Python 3.10+, Streamlit, pytest, Streamlit AppTest

## Global Constraints

- Do not change parameter defaults, widget keys, help text, or command semantics.
- Keep advanced parameters hidden by default behind `_show_advanced_parameters`.
- Do not commit, push, or modify Git history.

---

### Task 1: Render analysis parameters without an outer expander

**Files:**
- Modify: `fullpcr/gui_app.py:1363-1367`
- Test: `tests/test_gui_helpers.py:2341-2404`
- Test: `tests/test_gui_helpers.py:5135-5180`
- Test: `tests/test_gui_helpers.py:5395-5415`

**Interfaces:**
- Consumes: `_render_analysis_parameter_controls() -> dict[str, object]`
- Produces: the unchanged `common_params` mapping used by the advanced workflow and quick-analysis pipeline

- [x] **Step 1: Write failing AppTest assertions**

Add assertions that no expander has label `分析参数`, that the base widgets are visible, and that `_show_advanced_parameters` remains false by default:

```python
expander_labels = [item.label for item in at.expander]
assert "分析参数" not in expander_labels
assert at.number_input("_wf_s3_minsize").value == 80
assert at.number_input("_wf_s3_maxsize").value == 500
assert at.number_input("_wf_s3_mismatch").value == 2
assert at.toggle("_show_advanced_parameters").value is False
```

Update obsolete assertions that previously required the `分析参数` expander; keep all assertions about the independent advanced toggle and execution-settings expander.

- [x] **Step 2: Run the focused test and verify RED**

Run:

```bash
pytest -q tests/test_gui_helpers.py -k "AnalysisParameterPanel or NoviceWorkbenchLayout or parameter_panel_uses_conditional"
```

Expected: at least one failure because `gui_app.py` still renders `st.expander("分析参数", expanded=True)`.

- [x] **Step 3: Implement the minimal layout change**

Replace the outer expander in `_render_analysis_workbench()` with direct rendering:

```python
st.markdown("### 分析参数")
st.caption("不修改时自动使用默认参数。")
common_params = _render_analysis_parameter_controls()
```

Do not change `_render_analysis_parameter_controls()`.

- [x] **Step 4: Run focused and complete verification**

Run:

```bash
pytest -q tests/test_gui_helpers.py -k "AnalysisParameterPanel or NoviceWorkbenchLayout or parameter_panel_uses_conditional"
pytest -q tests/test_gui_helpers.py
pytest -q
python3 -m compileall -q fullpcr
git diff --check
```

Expected: all tests pass; compileall and diff check produce no errors.

- [x] **Step 5: Restart and smoke-test the local service**

Run:

```bash
systemctl --user restart fullpcr.service
systemctl --user is-active fullpcr.service
curl -fsS http://127.0.0.1:18503/_stcore/health
```

Expected: service is `active` and health response is `ok`.
