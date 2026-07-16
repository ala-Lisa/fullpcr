# Streamlit Shell Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the empty translucent Streamlit header and keep the locked desktop sidebar fully visible without its own scrollbar.

**Architecture:** Limit the change to the existing CSS injected by `_inject_brand_styles()`. Add AppTest-based style-contract regressions, then verify the rendered desktop page at 125% scale without changing navigation or application state.

**Tech Stack:** Python 3.10+, Streamlit 1.59.1, pytest, Streamlit AppTest, CSS.

## Global Constraints

- Preserve the existing brand card, environment popover, three navigation options, and internal platform footer.
- Do not change routing, analysis execution, result rendering, downloads, or session state.
- Keep `initial_sidebar_state="locked"`.
- Do not add dependencies, commit, push, or modify Git history.

---

### Task 1: Add shell layout regression contracts

**Files:**
- Modify: `tests/test_gui_helpers.py`
- Test: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: the CSS markup emitted by `_inject_brand_styles()` through `AppTest`.
- Produces: regression contracts for zero-height `stHeader` and non-scrolling `stSidebarContent`.

- [x] **Step 1: Add failing tests to `TestCorporateBranding`**

```python
def test_streamlit_header_has_no_visual_footprint(self):
    at = AppTest.from_file(str(self._app_path()))
    at.run(timeout=30)
    markup = "\n".join(str(item.value) for item in at.markdown)
    assert 'height: 0 !important' in markup
    assert 'min-height: 0 !important' in markup
    assert 'pointer-events: none' in markup

def test_sidebar_content_does_not_scroll(self):
    at = AppTest.from_file(str(self._app_path()))
    at.run(timeout=30)
    markup = "\n".join(str(item.value) for item in at.markdown)
    assert 'height: 100dvh' in markup
    assert 'overflow: hidden' in markup
    assert 'margin-top: auto' in markup
```

- [x] **Step 2: Run the new tests and require them to fail before implementation**

Run:

```bash
pytest -q \
  tests/test_gui_helpers.py::TestCorporateBranding::test_streamlit_header_has_no_visual_footprint \
  tests/test_gui_helpers.py::TestCorporateBranding::test_sidebar_content_does_not_scroll
```

Expected: two assertion failures because the existing header retains height and the sidebar retains automatic overflow.

### Task 2: Remove the header footprint and sidebar overflow

**Files:**
- Modify: `fullpcr/gui_app.py:173-176`
- Modify: `fullpcr/gui_app.py:336-490`
- Test: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: Streamlit shell selectors `[data-testid="stHeader"]` and `[data-testid="stSidebarContent"]`.
- Produces: the same application UI with no framework header footprint and no sidebar scrollbar.

- [x] **Step 1: Replace the translucent header rule with a zero-footprint rule**

```css
[data-testid="stHeader"] {
    height: 0 !important;
    min-height: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    backdrop-filter: none !important;
    pointer-events: none;
}
```

- [x] **Step 2: Make the sidebar a non-scrolling viewport layout**

```css
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    height: 100dvh;
    overflow: hidden;
    padding: 0.6rem 0.68rem 0.72rem;
}

.sidebar-brand-panel {
    margin-bottom: 0.75rem;
    padding: 0.78rem;
}

.sidebar-footer {
    margin-top: auto;
}
```

- [x] **Step 3: Add a short-height desktop media query**

```css
@media (max-height: 800px) and (min-width: 801px) {
    .sidebar-brand-panel { padding: 0.58rem 0.72rem; }
    section[data-testid="stSidebar"] [role="radiogroup"] > label {
        min-height: 62px;
        padding-top: 0.56rem !important;
        padding-bottom: 0.56rem !important;
    }
    .sidebar-footer { padding: 0.58rem 0.78rem; }
}
```

- [x] **Step 4: Run focused GUI tests**

Run:

```bash
pytest -q tests/test_gui_helpers.py -k "CorporateBranding"
```

Expected: all selected tests pass.

### Task 3: Render and regression verification

**Files:**
- Verify: `fullpcr/gui_app.py`
- Verify: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: completed CSS and tests from Tasks 1-2.
- Produces: fresh evidence that the layout and application remain functional.

- [x] **Step 1: Restart the service and capture the page at 125% scale**

Expected visual result: no translucent strip above the hero, no sidebar scrollbar, and all sidebar modules visible.

- [x] **Step 2: Run the full verification suite**

```bash
pytest -q
python3 -m compileall -q fullpcr
git diff --check
```

Expected: zero test failures, no compile errors, and no whitespace errors.

- [x] **Step 3: Verify the running service**

```bash
systemctl --user is-active fullpcr.service
curl -fsS http://127.0.0.1:18503/_stcore/health
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18503/
```

Expected: `active`, `ok`, and `200`.
