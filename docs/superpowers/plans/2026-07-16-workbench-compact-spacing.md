# Workbench Compact Spacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shorten the sidebar subtitle and reduce analysis-workbench vertical whitespace without changing controls, type sizes, or the other two pages.

**Architecture:** Wrap the existing workbench renderer in a keyed Streamlit container and scope all density CSS to its generated class. Keep the result and download pages outside that container, so their layout remains unchanged.

**Tech Stack:** Python 3.10+, Streamlit 1.59, CSS, pytest, Streamlit AppTest

## Global Constraints

- Sidebar subtitle must be exactly `全库引物评测平台`.
- Compact spacing applies only under `.st-key-analysis_workbench_compact`.
- Do not reduce font sizes, input heights, button sizes, or click targets.
- Do not change parameters, session state, commands, validation, results, or downloads.
- Do not commit, push, or modify Git history.

---

### Task 1: Add scoped workbench density styling

**Files:**
- Modify: `fullpcr/gui_app.py:187-325`
- Modify: `fullpcr/gui_app.py:1345-1377`
- Modify: `fullpcr/gui_app.py:3280-3290`
- Test: `tests/test_gui_helpers.py:2204-2290`

**Interfaces:**
- Consumes: `_render_analysis_workbench()` and the existing sidebar brand markup
- Produces: the same workbench controls inside `st.container(key="analysis_workbench_compact")`

- [x] **Step 1: Write failing branding and scoped-density tests**

Update the branding AppTest to require the shorter subtitle:

```python
assert "fullpcr 全库引物评测平台" not in shell_text
assert "全库引物评测平台" in shell_text
```

Add a source/style contract test:

```python
source = self._app_path().read_text(encoding="utf-8")
assert 'st.container(key="analysis_workbench_compact")' in source
assert ".st-key-analysis_workbench_compact" in source
assert ".st-key-analysis_workbench_compact h3" in source
assert ".st-key-analysis_workbench_compact hr" in source
```

- [x] **Step 2: Run focused tests and verify RED**

Run:

```bash
pytest -q tests/test_gui_helpers.py -k "CorporateBranding or AnalysisParameterPanel or NoviceWorkbenchLayout"
```

Expected: failures for the old sidebar subtitle and missing keyed workbench/CSS scope.

- [x] **Step 3: Implement the minimal scoped layout change**

Change the sidebar subtitle to:

```html
<p>全库引物评测平台</p>
```

Wrap the existing workbench body without changing its order or logic:

```python
with st.container(key="analysis_workbench_compact"):
    # existing workbench rendering, unchanged
```

Add only scoped spacing rules:

```css
.st-key-analysis_workbench_compact [data-testid="stVerticalBlock"] {
    gap: 0.72rem;
}

.st-key-analysis_workbench_compact h2,
.st-key-analysis_workbench_compact h3 {
    margin-top: 0.45rem;
    margin-bottom: 0.25rem;
}

.st-key-analysis_workbench_compact hr {
    margin: 0.55rem 0;
}

.st-key-analysis_workbench_compact .workflow-strip {
    margin: 0.55rem 0 0.9rem;
}
```

- [x] **Step 4: Run focused and complete verification**

Run:

```bash
pytest -q tests/test_gui_helpers.py -k "CorporateBranding or AnalysisParameterPanel or NoviceWorkbenchLayout"
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
