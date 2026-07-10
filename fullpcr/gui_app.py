"""fullpcr Streamlit GUI — Phase 7A: IA restructure + env popover + tabs.

Launch with::

    streamlit run fullpcr/gui_app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from fullpcr.gui_helpers import (
    _WORKFLOW_PATH_MAP,
    apply_primer_preset_to_state,
    apply_project_paths_to_state,
    build_final_report_command,
    build_obipcr_run_command,
    build_qc_pre_command,
    build_qc_spec_command,
    build_qc_summary_command,
    check_command_available,
    collect_environment_status,
    compute_inputs_validated,
    derive_project_paths,
    ensure_widget_key,
    get_fullpcr_info,
    get_primer_preset,
    get_python_info,
    init_canonical_defaults,
    load_markdown_file,
    load_primer_rank,
    load_tsv_file,
    run_gui_command,
    should_refresh_environment_status,
    summarize_primer_rank,
    summarize_status_counts,
    sync_widgets_to_canonical,
    translate_recommendation,
    translate_status,
    translate_warning_label,
    validate_database_file,
    validate_file_exists,
    validate_output_directory,
    validate_primers_file,
    validate_taxonomy_file,
)


# ═══════════════════════════════════════════════════════════════════════════
# Render helpers
# ═══════════════════════════════════════════════════════════════════════════


def _render_file_validation(
    label: str,
    result: dict,
    *,
    show_preview: bool = False,
    preview_caption: str = "",
) -> None:
    """Render a PASS / FAIL / WARN card for a validated input file.

    Args:
        label: Human-readable label for the file.
        result: Dict returned by a ``validate_*`` function.
        show_preview: If True and ``result["preview"]`` is non-empty,
            render a ``st.dataframe`` preview.
        preview_caption: Caption shown above the preview table.
    """
    path = result.get("path", "")
    status = result.get("status", "FAIL")
    status_cn = translate_status(status)

    if not path:
        st.info(f"**{label}** — 未提供")
        return

    if status == "PASS":
        st.success(f"✓ **{label}** — {status_cn} — `{path}`")
    elif status == "WARN":
        st.warning(f"⚠ **{label}** — {status_cn} — `{path}`")
    else:
        st.error(f"✗ **{label}** — {status_cn} — `{path}`")

    error = result.get("error")
    if error:
        st.caption(f"错误: {error}")

    if show_preview and result.get("preview"):
        st.caption(preview_caption)
        preview_rows = result["preview"]
        if preview_rows:
            st.dataframe(
                preview_rows[1:],  # data rows
                column_config=None,
                use_container_width=True,
                hide_index=True,
            )
            # Show column names separately since we passed data rows without header
            st.caption(f"字段: {', '.join(preview_rows[0])}")


# ── header ─────────────────────────────────────────────────────────────────


def _render_header() -> None:
    """Two-column top bar: project info (left) + environment popover (right)."""
    col_left, col_right = st.columns([3, 1])

    with col_left:
        st.markdown("## 🧬 fullpcr 全库引物评测平台")
        st.caption("基于 OBITools4 obipcr 和 MFEprimer 的全库引物评测工具")

        # Current project indicator
        project_root = (
            st.session_state.get("project_output_root")
            or st.session_state.get("inputs_output_dir")
            or ""
        )
        if project_root:
            st.caption(f"📁 当前项目: `{project_root}`")
        else:
            st.caption("📁 当前项目: 未设置")

    with col_right:
        _render_environment_popover()


# ── environment popover ──────────────────────────────────────────────────────


def _render_environment_popover() -> None:
    """Cached environment status displayed in a ``st.popover``.

    Reads/updates ``environment_status`` and ``environment_checked_at``
    in ``st.session_state``.  External commands are only re-run when the
    60-second TTL has expired or the user clicks 重新检查环境.
    """
    import time

    now = time.time()
    checked_at: float | None = st.session_state.get("environment_checked_at")
    status: dict | None = st.session_state.get("environment_status")

    # Determine if a refresh is needed.
    force_refresh = st.session_state.pop("_env_force_refresh", False)
    needs_refresh = force_refresh or should_refresh_environment_status(checked_at, now)

    if needs_refresh or status is None:
        status = collect_environment_status()
        st.session_state["environment_status"] = status
        st.session_state["environment_checked_at"] = status["checked_at"]

    ok_count: int = status["ok_count"]
    fail_count: int = status["fail_count"]

    # Popover trigger label.
    if fail_count == 0:
        trigger_label = "🟢 环境正常"
    else:
        trigger_label = f"🔴 环境异常 ({fail_count})"

    with st.popover(trigger_label, width="stretch"):
        st.markdown("### 环境检查")

        # Summary metrics
        c1, c2 = st.columns(2)
        with c1:
            st.metric("正常", ok_count)
        with c2:
            st.metric("异常", fail_count)

        if fail_count == 0:
            st.success("✅ 满足完整运行条件")
        else:
            st.warning("⚠ 部分功能不可用")

        st.divider()

        # Python
        py_info: dict = status["python"]
        st.markdown("**Python**")
        st.caption(f"可执行文件: `{py_info['executable']}`")
        with st.expander("版本详情"):
            st.code(py_info["version"], language=None)

        # fullpcr
        fp_info: dict = status["fullpcr"]
        st.markdown("**fullpcr**")
        if fp_info["importable"]:
            st.success(f"✓ 可正常导入 — 版本 {fp_info.get('version', 'N/A')}")
        else:
            st.error(f"✗ 导入失败: {fp_info['error']}")

        # obipcr
        obi: dict = status["obipcr"]
        st.markdown("**obipcr**")
        if obi["available"]:
            st.success("✓ 可用")
            if obi.get("version"):
                st.caption(obi["version"])
        else:
            st.error(f"✗ {obi.get('error', '不可用')}")

        # MFEprimer
        mfe: dict = status["mfeprimer"]
        st.markdown("**MFEprimer**")
        if mfe["available"]:
            st.success("✓ 可用")
            if mfe.get("version"):
                st.caption(mfe["version"])
        else:
            st.error(f"✗ {mfe.get('error', '不可用')}")

        # Working directory
        st.markdown("**当前工作目录**")
        st.code(status["cwd"], language=None)

        st.divider()

        # Re-check button
        if st.button("重新检查环境", key="env_recheck_btn"):
            st.session_state["_env_force_refresh"] = True
            st.rerun()


# ── analysis workbench ───────────────────────────────────────────────────────


def _render_analysis_workbench() -> None:
    """合并后的分析工作台：输入文件 + 验证 + 预设 + 五步流程。"""
    _render_project_inputs()
    _render_input_validation_snapshot()
    common_params = _render_preset_controls()
    _render_workflow_status_row()

    tab_labels = [
        "1. 基础质控",
        "2. 质控汇总",
        "3. 特异性分析",
        "4. obipcr",
        "5. 最终报告",
    ]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        _render_workflow_step_1()
    with tabs[1]:
        _render_workflow_step_2()
    with tabs[2]:
        _render_workflow_step_3(common_params)
    with tabs[3]:
        _render_workflow_step_4(common_params)
    with tabs[4]:
        _render_workflow_step_5()


# ── project inputs (formerly 输入文件 page) ──────────────────────────────────


def _make_path_edited_callback(canonical_key: str):
    """Return an on_change callback that marks *canonical_key* as user-edited.

    The callback adds *canonical_key* to the ``workflow_path_user_edited``
    set in ``st.session_state``.  Used by all 14 workflow path
    ``st.text_input`` widgets so the first validation can avoid
    overwriting paths the user has already typed.
    """

    def _callback() -> None:
        import streamlit as st_inner

        edited: set[str] = st_inner.session_state.setdefault(
            "workflow_path_user_edited", set()
        )
        edited.add(canonical_key)
        st_inner.session_state["workflow_path_user_edited"] = edited

    return _callback


def _render_project_inputs() -> None:
    """File path inputs + validate button (same logic as Phase 6B)."""
    st.subheader("项目与输入文件")

    col_left, col_right = st.columns(2)

    with col_left:
        ensure_widget_key(st.session_state, "_inputs_primers_path")
        primers_path = st.text_input(
            "引物文件（primers.tsv）",
            help="Path to the primers file (Tab-separated).",
            key="_inputs_primers_path",
        )
        ensure_widget_key(st.session_state, "_inputs_database_path")
        database_path = st.text_input(
            "参考数据库（database.fasta）",
            help="Path to the FASTA database (.fasta, .fa, .fasta.gz, .fa.gz).",
            key="_inputs_database_path",
        )

    with col_right:
        ensure_widget_key(st.session_state, "_inputs_taxonomy_path")
        taxonomy_path = st.text_input(
            "分类信息（taxonomy.tsv）",
            help="Path to the taxonomy file (Tab-separated).",
            key="_inputs_taxonomy_path",
        )
        ensure_widget_key(st.session_state, "_inputs_output_dir")
        output_dir = st.text_input(
            "项目输出目录",
            help="Root directory for all output files.",
            key="_inputs_output_dir",
        )

    if st.button("验证输入文件", type="primary", key="inputs_validate_btn"):
        # -- primers ---------------------------------------------------
        primers_result = validate_primers_file(primers_path)
        # -- database ---------------------------------------------------
        db_result = validate_database_file(database_path)
        # -- taxonomy ---------------------------------------------------
        tax_result = validate_taxonomy_file(taxonomy_path)
        # -- output directory -------------------------------------------
        out_result = validate_output_directory(output_dir)

        # Compute validity
        primers_status = primers_result.get("status", "FAIL")
        database_status = db_result.get("status", "FAIL")
        taxonomy_status = tax_result.get("status", "FAIL")
        output_status = out_result.get("status", "FAIL")

        all_valid = compute_inputs_validated(
            primers_status, database_status, taxonomy_status, output_status
        )
        st.session_state["inputs_validated"] = all_valid

        derived = {}
        if all_valid:
            derived = derive_project_paths(output_dir)
            spec_index_db = ""
            if derived.get("qc_spec_results_dir"):
                spec_index_db = str(
                    Path(derived["qc_spec_results_dir"]) / "index" / "database.fasta"
                )

            # Persist the full project snapshot.
            st.session_state["project_primers_path"] = primers_path
            st.session_state["project_database_path"] = database_path
            st.session_state["project_taxonomy_path"] = taxonomy_path
            st.session_state["project_output_root"] = output_dir
            st.session_state["project_derived_paths"] = derived

            # Populate workflow canonical keys with first-init logic.
            paths_dict = {
                "output_root": output_dir,
                "primers_path": primers_path,
                "database_path": database_path,
                "taxonomy_path": taxonomy_path,
                "qc_results_dir": derived.get("qc_results_dir", ""),
                "qc_spec_results_dir": derived.get("qc_spec_results_dir", ""),
                "obipcr_results_dir": derived.get("obipcr_results_dir", ""),
                "final_results_dir": derived.get("final_results_dir", ""),
                "spec_index_database": spec_index_db,
            }
            if not st.session_state.get("workflow_paths_initialized"):
                # First successful validation: fill canonical keys that the
                # user has NOT explicitly edited, OR that are currently
                # empty/None (empty takes priority over user_edited).
                # Widget keys are also written because the Workflow widgets
                # may not have been created yet on a fresh session.
                user_edited: set[str] = st.session_state.get(
                    "workflow_path_user_edited", set()
                )
                for _pk, state_key in _WORKFLOW_PATH_MAP:
                    current = st.session_state.get(state_key)
                    current_w = st.session_state.get(f"_{state_key}")
                    is_empty = (
                        current is None
                        or current == ""
                        or current_w is None
                        or current_w == ""
                    )
                    if state_key not in user_edited or is_empty:
                        value = paths_dict.get(_pk, "")
                        if value:
                            st.session_state[state_key] = value
                            st.session_state[f"_{state_key}"] = value
                st.session_state["workflow_paths_initialized"] = True
            else:
                # Subsequent validations: record which canonical keys are
                # currently empty/missing, apply strict overwrite=False
                # (canonical only, no widget keys), then clean up old empty
                # temp keys so ensure_widget_key() reloads from canonical
                # before the Workflow widgets are created.
                empty_before: set[str] = set()
                for _pk, state_key in _WORKFLOW_PATH_MAP:
                    cv = st.session_state.get(state_key)
                    if cv is None or cv == "":
                        empty_before.add(state_key)
                apply_project_paths_to_state(
                    st.session_state,
                    paths_dict,
                    overwrite=False,
                )
                for state_key in empty_before:
                    cv = st.session_state.get(state_key)
                    if cv is not None and cv != "":
                        # Filled — remove old empty widget key so
                        # ensure_widget_key() reloads from canonical.
                        st.session_state.pop(f"_{state_key}", None)
        else:
            failures: list[str] = []
            if primers_status != "PASS":
                failures.append("引物文件")
            if database_status != "PASS":
                failures.append("参考数据库")
            if taxonomy_status != "PASS":
                failures.append("分类信息")
            if output_status not in ("PASS", "WARN"):
                failures.append("输出目录")

        # Save snapshot for display across reruns.
        st.session_state["input_validation_snapshot"] = {
            "primers_result": primers_result,
            "db_result": db_result,
            "tax_result": tax_result,
            "out_result": out_result,
            "all_valid": all_valid,
            "derived": derived,
            "failures": failures if not all_valid else [],
        }


# ── input validation snapshot ────────────────────────────────────────────────


def _render_input_validation_snapshot() -> None:
    """Show persisted validation results even after ordinary reruns."""
    snapshot = st.session_state.get("input_validation_snapshot")
    if snapshot is None:
        st.info("点击 **验证输入文件** 检查所有输入文件和路径。")
        return

    st.divider()
    st.subheader("验证结果")

    primers_result: dict = snapshot.get("primers_result", {})
    db_result: dict = snapshot.get("db_result", {})
    tax_result: dict = snapshot.get("tax_result", {})
    out_result: dict = snapshot.get("out_result", {})
    all_valid: bool = snapshot.get("all_valid", False)
    derived: dict = snapshot.get("derived", {})
    failures: list[str] = snapshot.get("failures", [])

    # -- primers --
    st.markdown("#### 引物文件 (primers.tsv)")
    _render_file_validation(
        label="primers.tsv",
        result=primers_result,
        show_preview=True,
        preview_caption="前 10 行（含表头）",
    )

    # -- database --
    st.markdown("#### 参考数据库 (database.fasta)")
    _render_file_validation(label="database", result=db_result, show_preview=False)
    if db_result.get("record_count") is not None:
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("FASTA 序列数量", db_result["record_count"])
        with col_b:
            st.metric(
                "总碱基数",
                f"{db_result['total_bases']:,}" if db_result.get("total_bases") else "N/A",
            )

    # -- taxonomy --
    st.markdown("#### 分类信息 (taxonomy.tsv)")
    _render_file_validation(
        label="taxonomy.tsv",
        result=tax_result,
        show_preview=True,
        preview_caption="前 10 行（含表头）",
    )
    if tax_result.get("record_count") is not None:
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("分类记录数", tax_result["record_count"])
        with col_b:
            st.metric(
                "物种数量",
                tax_result["unique_species"]
                if tax_result.get("unique_species") is not None
                else "N/A",
            )

    # -- output directory --
    st.markdown("#### 输出目录")
    out_status = translate_status(out_result.get("status", "FAIL"))
    if out_result.get("status") == "PASS":
        st.success(f"✓ 目录已存在 ({out_status}): `{out_result.get('path', '')}`")
    elif out_result.get("will_create"):
        st.warning(f"后续将自动创建 ({out_status}): `{out_result.get('path', '')}`")
    elif out_result.get("error"):
        st.error(out_result.get("error", "未知错误"))

    # -- validation summary --
    if all_valid:
        st.success("项目路径已保存，分析流程将自动使用这些路径。")
        if derived:
            st.markdown("#### 项目输出目录结构（自动派生）")
            st.code(
                f"{derived.get('output_root', 'results')}/\n"
                f"├── qc_results/          → {derived.get('qc_results_dir', '')}\n"
                f"├── qc_spec_results/     → {derived.get('qc_spec_results_dir', '')}\n"
                f"├── obipcr_results/      → {derived.get('obipcr_results_dir', '')}\n"
                f"└── final_results/        → {derived.get('final_results_dir', '')}\n",
                language=None,
            )
    elif failures:
        st.warning(f"以下输入未通过验证: {', '.join(failures)}。请修正后重新验证。")
    else:
        output_dir = st.session_state.get("inputs_output_dir", "results")
        st.markdown("#### 项目输出目录结构")
        st.code(
            f"{output_dir or 'results'}/\n"
            f"├── qc_results/          MFEprimer 基础质控\n"
            f"├── qc_spec_results/     MFEprimer 特异性分析\n"
            f"├── obipcr_results/      obipcr 全库模拟 PCR\n"
            f"└── final_results/       最终综合结果\n",
            language=None,
        )


# ── preset controls ──────────────────────────────────────────────────────────


def _render_preset_controls() -> dict[str, object]:
    """Sync button, preset selectbox, apply button, and dry-run toggle."""
    st.divider()
    st.subheader("分析参数")

    sync_col, preset_col, apply_col = st.columns([1, 2, 1])

    with sync_col:
        if st.button("从输入文件同步路径", key="wf_sync_btn"):
            if st.session_state.get("inputs_validated"):
                derived = st.session_state.get("project_derived_paths", {})
                spec_index_db = ""
                if derived.get("qc_spec_results_dir"):
                    spec_index_db = str(
                        Path(derived["qc_spec_results_dir"])
                        / "index"
                        / "database.fasta"
                    )
                apply_project_paths_to_state(
                    st.session_state,
                    {
                        "output_root": st.session_state.get("project_output_root", ""),
                        "primers_path": st.session_state.get("project_primers_path", ""),
                        "database_path": st.session_state.get("project_database_path", ""),
                        "taxonomy_path": st.session_state.get("project_taxonomy_path", ""),
                        "qc_results_dir": derived.get("qc_results_dir", ""),
                        "qc_spec_results_dir": derived.get("qc_spec_results_dir", ""),
                        "obipcr_results_dir": derived.get("obipcr_results_dir", ""),
                        "final_results_dir": derived.get("final_results_dir", ""),
                        "spec_index_database": spec_index_db,
                    },
                    overwrite=True,
                )
                st.success("已同步：所有工作流路径已更新为项目路径。")
            else:
                st.warning("请先验证输入文件。")

    with preset_col:
        preset_options = [
            "12S/16S 短片段",
            "COI mini-barcode",
            "COI Folmer",
            "Cytb",
            "自定义",
        ]
        ensure_widget_key(st.session_state, "_wf_preset_select")
        selected_preset = st.selectbox(
            "引物类型预设",
            preset_options,
            key="_wf_preset_select",
        )
        preset_info = get_primer_preset(selected_preset)
        if selected_preset != "自定义":
            st.caption(f"📋 {preset_info['description']}")

    with apply_col:
        st.write("")  # vertical spacer
        if st.button("应用参数预设", key="wf_apply_preset_btn"):
            apply_primer_preset_to_state(st.session_state, selected_preset)
            if selected_preset == "自定义":
                st.info("「自定义」模式不修改任何参数。")
            else:
                st.success(f"已应用「{selected_preset}」参数预设。")

    # ── common analysis params (front-placed, read by steps 3 & 4) ──────

    st.markdown("#### 常用分析参数")
    pcol1, pcol2, pcol3, pcol4, pcol5 = st.columns(5)
    with pcol1:
        ensure_widget_key(st.session_state, "_wf_s3_minsize")
        minsize = st.number_input("min_size (bp)", key="_wf_s3_minsize")
    with pcol2:
        ensure_widget_key(st.session_state, "_wf_s3_maxsize")
        maxsize = st.number_input("max_size (bp)", key="_wf_s3_maxsize")
    with pcol3:
        ensure_widget_key(st.session_state, "_wf_s3_mismatch")
        spec_mismatch = st.number_input("spec mismatch", key="_wf_s3_mismatch")
    with pcol4:
        ensure_widget_key(st.session_state, "_wf_s4_mismatches")
        mismatches = st.text_input(
            "obipcr mismatches",
            key="_wf_s4_mismatches",
            help="Comma-separated mismatch levels.",
        )
    with pcol5:
        ensure_widget_key(st.session_state, "_wf_s4_circular")
        circular = st.checkbox("Circular", key="_wf_s4_circular")

    st.divider()

    # Return captured widget values so callers can pass them to step 3/4
    # command builders within the same render cycle — canonical keys are
    # only synced at the bottom of the script.
    common_params = {
        "min_size": int(minsize) if minsize is not None else 80,
        "max_size": int(maxsize) if maxsize is not None else 500,
        "spec_mismatch": int(spec_mismatch) if spec_mismatch is not None else 2,
        "obipcr_mismatches": str(mismatches),
        "circular": bool(circular),
    }

    # Dry-run toggle
    ensure_widget_key(st.session_state, "_workflow_dry_run")
    dry_run = st.toggle(
        "仅预览命令，不执行",
        key="_workflow_dry_run",
        help="启用后命令仅预览，不会实际执行。",
    )
    if dry_run:
        st.info("🔍 **仅预览命令模式** — 命令将显示但不会实际执行。")

    st.caption("建议首次运行时先开启「仅预览命令」以检查参数。")

    return common_params


# ── workflow status row ──────────────────────────────────────────────────────


def _render_workflow_status_row() -> None:
    """Five compact status cards above the workflow tabs."""
    steps: list[tuple[str, str]] = [
        ("1. 基础质控", "wf_s1_result"),
        ("2. 质控汇总", "wf_s2_result"),
        ("3. 特异性分析", "wf_s3_result"),
        ("4. obipcr", "wf_s4_result"),
        ("5. 最终报告", "wf_s5_result"),
    ]

    st.divider()
    st.subheader("分析流程")
    cols = st.columns(5)
    for i, (label, state_key) in enumerate(steps):
        result = st.session_state.get(state_key)
        if result is None:
            icon = "⬜"
            cn_status = "未运行"
        elif result.get("status") == "PASS":
            icon = "✅"
            cn_status = "成功"
        elif result.get("status") == "TIMEOUT":
            icon = "⏱️"
            cn_status = "超时"
        else:
            icon = "❌"
            cn_status = "失败"
        with cols[i]:
            st.markdown(f"{icon} **{label}**")
            st.caption(cn_status)


# ── step result helper ───────────────────────────────────────────────────────


def _render_step_result(run_result: dict | None, step_key: str) -> None:
    """Display the result of a command execution.

    Uses ``st.code`` (stateless, no widget key) inside expanders so
    that second and subsequent runs immediately show the latest output.

    Args:
        run_result: Dict returned by :func:`run_gui_command`, or ``None``.
        step_key: Stable key suffix (e.g. ``"s1"``) used only for the
            expander label — never as a Streamlit widget key.
    """
    if run_result is None:
        return

    status = run_result["status"]
    status_cn = translate_status(status)
    if status == "PASS":
        st.success(f"运行成功 — {status_cn}")
    elif status == "TIMEOUT":
        st.error(f"运行超时 — {status_cn}: {run_result['message']}")
    else:
        st.error(f"运行失败 — {status_cn}: {run_result['message']}")

    if run_result.get("returncode") is not None:
        st.metric("返回码", run_result["returncode"])

    stdout_text = run_result.get("stdout", "")
    with st.expander("查看运行输出"):
        st.code(stdout_text if stdout_text else "(empty)", language=None)

    stderr_text = run_result.get("stderr", "")
    if stderr_text:
        with st.expander("查看错误信息"):
            st.code(stderr_text, language=None)


# ── workflow tabs ────────────────────────────────────────────────────────────


def _render_workflow_step_1() -> None:
    """Tab: MFEprimer 引物基础质控."""
    st.caption("计算 Tm、GC、二聚体、发卡结构和简并引物展开。")

    step1_col1, step1_col2 = st.columns(2)
    with step1_col1:
        ensure_widget_key(st.session_state, "_wf_s1_primers")
        s1_primers = st.text_input(
            "引物文件 (primers.tsv)",
            key="_wf_s1_primers",
            on_change=_make_path_edited_callback("wf_s1_primers"),
        )
    with step1_col2:
        ensure_widget_key(st.session_state, "_wf_s1_outdir")
        s1_outdir = st.text_input(
            "质控输出目录",
            key="_wf_s1_outdir",
            on_change=_make_path_edited_callback("wf_s1_outdir"),
        )

    s1_col_flags, _s1_spacer = st.columns([1, 2])
    with s1_col_flags:
        ensure_widget_key(st.session_state, "_wf_s1_thermo")
        s1_thermo = st.checkbox("Thermo（Tm 计算）", key="_wf_s1_thermo")
        ensure_widget_key(st.session_state, "_wf_s1_dimer")
        s1_dimer = st.checkbox("Dimer（二聚体检测）", key="_wf_s1_dimer")
        ensure_widget_key(st.session_state, "_wf_s1_hairpin")
        s1_hairpin = st.checkbox("Hairpin（发卡结构检测）", key="_wf_s1_hairpin")
        ensure_widget_key(st.session_state, "_wf_s1_degen")
        s1_degen = st.checkbox("Degen（简并引物展开）", key="_wf_s1_degen")

    with st.expander("高级参数"):
        as1c1, as1c2 = st.columns(2)
        with as1c1:
            ensure_widget_key(st.session_state, "_wf_s1_score")
            s1_score = st.number_input("score", key="_wf_s1_score")
            ensure_widget_key(st.session_state, "_wf_s1_dg")
            s1_dg = st.number_input("dg", key="_wf_s1_dg")
            ensure_widget_key(st.session_state, "_wf_s1_tm")
            s1_tm = st.number_input("tm", key="_wf_s1_tm")
        with as1c2:
            ensure_widget_key(st.session_state, "_wf_s1_mismatch")
            s1_mismatch = st.number_input("mismatch", key="_wf_s1_mismatch")
            ensure_widget_key(st.session_state, "_wf_s1_maxdeg")
            s1_max_deg = st.number_input("max_degenerate_variants", key="_wf_s1_maxdeg")
            ensure_widget_key(st.session_state, "_wf_s1_timeout")
            s1_timeout = st.number_input("timeout (s)", key="_wf_s1_timeout")

    with st.expander("查看实际执行命令"):
        s1_cmd = build_qc_pre_command(
            primers=s1_primers,
            outdir=s1_outdir,
            thermo=s1_thermo,
            dimer=s1_dimer,
            hairpin=s1_hairpin,
            degen=s1_degen,
            max_degenerate_variants=s1_max_deg,
            score=s1_score,
            mismatch=s1_mismatch,
            dg=s1_dg,
            tm=s1_tm,
            timeout=s1_timeout,
        )
        st.code(" ".join(s1_cmd), language="bash")

    dry_run = st.session_state.get("workflow_dry_run", False)
    if st.button("运行基础质控", key="wf_run_s1"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            with st.spinner("正在运行基础质控..."):
                result = run_gui_command(s1_cmd, timeout=s1_timeout)
                st.session_state["wf_s1_result"] = result
    _render_step_result(st.session_state.get("wf_s1_result"), "s1")


def _render_workflow_step_2() -> None:
    """Tab: 生成质控汇总."""
    st.caption("解析 MFEprimer 原始输出并生成质控汇总表。")

    ensure_widget_key(st.session_state, "_wf_s2_qcdir")
    s2_qc_dir = st.text_input(
        "质控结果目录",
        key="_wf_s2_qcdir",
        on_change=_make_path_edited_callback("wf_s2_qcdir"),
    )
    s2_cmd = build_qc_summary_command(qc_dir=s2_qc_dir)
    with st.expander("查看实际执行命令"):
        st.code(" ".join(s2_cmd), language="bash")

    dry_run = st.session_state.get("workflow_dry_run", False)
    if st.button("生成质控汇总", key="wf_run_s2"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            with st.spinner("正在生成质控汇总..."):
                result = run_gui_command(s2_cmd)
                st.session_state["wf_s2_result"] = result
    _render_step_result(st.session_state.get("wf_s2_result"), "s2")


def _render_workflow_step_3(common_params: dict) -> None:
    """Tab: MFEprimer 特异性分析."""
    st.caption("建立参考数据库索引并评估引物扩增特异性。")

    s3_col1, s3_col2 = st.columns(2)
    with s3_col1:
        ensure_widget_key(st.session_state, "_wf_s3_primers")
        s3_primers = st.text_input(
            "引物文件 (primers.tsv)",
            key="_wf_s3_primers",
            on_change=_make_path_edited_callback("wf_s3_primers"),
        )
        ensure_widget_key(st.session_state, "_wf_s3_database")
        s3_database = st.text_input(
            "参考数据库 (database.fasta)",
            key="_wf_s3_database",
            on_change=_make_path_edited_callback("wf_s3_database"),
        )
    with s3_col2:
        ensure_widget_key(st.session_state, "_wf_s3_outdir")
        s3_outdir = st.text_input(
            "特异性分析输出目录",
            key="_wf_s3_outdir",
            on_change=_make_path_edited_callback("wf_s3_outdir"),
        )

    # Common params — minsize/maxsize/mismatch are front-placed (see _render_preset_controls)
    ensure_widget_key(st.session_state, "_wf_s3_timeout")
    s3_timeout = st.number_input("timeout (s)", key="_wf_s3_timeout")

    with st.expander("高级参数"):
        as3c1, as3c2 = st.columns(2)
        with as3c1:
            ensure_widget_key(st.session_state, "_wf_s3_tm")
            s3_tm = st.number_input("tm", key="_wf_s3_tm")
            ensure_widget_key(st.session_state, "_wf_s3_cpu")
            s3_cpu = st.number_input("cpu", key="_wf_s3_cpu")
        with as3c2:
            ensure_widget_key(st.session_state, "_wf_s3_maxtm")
            s3_max_tm = st.number_input("max_tm", key="_wf_s3_maxtm")
            ensure_widget_key(st.session_state, "_wf_s3_kvalue")
            s3_kvalue = st.number_input("kvalue", key="_wf_s3_kvalue")
        ensure_widget_key(st.session_state, "_wf_s3_force")
        s3_force = st.checkbox("Force（覆盖已有结果）", key="_wf_s3_force")

    with st.expander("查看实际执行命令"):
        s3_cmd = build_qc_spec_command(
            primers=s3_primers,
            database=s3_database,
            outdir=s3_outdir,
            min_size=common_params["min_size"],
            max_size=common_params["max_size"],
            tm=s3_tm,
            max_tm=s3_max_tm,
            mismatch=common_params["spec_mismatch"],
            cpu=s3_cpu,
            kvalue=s3_kvalue,
            timeout=s3_timeout,
            force=s3_force,
        )
        st.code(" ".join(s3_cmd), language="bash")

    dry_run = st.session_state.get("workflow_dry_run", False)
    if st.button("运行特异性分析", key="wf_run_s3"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            with st.spinner("正在运行特异性分析..."):
                result = run_gui_command(s3_cmd, timeout=s3_timeout)
                st.session_state["wf_s3_result"] = result
    _render_step_result(st.session_state.get("wf_s3_result"), "s3")


def _render_workflow_step_4(common_params: dict) -> None:
    """Tab: obipcr 全库模拟 PCR."""
    st.caption("在参考数据库中批量模拟引物扩增。")

    s4_col1, s4_col2 = st.columns(2)
    with s4_col1:
        ensure_widget_key(st.session_state, "_wf_s4_primers")
        s4_primers = st.text_input(
            "引物文件 (primers.tsv)",
            key="_wf_s4_primers",
            on_change=_make_path_edited_callback("wf_s4_primers"),
        )
        ensure_widget_key(st.session_state, "_wf_s4_database")
        s4_database = st.text_input(
            "参考数据库 (normalized FASTA)",
            key="_wf_s4_database",
            on_change=_make_path_edited_callback("wf_s4_database"),
        )
    with s4_col2:
        ensure_widget_key(st.session_state, "_wf_s4_taxonomy")
        s4_taxonomy = st.text_input(
            "分类信息 (taxonomy.tsv)",
            key="_wf_s4_taxonomy",
            on_change=_make_path_edited_callback("wf_s4_taxonomy"),
        )
        ensure_widget_key(st.session_state, "_wf_s4_outdir")
        s4_outdir = st.text_input(
            "obipcr 输出目录",
            key="_wf_s4_outdir",
            on_change=_make_path_edited_callback("wf_s4_outdir"),
        )

    # mismatches & circular are front-placed (see _render_preset_controls)

    s4_flags_col, s4_timeout_col = st.columns([2, 1])
    with s4_flags_col:
        ensure_widget_key(st.session_state, "_wf_s4_summarize")
        s4_summarize = st.checkbox("Summarize（汇总统计）", key="_wf_s4_summarize")
        ensure_widget_key(st.session_state, "_wf_s4_report")
        s4_report = st.checkbox("Report（生成报告）", key="_wf_s4_report")
        ensure_widget_key(st.session_state, "_wf_s4_force")
        s4_force = st.checkbox("Force（覆盖已有结果）", key="_wf_s4_force")
    with s4_timeout_col:
        ensure_widget_key(st.session_state, "_wf_s4_timeout")
        s4_timeout = st.number_input("timeout (s)", key="_wf_s4_timeout")

    with st.expander("查看实际执行命令"):
        s4_cmd = build_obipcr_run_command(
            primers=s4_primers,
            database=s4_database,
            outdir=s4_outdir,
            taxonomy=s4_taxonomy,
            mismatches=common_params["obipcr_mismatches"],
            circular=common_params["circular"],
            summarize=s4_summarize,
            report=s4_report,
            force=s4_force,
            timeout=s4_timeout,
        )
        st.code(" ".join(s4_cmd), language="bash")

    dry_run = st.session_state.get("workflow_dry_run", False)
    if st.button("运行全库模拟 PCR", key="wf_run_s4"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            with st.spinner("正在运行 obipcr 全库模拟 PCR..."):
                result = run_gui_command(s4_cmd, timeout=s4_timeout)
                st.session_state["wf_s4_result"] = result
    _render_step_result(st.session_state.get("wf_s4_result"), "s4")


def _render_workflow_step_5() -> None:
    """Tab: 生成最终综合报告."""
    st.caption("整合 obipcr、引物质控和特异性分析结果。")

    s5_col1, s5_col2 = st.columns(2)
    with s5_col1:
        ensure_widget_key(st.session_state, "_wf_s5_obipcr_dir")
        s5_obipcr_dir = st.text_input(
            "obipcr 结果目录",
            key="_wf_s5_obipcr_dir",
            on_change=_make_path_edited_callback("wf_s5_obipcr_dir"),
        )
        ensure_widget_key(st.session_state, "_wf_s5_qc_dir")
        s5_qc_dir = st.text_input(
            "质控结果目录",
            key="_wf_s5_qc_dir",
            on_change=_make_path_edited_callback("wf_s5_qc_dir"),
        )
    with s5_col2:
        ensure_widget_key(st.session_state, "_wf_s5_spec_dir")
        s5_spec_dir = st.text_input(
            "特异性分析结果目录",
            key="_wf_s5_spec_dir",
            on_change=_make_path_edited_callback("wf_s5_spec_dir"),
        )
        ensure_widget_key(st.session_state, "_wf_s5_outdir")
        s5_outdir = st.text_input(
            "最终报告输出目录",
            key="_wf_s5_outdir",
            on_change=_make_path_edited_callback("wf_s5_outdir"),
        )

    with st.expander("查看实际执行命令"):
        s5_cmd = build_final_report_command(
            obipcr_dir=s5_obipcr_dir,
            qc_dir=s5_qc_dir,
            spec_dir=s5_spec_dir,
            outdir=s5_outdir,
        )
        st.code(" ".join(s5_cmd), language="bash")

    dry_run = st.session_state.get("workflow_dry_run", False)
    if st.button("生成最终报告", key="wf_run_s5"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            with st.spinner("正在生成最终综合报告..."):
                result = run_gui_command(s5_cmd)
                st.session_state["wf_s5_result"] = result
    _render_step_result(st.session_state.get("wf_s5_result"), "s5")


# ═══════════════════════════════════════════════════════════════════════════
# Page config
# ═══════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="fullpcr 引物评测平台",
    page_icon="🧬",
    layout="wide",
)

# ═══════════════════════════════════════════════════════════════════════════
# Cross-page persistence: canonical defaults
# ═══════════════════════════════════════════════════════════════════════════

init_canonical_defaults(st.session_state)

# ═══════════════════════════════════════════════════════════════════════════
# Header
# ═══════════════════════════════════════════════════════════════════════════

_render_header()

# ═══════════════════════════════════════════════════════════════════════════
# Sidebar navigation
# ═══════════════════════════════════════════════════════════════════════════

st.sidebar.title("🧬 fullpcr")

page = st.sidebar.radio(
    "导航",
    ["分析工作台", "结果总览", "报告与下载"],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.caption("GUI Phase 7A")

# ═══════════════════════════════════════════════════════════════════════════
# Page routing
# ═══════════════════════════════════════════════════════════════════════════

if page == "分析工作台":
    _render_analysis_workbench()

elif page == "结果总览":
    st.header("结果总览")
    st.markdown("查看引物综合排名、物种覆盖率和质控状态。")

    # ── directory inputs ───────────────────────────────────────────────

    col1, col2 = st.columns(2)
    with col1:
        ensure_widget_key(st.session_state, "_res_final_dir")
        final_results_dir = st.text_input(
            "final_results 目录",
            key="_res_final_dir",
            help="Directory containing primer_rank.tsv.",
        )
        ensure_widget_key(st.session_state, "_res_obipcr_dir")
        obipcr_results_dir = st.text_input(
            "obipcr_results 目录",
            key="_res_obipcr_dir",
            help="Directory containing combined_summary.tsv.",
        )
    with col2:
        ensure_widget_key(st.session_state, "_res_qc_dir")
        qc_results_dir = st.text_input(
            "qc_results 目录",
            key="_res_qc_dir",
            help="Directory containing primer_qc_summary.tsv.",
        )
        ensure_widget_key(st.session_state, "_res_spec_dir")
        qc_spec_results_dir = st.text_input(
            "qc_spec_results 目录",
            key="_res_spec_dir",
            help="Directory containing spec/primer_spec.tsv.",
        )

    st.divider()

    if st.button("加载分析结果", type="primary", key="res_load_btn"):
        # ── load all files ──────────────────────────────────────────

        rank_result = load_primer_rank(
            str(Path(final_results_dir) / "primer_rank.tsv")
        )
        combined_result = load_tsv_file(
            str(Path(obipcr_results_dir) / "combined_summary.tsv")
        )
        qc_result = load_tsv_file(
            str(Path(qc_results_dir) / "primer_qc_summary.tsv")
        )
        spec_result = load_tsv_file(
            str(Path(qc_spec_results_dir) / "spec" / "primer_spec.tsv")
        )

        # Store in session state for download buttons
        st.session_state["res_rank_result"] = rank_result
        st.session_state["res_combined_result"] = combined_result
        st.session_state["res_qc_result"] = qc_result
        st.session_state["res_spec_result"] = spec_result

        # ── primer_rank.tsv ──────────────────────────────────────────

        st.header("引物综合排名")
        if rank_result["status"] == "PASS" and rank_result["df"] is not None:
            rank_df = rank_result["df"]
            rank_summary = summarize_primer_rank(rank_df)

            # -- metric cards --
            st.subheader("综合指标")
            mc1, mc2, mc3, mc4 = st.columns(4)
            with mc1:
                top = rank_summary.get("top_primer")
                st.metric("最佳引物", top if top else "N/A")
            with mc2:
                score = rank_summary.get("top_final_score")
                st.metric(
                    "最高综合得分",
                    f"{score:.4f}" if score is not None else "N/A",
                )
            with mc3:
                st.metric(
                    "推荐引物数量",
                    rank_summary.get("recommended_count", 0),
                )
            with mc4:
                st.metric(
                    "不推荐引物数量",
                    rank_summary.get("not_recommended_count", 0),
                )

            # -- final_status distribution (Chinese labels) --
            statuses = rank_summary.get("final_statuses", {})
            if statuses:
                st.markdown("**推荐等级分布**")
                status_cols = st.columns(len(statuses))
                for i, (status_name, count) in enumerate(sorted(statuses.items())):
                    with status_cols[i]:
                        st.metric(translate_recommendation(status_name), count)

            # -- full table (display copy with translated values) --
            st.subheader("引物综合排名表")
            display_df = rank_df.copy()
            if "final_status" in display_df.columns:
                display_df["final_status"] = display_df["final_status"].apply(
                    translate_recommendation
                )
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
            )

            # -- bar charts --
            st.subheader("可视化图表")

            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                st.markdown("**综合得分 (final_score)**")
                if "primer_id" in rank_df.columns and "final_score" in rank_df.columns:
                    chart_df = rank_df[["primer_id", "final_score"]].copy()
                    chart_df["final_score"] = pd.to_numeric(
                        chart_df["final_score"], errors="coerce"
                    ).fillna(0)
                    chart_df = chart_df.set_index("primer_id")
                    st.bar_chart(chart_df, use_container_width=True)
                else:
                    st.info("final_score 列不可用，无法绘图。")

            with chart_col2:
                st.markdown("**覆盖物种数 (obipcr_unique_species_count)**")
                if (
                    "primer_id" in rank_df.columns
                    and "obipcr_unique_species_count" in rank_df.columns
                ):
                    sp_df = rank_df[
                        ["primer_id", "obipcr_unique_species_count"]
                    ].copy()
                    sp_df["obipcr_unique_species_count"] = pd.to_numeric(
                        sp_df["obipcr_unique_species_count"], errors="coerce"
                    ).fillna(0)
                    sp_df = sp_df.set_index("primer_id")
                    st.bar_chart(sp_df, use_container_width=True)
                else:
                    st.info("obipcr_unique_species_count 列不可用，无法绘图。")

            # -- download button --
            primer_rank_path = Path(final_results_dir) / "primer_rank.tsv"
            if primer_rank_path.is_file():
                st.download_button(
                    label="下载引物排名表 (primer_rank.tsv)",
                    data=primer_rank_path.read_bytes(),
                    file_name="primer_rank.tsv",
                    mime="text/tab-separated-values",
                    key="dl_primer_rank",
                )

        else:
            st.warning(
                f"primer_rank.tsv 不可用: {rank_result.get('error', '未知错误')}"
            )

        st.divider()

        # ── QC / Spec status table ────────────────────────────────────

        st.header("质控与特异性状态")
        if rank_result["status"] == "PASS" and rank_result["df"] is not None:
            rank_df = rank_result["df"]
            status_cols = [
                "primer_id",
                "qc_status",
                "spec_status",
                "final_status",
                "recommendation",
            ]
            available = [c for c in status_cols if c in rank_df.columns]
            if available:
                status_df = rank_df[available].copy()
                # Translate status columns (display copy only)
                if "final_status" in status_df.columns:
                    status_df["final_status"] = status_df["final_status"].apply(
                        translate_recommendation
                    )
                if "qc_status" in status_df.columns:
                    status_df["qc_status"] = status_df["qc_status"].apply(
                        translate_warning_label
                    )
                if "spec_status" in status_df.columns:
                    status_df["spec_status"] = status_df["spec_status"].apply(
                        translate_warning_label
                    )
                st.dataframe(
                    status_df,
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("primer_rank.tsv 中没有状态字段。")
        else:
            st.info("加载 primer_rank.tsv 后可查看质控与特异性状态。")

        st.divider()

        # ── combined_summary.tsv ──────────────────────────────────────

        st.header("obipcr 汇总结果")
        if combined_result["status"] == "PASS" and combined_result["df"] is not None:
            st.caption(
                f"{combined_result['row_count']} 行, "
                f"{len(combined_result['columns'])} 列"
            )
            with st.expander("查看 combined_summary.tsv", expanded=False):
                st.dataframe(
                    combined_result["df"],
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.info(
                f"combined_summary.tsv 不可用: "
                f"{combined_result.get('error', '未知错误')}"
            )

        # ── primer_qc_summary.tsv ─────────────────────────────────────

        st.header("MFEprimer 质控汇总")
        if qc_result["status"] == "PASS" and qc_result["df"] is not None:
            st.caption(
                f"{qc_result['row_count']} 行, "
                f"{len(qc_result['columns'])} 列"
            )
            with st.expander("查看 primer_qc_summary.tsv", expanded=False):
                st.dataframe(
                    qc_result["df"],
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.info(
                f"primer_qc_summary.tsv 不可用: "
                f"{qc_result.get('error', '未知错误')}"
            )

        # ── primer_spec.tsv ───────────────────────────────────────────

        st.header("MFEprimer 特异性汇总")
        if spec_result["status"] == "PASS" and spec_result["df"] is not None:
            st.caption(
                f"{spec_result['row_count']} 行, "
                f"{len(spec_result['columns'])} 列"
            )
            with st.expander("查看 primer_spec.tsv", expanded=False):
                st.dataframe(
                    spec_result["df"],
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.info(
                f"primer_spec.tsv 不可用: "
                f"{spec_result.get('error', '未知错误')}"
            )

    else:
        st.info("点击 **加载分析结果** 查看分析输出。")

elif page == "报告与下载":
    st.header("报告与下载")
    st.markdown("查看最终综合报告和 obipcr 分析报告。")

    # ── file path inputs ──────────────────────────────────────────────

    col1, col2 = st.columns(2)
    with col1:
        ensure_widget_key(st.session_state, "_rpt_final_path")
        final_report_path = st.text_input(
            "最终报告路径",
            key="_rpt_final_path",
            help="Path to final_report.md.",
        )
    with col2:
        ensure_widget_key(st.session_state, "_rpt_obipcr_path")
        obipcr_report_path = st.text_input(
            "obipcr 报告路径",
            key="_rpt_obipcr_path",
            help="Path to obipcr_results/report.md.",
        )

    st.divider()

    if st.button("加载报告", type="primary", key="rpt_load_btn"):
        # ── load reports ──────────────────────────────────────────────

        final_rpt = load_markdown_file(final_report_path)
        obi_rpt = load_markdown_file(obipcr_report_path)

        st.session_state["rpt_final"] = final_rpt
        st.session_state["rpt_obipcr"] = obi_rpt

        # ── display in tabs ───────────────────────────────────────────

        tab1, tab2 = st.tabs(["最终综合报告", "obipcr 分析报告"])

        with tab1:
            st.markdown(f"**文件路径:** `{final_report_path}`")

            if final_rpt["status"] == "PASS" and final_rpt["content"]:
                st.markdown(final_rpt["content"])
                # Download button
                st.download_button(
                    label="下载最终报告 (final_report.md)",
                    data=final_rpt["content"],
                    file_name="final_report.md",
                    mime="text/markdown",
                    key="dl_final_report",
                )
            elif final_rpt["status"] == "WARN":
                st.warning(final_rpt.get("error", "文件为空"))
            else:
                st.info(
                    f"报告不可用: {final_rpt.get('error', '未知错误')}"
                )

        with tab2:
            st.markdown(f"**文件路径:** `{obipcr_report_path}`")

            if obi_rpt["status"] == "PASS" and obi_rpt["content"]:
                st.markdown(obi_rpt["content"])
                # Download button
                st.download_button(
                    label="下载 obipcr 报告 (report.md)",
                    data=obi_rpt["content"],
                    file_name="obipcr_report.md",
                    mime="text/markdown",
                    key="dl_obipcr_report",
                )
            elif obi_rpt["status"] == "WARN":
                st.warning(obi_rpt.get("error", "文件为空"))
            else:
                st.info(
                    f"报告不可用: {obi_rpt.get('error', '未知错误')}"
                )

    else:
        st.info("点击 **加载报告** 查看生成的报告。")

# ═══════════════════════════════════════════════════════════════════════════
# Cross-page persistence: sync widget → canonical
# ═══════════════════════════════════════════════════════════════════════════

sync_widgets_to_canonical(st.session_state)
