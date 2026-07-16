# Optional Analysis Parameters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the top analysis-parameter panel so basic values remain directly editable while seven advanced numeric overrides only appear and affect commands after users enable them.

**Architecture:** Add persisted enable flags beside the existing canonical parameter values. Render advanced numeric widgets conditionally and derive `common_params` from enable flags, preserving the existing command builders and the shared one-click/step-3 command path.

**Tech Stack:** Python 3.10+, Streamlit 1.59.1, pytest, Streamlit AppTest.

## Global Constraints

- Change only the top `分析参数` area; do not redesign the five-step manual workflow parameter panels.
- Preserve current default commands when every new enable flag is false.
- Applying a primer preset must not modify advanced enable flags or remembered advanced values.
- Do not change CLI parsers, command builders, core algorithms, dependencies, or Git history.

---

### Task 1: Persist optional-parameter enable state

**Files:**
- Modify: `fullpcr/gui_helpers.py:1283-1293`
- Test: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: `_CANONICAL_DEFAULTS`, `ensure_widget_key()`, and `sync_widgets_to_canonical()`.
- Produces: canonical booleans `wf_s3_use_tm`, `wf_s3_use_misstart`, `wf_s3_use_misend`, `wf_s3_use_mono`, `wf_s3_use_diva`, `wf_s3_use_dntp`, and `wf_s3_use_oligo`.

- [x] **Step 1: Add failing default-state assertions**

```python
for key in (
    "wf_s3_use_tm", "wf_s3_use_misstart", "wf_s3_use_misend",
    "wf_s3_use_mono", "wf_s3_use_diva", "wf_s3_use_dntp",
    "wf_s3_use_oligo",
):
    assert at.session_state[key] is False
```

- [x] **Step 2: Run the focused test and require a missing-key failure**

```bash
pytest -q tests/test_gui_helpers.py::TestSpecCustomParams::test_default_spec_params_are_none_or_false
```

- [x] **Step 3: Add the seven defaults**

```python
"wf_s3_use_tm": False,
"wf_s3_use_misstart": False,
"wf_s3_use_misend": False,
"wf_s3_use_mono": False,
"wf_s3_use_diva": False,
"wf_s3_use_dntp": False,
"wf_s3_use_oligo": False,
```

### Task 2: Implement checkbox-driven advanced inputs and semantic steps

**Files:**
- Modify: `fullpcr/gui_app.py:1365`
- Modify: `fullpcr/gui_app.py:2574-2730`
- Test: `tests/test_gui_helpers.py:5460-5830`

**Interfaces:**
- Consumes: the seven canonical enable flags from Task 1 and existing numeric value keys.
- Produces: `common_params` with `spec_tm=50.0` when disabled and `None` for the six optional CLI values when disabled.

- [x] **Step 1: Add failing layout and step tests**

```python
assert "分析参数（可选）" not in [e.label for e in at.expander]
assert "分析参数" in [e.label for e in at.expander]
assert "_wf_s3_misstart" not in [w.key for w in at.number_input]
assert at.number_input("_wf_s3_minsize").step == 10.0
assert at.number_input("_wf_s3_maxsize").step == 10.0
assert at.number_input("_wf_s3_mismatch").step == 1.0
```

- [x] **Step 2: Add a local conditional-number helper inside `_render_preset_controls()`**

```python
def optional_number(
    label: str,
    *,
    use_key: str,
    value_key: str,
    default: int | float,
    step: int | float,
    help_text: str,
    min_value: int | None = None,
    number_format: str | None = None,
) -> tuple[bool, int | float | None]:
    ensure_widget_key(st.session_state, use_key)
    enabled = st.checkbox(f"设置{label}", key=use_key, help=help_text)
    if not enabled:
        return False, None
    ensure_widget_key(st.session_state, value_key)
    if st.session_state.get(value_key) is None:
        st.session_state[value_key] = default
    kwargs = {"key": value_key, "step": step}
    if min_value is not None:
        kwargs["min_value"] = min_value
    if number_format is not None:
        kwargs["format"] = number_format
    return True, st.number_input(label, **kwargs)
```

- [x] **Step 3: Rename and regroup the panel**

```python
with st.expander("分析参数", expanded=True):
    st.caption("不修改时自动使用默认参数。")
    common_params = _render_preset_controls()
```

Within `_render_preset_controls()`, rename `常用分析参数` to `基础参数`, rename `Spec 特异性参数` to `高级参数`, and render the seven conditional controls in two columns. Keep `输出引物结合位点` and `从扩增序列中切除引物` as direct checkboxes under `输出选项`.

- [x] **Step 4: Apply exact numeric steps**

```python
minsize: step=10, format="%d"
maxsize: step=10, format="%d"
spec_mismatch: step=1, format="%d"
spec_tm: step=0.5, format="%.1f"
spec_mis_start: step=1, format="%d", min_value=1
spec_mis_end: step=1, format="%d", min_value=1
spec_mono: step=1.0, format="%.1f"
spec_diva: step=0.1, format="%.1f"
spec_dntp: step=0.05, format="%.2f"
spec_oligo: step=1.0, format="%.1f"
```

- [x] **Step 5: Derive command values from enable flags**

```python
"spec_tm": float(spec_tm_val) if use_tm and spec_tm_val is not None else 50.0,
"spec_mis_start": int(spec_mis_start) if use_mis_start and spec_mis_start is not None else None,
"spec_mis_end": int(spec_mis_end) if use_mis_end and spec_mis_end is not None else None,
"spec_mono": float(spec_mono) if use_mono and spec_mono is not None else None,
"spec_diva": float(spec_diva) if use_diva and spec_diva is not None else None,
"spec_dntp": float(spec_dntp) if use_dntp and spec_dntp is not None else None,
"spec_oligo": float(spec_oligo) if use_oligo and spec_oligo is not None else None,
```

### Task 3: Update state and command regression coverage

**Files:**
- Modify: `tests/test_gui_helpers.py:5460-5830`
- Test: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: conditional widgets and enable-state semantics from Tasks 1-2.
- Produces: regression evidence for visibility, round trips, presets, validation, disable behavior, and command parity.

- [x] **Step 1: Update existing custom-parameter tests to enable numeric controls before setting values**

```python
at.checkbox("_wf_s3_use_misstart").set_value(True).run()
at.number_input("_wf_s3_misstart").set_value(3).run()
```

Repeat for all seven numeric controls used by each test.

- [x] **Step 2: Add disable-restores-default-command coverage**

```python
at.checkbox("_wf_s3_use_mono").set_value(True).run()
at.number_input("_wf_s3_mono").set_value(75.0).run()
at.checkbox("_wf_s3_use_mono").set_value(False).run()
assert "_wf_s3_mono" not in [w.key for w in at.number_input]
```

Build the dry-run plan and assert `--mono` is absent while the remembered canonical value remains `75.0`.

- [x] **Step 3: Verify preset and page round trips include all enable flags**

Assert that applying a preset, switching pages, validating inputs, and toggling the advanced workflow preserve both each `wf_s3_use_*` boolean and its remembered numeric value.

- [x] **Step 4: Run focused tests**

```bash
pytest -q tests/test_gui_helpers.py -k "SpecCustomParams or NoviceWorkbenchLayout"
```

Expected: all selected tests pass.

### Task 4: Render and complete verification

**Files:**
- Verify: `fullpcr/gui_app.py`
- Verify: `fullpcr/gui_helpers.py`
- Verify: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: completed state, UI, and tests from Tasks 1-3.
- Produces: fresh functional, visual, and service evidence.

- [x] **Step 1: Verify at 125% browser scale**

Confirm that the panel title is `分析参数`, basic controls are aligned, advanced checkboxes render in two columns, and numeric fields only appear after selection.

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
