# Analysis Parameter Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the unused GUI path/preset shortcuts, make advanced parameters independently collapsible, and provide accurate application/flag help for every visible analysis parameter.

**Architecture:** Keep the existing command builders and canonical parameter state. Replace `_render_preset_controls()` with a focused analysis-parameter renderer, use a visibility-only toggle for the advanced controls, and derive command values from canonical state while that subsection is hidden.

**Tech Stack:** Python 3.10+, Streamlit 1.59.1, Streamlit AppTest, pytest.

## Global Constraints

- Modify only the analysis-parameter GUI and directly affected AppTests.
- Remove the path-sync button and primer-preset controls from the GUI, but retain backend helper APIs.
- Advanced visibility must not enable, disable, reset, or change command values.
- Preserve the five-step manual workflow, CLI parsers, command builders, algorithms, dependencies, and Git history.
- Do not commit, push, or overwrite unrelated dirty-worktree changes.

---

### Task 1: Define the simplified panel contract with failing AppTests

**Files:**
- Modify: `tests/test_gui_helpers.py:2360-2520`
- Modify: `tests/test_gui_helpers.py:5270-5310`
- Modify: `tests/test_gui_helpers.py:5470-5960`

**Interfaces:**
- Consumes: Streamlit widget keys `wf_sync_btn`, `_wf_preset_select`, `wf_apply_preset_btn`, `_show_advanced_parameters`, and existing `_wf_s3_*` parameter keys.
- Produces: regression assertions for removed shortcuts, conditional advanced visibility, help content, and hidden-state command preservation.

- [x] **Step 1: Replace GUI preset integration coverage with removal assertions**

Create an AppTest that asserts the analysis workbench contains none of these keys:

```python
assert "wf_sync_btn" not in [button.key for button in at.button]
assert "wf_apply_preset_btn" not in [button.key for button in at.button]
assert "_wf_preset_select" not in [selectbox.key for selectbox in at.selectbox]
```

Keep the pure `get_primer_preset()` and `apply_primer_preset_to_state()` tests unchanged because their backend APIs remain supported.

- [x] **Step 2: Add default-folded and expansion assertions**

```python
assert at.toggle("_show_advanced_parameters").value is False
assert "_wf_s3_use_tm" not in [checkbox.key for checkbox in at.checkbox]
at.toggle("_show_advanced_parameters").set_value(True).run()
assert "_wf_s3_use_tm" in [checkbox.key for checkbox in at.checkbox]
assert "_wf_s3_bind" in [checkbox.key for checkbox in at.checkbox]
assert "_wf_s3_cutprimer" in [checkbox.key for checkbox in at.checkbox]
```

- [x] **Step 3: Add help-contract assertions**

Check every basic control and every advanced control after expansion. Each help string must include its owning application/module and real flag, for example:

```python
assert "MFEprimer spec" in at.number_input("_wf_s3_minsize").help
assert "-s" in at.number_input("_wf_s3_minsize").help
assert "obipcr" in at.text_input("_wf_s4_mismatches").help
assert "--mismatches" in at.text_input("_wf_s4_mismatches").help
assert "MFEprimer spec" in at.checkbox("_wf_s3_use_tm").help
assert "-t" in at.checkbox("_wf_s3_use_tm").help
assert "--cutprimer" in at.checkbox("_wf_s3_cutprimer").help
```

- [x] **Step 4: Run the focused tests and require failure**

```bash
pytest -q tests/test_gui_helpers.py -k "AnalysisParameterPanel or SpecCustomParams or NoviceWorkbenchLayout"
```

Expected: failures because the old shortcuts still render, `_show_advanced_parameters` does not exist, and basic help is incomplete.

### Task 2: Implement the simplified parameter renderer

**Files:**
- Modify: `fullpcr/gui_app.py:15-45`
- Modify: `fullpcr/gui_app.py:1362-1370`
- Modify: `fullpcr/gui_app.py:2575-2835`

**Interfaces:**
- Consumes: existing canonical keys `wf_s3_use_*`, `wf_s3_*`, `wf_s4_mismatches`, and `wf_s4_circular`.
- Produces: `_render_analysis_parameter_controls() -> dict[str, object]` with the same `common_params` keys consumed by one-click analysis and step 3/4 command construction.

- [x] **Step 1: Remove GUI-only preset imports and rename the renderer**

Remove `get_primer_preset` and `apply_primer_preset_to_state` imports from `gui_app.py` only. Rename `_render_preset_controls()` to `_render_analysis_parameter_controls()` and update its call and comments.

- [x] **Step 2: Delete the shortcut row**

Delete the `sync_col`, `preset_col`, and `apply_col` widget block. Do not delete the backend helper functions from `gui_helpers.py`.

- [x] **Step 3: Add complete basic help text**

Add `help=` strings to all five basic controls using these exact identifiers:

```text
MFEprimer spec · -s
MFEprimer spec · -S
MFEprimer spec · --misMatch
fullpcr run / obipcr · --mismatches
fullpcr run / obipcr · --circular
```

Each string must also state what the value controls and its current default behavior.

- [x] **Step 4: Make advanced controls independently collapsible**

Render:

```python
show_advanced = st.toggle(
    "显示高级参数",
    key="_show_advanced_parameters",
    help="仅控制高级参数的显示与隐藏，不会改变已经启用的参数。",
)
```

Render the seven conditional numeric controls plus `bind` and `cutprimer` only when `show_advanced` is true. Update each help string with `MFEprimer spec`, the real MFEprimer flag, purpose, unit, and default behavior.

- [x] **Step 5: Preserve advanced command state while hidden**

When the subsection is hidden, derive `use_tm`, `use_mis_start`, `use_mis_end`, `use_mono`, `use_diva`, `use_dntp`, `use_oligo`, `spec_bind`, and `spec_cut_primer` from canonical session-state keys instead of resetting them. Read remembered numeric values from their canonical keys. Keep the returned `common_params` schema unchanged.

- [x] **Step 6: Run the focused tests**

```bash
pytest -q tests/test_gui_helpers.py -k "AnalysisParameterPanel or SpecCustomParams or NoviceWorkbenchLayout"
```

Expected: all selected tests pass.

### Task 3: Update affected workflow AppTests without weakening behavior

**Files:**
- Modify: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: the new visibility toggle and direct base-parameter widgets.
- Produces: existing workflow, validation, path preservation, page round-trip, and command parity coverage without references to removed widgets.

- [x] **Step 1: Remove only obsolete UI interactions**

Delete AppTest actions that select `_wf_preset_select` or click `wf_apply_preset_btn`/`wf_sync_btn`. Where a broader test needs non-default base values, set `_wf_s3_minsize`, `_wf_s3_maxsize`, `_wf_s3_mismatch`, `_wf_s4_mismatches`, and `_wf_s4_circular` directly.

- [x] **Step 2: Expand advanced controls before interacting with them**

Update the shared optional-number test helper to enable `_show_advanced_parameters` before accessing `_wf_s3_use_*`. Tests that set `bind` or `cutprimer` must do the same.

- [x] **Step 3: Add collapse-preserves-command regression coverage**

Enable a numeric override and `bind`, collapse `_show_advanced_parameters`, generate the dry-run plan, and assert the step-3 command still contains the custom numeric flag and `--bind`. Re-expand and assert the UI values return unchanged.

- [x] **Step 4: Run GUI tests**

```bash
pytest -q tests/test_gui_helpers.py
```

Expected: zero failures.

### Task 4: Visual and full verification

**Files:**
- Verify: `fullpcr/gui_app.py`
- Verify: `fullpcr/gui_helpers.py`
- Verify: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: completed GUI and tests.
- Produces: fresh completion evidence.

- [x] **Step 1: Verify at 125% browser scale**

Confirm the shortcut row is gone, basic parameters remain aligned, advanced parameters are hidden by default, expansion reveals all nine advanced controls, and help icons do not break the layout.

- [x] **Step 2: Run complete checks**

```bash
pytest -q
python3 -m compileall -q fullpcr
git diff --check
```

Expected: zero failures and zero check errors.

- [x] **Step 3: Restart and verify the service**

```bash
systemctl --user restart fullpcr.service
systemctl --user is-active fullpcr.service
curl -fsS http://127.0.0.1:18503/_stcore/health
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18503/
```

Expected: `active`, `ok`, and `200`.
