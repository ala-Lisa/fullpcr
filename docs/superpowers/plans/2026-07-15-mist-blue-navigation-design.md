# Mist Blue Navigation and Header Implementation Plan

> **For agentic workers:** Execute inline in the current session. Do not delegate, commit, push, or modify Git history.

**Goal:** Restyle the fixed desktop navigation and page header with a deeper mist-blue translucent visual system while preserving all existing application behavior.

**Architecture:** Keep the existing three-page Streamlit radio navigation and header functions. Apply the redesign through the existing `_inject_brand_styles()` CSS and small presentational markup around the current sidebar content; remove only the requested report sentence.

**Tech Stack:** Python 3.10+, Streamlit 1.59.1, HTML/CSS embedded through `st.markdown`, pytest AppTest.

## Global Constraints

- Keep `initial_sidebar_state="locked"` and the exact three navigation values.
- Use only mist blue, navy, white, and the existing green brand accent.
- Use translucent surfaces; preserve readable contrast.
- Do not change analysis, state, file, download, or routing behavior.
- Do not commit or push.

---

### Task 1: Visual contract tests

**Files:**
- Modify: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: HTML/CSS emitted by `_inject_brand_styles()` and sidebar markup emitted by `gui_app.py`.
- Produces: regression assertions for mist-blue tokens, translucent navigation cards, the expanded header, and the removed report sentence.

- [ ] Add assertions that the page contains the new sidebar brand eyebrow and navigation descriptions.
- [ ] Assert the CSS contains the mist-blue background, `backdrop-filter`, active navigation rail, and expanded hero dimensions.
- [ ] Assert the old report sentence is absent after loading the Chinese report.
- [ ] Run the focused tests and confirm they fail before implementation.

### Task 2: Header and navigation presentation

**Files:**
- Modify: `fullpcr/gui_app.py`

**Interfaces:**
- Consumes: existing `BRAND_NAME`, `BRAND_LOGO_PATH`, `_render_header()`, and sidebar radio state.
- Produces: unchanged `page` string values with redesigned presentation.

- [ ] Extend `.brand-hero` with a wider translucent blue gradient, increased minimum height, and a stronger but restrained shadow.
- [ ] Replace the dark sidebar background with a deeper mist-blue gradient and translucent inset panels.
- [ ] Style each radio option as a glass navigation card with an active left rail and maintain the existing green selection indicator.
- [ ] Add compact brand and navigation guidance markup without changing radio labels or keys.
- [ ] Remove `并不是单独的 MFEprimer 报告` from the Chinese report introduction.

### Task 3: Verification and deployment

**Files:**
- Test: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: completed presentation changes.
- Produces: verified and restarted Streamlit service on port 18503.

- [ ] Run focused branding and report tests.
- [ ] Run `python3 -m compileall -q fullpcr` and `git diff --check`.
- [ ] Run `pytest -q` and require zero failures.
- [ ] Restart `fullpcr.service`, verify `active`, HTTP 200, and `/_stcore/health` returns `ok`.

### Task 4: Header and navigation proportion refinement

**Files:**
- Modify: `fullpcr/gui_app.py`
- Test: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: `_render_environment_popover()` and the existing sidebar radio.
- Produces: the same environment popover and page values in a corrected layout.

- [x] Move `_render_environment_popover()` from the header into the sidebar between the brand block and navigation heading.
- [x] Render `.brand-hero` without a Streamlit column split so it uses the full main-content width.
- [x] Force the radio group and all three labels to stretch to `width: 100%` with `box-sizing: border-box`.
- [x] Balance number, title, and description sizes at `0.68rem`, `0.90rem`, and `0.62rem` respectively.
- [x] Verify at 125% browser scale, run focused tests, then run the full suite.
