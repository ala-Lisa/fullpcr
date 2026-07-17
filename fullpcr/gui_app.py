"""fullpcr Streamlit GUI — Phase 7A: IA restructure + env popover + tabs.

Launch with::

    streamlit run fullpcr/gui_app.py
"""

from __future__ import annotations

import base64
import os
from collections.abc import MutableMapping
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from fullpcr.gui_helpers import (
    _WORKFLOW_PATH_MAP,
    apply_project_paths_to_state,
    build_execution_error_details,
    build_final_report_command,
    build_full_pipeline_plan,
    build_manual_primers_tsv,
    build_obipcr_run_command,
    build_qc_pre_command,
    build_qc_spec_command,
    build_qc_summary_command,
    build_spec_index_database_path,
    check_command_available,
    clear_upload_mode,
    collect_environment_status,
    compute_inputs_validated,
    derive_project_paths,
    ensure_widget_key,
    get_available_cpu_threads,
    get_effective_database_path,
    get_effective_primers_path,
    get_effective_taxonomy_path,
    get_fullpcr_info,
    get_python_info,
    init_canonical_defaults,
    init_workspace_session_state,
    load_markdown_file,
    load_primer_rank,
    load_tsv_file,
    resolve_spec_cpu_threads,
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
    build_results_archive,
)
from fullpcr.pipeline_jobs import (
    get_pipeline_job,
    request_pipeline_cancel,
    start_pipeline_job,
)
from fullpcr.web_workspace import (
    DATABASE_FILE,
    PRIMERS_FILE,
    TAXONOMY_FILE,
    create_run_workspace,
    get_data_root,
    save_uploaded_file,
)


BRAND_NAME = "博坤生物"
BRAND_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "bokun-bio-logo.png"


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

    error = result.get("error")
    if not path:
        if status == "FAIL" and error:
            st.error(f"✗ **{label}** — 异常 — {error}")
        else:
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


def _brand_logo_data_uri() -> str:
    """Return the bundled company logo as a browser-safe data URI."""
    encoded = base64.b64encode(BRAND_LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _inject_brand_styles() -> None:
    """Apply the restrained Bokun Bio visual system to the Streamlit shell."""
    st.markdown(
        """
        <style>
        html {
            font-size: 20px;
            color-scheme: light;
        }

        :root {
            --bk-navy: #102a43;
            --bk-navy-soft: #1f4668;
            --bk-green: #2eae7b;
            --bk-surface: #ffffff;
            --bk-bg: #f3f7f2;
            --bk-mist-blue: #d6e4f1;
            --bk-mist-blue-deep: #b8cee2;
            --bk-muted: #5f7079;
            --bk-border: rgba(16, 42, 67, 0.10);
        }

        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at 88% 2%, rgba(46, 174, 123, 0.09), transparent 28rem),
                linear-gradient(180deg, #fbfcf9 0%, #f7f9f5 48%, var(--bk-bg) 100%);
        }

        [data-testid="stHeader"] {
            height: 0 !important;
            min-height: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
            pointer-events: none;
        }

        [data-testid="stToolbar"],
        [data-testid="stMainMenu"],
        [data-testid="stDeployButton"],
        [data-testid="stDecoration"] {
            display: none !important;
        }

        .block-container {
            max-width: 1220px;
            padding-top: 1.35rem;
            padding-bottom: 4rem;
        }

        .brand-hero {
            position: relative;
            min-height: 168px;
            width: 100%;
            display: flex;
            align-items: center;
            gap: 1.55rem;
            overflow: hidden;
            padding: 1.9rem 2.35rem;
            border: 1px solid rgba(35, 75, 108, 0.13);
            border-radius: 22px;
            background: linear-gradient(
                118deg,
                rgba(255,255,255,0.96) 0%,
                rgba(224,236,246,0.90) 58%,
                rgba(207,226,239,0.82) 100%
            );
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
            box-shadow: 0 22px 58px rgba(30, 65, 94, 0.13);
        }

        .brand-hero::after {
            content: "";
            position: absolute;
            inset: 0 0 0 auto;
            width: 56%;
            opacity: 0.42;
            background-position: center right;
            background-repeat: no-repeat;
            background-size: cover;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 460 170'%3E%3Cg fill='none' stroke-linecap='round'%3E%3Cpath d='M20 25 C125 25 125 145 230 145 S335 25 440 25' stroke='%23102a43' stroke-width='2.2' opacity='.34'/%3E%3Cpath d='M20 145 C125 145 125 25 230 25 S335 145 440 145' stroke='%232eae7b' stroke-width='2.2' opacity='.55'/%3E%3Cg stroke='%231f4668' stroke-width='1' opacity='.20'%3E%3Cpath d='M58 43 L58 127'/%3E%3Cpath d='M98 69 L98 101'/%3E%3Cpath d='M138 112 L138 58'/%3E%3Cpath d='M188 142 L188 28'/%3E%3Cpath d='M236 145 L236 25'/%3E%3Cpath d='M286 116 L286 54'/%3E%3Cpath d='M330 70 L330 100'/%3E%3Cpath d='M380 33 L380 137'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
        }

        .brand-logo {
            position: relative;
            z-index: 1;
            width: 90px;
            height: 90px;
            object-fit: contain;
            flex: 0 0 auto;
            filter: drop-shadow(0 9px 14px rgba(16, 42, 67, 0.12));
        }

        .brand-copy {
            position: relative;
            z-index: 1;
        }

        .brand-kicker {
            margin-bottom: 0.28rem;
            color: var(--bk-green);
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.16em;
        }

        .brand-title {
            margin: 0;
            color: var(--bk-navy);
            font-size: clamp(1.75rem, 3vw, 2.55rem);
            font-weight: 750;
            line-height: 1.08;
            letter-spacing: -0.035em;
        }

        .brand-title span {
            color: var(--bk-navy-soft);
            font-weight: 620;
        }

        .brand-subtitle {
            margin: 0.62rem 0 0;
            color: var(--bk-muted);
            font-size: 0.95rem;
        }

        .brand-subtitle b {
            color: var(--bk-navy-soft);
            font-weight: 650;
        }

        [data-testid="stPopover"] button,
        [data-testid="stPopover"] button p,
        [data-testid="stPopover"] button span {
            min-width: 0;
            white-space: nowrap;
            font-size: 0.79rem;
        }

        [data-testid="stPopover"] button {
            padding: 0.55rem 0.62rem;
        }

        section[data-testid="stSidebar"] [data-testid="stPopover"] {
            width: 100%;
            margin: 0 0 0.55rem;
        }

        section[data-testid="stSidebar"] [data-testid="stPopover"] > button {
            width: 100%;
            min-height: 44px;
            justify-content: flex-start;
            padding: 0.58rem 0.78rem;
            border: 1px solid rgba(35, 75, 108, 0.13);
            border-radius: 12px;
            background: rgba(255,255,255,0.48);
            box-shadow: 0 7px 18px rgba(39, 76, 106, 0.05);
        }

        .workflow-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.6rem;
            margin: 0.95rem 0 1.45rem;
        }

        .workflow-step {
            display: flex;
            align-items: center;
            gap: 0.58rem;
            min-height: 48px;
            padding: 0.68rem 0.82rem;
            color: var(--bk-navy-soft);
            border: 1px solid var(--bk-border);
            border-radius: 12px;
            background: rgba(255,255,255,0.72);
            font-size: 0.82rem;
            font-weight: 560;
        }

        .workflow-step b {
            color: var(--bk-green);
            font-size: 0.7rem;
            letter-spacing: 0.08em;
        }

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

        section[data-testid="stSidebar"] {
            overflow: hidden;
            border-right: 1px solid rgba(35, 75, 108, 0.16);
            background:
                radial-gradient(circle at 12% 4%, rgba(255,255,255,0.72), transparent 13rem),
                linear-gradient(155deg, #e2edf6 0%, var(--bk-mist-blue) 48%, var(--bk-mist-blue-deep) 100%);
            box-shadow: 12px 0 34px rgba(34, 69, 99, 0.10);
        }

        section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
            height: 100dvh;
            max-height: 100dvh;
            overflow: hidden;
            padding: 0.6rem 0.68rem 0.72rem;
        }

        section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
            display: none !important;
        }

        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] span {
            color: var(--bk-navy) !important;
        }

        .sidebar-brand-panel {
            display: grid;
            grid-template-columns: 58px minmax(0, 1fr);
            align-items: center;
            gap: 0.85rem;
            margin: 0.2rem 0.18rem 0.75rem;
            padding: 0.78rem;
            border: 1px solid rgba(35, 75, 108, 0.13);
            border-radius: 18px;
            background: rgba(255,255,255,0.58);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
            box-shadow: 0 14px 34px rgba(38, 76, 107, 0.11);
        }

        .sidebar-brand-panel img {
            width: 58px;
            height: 58px;
            object-fit: contain;
            filter: drop-shadow(0 8px 10px rgba(31,70,104,0.13));
        }

        .sidebar-brand-panel .eyebrow,
        .sidebar-env-intro .eyebrow,
        .sidebar-nav-intro .eyebrow,
        .sidebar-footer .eyebrow {
            color: #397092;
            font-size: 0.58rem;
            font-weight: 760;
            letter-spacing: 0.13em;
        }

        .sidebar-brand-panel h2 {
            margin: 0.16rem 0 0.08rem;
            color: var(--bk-navy);
            font-size: 1.13rem;
            letter-spacing: -0.025em;
        }

        .sidebar-brand-panel p {
            margin: 0;
            color: #587184 !important;
            font-size: 0.66rem;
            line-height: 1.35;
        }

        .sidebar-nav-intro {
            margin: 0 0.32rem 0.7rem;
        }

        .sidebar-env-intro {
            margin: 0 0.32rem 0.34rem;
        }

        .sidebar-nav-intro strong {
            display: block;
            margin-top: 0.12rem;
            color: var(--bk-navy);
            font-size: 0.88rem;
        }

        section[data-testid="stSidebar"] [role="radiogroup"] {
            align-items: stretch;
            width: 100%;
            gap: 0.48rem;
        }

        section[data-testid="stSidebar"] [role="radiogroup"] > label {
            position: relative;
            width: 100% !important;
            box-sizing: border-box;
            min-height: 72px;
            margin: 0;
            padding: 0.78rem 0.72rem 0.78rem 2.7rem !important;
            border: 1px solid rgba(35, 75, 108, 0.10);
            border-left: 4px solid transparent;
            border-radius: 14px;
            background: rgba(255,255,255,0.30);
            box-shadow: 0 7px 18px rgba(39, 76, 106, 0.05);
            transition: transform 140ms ease, background 140ms ease, box-shadow 140ms ease;
        }

        section[data-testid="stSidebar"] [role="radiogroup"] > label:hover {
            background: rgba(255,255,255,0.48);
        }

        section[data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) {
            border-left: 4px solid var(--bk-green);
            background: rgba(255,255,255,0.72);
            box-shadow: 0 12px 26px rgba(34, 70, 99, 0.13);
        }

        section[data-testid="stSidebar"] [role="radiogroup"] > label::before {
            position: absolute;
            top: 0.84rem;
            left: 0.82rem;
            color: #4d7895;
            font-size: 0.68rem;
            font-weight: 780;
            letter-spacing: 0.08em;
        }

        section[data-testid="stSidebar"] [role="radiogroup"] > label:nth-child(1)::before { content: "01"; }
        section[data-testid="stSidebar"] [role="radiogroup"] > label:nth-child(2)::before { content: "02"; }
        section[data-testid="stSidebar"] [role="radiogroup"] > label:nth-child(3)::before { content: "03"; }

        section[data-testid="stSidebar"] [role="radiogroup"] > label::after {
            position: absolute;
            top: 2.25rem;
            left: 2.78rem;
            color: #607b8e;
            font-size: 0.62rem;
            line-height: 1.2;
        }

        section[data-testid="stSidebar"] [role="radiogroup"] > label:nth-child(1)::after { content: "输入、验证并启动分析"; }
        section[data-testid="stSidebar"] [role="radiogroup"] > label:nth-child(2)::after { content: "查看排名与详细结果"; }
        section[data-testid="stSidebar"] [role="radiogroup"] > label:nth-child(3)::after { content: "解读报告并打包下载"; }

        section[data-testid="stSidebar"] [role="radiogroup"] > label p {
            color: var(--bk-navy) !important;
            font-size: 0.90rem;
            font-weight: 680;
        }

        .sidebar-footer {
            margin: auto 0.18rem 0;
            margin-top: auto;
            padding: 0.75rem 0.9rem;
            border: 1px solid rgba(35, 75, 108, 0.10);
            border-radius: 14px;
            background: rgba(255,255,255,0.28);
        }

        .sidebar-footer strong {
            display: block;
            margin-top: 0.12rem;
            color: var(--bk-navy);
            font-size: 0.75rem;
        }

        .sidebar-footer p {
            margin: 0.18rem 0 0;
            color: #607b8e !important;
            font-size: 0.62rem;
        }

        label[data-testid="stRadioOption"][data-selected="true"]
        > div > div > div:first-child {
            border-color: var(--bk-green) !important;
            background-color: var(--bk-green) !important;
        }

        h1, h2, h3 {
            color: var(--bk-navy);
            letter-spacing: -0.018em;
        }

        [data-testid="stFileUploaderDropzone"],
        [data-baseweb="input"] > div,
        [data-baseweb="select"] > div {
            border-color: var(--bk-border) !important;
            border-radius: 10px !important;
            background: rgba(255,255,255,0.82) !important;
        }

        [data-testid="stExpander"] {
            overflow: hidden;
            border-color: var(--bk-border);
            border-radius: 12px;
            background: rgba(255,255,255,0.62);
        }

        .stButton > button,
        .stDownloadButton > button {
            border-radius: 10px;
            font-weight: 650;
            transition: transform 120ms ease, box-shadow 120ms ease;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 8px 18px rgba(16,42,67,0.10);
        }

        [data-testid="stBaseButton-primary"] {
            border: 0;
            background: linear-gradient(100deg, var(--bk-navy-soft), #247a77);
        }

        [data-testid="stBaseButton-primary"],
        [data-testid="stBaseButton-primary"] p,
        [data-testid="stBaseButton-primary"] span {
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
        }

        [data-testid="stBaseButton-primary"]:disabled {
            border: 0 !important;
            background: linear-gradient(100deg, var(--bk-navy-soft), #247a77) !important;
            opacity: 1 !important;
        }

        [data-testid="stBaseButton-primary"]:disabled,
        [data-testid="stBaseButton-primary"]:disabled p,
        [data-testid="stBaseButton-primary"]:disabled span {
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
        }

        @media (max-width: 800px) {
            html { font-size: 16px; }
            .brand-hero { padding: 1.25rem; }
            .brand-hero::after { width: 62%; opacity: 0.20; }
            .brand-logo { width: 66px; height: 66px; }
            .workflow-strip { grid-template-columns: 1fr 1fr; }
        }

        @media (max-height: 800px) and (min-width: 801px) {
            section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
                padding-top: 0.4rem;
                padding-bottom: 0.45rem;
            }

            .sidebar-brand-panel {
                grid-template-columns: 46px minmax(0, 1fr);
                gap: 0.65rem;
                margin-bottom: 0.5rem;
                padding: 0.58rem 0.72rem;
            }

            .sidebar-brand-panel img {
                width: 46px;
                height: 46px;
            }

            .sidebar-brand-panel h2 { font-size: 1rem; }
            .sidebar-brand-panel p { font-size: 0.6rem; }
            .sidebar-env-intro { margin-bottom: 0.2rem; }
            .sidebar-nav-intro { margin-bottom: 0.4rem; }

            section[data-testid="stSidebar"] [data-testid="stPopover"] {
                margin-bottom: 0.35rem;
            }

            section[data-testid="stSidebar"] [role="radiogroup"] {
                gap: 0.3rem;
            }

            section[data-testid="stSidebar"] [role="radiogroup"] > label {
                min-height: 62px;
                padding-top: 0.56rem !important;
                padding-bottom: 0.56rem !important;
            }

            section[data-testid="stSidebar"] [role="radiogroup"] > label::before {
                top: 0.65rem;
            }

            section[data-testid="stSidebar"] [role="radiogroup"] > label::after {
                top: 1.95rem;
            }

            .sidebar-footer {
                padding: 0.58rem 0.78rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    """Render the full-width corporate project header."""
    st.markdown(
        f"""
        <div class="brand-hero">
            <img class="brand-logo" src="{_brand_logo_data_uri()}" alt="{BRAND_NAME} Logo">
            <div class="brand-copy">
                <div class="brand-kicker">PCR PRIMER EVALUATION SYSTEM</div>
                <h1 class="brand-title">{BRAND_NAME} <span>· fullpcr</span></h1>
                <p class="brand-subtitle">全库引物评测平台 · <b>QC / SPEC / in silico PCR</b></p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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


def _read_state_value(state, widget_key, canonical_key, default=""):
    """Read a value from *state*, preferring *widget_key* over *canonical_key*."""
    if widget_key in state:
        val = state[widget_key]
        if val is not None and val != "":
            return val
    if canonical_key in state:
        val = state[canonical_key]
        if val is not None and val != "":
            return val
    return default


def _build_pipeline_plan_from_state(state, common_params):
    """Build the five-step pipeline plan from current session state."""
    s1_primers = _read_state_value(state, "_wf_s1_primers", "wf_s1_primers")
    s1_outdir = _read_state_value(state, "_wf_s1_outdir", "wf_s1_outdir")
    s1_thermo = _read_state_value(state, "_wf_s1_thermo", "wf_s1_thermo", True)
    s1_dimer = _read_state_value(state, "_wf_s1_dimer", "wf_s1_dimer", True)
    s1_hairpin = _read_state_value(state, "_wf_s1_hairpin", "wf_s1_hairpin", True)
    s1_degen = _read_state_value(state, "_wf_s1_degen", "wf_s1_degen", True)
    s1_maxdeg = _read_state_value(state, "_wf_s1_maxdeg", "wf_s1_maxdeg", 256)
    s1_score = _read_state_value(state, "_wf_s1_score", "wf_s1_score", 5)
    s1_mismatch = _read_state_value(state, "_wf_s1_mismatch", "wf_s1_mismatch", 2)
    s1_dg = _read_state_value(state, "_wf_s1_dg", "wf_s1_dg", -5.0)
    s1_tm = _read_state_value(state, "_wf_s1_tm", "wf_s1_tm", 50.0)

    s2_qcdir = _read_state_value(state, "_wf_s2_qcdir", "wf_s2_qcdir")

    s3_primers = _read_state_value(state, "_wf_s3_primers", "wf_s3_primers")
    s3_database = _read_state_value(state, "_wf_s3_database", "wf_s3_database")
    s3_outdir = _read_state_value(state, "_wf_s3_outdir", "wf_s3_outdir")
    s3_tm = _read_state_value(state, "_wf_s3_tm", "wf_s3_tm", 50.0)
    s3_maxtm = _read_state_value(state, "_wf_s3_maxtm", "wf_s3_maxtm", 100.0)
    s3_manual_enabled = _read_state_value(
        state, "_wf_s3_manual_cpu_enabled", "wf_s3_manual_cpu_enabled", False
    )
    s3_manual_cpu = _read_state_value(state, "_wf_s3_cpu", "wf_s3_cpu", 4)
    s3_kvalue = _read_state_value(state, "_wf_s3_kvalue", "wf_s3_kvalue", 9)
    s3_cpu = resolve_spec_cpu_threads(
        manual_enabled=bool(s3_manual_enabled),
        manual_threads=int(s3_manual_cpu) if s3_manual_cpu is not None else None,
    )
    s3_force = _read_state_value(state, "_wf_s3_force", "wf_s3_force", True)

    s4_primers = _read_state_value(state, "_wf_s4_primers", "wf_s4_primers")
    s4_database = _read_state_value(state, "_wf_s4_database", "wf_s4_database")
    s4_taxonomy = _read_state_value(state, "_wf_s4_taxonomy", "wf_s4_taxonomy")
    s4_outdir = _read_state_value(state, "_wf_s4_outdir", "wf_s4_outdir")
    s4_summarize = _read_state_value(state, "_wf_s4_summarize", "wf_s4_summarize", True)
    s4_report = _read_state_value(state, "_wf_s4_report", "wf_s4_report", True)
    s4_force = _read_state_value(state, "_wf_s4_force", "wf_s4_force", True)

    s5_obipcr_dir = _read_state_value(state, "_wf_s5_obipcr_dir", "wf_s5_obipcr_dir")
    s5_qc_dir = _read_state_value(state, "_wf_s5_qc_dir", "wf_s5_qc_dir")
    s5_spec_dir = _read_state_value(state, "_wf_s5_spec_dir", "wf_s5_spec_dir")
    s5_outdir = _read_state_value(state, "_wf_s5_outdir", "wf_s5_outdir")

    return build_full_pipeline_plan(
        qc_pre_command=build_qc_pre_command(
            primers=str(s1_primers), outdir=str(s1_outdir),
            thermo=bool(s1_thermo), dimer=bool(s1_dimer),
            hairpin=bool(s1_hairpin), degen=bool(s1_degen),
            max_degenerate_variants=int(s1_maxdeg),
            score=int(s1_score), mismatch=int(s1_mismatch),
            dg=float(s1_dg), tm=float(s1_tm),
            timeout=None,
        ),
        qc_summary_command=build_qc_summary_command(qc_dir=str(s2_qcdir)),
        qc_spec_command=build_qc_spec_command(
            primers=str(s3_primers), database=str(s3_database),
            outdir=str(s3_outdir),
            min_size=common_params.get("min_size"),
            max_size=int(common_params.get("max_size", 500)),
            tm=float(common_params.get("spec_tm", 50.0)),
            max_tm=float(s3_maxtm),
            mismatch=common_params.get("spec_mismatch", 2),
            mis_start=common_params.get("spec_mis_start"),
            mis_end=common_params.get("spec_mis_end"),
            cpu=int(s3_cpu), kvalue=int(s3_kvalue),
            bind=bool(common_params.get("spec_bind", False)),
            cut_primer=bool(common_params.get("spec_cut_primer", False)),
            mono=common_params.get("spec_mono"),
            diva=common_params.get("spec_diva"),
            dntp=common_params.get("spec_dntp"),
            oligo=common_params.get("spec_oligo"),
            timeout=None,
            force=bool(s3_force),
        ),
        obipcr_command=build_obipcr_run_command(
            primers=str(s4_primers), database=str(s4_database),
            taxonomy=str(s4_taxonomy), outdir=str(s4_outdir),
            mismatches=str(common_params.get("obipcr_mismatches", "0,1,2")),
            circular=bool(common_params.get("circular", True)),
            summarize=bool(s4_summarize), report=bool(s4_report),
            force=bool(s4_force),
            timeout=None,
        ),
        final_report_command=build_final_report_command(
            obipcr_dir=str(s5_obipcr_dir), qc_dir=str(s5_qc_dir),
            spec_dir=str(s5_spec_dir), outdir=str(s5_outdir),
        ),
        qc_pre_timeout=None,
        qc_summary_timeout=None,
        qc_spec_timeout=None,
        obipcr_timeout=None,
        final_report_timeout=None,
    )


def _render_full_pipeline_outcome(outcome: dict | None) -> None:
    """Stateless render of a pipeline outcome dict.  Survives reruns."""
    if outcome is None:
        return
    status = outcome.get("status", "")
    if status == "PASS":
        st.success("完整分析已完成。")
    elif status == "TIMEOUT":
        st.error(outcome.get("message", "流程超时。"))
        if outcome.get("failed_step"):
            st.caption(f"超时步骤: {outcome['failed_step']}，后续步骤未执行。")
    elif status == "CANCELLED":
        st.warning(outcome.get("message", "分析已由用户终止。"))
        if outcome.get("failed_step"):
            st.caption(f"终止步骤: {outcome['failed_step']}，后续步骤未执行。")
    elif status == "FAIL":
        st.error(outcome.get("message", "流程失败。"))
        if outcome.get("failed_step"):
            st.caption(f"失败步骤: {outcome['failed_step']}，后续步骤未执行。")
    else:
        # Unknown status — treat as failure.
        st.warning(outcome.get("message", "流程状态未知。"))

    # Show "查看完整错误" button for FAIL/TIMEOUT background pipeline jobs
    if status in ("FAIL", "TIMEOUT"):
        job_id = st.session_state.get("full_pipeline_job_id", "")
        job = get_pipeline_job(
            st.session_state.get("project_output_root", "")
        ) if job_id else {}

        error_details = _extract_pipeline_error_details(outcome, job)
        if error_details is None:
            return  # PASS/CANCELLED handled above, defensive guard

        # Auto-popup: only once per job_id, via pending_error_dialog.
        # Trigger a full script rerun so the outer dialog renderer (outside
        # this fragment) gets a chance to open the dialog.  Dedup via
        # last_auto_shown_error_job_id prevents infinite rerun loops.
        if job_id and job_id != st.session_state.get("last_auto_shown_error_job_id", ""):
            st.session_state["last_auto_shown_error_job_id"] = job_id
            st.session_state["pending_error_dialog"] = error_details
            st.rerun()

        # Manual button: also routes through pending_error_dialog.
        # Trigger a full script rerun so the outer dialog renderer opens
        # the dialog immediately.  Does NOT touch last_auto_shown_error_job_id
        # so manual clicks never interfere with auto-popup dedup.
        if st.button("查看完整错误", key="view_full_error_pipeline"):
            st.session_state["pending_error_dialog"] = error_details
            st.rerun()


def _flag_value(cmd: list[str], flag: str) -> str | None:
    """Return the argument following *flag* in *cmd*, or None."""
    try:
        idx = cmd.index(flag)
        return cmd[idx + 1]
    except (ValueError, IndexError):
        return None


def _get_pipeline_rank_path() -> str | None:
    """Derive ``primer_rank.tsv`` path from the stored pipeline plan's s5 --outdir."""
    plan = st.session_state["full_pipeline_plan"] if "full_pipeline_plan" in st.session_state else None
    if plan is None:
        return None
    s5 = next((s for s in plan if s.get("key") == "s5"), None)
    if s5 is None:
        return None
    outdir = _flag_value(s5["command"], "--outdir")
    if outdir is None:
        return None
    return str(Path(outdir) / "primer_rank.tsv")


def _render_quick_recommendation(rank_result: dict | None = None) -> None:
    """Display a recommendation from loaded or just-produced ranking data."""
    if rank_result is None:
        outcome = (
            st.session_state.get("full_pipeline_result")
            if "full_pipeline_result" in st.session_state
            else None
        )
        if outcome is None or outcome.get("status") != "PASS":
            return

        rank_path = _get_pipeline_rank_path()
        if rank_path is None:
            st.info("无法确定 primer_rank.tsv 路径。")
            return
        rank_result = load_primer_rank(rank_path)
    if rank_result["status"] != "PASS" or rank_result["df"] is None:
        st.warning(f"primer_rank.tsv 不可用: {rank_result.get('error', '未知错误')}")
        return

    df = rank_result["df"]

    # Check required columns.
    required = ["primer_id", "final_score", "final_status"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.warning(f"primer_rank.tsv 缺少必要字段: {', '.join(missing)}")
        return

    ranks = summarize_primer_rank(df)

    st.divider()
    st.subheader("本次推荐结果")

    # Top primer.
    top_id = ranks.get("top_primer")
    top_score = ranks.get("top_final_score")
    if top_id is None or top_score is None:
        st.info("无法确定最高评分引物。")
        return

    # Look up the row for final_status, recommendation, reason.
    try:
        scores = pd.to_numeric(df["final_score"], errors="coerce")
        best_idx = scores.idxmax()
        if pd.isna(best_idx):
            st.info("final_score 无法解析。")
            return
        row = df.loc[best_idx]
    except (ValueError, KeyError):
        st.info("final_score 无法解析。")
        return

    fstatus = str(row.get("final_status", "NEEDS_REVIEW"))
    fstatus_cn = translate_recommendation(fstatus)
    rec = str(row.get("recommendation", "")) or "未提供"
    reason = str(row.get("reason", "")) or "未提供"

    # Status-dependent display.
    if fstatus == "RECOMMENDED":
        st.success(f"**最高评分引物:** {top_id}  ({fstatus_cn})")
    elif fstatus in ("ACCEPTABLE_WITH_WARNINGS", "NEEDS_REVIEW"):
        st.warning(f"**最高评分引物:** {top_id}  ({fstatus_cn})")
    else:
        st.error(f"**最高评分引物:** {top_id}  ({fstatus_cn}) — 建议人工检查或更换引物。")

    c1, c2 = st.columns(2)
    with c1:
        st.metric("最高综合得分", f"{top_score:.4f}")
    with c2:
        st.metric("推荐等级", fstatus_cn)

    st.caption(f"**推荐原因:** {reason}")
    if rec != reason:
        st.caption(f"**建议:** {rec}")


def _sync_pipeline_job_outcome(job: dict) -> dict | None:
    """Restore a terminal background job outcome into this GUI session."""
    outcome = job.get("outcome")
    if not isinstance(outcome, dict):
        return None
    for result_key, result_value in outcome.get("results", {}).items():
        st.session_state[result_key] = result_value
    st.session_state["full_pipeline_result"] = outcome
    st.session_state["full_pipeline_job_id"] = job.get("job_id")
    return outcome


_PIPELINE_STEP_LABELS = {
    "s1": "基础质控",
    "s2": "质控汇总",
    "s3": "特异性分析",
    "s4": "obipcr",
    "s5": "最终报告",
}


def _extract_pipeline_error_details(outcome: dict | None, job: dict) -> dict | None:
    """Centralised pipeline error-detail extraction.

    Returns ``None`` for PASS and CANCELLED (no error dialog needed).
    For FAIL / TIMEOUT returns a dict ready for the unified dialog.

    When *outcome* is ``None`` (background exception), the terminal *job*
    status and message are used as fallback so the dialog displays FAIL
    or TIMEOUT while retaining background error and traceback.
    """
    status = outcome.get("status", "") if outcome else job.get("status", "FAIL")

    if status in ("PASS", "CANCELLED"):
        return None

    job_id = job.get("job_id", "")
    bg_error = str(job.get("error", ""))
    bg_traceback = str(job.get("traceback", ""))

    failed_key = outcome.get("failed_step", "") if outcome else ""
    step_label = _PIPELINE_STEP_LABELS.get(failed_key, failed_key)

    # Try to locate the per-step result for the failed step.  Only use it
    # when the value is actually a dict; otherwise fall back through
    # outcome → job so the dialog always has a correct FAIL/TIMEOUT status.
    step_result = None
    if outcome and outcome.get("results") and failed_key:
        candidate = outcome["results"].get(f"wf_{failed_key}_result")
        if isinstance(candidate, dict):
            step_result = candidate

    if step_result is None:
        if outcome:
            step_result = {
                "status": outcome.get("status") or job.get("status", "FAIL"),
                "returncode": None,
                "command": [],
                "stderr": "",
                "stdout": "",
                "message": outcome.get("message") or job.get("error", ""),
            }
        else:
            # outcome=None or no per-step result: use terminal job status/message
            step_result = {
                "status": job.get("status", "FAIL"),
                "returncode": None,
                "command": [],
                "stderr": "",
                "stdout": "",
                "message": job.get("error", ""),
            }

    return build_execution_error_details(
        step_key=failed_key,
        step_label=step_label,
        result=step_result,
        job_id=job_id,
        background_error=bg_error,
        background_traceback=bg_traceback,
    )


def _parse_pipeline_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _format_pipeline_duration(seconds: float | int | None) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _duration_between(start: object, end: object) -> float | None:
    started = _parse_pipeline_time(start)
    finished = _parse_pipeline_time(end)
    if started is None or finished is None:
        return None
    return max(0.0, (finished - started).total_seconds())


def _render_pipeline_step_timings(job: dict, now: datetime) -> None:
    timings = job.get("step_timings")
    if not isinstance(timings, dict) or not timings:
        return
    items: list[str] = []
    for key, label in _PIPELINE_STEP_LABELS.items():
        timing = timings.get(key)
        if not isinstance(timing, dict):
            items.append(f"{label}：等待中")
            continue
        timing_status = str(timing.get("status", ""))
        elapsed = timing.get("elapsed_seconds")
        if timing_status == "RUNNING":
            elapsed = _duration_between(timing.get("started_at"), now.isoformat())
            items.append(f"{label}：{_format_pipeline_duration(elapsed)}（运行中）")
        else:
            items.append(f"{label}：{_format_pipeline_duration(elapsed)}")
    st.caption("　·　".join(items))


def _render_pipeline_job_progress(job: dict | None) -> None:
    """Render persisted progress without changing or restarting the job."""
    if not job:
        return
    status = str(job.get("status", ""))
    current = max(0, int(job.get("progress_current", 0) or 0))
    total = max(1, int(job.get("progress_total", 5) or 5))
    label = str(job.get("current_label") or "准备开始五步分析")
    now = datetime.now(timezone.utc)
    end_time = now.isoformat() if status == "RUNNING" else job.get("finished_at")
    total_elapsed = _duration_between(job.get("started_at"), end_time)
    if status == "RUNNING":
        text_parts = [f"已完成 {current}/{total} 步", f"当前：{label}"]
        if total_elapsed is not None:
            text_parts.append(f"总用时 {_format_pipeline_duration(total_elapsed)}")
        st.progress(
            min(current / total, 1.0),
            text=" · ".join(text_parts),
        )
        st.info(f"正在进行：{label}")
        _render_pipeline_step_timings(job, now)
        return

    if status == "PASS":
        suffix = (
            f" · 总用时 {_format_pipeline_duration(total_elapsed)}"
            if total_elapsed is not None else ""
        )
        st.progress(1.0, text=f"五步分析全部完成{suffix}")
        _render_pipeline_step_timings(job, now)
        st.success("分析完成，结果已保存。")
        return
    if status == "TIMEOUT":
        st.progress(min(current / total, 1.0), text=f"分析超时 · {label}")
        _render_pipeline_step_timings(job, now)
        return
    if status == "CANCELLED":
        st.progress(min(current / total, 1.0), text=f"分析已由用户终止 · {label}")
        _render_pipeline_step_timings(job, now)
        return
    if status == "FAIL" and job.get("state_error"):
        st.error(str(job.get("error", "任务状态不可用。")))


@st.fragment(run_every=1.0)
def _render_pipeline_job_controls(
    project_root: str,
    plan: list[dict],
    *,
    base_disabled: bool,
) -> None:
    """Submit at most one job and poll its stable persisted state."""
    job = get_pipeline_job(project_root) if project_root else None
    running = bool(job and job.get("status") == "RUNNING")

    # Skip restoring outcome for a terminal job that was dismissed via
    # re-validation — the user has explicitly invalidated those results.
    dismissed = st.session_state.get("dismissed_terminal_job_id", "")
    if dismissed and job and not running and job.get("job_id") == dismissed:
        pass  # Suppress outcome restoration for this job
    elif job and not running:
        _sync_pipeline_job_outcome(job)

    clicked = st.button(
        "分析正在运行" if running else "一键运行完整分析",
        type="primary",
        key="full_pipeline_run_btn",
        disabled=base_disabled or running,
    )
    if clicked:
        # New job: clear any previous dismissal marker
        st.session_state.pop("dismissed_terminal_job_id", None)
        st.session_state["full_pipeline_plan"] = plan
        for result_key in [
            "wf_s1_result",
            "wf_s2_result",
            "wf_s3_result",
            "wf_s4_result",
            "wf_s5_result",
            "full_pipeline_result",
        ]:
            st.session_state.pop(result_key, None)
        _clear_result_download_state()
        job = start_pipeline_job(project_root, plan)
        running = bool(job and job.get("status") == "RUNNING")
        if not job.get("started", False) and running:
            st.info("该项目的分析已在运行，本次没有重复提交。")
        elif job.get("state_error"):
            st.error(str(job.get("error", "无法启动后台分析任务。")))

    _render_pipeline_job_progress(job)
    if running and job and job.get("suspected_stuck") is True:
        last_activity = str(job.get("last_activity_at") or "未知")
        last_check = str(job.get("last_health_check_at") or "未知")
        st.warning(
            f"当前步骤“{job.get('current_label', '未知')}”已连续 10 分钟未检测到 "
            f"CPU 或输出变化，可能已经卡住。最后活动：{last_activity}；"
            f"最近检测：{last_check}。"
        )
        if st.button(
            "终止当前分析",
            key=f"cancel_pipeline_{job.get('job_id', 'unknown')}",
        ):
            cancel_result = request_pipeline_cancel(
                project_root, str(job.get("job_id", ""))
            )
            if cancel_result.get("cancelled"):
                st.warning("已提交终止请求，正在清理当前分析进程。")
            else:
                st.error(str(cancel_result.get("error", "无法终止当前分析。")))
    if job and job.get("status") != "RUNNING":
        dismissed = st.session_state.get("dismissed_terminal_job_id", "")
        if dismissed and job.get("job_id") == dismissed:
            # Suppress all sync, state writes, and error dialogs for a
            # terminal job the user explicitly dismissed via re-validation.
            pass
        else:
            # Always store job_id before inspecting outcome.
            st.session_state["full_pipeline_job_id"] = job.get("job_id", "")
            outcome = _sync_pipeline_job_outcome(job)
            if outcome is not None:
                _render_full_pipeline_outcome(outcome)
                if outcome.get("status") == "PASS":
                    st.info("分析结果已生成，请前往左侧「结果总览」查看推荐与详细结果。")
            elif job.get("status") in ("FAIL", "TIMEOUT"):
                # Background exception: no outcome dict, but error + traceback available.
                # Build synthetic outcome so the error dialog can render.
                synthetic = {
                    "status": job.get("status", "FAIL"),
                    "failed_step": "",
                    "results": {},
                    "message": job.get("error", "后台任务异常。"),
                }
                st.session_state["full_pipeline_result"] = synthetic
                _render_full_pipeline_outcome(synthetic)
    elif job is None:
        # Preserve results created before the persistent job manager existed,
        # or injected by an existing advanced workflow/session.
        previous = st.session_state.get("full_pipeline_result")
        if isinstance(previous, dict):
            _render_full_pipeline_outcome(previous)
            if previous.get("status") == "PASS":
                st.info("分析结果已生成，请前往左侧「结果总览」查看推荐与详细结果。")


def _render_quick_analysis(common_params) -> None:
    """Render the one-click pipeline runner section."""
    st.subheader("快速分析（推荐）")
    st.caption("系统将依次完成基础质控、质控汇总、特异性分析、全库模拟 PCR 和最终综合报告。")

    inputs_ok = st.session_state.get("inputs_validated", False)
    plan = None
    if inputs_ok:
        plan = _build_pipeline_plan_from_state(st.session_state, common_params)

    with st.expander("执行设置与五步命令"):
        ensure_widget_key(st.session_state, "_workflow_dry_run")
        dry_run = st.toggle(
            "仅预览命令，不执行",
            key="_workflow_dry_run",
            help="开启后，下方按钮只生成执行计划，不会运行分析。",
        )
        if dry_run:
            st.caption("预览模式已开启：可以检查五步命令，不会启动分析。")

        st.markdown("**五步执行命令**")
        if plan is None:
            st.info("请先保存并验证输入文件。")
        else:
            for step_data in plan:
                timeout = step_data.get("timeout")
                label = f"**{step_data['label']}**"
                if timeout is not None:
                    label += f"（上限 {timeout} 秒）"
                st.caption(label)
                st.code(" ".join(step_data["command"]), language="bash")

    btn_disabled = not inputs_ok
    if inputs_ok and not dry_run:
        env = st.session_state["environment_status"] if "environment_status" in st.session_state else {}
        obi_ok = (env.get("obipcr") or {}).get("available", False)
        mfe_ok = (env.get("mfeprimer") or {}).get("available", False)
        if not obi_ok or not mfe_ok:
            btn_disabled = True
            missing = []
            if not obi_ok:
                missing.append("obipcr")
            if not mfe_ok:
                missing.append("MFEprimer")
            st.warning(
                f"缺少外部依赖: {', '.join(missing)}。"
                f"请安装后再运行，或开启「仅预览命令」模式查看计划。"
            )

    if dry_run:
        if st.button(
            "生成五步命令预览",
            type="primary",
            key="full_pipeline_run_btn",
            disabled=btn_disabled,
        ):
            if not inputs_ok:
                st.warning("请先保存并验证输入文件。")
                return
            if plan is None:
                st.warning("无法生成执行计划，请检查工作流路径。")
                return
            st.session_state["full_pipeline_plan"] = plan
            st.info("仅预览模式：未执行任何命令。")
        return

    project_root = str(st.session_state.get("project_output_root", ""))
    if plan is None:
        # Keep a stable disabled control before validation.
        st.button(
            "一键运行完整分析",
            type="primary",
            key="full_pipeline_run_btn",
            disabled=True,
        )
        return
    _render_pipeline_job_controls(
        project_root,
        plan,
        base_disabled=btn_disabled or not bool(project_root),
    )


def _render_advanced_workflow_tabs(common_params) -> None:
    """Render the five-step manual workflow status row and tabs."""
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


def _clear_result_download_state() -> None:
    """Clear download-related state when analysis results may change."""
    for k in (
        "results_archive_info",
        "results_archive_root",
        "results_archive_selection",
        "res_rank_result",
        "res_combined_result",
        "res_qc_result",
        "res_spec_result",
        "res_loaded_dirs",
        "res_loaded_project_root",
        "res_loaded_project_label",
    ):
        st.session_state.pop(k, None)


_PROJECT_RESULT_FILES = (
    Path("final_results/primer_rank.tsv"),
    Path("final_results/final_report.md"),
    Path("obipcr_results/combined_summary.tsv"),
    Path("obipcr_results/report.md"),
    Path("qc_results/primer_qc_summary.tsv"),
    Path("qc_spec_results/spec/primer_spec.tsv"),
)


def _project_result_mtime(project: Path) -> float:
    """Return the latest known result timestamp for a project."""
    timestamps: list[float] = []
    try:
        timestamps.append(project.stat().st_mtime)
    except OSError:
        pass
    for relative_path in _PROJECT_RESULT_FILES:
        try:
            candidate = project / relative_path
            if candidate.is_file() and not candidate.is_symlink():
                timestamps.append(candidate.stat().st_mtime)
        except OSError:
            continue
    return max(timestamps, default=0.0)


def _project_time_name(project: Path) -> str:
    """Return the user-facing ``YYYY_MM_DD_HH_MM`` project name."""
    timestamp = _project_result_mtime(project)
    return datetime.fromtimestamp(timestamp).strftime("%Y_%m_%d_%H_%M")


def _available_project_roots() -> dict[str, str]:
    """Return selectable current/history projects, newest first.

    The current session project is kept first even when it lives outside the
    configured data root (useful for an administrator-provided project).  Run
    history is discovered from ``FULLPCR_DATA_DIR/runs`` and only directories
    containing a known result file are shown.
    """
    current_raw = st.session_state.get("project_output_root")
    current: Path | None = None
    if current_raw:
        candidate = Path(str(current_raw))
        if candidate.exists() and candidate.is_dir() and not candidate.is_symlink():
            current = candidate.resolve()

    candidates: list[Path] = []
    if current is not None:
        candidates.append(current)

    runs_dir = get_data_root() / "runs"
    if runs_dir.exists() and runs_dir.is_dir() and not runs_dir.is_symlink():
        try:
            history = sorted(
                (
                    child
                    for child in runs_dir.iterdir()
                    if child.is_dir()
                    and not child.is_symlink()
                    and any((child / rel).is_file() for rel in _PROJECT_RESULT_FILES)
                ),
                key=_project_result_mtime,
                reverse=True,
            )
        except OSError:
            history = []
        for child in history:
            resolved = child.resolve()
            if resolved not in candidates:
                candidates.append(resolved)

    options: dict[str, str] = {}
    for project in candidates:
        prefix = "当前项目 · " if current is not None and project == current else "历史项目 · "
        base_label = f"{prefix}{_project_time_name(project)}"
        label = base_label
        duplicate_index = 2
        while label in options:
            label = f"{base_label}（{duplicate_index}）"
            duplicate_index += 1
        options[label] = str(project)
    return options


def _select_project_root(*, key: str = "_selected_result_project") -> str | None:
    """Render a real project selector and return the selected workspace root."""
    options = _available_project_roots()
    if not options:
        return None
    labels = list(options)
    current_raw = st.session_state.get("project_output_root")
    current_root = ""
    if current_raw:
        candidate = Path(str(current_raw))
        if candidate.exists() and candidate.is_dir() and not candidate.is_symlink():
            current_root = str(candidate.resolve())
    current_marker_key = f"{key}_current_root"
    if current_root and st.session_state.get(current_marker_key) != current_root:
        current_label = next(
            (label for label, value in options.items() if value == current_root),
            labels[0],
        )
        st.session_state[key] = current_label
        st.session_state[current_marker_key] = current_root
    elif st.session_state.get(key) not in options:
        st.session_state[key] = labels[0]
    selected = st.selectbox(
        "选择分析项目",
        labels,
        key=key,
        help="显示当前项目和服务器数据目录中已有结果的历史项目。",
    )
    return options[selected]


def _project_label_for_root(project_root: str | Path) -> str:
    """Return the same time-based label used by the project selector."""
    project = Path(project_root).resolve()
    for label, path in _available_project_roots().items():
        if Path(path).resolve() == project:
            return label
    return f"项目 · {_project_time_name(project)}"


_ARCHIVE_GROUPS = {
    "MFEprimer 基础质控结果": "qc_results",
    "MFEprimer 特异性分析结果": "qc_spec_results",
    "obipcr 扩增结果": "obipcr_results",
    "综合排名与最终报告": "final_results",
}


def _render_result_downloads(project_root: str) -> None:
    """Render checkbox-style result archives without project input files."""
    st.subheader("结果下载")

    root = Path(project_root)

    # ── selected results ZIP ─────────────────────────────────────────
    available_groups = [
        label
        for label, dirname in _ARCHIVE_GROUPS.items()
        if (root / dirname).is_dir()
        and any(item.is_file() for item in (root / dirname).rglob("*"))
    ]
    group_options = available_groups
    group_project_key = "_results_zip_groups_project_root"
    if st.session_state.get(group_project_key) != project_root:
        st.session_state["_results_zip_groups"] = []
        st.session_state[group_project_key] = project_root
    existing = st.session_state.get("_results_zip_groups", [])
    valid_existing = [item for item in existing if item in group_options]
    st.session_state["_results_zip_groups"] = valid_existing
    selected_groups = st.multiselect(
        "选择要打包的内容",
        group_options,
        key="_results_zip_groups",
        help="可选择一个或多个分析结果类别；不会包含本次分析的输入文件。",
    )
    build_clicked = st.button(
        "生成或刷新所选结果 ZIP",
        key="build_results_zip_btn",
        disabled=not selected_groups,
    )
    if build_clicked:
        included_dirs = [_ARCHIVE_GROUPS[label] for label in selected_groups]
        all_available_selected = set(selected_groups) == set(available_groups)
        archive_name = (
            "fullpcr_all_results.zip"
            if all_available_selected
            else "fullpcr_selected_results.zip"
        )
        zip_info = build_results_archive(
            project_root,
            included_dirs=included_dirs,
            archive_name=archive_name,
        )
        st.session_state["results_archive_info"] = zip_info
        st.session_state["results_archive_root"] = project_root
        st.session_state["results_archive_selection"] = tuple(selected_groups)

    zip_info = st.session_state.get("results_archive_info")
    zip_root = st.session_state.get("results_archive_root")
    zip_selection = st.session_state.get("results_archive_selection")

    # Only show the download button if the ZIP was built from the current
    # project root (stale info from a different project is ignored).
    if (
        zip_info is not None
        and zip_root == project_root
        and zip_selection == tuple(selected_groups)
    ):
        if zip_info["status"] == "PASS":
            try:
                data = Path(zip_info["path"]).read_bytes()
                st.success(
                    f"ZIP 已就绪：{zip_info['file_count']} 个文件，"
                    f"{zip_info['size']:,} 字节"
                )
                st.download_button(
                    label="下载所选结果 ZIP",
                    data=data,
                    file_name=zip_info["file_name"],
                    mime="application/zip",
                    key="dl_results_zip",
                )
            except OSError as exc:
                st.warning(f"ZIP 文件暂不可读取：{exc}")
        else:
            st.warning(f"结果 ZIP 生成失败：{zip_info['error']}")


def _render_analysis_workbench() -> None:
    """分析工作台：输入 → 验证 → 可选分步设置 → 一键分析。
    高级五步手工工作流默认隐藏。"""
    with st.container(key="analysis_workbench_compact"):
        st.markdown(
            """
            <div class="workflow-strip">
                <div class="workflow-step"><b>01</b><span>填写或上传输入</span></div>
                <div class="workflow-step"><b>02</b><span>保存并验证</span></div>
                <div class="workflow-step"><b>03</b><span>一键运行完整分析</span></div>
                <div class="workflow-step"><b>04</b><span>前往结果总览</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        _render_project_inputs()
        _render_input_validation_snapshot()

        st.markdown("### 分析参数")
        st.caption("不修改时自动使用默认参数。")
        common_params = _render_analysis_parameter_controls()

        show_advanced = st.toggle(
            "显示高级分步工作流",
            key="_show_advanced_workflow",
            value=st.session_state.get("_show_advanced_workflow", False),
        )
        if show_advanced:
            _render_advanced_workflow_tabs(common_params)

        # 快速分析是工作台的最后一个操作区；结果统一在「结果总览」展示。
        _render_quick_analysis(common_params)


_RESULT_SECTION_OPTIONS = [
    "obipcr 汇总",
    "MFEprimer 质控",
    "MFEprimer 特异性",
]


def _get_pipeline_result_directories() -> tuple[str, str, str, str] | None:
    """Return result directories from the exact commands used by the pipeline."""
    plan = st.session_state.get("full_pipeline_plan")
    if not plan:
        return None

    step_flags = [
        ("s5", "--outdir"),
        ("s4", "--outdir"),
        ("s1", "--outdir"),
        ("s3", "--outdir"),
    ]
    directories: list[str] = []
    for step_key, flag in step_flags:
        step = next((item for item in plan if item.get("key") == step_key), None)
        if step is None:
            return None
        directory = _flag_value(step.get("command", []), flag)
        if not directory:
            return None
        directories.append(directory)
    return tuple(directories)  # type: ignore[return-value]


def _load_results_overview(
    final_results_dir: str,
    obipcr_results_dir: str,
    qc_results_dir: str,
    qc_spec_results_dir: str,
) -> None:
    """Load the four overview inputs and persist them across Streamlit reruns."""
    st.session_state["res_rank_result"] = load_primer_rank(
        str(Path(final_results_dir) / "primer_rank.tsv")
    )
    st.session_state["res_combined_result"] = load_tsv_file(
        str(Path(obipcr_results_dir) / "combined_summary.tsv")
    )
    st.session_state["res_qc_result"] = load_tsv_file(
        str(Path(qc_results_dir) / "primer_qc_summary.tsv")
    )
    st.session_state["res_spec_result"] = load_tsv_file(
        str(Path(qc_spec_results_dir) / "spec" / "primer_spec.tsv")
    )
    st.session_state["res_loaded_dirs"] = (
        final_results_dir,
        obipcr_results_dir,
        qc_results_dir,
        qc_spec_results_dir,
    )


def _render_rank_overview(
    rank_result: dict,
    final_results_dir: str,
    *,
    inline: bool = False,
) -> None:
    """Render complete ranking details in one collapsed, non-duplicating area."""
    if rank_result["status"] != "PASS" or rank_result["df"] is None:
        st.warning(
            f"primer_rank.tsv 不可用: {rank_result.get('error', '未知错误')}"
        )
        return

    rank_df = rank_result["df"]
    rank_summary = summarize_primer_rank(rank_df)
    section = (
        st.container()
        if inline
        else st.expander("查看完整排名与状态", expanded=False)
    )
    with section:
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
            st.metric("推荐引物数量", rank_summary.get("recommended_count", 0))
        with mc4:
            st.metric(
                "不推荐引物数量",
                rank_summary.get("not_recommended_count", 0),
            )

        statuses = rank_summary.get("final_statuses", {})
        if statuses:
            st.markdown("**推荐等级分布**")
            status_cols = st.columns(len(statuses))
            for index, (status_name, count) in enumerate(sorted(statuses.items())):
                with status_cols[index]:
                    st.metric(translate_recommendation(status_name), count)

        st.subheader("引物综合排名表")
        display_df = rank_df.copy()
        if "final_status" in display_df.columns:
            display_df["final_status"] = display_df["final_status"].apply(
                translate_recommendation
            )
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        st.subheader("质控与特异性状态")
        status_columns = [
            "primer_id",
            "qc_status",
            "spec_status",
            "final_status",
            "recommendation",
        ]
        available = [column for column in status_columns if column in rank_df.columns]
        if available:
            status_df = rank_df[available].copy()
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
            st.dataframe(status_df, use_container_width=True, hide_index=True)
        else:
            st.info("primer_rank.tsv 中没有状态字段。")

        primer_rank_path = Path(final_results_dir) / "primer_rank.tsv"
        if primer_rank_path.is_file():
            st.download_button(
                label="下载引物排名表 (primer_rank.tsv)",
                data=primer_rank_path.read_bytes(),
                file_name="primer_rank.tsv",
                mime="text/tab-separated-values",
                key="dl_primer_rank",
            )


def _render_result_tsv_section(
    heading: str,
    file_name: str,
    result: dict,
    *,
    inline: bool = False,
) -> None:
    """Render one selectable raw-result summary."""
    st.header(heading)
    if result["status"] == "PASS" and result["df"] is not None:
        st.caption(f"{result['row_count']} 行, {len(result['columns'])} 列")
        if inline:
            st.dataframe(result["df"], use_container_width=True, hide_index=True)
        else:
            with st.expander(f"查看 {file_name}", expanded=False):
                st.dataframe(
                    result["df"], use_container_width=True, hide_index=True
                )
    else:
        st.info(f"{file_name} 不可用: {result.get('error', '未知错误')}")


def _analysis_status_cn(value: object) -> str:
    """Translate common report status codes without changing source files."""
    mapping = {
        "PASS": "正常",
        "RECOMMENDED": "推荐",
        "ACCEPTABLE_WITH_WARNINGS": "可用但有警告",
        "NOT_RECOMMENDED": "不推荐",
        "NEEDS_REVIEW": "需要人工复核",
        "WARN_TM_DIFF": "Tm 差异警告",
        "WARN_NO_AMP": "未检出扩增产物",
        "WARN": "警告",
        "FAIL": "异常",
        "NA": "未提供",
    }
    text = str(value)
    return mapping.get(text, text)


def _render_chinese_project_report(project_root: str) -> None:
    """Render a detailed Chinese interpretation of all four analysis stages."""
    root = Path(project_root)
    rank_result = load_primer_rank(str(root / "final_results" / "primer_rank.tsv"))
    qc_result = load_tsv_file(
        str(root / "qc_results" / "primer_qc_summary.tsv")
    )
    spec_result = load_tsv_file(
        str(root / "qc_spec_results" / "spec" / "primer_spec.tsv")
    )
    combined_result = load_tsv_file(
        str(root / "obipcr_results" / "combined_summary.tsv")
    )

    st.info(
        "这是一份 **fullpcr 综合报告**：综合 MFEprimer 基础质控、"
        "MFEprimer 特异性分析、obipcr 全库模拟扩增和最终排名。"
    )

    st.markdown("#### 综合结论")
    if rank_result["status"] == "PASS" and rank_result["df"] is not None:
        rank_df = rank_result["df"].copy()
        summary = summarize_primer_rank(rank_df)
        top_primer = summary.get("top_primer")
        top_score = summary.get("top_final_score")
        top_row = (
            rank_df.loc[rank_df["primer_id"].astype(str) == str(top_primer)]
            if top_primer is not None and "primer_id" in rank_df.columns
            else pd.DataFrame()
        )
        top_status = ""
        top_reason = ""
        if not top_row.empty:
            top_status = _analysis_status_cn(top_row.iloc[0].get("final_status", ""))
            top_reason = str(top_row.iloc[0].get("reason", "")).strip()

        col1, col2, col3 = st.columns(3)
        col1.metric("综合排名第一", top_primer or "暂无")
        col2.metric("综合得分", f"{top_score:.4f}" if top_score is not None else "暂无")
        col3.metric("综合判断", top_status or "暂无")
        if top_primer:
            conclusion = f"本次综合表现最好的引物是 **{top_primer}**"
            if top_reason:
                conclusion += f"。主要依据：{top_reason}"
            st.success(conclusion)

        columns = [
            name
            for name in (
                "primer_id",
                "final_score",
                "final_status",
                "qc_status",
                "spec_status",
                "obipcr_unique_species_count",
                "obipcr_species_resolution_rate",
                "reason",
            )
            if name in rank_df.columns
        ]
        display_df = rank_df[columns].copy()
        for status_column in ("final_status", "qc_status", "spec_status"):
            if status_column in display_df.columns:
                display_df[status_column] = display_df[status_column].map(
                    _analysis_status_cn
                )
        display_df = display_df.rename(
            columns={
                "primer_id": "引物",
                "final_score": "综合得分",
                "final_status": "综合判断",
                "qc_status": "基础质控",
                "spec_status": "特异性分析",
                "obipcr_unique_species_count": "覆盖物种数",
                "obipcr_species_resolution_rate": "物种分辨率",
                "reason": "说明",
            }
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info(
            "综合排名暂不可用："
            f"{rank_result.get('error', '未生成 primer_rank.tsv')}"
        )

    st.markdown("#### MFEprimer 基础质控解读")
    if qc_result["status"] == "PASS" and qc_result["df"] is not None:
        qc_df = qc_result["df"].copy()
        if "qc_status" in qc_df.columns:
            qc_statuses = qc_df["qc_status"].astype(str)
            pass_count = int((qc_statuses == "PASS").sum())
            warning_count = int((qc_statuses != "PASS").sum())
            st.info(
                f"共检查 {len(qc_df)} 条引物：{pass_count} 条基础质控正常，"
                f"{warning_count} 条存在需要关注的热力学或结构警告。"
            )
        qc_columns = [
            name
            for name in (
                "primer_id",
                "forward_tm",
                "reverse_tm",
                "tm_difference",
                "forward_gc",
                "reverse_gc",
                "dimer_count",
                "forward_hairpin_count",
                "reverse_hairpin_count",
                "qc_status",
                "qc_reason",
            )
            if name in qc_df.columns
        ]
        qc_display = qc_df[qc_columns].copy()
        if "qc_status" in qc_display.columns:
            qc_display["qc_status"] = qc_display["qc_status"].map(
                _analysis_status_cn
            )
        qc_display = qc_display.rename(
            columns={
                "primer_id": "引物",
                "forward_tm": "前向 Tm(°C)",
                "reverse_tm": "反向 Tm(°C)",
                "tm_difference": "Tm 差值(°C)",
                "forward_gc": "前向 GC(%)",
                "reverse_gc": "反向 GC(%)",
                "dimer_count": "二聚体数",
                "forward_hairpin_count": "前向发卡数",
                "reverse_hairpin_count": "反向发卡数",
                "qc_status": "质控判断",
                "qc_reason": "说明",
            }
        )
        st.dataframe(qc_display, use_container_width=True, hide_index=True)
        st.caption(
            "解释：前后向引物 Tm 越接近，通常越容易采用同一退火条件；"
            "二聚体和发卡结构可能降低有效扩增。警告表示需要关注，不等于一定不能使用。"
        )
    else:
        st.info(
            "MFEprimer 基础质控汇总暂不可用："
            f"{qc_result.get('error', '未生成 primer_qc_summary.tsv')}"
        )

    st.markdown("#### MFEprimer 特异性分析解读")
    if spec_result["status"] == "PASS" and spec_result["df"] is not None:
        spec_df = spec_result["df"].copy()
        status_column = "status" if "status" in spec_df.columns else "spec_status"
        if status_column in spec_df.columns:
            status_values = spec_df[status_column].astype(str)
            pass_count = int((status_values == "PASS").sum())
            no_amp_count = int((status_values == "WARN_NO_AMP").sum())
            st.info(
                f"共分析 {len(spec_df)} 条引物：{pass_count} 条通过特异性分析；"
                f"{no_amp_count} 条未检出符合条件的扩增产物。"
            )
        spec_columns = [
            name
            for name in (
                "primer_id",
                "spec_amplicon_count",
                "unique_reference_count",
                "unique_species_count",
                "min_amplicon_size",
                "max_amplicon_size",
                "mean_amplicon_size",
                "spec_reference_fraction",
                status_column,
                "reason",
            )
            if name in spec_df.columns
        ]
        spec_display = spec_df[spec_columns].copy()
        if status_column in spec_display.columns:
            spec_display[status_column] = spec_display[status_column].map(
                _analysis_status_cn
            )
        spec_display = spec_display.rename(
            columns={
                "primer_id": "引物",
                "spec_amplicon_count": "扩增产物数",
                "unique_reference_count": "覆盖参考序列数",
                "unique_species_count": "覆盖物种数",
                "min_amplicon_size": "最短片段(bp)",
                "max_amplicon_size": "最长片段(bp)",
                "mean_amplicon_size": "平均片段(bp)",
                "spec_reference_fraction": "参考序列覆盖率",
                status_column: "特异性判断",
                "reason": "说明",
            }
        )
        st.dataframe(spec_display, use_container_width=True, hide_index=True)
        st.caption(
            "解释：MFEprimer 会基于引物结合、Tm 和错配条件筛选可能扩增的参考序列。"
            "用于宏条形码时，覆盖多个目标物种通常是设计目标；"
            "“未检出扩增产物”需要结合参数、数据库覆盖度和 obipcr 结果一起判断。"
        )
    else:
        st.info(
            "MFEprimer 特异性汇总暂不可用："
            f"{spec_result.get('error', '未生成 primer_spec.tsv')}"
        )

    st.markdown("#### obipcr 扩增结果解读")
    if combined_result["status"] == "PASS" and combined_result["df"] is not None:
        combined_df = combined_result["df"].copy()
        required = {"primer_id", "unique_species_count", "amplicon_count"}
        if required.issubset(combined_df.columns):
            combined_df["_species"] = pd.to_numeric(
                combined_df["unique_species_count"], errors="coerce"
            ).fillna(-1)
            combined_df["_amplicons"] = pd.to_numeric(
                combined_df["amplicon_count"], errors="coerce"
            ).fillna(-1)
            best_rows = (
                combined_df.sort_values(
                    ["primer_id", "_species", "_amplicons"],
                    ascending=[True, False, False],
                )
                .groupby("primer_id", as_index=False)
                .head(1)
            )
            best_coverage = best_rows.sort_values(
                ["_species", "_amplicons"], ascending=False
            ).iloc[0]
            st.info(
                f"按每条引物的最佳错配条件比较，**{best_coverage['primer_id']}** "
                f"覆盖物种数最高（{int(best_coverage['_species'])} 个），"
                f"共检出 {int(best_coverage['_amplicons'])} 个扩增产物。"
            )
            columns = [
                name
                for name in (
                    "primer_id",
                    "mismatch",
                    "amplicon_count",
                    "unique_species_count",
                    "species_level_unique_resolution_rate",
                    "mean_amplicon_length",
                    "missing_taxonomy_count",
                )
                if name in best_rows.columns
            ]
            display_df = best_rows[columns].rename(
                columns={
                    "primer_id": "引物",
                    "mismatch": "最佳错配数",
                    "amplicon_count": "扩增产物数",
                    "unique_species_count": "覆盖物种数",
                    "species_level_unique_resolution_rate": "物种分辨率",
                    "mean_amplicon_length": "平均扩增长度(bp)",
                    "missing_taxonomy_count": "缺失分类信息数",
                }
            )
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            st.caption(
                "解释：覆盖物种数反映可检出的物种范围；物种分辨率越接近 1，"
                "代表扩增序列区分物种的能力越强。计算结果仍需结合湿实验验证。"
            )
        else:
            st.info("obipcr 汇总文件存在，但缺少生成中文解读所需的字段。")
    else:
        st.info(
            "obipcr 汇总暂不可用："
            f"{combined_result.get('error', '未生成 combined_summary.tsv')}"
        )

    st.markdown("#### 结果使用建议")
    st.markdown(
        "- 优先比较综合得分、覆盖物种数和物种分辨率，不要只看单一指标。\n"
        "- 对“可用但有警告”的引物，重点检查表中的 Tm 差值、无扩增或覆盖不足原因。\n"
        "- 数据库完整度和分类信息会直接影响覆盖率结论；最终选择仍需湿实验验证。"
    )

    final_report = load_markdown_file(str(root / "final_results" / "final_report.md"))
    obipcr_report = load_markdown_file(str(root / "obipcr_results" / "report.md"))
    st.caption(
        "下方两个文件是程序生成的原始 Markdown：fullpcr 综合报告整合全部分析，"
        "obipcr 独立报告只记录模拟扩增结果。"
    )
    download_columns = st.columns(2)
    if final_report["status"] == "PASS" and final_report["content"]:
        with download_columns[0]:
            st.download_button(
                "下载 fullpcr 综合报告（原始 Markdown）",
                data=final_report["content"],
                file_name="final_report.md",
                mime="text/markdown",
                key="dl_final_report",
            )
    if obipcr_report["status"] == "PASS" and obipcr_report["content"]:
        with download_columns[1]:
            st.download_button(
                "下载 obipcr 独立报告（原始 Markdown）",
                data=obipcr_report["content"],
                file_name="obipcr_report.md",
                mime="text/markdown",
                key="dl_obipcr_report",
            )


def _render_reports_and_downloads() -> None:
    """Render a compact reports-first page for one selected project."""
    st.header("报告与下载")
    st.caption("先查看中文结果解读，再按需要下载原始文件或结果 ZIP。")

    project_root = _select_project_root()
    if project_root is None:
        st.info("尚未发现可用项目。请先在「分析工作台」保存输入并完成分析。")
        return

    with st.expander("查看中文分析报告", expanded=False):
        if st.button("加载中文报告", type="primary", key="rpt_load_btn"):
            st.session_state["rpt_loaded_project_root"] = project_root
        if st.session_state.get("rpt_loaded_project_root") == project_root:
            _render_chinese_project_report(project_root)
        else:
            st.caption("点击按钮后显示中文综合结论与 obipcr 扩增结果解读。")

    _render_result_downloads(project_root)


def _remember_result_section_selection() -> None:
    """Persist the detail selector even while the Results page is not rendered."""
    st.session_state["res_visible_sections"] = list(
        st.session_state.get("_res_visible_sections", ["obipcr 汇总"])
    )


def _render_results_overview() -> None:
    """Render results produced by the workbench or a selected history project."""
    st.header("结果总览")
    st.markdown("查看本次推荐、引物综合排名和可选择的详细分析结果。")

    outcome = st.session_state.get("full_pipeline_result")

    st.markdown("#### 加载当前或历史项目结果")
    selected_project = _select_project_root()
    if selected_project is None:
        st.caption("服务器数据目录中暂未发现可加载的分析结果。")
        manual_load = False
    else:
        manual_load = st.button(
            "加载所选项目", type="primary", key="res_load_btn"
        )

    if manual_load and selected_project is not None:
        selected_root = Path(selected_project)
        _load_results_overview(
            str(selected_root / "final_results"),
            str(selected_root / "obipcr_results"),
            str(selected_root / "qc_results"),
            str(selected_root / "qc_spec_results"),
        )
        st.session_state["res_loaded_project_root"] = str(selected_root)
        st.session_state["res_loaded_project_label"] = st.session_state.get(
            "_selected_result_project",
            _project_label_for_root(selected_root),
        )

    pipeline_dirs = _get_pipeline_result_directories()
    has_loaded_results = "res_rank_result" in st.session_state
    if (
        not has_loaded_results
        and outcome
        and outcome.get("status") == "PASS"
        and pipeline_dirs is not None
    ):
        _load_results_overview(*pipeline_dirs)
        pipeline_root = str(Path(pipeline_dirs[0]).parent)
        st.session_state["res_loaded_project_root"] = pipeline_root
        st.session_state["res_loaded_project_label"] = _project_label_for_root(
            pipeline_root
        )
        st.caption("已自动载入分析工作台刚刚生成的结果。")

    if "res_rank_result" not in st.session_state:
        if outcome and outcome.get("status") == "PASS":
            # Compatibility fallback for plans that only expose the final
            # report directory: the recommendation can still be shown even
            # when the other three result directories cannot be derived.
            _render_quick_recommendation()
            st.info("分析已经完成，但无法从执行计划确定结果目录；可在上方选择项目加载。")
        else:
            st.info("请先在「分析工作台」完成快速分析，或在上方选择已有项目。")
        return

    loaded_label = st.session_state.get("res_loaded_project_label")
    if not loaded_label:
        loaded_root = st.session_state.get("res_loaded_project_root")
        loaded_label = (
            _project_label_for_root(loaded_root) if loaded_root else "已加载项目"
        )
    with st.expander(f"查看已加载项目结果 · {loaded_label}", expanded=True):
        _render_quick_recommendation(st.session_state["res_rank_result"])
        loaded_dirs = st.session_state.get("res_loaded_dirs")
        active_final_dir = loaded_dirs[0] if loaded_dirs else ""
        _render_rank_overview(
            st.session_state["res_rank_result"],
            active_final_dir,
            inline=True,
        )

        st.divider()
        selector_kwargs = {}
        if "_res_visible_sections" not in st.session_state:
            selector_kwargs["default"] = st.session_state.get(
                "res_visible_sections", ["obipcr 汇总"]
            )
        selected_sections = st.multiselect(
            "选择展示的详细结果",
            options=_RESULT_SECTION_OPTIONS,
            key="_res_visible_sections",
            help="可选择一个或多个结果区域；未选择的区域不会占用页面空间。",
            on_change=_remember_result_section_selection,
            **selector_kwargs,
        )

        section_specs = [
            (
                "obipcr 汇总",
                "obipcr 汇总结果",
                "combined_summary.tsv",
                "res_combined_result",
            ),
            (
                "MFEprimer 质控",
                "MFEprimer 质控汇总",
                "primer_qc_summary.tsv",
                "res_qc_result",
            ),
            (
                "MFEprimer 特异性",
                "MFEprimer 特异性汇总",
                "primer_spec.tsv",
                "res_spec_result",
            ),
        ]
        for option, heading, file_name, state_key in section_specs:
            if option in selected_sections:
                _render_result_tsv_section(
                    heading,
                    file_name,
                    st.session_state[state_key],
                    inline=True,
                )


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


def _render_manual_primers() -> None:
    """Render the direct primer entry form."""
    ensure_widget_key(st.session_state, "_manual_primer_count")
    count = st.number_input(
        "引物对数量",
        min_value=1,
        max_value=100,
        value=st.session_state.get("_manual_primer_count", 1),
        key="_manual_primer_count",
    )
    st.caption(
        "填写引物序列后可直接评估，无需手工制作 primers.tsv。"
        "完整推荐结果仍需要参考 FASTA 和 taxonomy。"
    )
    for i in range(count):
        with st.expander(f"引物对 {i + 1}", expanded=(count <= 2)):
            st.text_input(
                "引物名称", key=f"_manual_primer_id_{i}",
                placeholder="例如: COI_short",
            )
            sequence_col1, sequence_col2 = st.columns(2)
            with sequence_col1:
                st.text_input(
                    "前向引物（5'→3'）", key=f"_manual_forward_{i}",
                    placeholder="例如: GGTCAACAAATCATAAAGATATTGG",
                )
            with sequence_col2:
                st.text_input(
                    "反向引物（5'→3'）", key=f"_manual_reverse_{i}",
                    placeholder="例如: TAAACTTCAGGGTGACCAAAAAATCA",
                )
            length_col1, length_col2 = st.columns(2)
            with length_col1:
                st.text_input(
                    "最小扩增长度 (bp)", key=f"_manual_min_length_{i}",
                    placeholder="例如: 100",
                )
            with length_col2:
                st.text_input(
                    "最大扩增长度 (bp)", key=f"_manual_max_length_{i}",
                    placeholder="例如: 400",
                )


def _collect_manual_rows(state: MutableMapping, count: int) -> list[dict[str, str]]:
    """Read manual primer rows from widget state keys."""
    rows: list[dict[str, str]] = []
    for i in range(count):
        rows.append({
            "primer_id": str(state.get(f"_manual_primer_id_{i}", "")),
            "forward": str(state.get(f"_manual_forward_{i}", "")),
            "reverse": str(state.get(f"_manual_reverse_{i}", "")),
            "min_length": str(state.get(f"_manual_min_length_{i}", "")),
            "max_length": str(state.get(f"_manual_max_length_{i}", "")),
        })
    return rows


def _render_project_inputs() -> None:
    """File inputs with upload + server-path modes, plus validation."""
    st.subheader("项目与输入文件")

    col_left, col_right = st.columns(2)

    with col_left:
        # ── primers ────────────────────────────────────────────────────
        st.markdown("**引物文件 (primers.tsv)**")
        primers_mode = st.radio(
            "输入方式",
            ["直接填写", "本地上传", "服务器路径"],
            index=0,
            key="_inputs_primers_mode",
            horizontal=True,
        )
        primers_use_manual = primers_mode == "直接填写"
        primers_use_upload = primers_mode == "本地上传"
        st.session_state["ws_use_upload_primers"] = (
            primers_use_manual or primers_use_upload
        )
        if primers_use_manual:
            _render_manual_primers()
        elif primers_use_upload:
            st.file_uploader(
                "选择 primers.tsv",
                type=["tsv"],
                key="_ws_primers_uploader",
                help="上传 Tab 分隔的引物文件（.tsv）",
            )
        else:
            ensure_widget_key(st.session_state, "_inputs_primers_path")
            st.text_input(
                "引物文件路径",
                help="服务器上的 primers.tsv 绝对或相对路径。",
                key="_inputs_primers_path",
            )

    with col_right:
        # ── database ───────────────────────────────────────────────────
        st.markdown("**参考数据库**")
        database_mode = st.radio(
            "输入方式",
            ["本地上传", "服务器路径"],
            index=0,
            key="_inputs_database_mode",
            horizontal=True,
        )
        database_use_upload = database_mode == "本地上传"
        st.session_state["ws_use_upload_database"] = database_use_upload
        if database_use_upload:
            st.file_uploader(
                "选择参考数据库",
                type=["fasta", "fa", "gz"],
                key="_ws_database_uploader",
                help="上传 FASTA 参考数据库（.fasta, .fa, .fasta.gz, .fa.gz）",
            )
        else:
            ensure_widget_key(st.session_state, "_inputs_database_path")
            st.text_input(
                "数据库文件路径",
                help="服务器上的未压缩 FASTA 数据库路径（.fasta/.fa）。gzip 请用本地上传或预先解压。",
                key="_inputs_database_path",
            )

        # ── taxonomy ───────────────────────────────────────────────────
        st.markdown("**分类信息 (taxonomy.tsv)**")
        taxonomy_mode = st.radio(
            "输入方式",
            ["本地上传", "服务器路径"],
            index=0,
            key="_inputs_taxonomy_mode",
            horizontal=True,
        )
        taxonomy_use_upload = taxonomy_mode == "本地上传"
        st.session_state["ws_use_upload_taxonomy"] = taxonomy_use_upload
        if taxonomy_use_upload:
            st.file_uploader(
                "选择 taxonomy.tsv",
                type=["tsv"],
                key="_ws_taxonomy_uploader",
                help="上传 Tab 分隔的分类信息文件（.tsv）",
            )
        else:
            ensure_widget_key(st.session_state, "_inputs_taxonomy_path")
            st.text_input(
                "分类信息文件路径",
                help="服务器上的 taxonomy.tsv 路径。",
                key="_inputs_taxonomy_path",
            )

    # Output roots remain an internal project detail.  Upload/manual modes use
    # their isolated workspace; all-server-path mode retains the persisted
    # canonical default without exposing a novice-facing path field.
    any_upload = (
        primers_use_manual
        or primers_use_upload
        or database_use_upload
        or taxonomy_use_upload
    )

    # ── save & validate ────────────────────────────────────────────────

    if st.button("保存并验证输入文件", type="primary", key="inputs_validate_btn"):
        # Clear old pipeline results — new inputs invalidate prior runs.
        for rk in [
            "full_pipeline_plan", "full_pipeline_result",
            "wf_s1_result", "wf_s2_result", "wf_s3_result",
            "wf_s4_result", "wf_s5_result",
        ]:
            st.session_state.pop(rk, None)
        # Clear queued error state from the previous pipeline run so
        # the old dialog does not render after re-validation.
        st.session_state.pop("pending_error_dialog", None)
        st.session_state.pop("last_auto_shown_error_job_id", None)
        # Dismiss the current terminal job so stale results don't
        # reappear after re-validation.
        old_job_id = st.session_state.get("full_pipeline_job_id", "")
        if old_job_id:
            st.session_state["dismissed_terminal_job_id"] = old_job_id
        st.session_state.pop("full_pipeline_job_id", None)
        _clear_result_download_state()

        ws = None
        save_errors: list[str] = []

        if any_upload:
            # Create workspace once, reuse across uploads.
            if st.session_state.get("ws_run_id") is None:
                ws = create_run_workspace()
                st.session_state["ws_run_id"] = ws["run_id"]
                st.session_state["ws_uploads_dir"] = ws["uploads_dir"]
            else:
                uploads = st.session_state.get("ws_uploads_dir", "")
                run_id = st.session_state.get("ws_run_id", "")
                ws = {
                    "run_id": run_id,
                    "uploads_dir": uploads,
                }

            uploads_dir = str(ws["uploads_dir"])

            # Save manual primers
            if primers_use_manual:
                count = st.session_state.get("_manual_primer_count", 1)
                rows = _collect_manual_rows(st.session_state, count)
                built = build_manual_primers_tsv(rows)
                if built["status"] == "PASS":
                    import io as _io
                    f = _io.BytesIO(built["content"])
                    f.name = "primers.tsv"
                    result = save_uploaded_file(
                        f,
                        file_type=PRIMERS_FILE,
                        uploads_dir=uploads_dir,
                        original_name="primers.tsv",
                    )
                    if result["status"] == "PASS":
                        st.session_state["ws_uploaded_primers_path"] = result["saved_path"]
                    else:
                        save_errors.append(f"引物文件: {result['error']}")
                else:
                    save_errors.append(f"引物文件: {built['error']}")

            # Save primers upload
            if primers_use_upload:
                pf = st.session_state.get("_ws_primers_uploader")
                if pf is not None:
                    result = save_uploaded_file(
                        pf,
                        file_type=PRIMERS_FILE,
                        uploads_dir=uploads_dir,
                        original_name=pf.name,
                    )
                    if result["status"] == "PASS":
                        st.session_state["ws_uploaded_primers_path"] = result[
                            "saved_path"
                        ]
                    else:
                        save_errors.append(f"引物文件: {result['error']}")
                else:
                    save_errors.append("引物文件: 未选择文件")

            # Save database upload
            if database_use_upload:
                df_upload = st.session_state.get("_ws_database_uploader")
                if df_upload is not None:
                    result = save_uploaded_file(
                        df_upload,
                        file_type=DATABASE_FILE,
                        uploads_dir=uploads_dir,
                        original_name=df_upload.name,
                    )
                    if result["status"] == "PASS":
                        st.session_state["ws_uploaded_database_path"] = result[
                            "saved_path"
                        ]
                    else:
                        save_errors.append(f"参考数据库: {result['error']}")
                else:
                    save_errors.append("参考数据库: 未选择文件")

            # Save taxonomy upload
            if taxonomy_use_upload:
                tf = st.session_state.get("_ws_taxonomy_uploader")
                if tf is not None:
                    result = save_uploaded_file(
                        tf,
                        file_type=TAXONOMY_FILE,
                        uploads_dir=uploads_dir,
                        original_name=tf.name,
                    )
                    if result["status"] == "PASS":
                        st.session_state["ws_uploaded_taxonomy_path"] = result[
                            "saved_path"
                        ]
                    else:
                        save_errors.append(f"分类信息: {result['error']}")
                else:
                    save_errors.append("分类信息: 未选择文件")

            if save_errors:
                st.error(
                    "文件保存失败: " + "；".join(save_errors)
                )
                st.session_state["inputs_validated"] = False

                primers_err = next(
                    (e.split(": ", 1)[-1] for e in save_errors if e.startswith("引物文件")),
                    None,
                )
                db_err = next(
                    (e.split(": ", 1)[-1] for e in save_errors if e.startswith("参考数据库")),
                    None,
                )
                tax_err = next(
                    (e.split(": ", 1)[-1] for e in save_errors if e.startswith("分类信息")),
                    None,
                )

                primers_path = get_effective_primers_path(st.session_state)
                database_path = get_effective_database_path(st.session_state)
                taxonomy_path = get_effective_taxonomy_path(st.session_state)
                run_root = str(Path(uploads_dir).parent)

                primers_result = (
                    {"status": "FAIL", "error": primers_err, "path": ""}
                    if primers_err
                    else validate_primers_file(primers_path)
                )
                db_result = (
                    {"status": "FAIL", "error": db_err, "path": ""}
                    if db_err
                    else validate_database_file(database_path)
                )
                tax_result = (
                    {"status": "FAIL", "error": tax_err, "path": ""}
                    if tax_err
                    else validate_taxonomy_file(taxonomy_path)
                )
                out_result = validate_output_directory(run_root)

                failures: list[str] = []
                if primers_err:
                    failures.append("引物文件")
                if db_err:
                    failures.append("参考数据库")
                if tax_err:
                    failures.append("分类信息")

                st.session_state["input_validation_snapshot"] = {
                    "primers_result": primers_result,
                    "db_result": db_result,
                    "tax_result": tax_result,
                    "out_result": out_result,
                    "all_valid": False,
                    "derived": {},
                    "failures": failures,
                }
                return

            run_root = str(Path(uploads_dir).parent)
        else:
            run_root = str(st.session_state.get("inputs_output_dir", "results"))

        # ── effective paths for all three files (works for ANY mix) ───────
        primers_path = get_effective_primers_path(st.session_state)
        database_path = get_effective_database_path(st.session_state)
        taxonomy_path = get_effective_taxonomy_path(st.session_state)

        # ── validate ───────────────────────────────────────────────────
        primers_result = validate_primers_file(primers_path)
        db_result = validate_database_file(database_path)
        tax_result = validate_taxonomy_file(taxonomy_path)
        out_result = validate_output_directory(run_root)

        # ── server-path gzip rejection ──────────────────────────────────
        # Downstream qc-spec cannot read compressed FASTA, so server-path
        # mode must reject .fasta.gz / .fa.gz.  Upload mode is fine because
        # save_uploaded_file() decompresses on the fly.
        if (
            database_use_upload is False
            and db_result.get("status") == "PASS"
            and database_path.lower().endswith((".fasta.gz", ".fa.gz"))
        ):
            db_result = dict(db_result)
            db_result["status"] = "FAIL"
            db_result["error"] = (
                "服务器路径模式暂不支持压缩数据库（.fasta.gz/.fa.gz）。"
                "请先在服务器上解压为 .fasta/.fa，"
                "或切换到「本地上传」由系统自动解压。"
            )

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
            derived = derive_project_paths(run_root)
            spec_index_db = build_spec_index_database_path(
                derived.get("qc_spec_results_dir", ""), database_path
            )

            st.session_state["project_primers_path"] = primers_path
            st.session_state["project_database_path"] = database_path
            st.session_state["project_taxonomy_path"] = taxonomy_path
            st.session_state["project_output_root"] = run_root
            st.session_state["project_derived_paths"] = derived

            paths_dict = {
                "output_root": run_root,
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
                empty_before: set[str] = set()
                for _pk, state_key in _WORKFLOW_PATH_MAP:
                    cv = st.session_state.get(state_key)
                    if cv is None or cv == "":
                        empty_before.add(state_key)
                apply_project_paths_to_state(
                    st.session_state, paths_dict, overwrite=False
                )
                for state_key in empty_before:
                    cv = st.session_state.get(state_key)
                    if cv is not None and cv != "":
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
        st.info("点击 **保存并验证输入文件** 检查当前输入。")
        return

    st.divider()
    primers_result: dict = snapshot.get("primers_result", {})
    db_result: dict = snapshot.get("db_result", {})
    tax_result: dict = snapshot.get("tax_result", {})
    out_result: dict = snapshot.get("out_result", {})
    all_valid: bool = snapshot.get("all_valid", False)
    failures: list[str] = snapshot.get("failures", [])
    expander_label = "验证结果：已通过" if all_valid else "验证结果：需要处理"
    with st.expander(expander_label, expanded=False):
        st.markdown("#### 引物文件 (primers.tsv)")
        _render_file_validation(
            label="primers.tsv",
            result=primers_result,
            show_preview=True,
            preview_caption="前 10 行（含表头）",
        )

        st.markdown("#### 参考数据库 (database.fasta)")
        _render_file_validation(
            label="database", result=db_result, show_preview=False
        )
        if db_result.get("record_count") is not None:
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("FASTA 序列数量", db_result["record_count"])
            with col_b:
                st.metric(
                    "总碱基数",
                    f"{db_result['total_bases']:,}"
                    if db_result.get("total_bases")
                    else "N/A",
                )

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

        if all_valid:
            st.success("输入文件验证通过，可以开始快速分析。")
        else:
            visible_failures = [name for name in failures if name != "输出目录"]
            if visible_failures:
                st.warning(
                    f"以下输入未通过验证: {', '.join(visible_failures)}。"
                    "请修正后重新验证。"
                )
            if out_result.get("status") not in ("PASS", "WARN"):
                st.error("系统暂时无法准备项目环境，请稍后重试或联系管理员。")


# ── preset controls ──────────────────────────────────────────────────────────


def _render_analysis_parameter_controls() -> dict[str, object]:
    """Render basic parameters and optionally visible advanced overrides."""

    def optional_number(
        label: str,
        *,
        use_key: str,
        value_key: str,
        default: int | float,
        step: int | float,
        help_text: str,
        min_value: int | float | None = None,
        number_format: str | None = None,
    ) -> tuple[bool, int | float | None]:
        """Render a numeric override only when its enable box is selected."""
        ensure_widget_key(st.session_state, use_key)
        enabled = st.checkbox(
            f"设置{label}",
            key=use_key,
            help=help_text,
        )
        if not enabled:
            return False, None

        ensure_widget_key(st.session_state, value_key)
        if st.session_state.get(value_key) is None:
            st.session_state[value_key] = default

        number_kwargs: dict[str, object] = {
            "key": value_key,
            "step": step,
            "help": help_text,
        }
        if min_value is not None:
            number_kwargs["min_value"] = min_value
        if number_format is not None:
            number_kwargs["format"] = number_format
        value = st.number_input(label, **number_kwargs)
        return True, value

    # ── common analysis params (front-placed, read by steps 3 & 4) ──────

    st.markdown("#### 基础参数")
    pcol1, pcol2, pcol3 = st.columns(3)
    with pcol1:
        ensure_widget_key(st.session_state, "_wf_s3_minsize")
        minsize = st.number_input(
            "最小扩增片段长度 (bp)",
            key="_wf_s3_minsize",
            step=10,
            format="%d",
            help=(
                "MFEprimer spec · -s：预测扩增片段允许的最小长度，"
                "单位为 bp；默认 80 bp。"
            ),
        )
    with pcol2:
        ensure_widget_key(st.session_state, "_wf_s3_maxsize")
        maxsize = st.number_input(
            "最大扩增片段长度 (bp)",
            key="_wf_s3_maxsize",
            step=10,
            format="%d",
            help=(
                "MFEprimer spec · -S：预测扩增片段允许的最大长度，"
                "单位为 bp；默认 500 bp。"
            ),
        )
    with pcol3:
        ensure_widget_key(st.session_state, "_wf_s3_mismatch")
        spec_mismatch = st.number_input(
            "允许错配数",
            key="_wf_s3_mismatch",
            step=1,
            format="%d",
            help=(
                "MFEprimer spec · --misMatch：引物与参考序列进行 k-mer "
                "结合评估时允许的最大错配数；默认 2。"
            ),
        )

    pcol4, pcol5 = st.columns([2, 1])
    with pcol4:
        ensure_widget_key(st.session_state, "_wf_s4_mismatches")
        mismatches = st.text_input(
            "obipcr 错配等级",
            key="_wf_s4_mismatches",
            help=(
                "fullpcr run / obipcr · --mismatches：依次执行的允许错配"
                "等级，使用英文逗号分隔；默认 0,1,2。"
            ),
        )
    with pcol5:
        ensure_widget_key(st.session_state, "_wf_s4_circular")
        st.write("")
        circular = st.checkbox(
            "环状序列",
            key="_wf_s4_circular",
            help=(
                "fullpcr run / obipcr · --circular：按环状 DNA 处理参考"
                "序列，使跨越序列首尾的扩增也能被检出；默认启用。"
            ),
        )

    # ── optional Spec overrides ──────────────────────────────────────
    use_tm = bool(st.session_state.get("wf_s3_use_tm", False))
    use_mis_start = bool(st.session_state.get("wf_s3_use_misstart", False))
    use_mis_end = bool(st.session_state.get("wf_s3_use_misend", False))
    use_mono = bool(st.session_state.get("wf_s3_use_mono", False))
    use_diva = bool(st.session_state.get("wf_s3_use_diva", False))
    use_dntp = bool(st.session_state.get("wf_s3_use_dntp", False))
    use_oligo = bool(st.session_state.get("wf_s3_use_oligo", False))
    spec_tm_val = st.session_state.get("wf_s3_tm")
    spec_mis_start = st.session_state.get("wf_s3_misstart")
    spec_mis_end = st.session_state.get("wf_s3_misend")
    spec_mono = st.session_state.get("wf_s3_mono")
    spec_diva = st.session_state.get("wf_s3_diva")
    spec_dntp = st.session_state.get("wf_s3_dntp")
    spec_oligo = st.session_state.get("wf_s3_oligo")
    spec_bind = bool(st.session_state.get("wf_s3_bind", False))
    spec_cut_primer = bool(st.session_state.get("wf_s3_cutprimer", False))

    show_advanced = st.toggle(
        "显示高级参数",
        key="_show_advanced_parameters",
        help="仅控制高级参数的显示与隐藏，不会改变已经启用的参数和值。",
    )
    if show_advanced:
        st.caption("只勾选需要覆盖默认值的参数；未勾选时使用原有默认值。")
        spec_left, spec_right = st.columns(2)
        with spec_left:
            use_tm, spec_tm_val = optional_number(
                "最低 Tm (°C)",
                use_key="_wf_s3_use_tm",
                value_key="_wf_s3_tm",
                default=50.0,
                step=0.5,
                number_format="%.1f",
                help_text=(
                    "MFEprimer spec · -t：引物结合的最低熔解温度阈值，"
                    "单位为 °C；未勾选时 fullpcr 使用 50°C。"
                ),
            )
            use_mis_start, spec_mis_start = optional_number(
                "错配区域起点",
                use_key="_wf_s3_use_misstart",
                value_key="_wf_s3_misstart",
                default=1,
                step=1,
                min_value=1,
                number_format="%d",
                help_text=(
                    "MFEprimer spec · --misStart：从引物 3′ 端计算的错配"
                    "区域起点；未勾选时使用 MFEprimer 默认值 1。"
                ),
            )
            use_mis_end, spec_mis_end = optional_number(
                "错配区域终点",
                use_key="_wf_s3_use_misend",
                value_key="_wf_s3_misend",
                default=9,
                step=1,
                min_value=1,
                number_format="%d",
                help_text=(
                    "MFEprimer spec · --misEnd：从引物 3′ 端计算的错配"
                    "区域终点；未勾选时使用 MFEprimer 默认值 9。"
                ),
            )
            ensure_widget_key(st.session_state, "_wf_s3_bind")
            spec_bind = st.checkbox(
                "输出引物结合位点",
                key="_wf_s3_bind",
                help=(
                    "MFEprimer spec · -b / --bind：在结果中额外输出引物"
                    "结合位置和匹配形式；未勾选时不输出。"
                ),
            )

        with spec_right:
            use_mono, spec_mono = optional_number(
                "单价离子浓度 mono (mM)",
                use_key="_wf_s3_use_mono",
                value_key="_wf_s3_mono",
                default=50.0,
                step=1.0,
                number_format="%.1f",
                help_text=(
                    "MFEprimer spec · --mono：热力学计算使用的单价阳离子"
                    "浓度，单位为 mM；未勾选时使用默认值 50 mM。"
                ),
            )
            use_diva, spec_diva = optional_number(
                "二价离子浓度 diva (mM)",
                use_key="_wf_s3_use_diva",
                value_key="_wf_s3_diva",
                default=1.5,
                step=0.1,
                number_format="%.1f",
                help_text=(
                    "MFEprimer spec · --diva：热力学计算使用的二价阳离子"
                    "浓度，单位为 mM；未勾选时使用默认值 1.5 mM。"
                ),
            )
            use_dntp, spec_dntp = optional_number(
                "dNTP 浓度 (mM)",
                use_key="_wf_s3_use_dntp",
                value_key="_wf_s3_dntp",
                default=0.25,
                step=0.05,
                number_format="%.2f",
                help_text=(
                    "MFEprimer spec · --dntp：热力学计算使用的 dNTP "
                    "浓度，单位为 mM；未勾选时使用默认值 0.25 mM。"
                ),
            )
            use_oligo, spec_oligo = optional_number(
                "引物浓度 oligo (nM)",
                use_key="_wf_s3_use_oligo",
                value_key="_wf_s3_oligo",
                default=50.0,
                step=1.0,
                number_format="%.1f",
                help_text=(
                    "MFEprimer spec · --oligo：退火反应中的引物浓度，"
                    "单位为 nM；未勾选时使用默认值 50 nM。"
                ),
            )
            ensure_widget_key(st.session_state, "_wf_s3_cutprimer")
            spec_cut_primer = st.checkbox(
                "从扩增序列中切除引物",
                key="_wf_s3_cutprimer",
                help=(
                    "MFEprimer spec · --cutprimer：从预测扩增序列两端"
                    "移除引物序列；未勾选时保留引物。"
                ),
            )

    # Return captured widget values so callers can pass them to step 3/4
    # command builders within the same render cycle — canonical keys are
    # only synced at the bottom of the script.
    common_params = {
        "min_size": int(minsize) if minsize is not None else 80,
        "max_size": int(maxsize) if maxsize is not None else 500,
        "spec_mismatch": int(spec_mismatch) if spec_mismatch is not None else 2,
        "obipcr_mismatches": str(mismatches),
        "circular": bool(circular),
        "spec_tm": (
            float(spec_tm_val)
            if use_tm and spec_tm_val is not None
            else 50.0
        ),
        "spec_mis_start": (
            int(spec_mis_start)
            if use_mis_start and spec_mis_start is not None
            else None
        ),
        "spec_mis_end": (
            int(spec_mis_end)
            if use_mis_end and spec_mis_end is not None
            else None
        ),
        "spec_bind": bool(spec_bind),
        "spec_cut_primer": bool(spec_cut_primer),
        "spec_mono": (
            float(spec_mono) if use_mono and spec_mono is not None else None
        ),
        "spec_diva": (
            float(spec_diva) if use_diva and spec_diva is not None else None
        ),
        "spec_dntp": (
            float(spec_dntp) if use_dntp and spec_dntp is not None else None
        ),
        "spec_oligo": (
            float(spec_oligo) if use_oligo and spec_oligo is not None else None
        ),
    }

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


@st.dialog("分析失败", width="large")
def _render_error_dialog(error_details: dict) -> None:
    """Unified error dialog — used by both one-click and advanced steps.

    Displays all raw error fields without truncation in fixed order.
    Command, stderr, stdout, and traceback are rendered via
    ``st.code(..., language=None)``.  Empty textual fields show
    "（无内容）" and a missing return-code shows the same placeholder.
    """
    def _code_block(value: object) -> None:
        text = str(value) if value else ""
        st.code(text if text else "（无内容）", language=None)

    def _inline_or_placeholder(value: object) -> str:
        text = str(value) if value is not None and value != "" else ""
        return text if text else "（无内容）"

    # Fixed-section order per the approved plan.
    st.markdown(
        f"**失败步骤与状态:** "
        f"{_inline_or_placeholder(error_details.get('step_label'))}"
        f" — {translate_status(error_details.get('status', ''))}"
    )
    st.markdown(
        f"**后台任务ID:** "
        f"{_inline_or_placeholder(error_details.get('job_id'))}"
    )
    st.markdown(
        f"**返回码:** "
        f"{_inline_or_placeholder(error_details.get('returncode'))}"
    )
    st.markdown("**实际执行命令:**")
    _code_block(error_details.get("command"))
    st.markdown("**原始 stderr:**")
    _code_block(error_details.get("stderr"))
    st.markdown("**原始 stdout:**")
    _code_block(error_details.get("stdout"))
    st.markdown(
        f"**执行消息:** "
        f"{_inline_or_placeholder(error_details.get('message'))}"
    )
    st.markdown(
        f"**后台异常:** "
        f"{_inline_or_placeholder(error_details.get('background_error'))}"
    )
    st.markdown("**后台 Python traceback:**")
    _code_block(error_details.get("background_traceback"))


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

    # Show "查看完整错误" button for FAIL, TIMEOUT, or CANCELLED results
    if status in ("FAIL", "TIMEOUT", "CANCELLED"):
        step_label_map = {
            "s1": "基础质控", "s2": "质控汇总", "s3": "特异性分析",
            "s4": "obipcr 全库模拟 PCR", "s5": "最终综合报告",
        }
        # Auto-open dialog only for FAIL/TIMEOUT (not CANCELLED)
        if status in ("FAIL", "TIMEOUT"):
            error_details = st.session_state.get("show_advanced_error_details")
            has_pending = (
                isinstance(error_details, dict)
                and error_details.get("step_key") == step_key
            )
            if has_pending:
                # Route through pending_error_dialog for centralised rendering
                st.session_state.pop("show_advanced_error_details", None)
                st.session_state["pending_error_dialog"] = error_details

        # Manual "查看完整错误" button — also routes through pending_error_dialog.
        # Calls st.rerun() so the outer dialog renderer opens immediately.
        if st.button("查看完整错误", key=f"view_full_error_{step_key}"):
            manual_details = build_execution_error_details(
                step_key=step_key,
                step_label=step_label_map.get(step_key, step_key),
                result=run_result,
            )
            st.session_state["pending_error_dialog"] = manual_details
            st.rerun()


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
            timeout=None,
        )
        st.code(" ".join(s1_cmd), language="bash")

    dry_run = bool(_read_state_value(
        st.session_state, "_workflow_dry_run", "workflow_dry_run", False
    ))
    if st.button("运行基础质控", key="wf_run_s1"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            _clear_result_download_state()
            with st.spinner("正在运行基础质控..."):
                result = run_gui_command(s1_cmd, timeout=None)
                st.session_state["wf_s1_result"] = result
                if result.get("status") in ("FAIL", "TIMEOUT"):
                    st.session_state["show_advanced_error_details"] = build_execution_error_details(
                        step_key="s1", step_label="基础质控", result=result,
                    )
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

    dry_run = bool(_read_state_value(
        st.session_state, "_workflow_dry_run", "workflow_dry_run", False
    ))
    if st.button("生成质控汇总", key="wf_run_s2"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            _clear_result_download_state()
            with st.spinner("正在生成质控汇总..."):
                result = run_gui_command(s2_cmd)
                st.session_state["wf_s2_result"] = result
                if result.get("status") in ("FAIL", "TIMEOUT"):
                    st.session_state["show_advanced_error_details"] = build_execution_error_details(
                        step_key="s2", step_label="质控汇总", result=result,
                    )
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

    with st.expander("高级参数"):
        as3c1, as3c2 = st.columns(2)
        with as3c1:
            available_cpu = get_available_cpu_threads()
            auto_cpu = resolve_spec_cpu_threads(
                manual_enabled=False, manual_threads=None,
                available_threads=available_cpu,
            )
            ensure_widget_key(st.session_state, "_wf_s3_manual_cpu_enabled")
            s3_manual_enabled = st.toggle(
                "手动指定 CPU 线程数",
                key="_wf_s3_manual_cpu_enabled",
            )
            if s3_manual_enabled:
                # Clamp persisted value to current [1, available_cpu] range
                ensure_widget_key(st.session_state, "_wf_s3_cpu")
                persisted = st.session_state.get("_wf_s3_cpu")
                if isinstance(persisted, (int, float)):
                    st.session_state["_wf_s3_cpu"] = max(
                        1, min(int(persisted), available_cpu),
                    )
                s3_cpu_widget = st.number_input(
                    "cpu",
                    key="_wf_s3_cpu",
                    min_value=1,
                    max_value=available_cpu,
                    step=1,
                )
            else:
                st.caption(
                    f"自动使用 {auto_cpu} 个线程"
                    f"（当前进程可用 {available_cpu} 个逻辑线程的 60%）"
                )
                # Resolve auto value for downstream use
                s3_cpu_widget = auto_cpu
        with as3c2:
            ensure_widget_key(st.session_state, "_wf_s3_maxtm")
            s3_max_tm = st.number_input("max_tm", key="_wf_s3_maxtm")
            ensure_widget_key(st.session_state, "_wf_s3_kvalue")
            s3_kvalue = st.number_input("kvalue", key="_wf_s3_kvalue")
        ensure_widget_key(st.session_state, "_wf_s3_force")
        s3_force = st.checkbox("Force（覆盖已有结果）", key="_wf_s3_force")

    with st.expander("查看实际执行命令"):
        # Use resolved CPU for both preview and execution
        s3_resolved_cpu = resolve_spec_cpu_threads(
            manual_enabled=bool(s3_manual_enabled),
            manual_threads=int(s3_cpu_widget) if isinstance(s3_cpu_widget, (int, float)) else None,
            available_threads=available_cpu,
        )
        s3_cmd = build_qc_spec_command(
            primers=s3_primers,
            database=s3_database,
            outdir=s3_outdir,
            min_size=common_params["min_size"],
            max_size=common_params["max_size"],
            tm=common_params.get("spec_tm", 50.0),
            max_tm=s3_max_tm,
            mismatch=common_params["spec_mismatch"],
            mis_start=common_params.get("spec_mis_start"),
            mis_end=common_params.get("spec_mis_end"),
            cpu=s3_resolved_cpu,
            kvalue=s3_kvalue,
            bind=common_params.get("spec_bind", False),
            cut_primer=common_params.get("spec_cut_primer", False),
            mono=common_params.get("spec_mono"),
            diva=common_params.get("spec_diva"),
            dntp=common_params.get("spec_dntp"),
            oligo=common_params.get("spec_oligo"),
            timeout=None,
            force=s3_force,
        )
        st.code(" ".join(s3_cmd), language="bash")

    dry_run = bool(_read_state_value(
        st.session_state, "_workflow_dry_run", "workflow_dry_run", False
    ))
    if st.button("运行特异性分析", key="wf_run_s3"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            _clear_result_download_state()
            with st.spinner("正在运行特异性分析..."):
                result = run_gui_command(s3_cmd, timeout=None)
                st.session_state["wf_s3_result"] = result
                # Auto-open error dialog for FAIL/TIMEOUT on this click
                if result.get("status") in ("FAIL", "TIMEOUT"):
                    st.session_state["show_advanced_error_details"] = build_execution_error_details(
                        step_key="s3",
                        step_label="特异性分析",
                        result=result,
                    )
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

    # Mismatch levels and circular mode are front-placed in the parameter panel.

    ensure_widget_key(st.session_state, "_wf_s4_summarize")
    s4_summarize = st.checkbox("Summarize（汇总统计）", key="_wf_s4_summarize")
    ensure_widget_key(st.session_state, "_wf_s4_report")
    s4_report = st.checkbox("Report（生成报告）", key="_wf_s4_report")
    ensure_widget_key(st.session_state, "_wf_s4_force")
    s4_force = st.checkbox("Force（覆盖已有结果）", key="_wf_s4_force")

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
            timeout=None,
        )
        st.code(" ".join(s4_cmd), language="bash")

    dry_run = bool(_read_state_value(
        st.session_state, "_workflow_dry_run", "workflow_dry_run", False
    ))
    if st.button("运行全库模拟 PCR", key="wf_run_s4"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            _clear_result_download_state()
            with st.spinner("正在运行 obipcr 全库模拟 PCR..."):
                result = run_gui_command(s4_cmd, timeout=None)
                st.session_state["wf_s4_result"] = result
                if result.get("status") in ("FAIL", "TIMEOUT"):
                    st.session_state["show_advanced_error_details"] = build_execution_error_details(
                        step_key="s4", step_label="obipcr 全库模拟 PCR", result=result,
                    )
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

    dry_run = bool(_read_state_value(
        st.session_state, "_workflow_dry_run", "workflow_dry_run", False
    ))
    if st.button("生成最终报告", key="wf_run_s5"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            _clear_result_download_state()
            with st.spinner("正在生成最终综合报告..."):
                result = run_gui_command(s5_cmd)
                st.session_state["wf_s5_result"] = result
                if result.get("status") in ("FAIL", "TIMEOUT"):
                    st.session_state["show_advanced_error_details"] = build_execution_error_details(
                        step_key="s5", step_label="最终综合报告", result=result,
                    )
    _render_step_result(st.session_state.get("wf_s5_result"), "s5")


# ═══════════════════════════════════════════════════════════════════════════
# Page config
# ═══════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title=f"{BRAND_NAME} · fullpcr 引物评测平台",
    page_icon=str(BRAND_LOGO_PATH),
    layout="wide",
    initial_sidebar_state="locked",
)

_inject_brand_styles()

# ═══════════════════════════════════════════════════════════════════════════
# Cross-page persistence: canonical defaults
# ═══════════════════════════════════════════════════════════════════════════

init_canonical_defaults(st.session_state)
init_workspace_session_state(st.session_state)

# ═══════════════════════════════════════════════════════════════════════════
# Header
# ═══════════════════════════════════════════════════════════════════════════

_render_header()

# ═══════════════════════════════════════════════════════════════════════════
# Sidebar navigation
# ═══════════════════════════════════════════════════════════════════════════

st.sidebar.markdown(
    f"""
    <div class="sidebar-brand-panel">
        <img src="{_brand_logo_data_uri()}" alt="{BRAND_NAME} Logo">
        <div>
            <div class="eyebrow">BOKUN BIO</div>
            <h2>{BRAND_NAME}</h2>
            <p>全库引物评测平台</p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown(
    """
    <div class="sidebar-env-intro">
        <div class="eyebrow">SYSTEM STATUS</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    _render_environment_popover()

st.sidebar.markdown(
    """
    <div class="sidebar-nav-intro">
        <div class="eyebrow">ANALYSIS FLOW</div>
        <strong>分析导航</strong>
    </div>
    """,
    unsafe_allow_html=True,
)

page = st.sidebar.radio(
    "导航",
    ["分析工作台", "结果总览", "报告与下载"],
    index=0,
    label_visibility="collapsed",
)

st.sidebar.markdown(
    """
    <div class="sidebar-footer">
        <div class="eyebrow">INTERNAL PLATFORM</div>
        <strong>博坤生物 · 分析系统</strong>
        <p>QC · SPEC · in silico PCR</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ═══════════════════════════════════════════════════════════════════════════
# Page routing
# ═══════════════════════════════════════════════════════════════════════════

if page == "分析工作台":
    _render_analysis_workbench()

elif page == "结果总览":
    _render_results_overview()

elif page == "报告与下载":
    _render_reports_and_downloads()

# ═══════════════════════════════════════════════════════════════════════════
# Centralised error-dialog rendering (once per script run, any page)
# ═══════════════════════════════════════════════════════════════════════════

pending_dialog = st.session_state.get("pending_error_dialog")
if isinstance(pending_dialog, dict):
    _render_error_dialog(pending_dialog)
    st.session_state.pop("pending_error_dialog", None)

# ═══════════════════════════════════════════════════════════════════════════
# Cross-page persistence: sync widget → canonical
# ═══════════════════════════════════════════════════════════════════════════

sync_widgets_to_canonical(st.session_state)
