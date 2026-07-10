"""fullpcr Streamlit GUI — Phase 6A: 中文化 + 布局优化.

Launch with::

    streamlit run fullpcr/gui_app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from fullpcr.gui_helpers import (
    build_final_report_command,
    build_obipcr_run_command,
    build_qc_pre_command,
    build_qc_spec_command,
    build_qc_summary_command,
    check_command_available,
    get_fullpcr_info,
    get_python_info,
    load_markdown_file,
    load_primer_rank,
    load_tsv_file,
    run_gui_command,
    summarize_primer_rank,
    summarize_status_counts,
    translate_recommendation,
    translate_status,
    translate_warning_label,
    validate_database_file,
    validate_file_exists,
    validate_output_directory,
    validate_primers_file,
    validate_taxonomy_file,
)

# ── helper: render a validation result card ──────────────────────────────


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


# ── page config ──────────────────────────────────────────────────────────

st.set_page_config(
    page_title="fullpcr 引物评测平台",
    page_icon="🧬",
    layout="wide",
)

# ── main title ───────────────────────────────────────────────────────────

st.title("fullpcr 全库引物评测平台")
st.markdown("基于 OBITools4 obipcr 和 MFEprimer 的全库引物评测工具")
st.divider()

# ── sidebar navigation ───────────────────────────────────────────────────

st.sidebar.title("🧬 fullpcr")

page = st.sidebar.radio(
    "导航",
    ["环境检查", "输入文件", "分析流程", "结果总览", "报告查看"],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.caption("v0.1.0 — GUI Phase 6A")

# ── Environment page ─────────────────────────────────────────────────────

if page == "环境检查":
    st.header("环境检查")
    st.markdown("检查 fullpcr 运行所需的软件和环境。")

    # ── summary section ───────────────────────────────────────────────

    py_info = get_python_info()
    fp_info = get_fullpcr_info()
    obi = check_command_available(["obipcr", "--version"])
    mfe = check_command_available(["mfeprimer", "version"])

    checks = [
        ("Python", True, py_info["executable"]),
        ("fullpcr", fp_info["importable"], fp_info.get("version", "N/A")),
        ("obipcr", obi["available"], obi.get("version")),
        ("MFEprimer", mfe["available"], mfe.get("version")),
    ]

    ok_count = sum(1 for _, ok, _ in checks if ok)
    fail_count = len(checks) - ok_count

    col_sum1, col_sum2, col_sum3 = st.columns(3)
    with col_sum1:
        st.metric("环境正常", ok_count)
    with col_sum2:
        st.metric("环境异常", fail_count)
    with col_sum3:
        if fail_count == 0:
            st.success("可运行完整流程")
        else:
            st.warning("部分功能不可用")

    st.divider()

    # ── Python ─────────────────────────────────────────────────────────

    st.subheader("Python 环境")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("状态", "✓ 可用")
    with col2:
        st.metric("可执行文件", py_info["executable"])
    with st.expander("版本详情"):
        st.code(py_info["version"], language=None)

    st.divider()

    # ── fullpcr ────────────────────────────────────────────────────────

    st.subheader("fullpcr 程序")
    if fp_info["importable"]:
        st.success("fullpcr 可正常导入")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("版本", fp_info.get("version", "N/A"))
        with col2:
            st.metric("路径", fp_info.get("path", "N/A"))
    else:
        st.error(f"fullpcr 导入失败: {fp_info['error']}")

    st.divider()

    # ── obipcr ─────────────────────────────────────────────────────────

    st.subheader("obipcr")
    if obi["available"]:
        st.success("obipcr 可用")
        if obi["version"]:
            st.caption(obi["version"])
    else:
        st.error(obi["error"] or "obipcr 不可用")

    st.divider()

    # ── MFEprimer ──────────────────────────────────────────────────────

    st.subheader("MFEprimer")
    if mfe["available"]:
        st.success("MFEprimer 可用")
        if mfe["version"]:
            st.caption(mfe["version"])
    else:
        st.error(mfe["error"] or "MFEprimer 不可用")

    st.divider()

    # ── working directory ──────────────────────────────────────────────

    st.subheader("当前工作目录")
    st.code(os.getcwd(), language=None)

# ── Inputs page ──────────────────────────────────────────────────────────

elif page == "输入文件":
    st.header("输入文件")
    st.markdown("配置引物、参考数据库、分类信息和输出目录。")

    # ── file path inputs ──────────────────────────────────────────────

    col_left, col_right = st.columns(2)

    with col_left:
        primers_path = st.text_input(
            "引物文件（primers.tsv）",
            value="example_data/primers.tsv",
            help="Path to the primers file (Tab-separated).",
            key="inputs_primers_path",
        )
        database_path = st.text_input(
            "参考数据库（database.fasta）",
            value="example_data/real_mito_small.fasta",
            help="Path to the FASTA database (.fasta, .fa, .fasta.gz, .fa.gz).",
            key="inputs_database_path",
        )

    with col_right:
        taxonomy_path = st.text_input(
            "分类信息（taxonomy.tsv）",
            value="example_data/taxonomy.tsv",
            help="Path to the taxonomy file (Tab-separated).",
            key="inputs_taxonomy_path",
        )
        output_dir = st.text_input(
            "项目输出目录",
            value="results",
            help="Root directory for all output files.",
            key="inputs_output_dir",
        )

    st.divider()

    # ── validate button ───────────────────────────────────────────────

    if st.button("验证输入文件", type="primary", key="inputs_validate_btn"):
        st.subheader("验证结果")

        # -- primers ---------------------------------------------------
        st.markdown("#### 引物文件 (primers.tsv)")
        _render_file_validation(
            label="primers.tsv",
            result=validate_primers_file(primers_path),
            show_preview=True,
            preview_caption="前 10 行（含表头）",
        )

        # -- database ---------------------------------------------------
        st.markdown("#### 参考数据库 (database.fasta)")
        db_result = validate_database_file(database_path)
        _render_file_validation(
            label="database",
            result=db_result,
            show_preview=False,
        )
        if db_result.get("record_count") is not None:
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("FASTA 序列数量", db_result["record_count"])
            with col_b:
                st.metric(
                    "总碱基数",
                    f"{db_result['total_bases']:,}" if db_result.get("total_bases") else "N/A",
                )

        # -- taxonomy ---------------------------------------------------
        st.markdown("#### 分类信息 (taxonomy.tsv)")
        tax_result = validate_taxonomy_file(taxonomy_path)
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

        # -- output directory -------------------------------------------
        st.markdown("#### 输出目录")
        out_result = validate_output_directory(output_dir)
        out_status = translate_status(out_result["status"])
        if out_result["status"] == "PASS":
            st.success(f"✓ 目录已存在 ({out_status}): `{out_result['path']}`")
        elif out_result.get("will_create"):
            st.warning(f"后续将自动创建 ({out_status}): `{out_result['path']}`")
        else:
            st.error(out_result.get("error", "未知错误"))

        # -- suggested output structure ---------------------------------
        st.markdown("#### 项目输出目录结构")
        st.code(
            f"{output_dir or 'results'}/\n"
            f"├── qc_results/          MFEprimer 基础质控\n"
            f"├── qc_spec_results/     MFEprimer 特异性分析\n"
            f"├── obipcr_results/      obipcr 全库模拟 PCR\n"
            f"└── final_results/       最终综合结果\n",
            language=None,
        )

    # ── show suggestions even before validation ───────────────────────
    else:
        st.info("点击 **验证输入文件** 检查所有输入文件和路径。")

elif page == "分析流程":
    st.header("分析流程")
    st.markdown(
        "按照以下顺序完成引物质控、特异性分析、全库模拟 PCR 和综合报告生成。"
    )

    # ── dry-run toggle ────────────────────────────────────────────────

    dry_run = st.toggle(
        "仅预览命令，不执行",
        value=False,
        key="workflow_dry_run",
        help="When enabled, commands are previewed but NOT executed.",
    )

    if dry_run:
        st.info("🔍 **仅预览命令模式** — 命令将显示但不会实际执行。")

    st.caption("建议首次运行时先开启「仅预览命令」以检查参数。")

    st.divider()

    # ── helper: render a step result ──────────────────────────────────

    def _render_step_result(run_result: dict | None) -> None:
        """Display the result of a command execution."""
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

        with st.expander("查看运行输出"):
            stdout_text = run_result.get("stdout", "")
            st.text_area(
                "stdout",
                value=stdout_text if stdout_text else "(empty)",
                height=200,
                key=f"stdout_{id(run_result)}",
            )

        stderr_text = run_result.get("stderr", "")
        if stderr_text:
            with st.expander("查看错误信息"):
                st.text_area(
                    "stderr",
                    value=stderr_text,
                    height=200,
                    key=f"stderr_{id(run_result)}",
                )

    # ── Step 1: MFEprimer QC ──────────────────────────────────────────

    st.subheader("步骤 1：MFEprimer 引物基础质控")
    st.caption("计算 Tm、GC、二聚体、发卡结构和简并引物展开。")

    step1_col1, step1_col2 = st.columns(2)
    with step1_col1:
        s1_primers = st.text_input(
            "引物文件 (primers.tsv)",
            value="example_data/primers.tsv",
            key="wf_s1_primers",
        )
    with step1_col2:
        s1_outdir = st.text_input(
            "质控输出目录",
            value="qc_results",
            key="wf_s1_outdir",
        )

    s1_col_flags, _s1_spacer = st.columns([1, 2])
    with s1_col_flags:
        s1_thermo = st.checkbox("Thermo（Tm 计算）", value=True, key="wf_s1_thermo")
        s1_dimer = st.checkbox("Dimer（二聚体检测）", value=True, key="wf_s1_dimer")
        s1_hairpin = st.checkbox("Hairpin（发卡结构检测）", value=True, key="wf_s1_hairpin")
        s1_degen = st.checkbox("Degen（简并引物展开）", value=True, key="wf_s1_degen")

    with st.expander("高级参数"):
        as1c1, as1c2 = st.columns(2)
        with as1c1:
            s1_score = st.number_input("score", value=5, key="wf_s1_score")
            s1_dg = st.number_input("dg", value=-5.0, key="wf_s1_dg")
            s1_tm = st.number_input("tm", value=50.0, key="wf_s1_tm")
        with as1c2:
            s1_mismatch = st.number_input("mismatch", value=2, key="wf_s1_mismatch")
            s1_max_deg = st.number_input("max_degenerate_variants", value=256, key="wf_s1_maxdeg")
            s1_timeout = st.number_input("timeout (s)", value=60, key="wf_s1_timeout")

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

    if st.button("运行基础质控", key="wf_run_s1"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            with st.spinner("正在运行基础质控..."):
                result = run_gui_command(s1_cmd, timeout=s1_timeout)
                st.session_state["wf_s1_result"] = result
    _render_step_result(st.session_state.get("wf_s1_result"))

    st.divider()

    # ── Step 2: QC Summary ────────────────────────────────────────────

    st.subheader("步骤 2：生成质控汇总")
    st.caption("解析 MFEprimer 原始输出并生成质控汇总表。")

    s2_qc_dir = st.text_input(
        "质控结果目录",
        value="qc_results",
        key="wf_s2_qcdir",
    )
    s2_cmd = build_qc_summary_command(qc_dir=s2_qc_dir)
    with st.expander("查看实际执行命令"):
        st.code(" ".join(s2_cmd), language="bash")

    if st.button("生成质控汇总", key="wf_run_s2"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            with st.spinner("正在生成质控汇总..."):
                result = run_gui_command(s2_cmd)
                st.session_state["wf_s2_result"] = result
    _render_step_result(st.session_state.get("wf_s2_result"))

    st.divider()

    # ── Step 3: MFEprimer Spec ────────────────────────────────────────

    st.subheader("步骤 3：MFEprimer 特异性分析")
    st.caption("建立参考数据库索引并评估引物扩增特异性。")

    s3_col1, s3_col2 = st.columns(2)
    with s3_col1:
        s3_primers = st.text_input(
            "引物文件 (primers.tsv)",
            value="example_data/primers.tsv",
            key="wf_s3_primers",
        )
        s3_database = st.text_input(
            "参考数据库 (database.fasta)",
            value="example_data/real_mito_small.fasta",
            key="wf_s3_database",
        )
    with s3_col2:
        s3_outdir = st.text_input(
            "特异性分析输出目录",
            value="qc_spec_results",
            key="wf_s3_outdir",
        )

    # Common params
    s3_col_p1, s3_col_p2 = st.columns(2)
    with s3_col_p1:
        s3_min_size = st.number_input("min_size", value=80, key="wf_s3_minsize")
        s3_max_size = st.number_input("max_size", value=500, key="wf_s3_maxsize")
    with s3_col_p2:
        s3_mismatch = st.number_input("mismatch", value=2, key="wf_s3_mismatch")
        s3_timeout = st.number_input("timeout (s)", value=300, key="wf_s3_timeout")

    with st.expander("高级参数"):
        as3c1, as3c2 = st.columns(2)
        with as3c1:
            s3_tm = st.number_input("tm", value=50.0, key="wf_s3_tm")
            s3_cpu = st.number_input("cpu", value=4, key="wf_s3_cpu")
        with as3c2:
            s3_max_tm = st.number_input("max_tm", value=75.0, key="wf_s3_maxtm")
            s3_kvalue = st.number_input("kvalue", value=9, key="wf_s3_kvalue")
        s3_force = st.checkbox("Force（覆盖已有结果）", value=True, key="wf_s3_force")

    with st.expander("查看实际执行命令"):
        s3_cmd = build_qc_spec_command(
            primers=s3_primers,
            database=s3_database,
            outdir=s3_outdir,
            min_size=s3_min_size,
            max_size=s3_max_size,
            tm=s3_tm,
            max_tm=s3_max_tm,
            mismatch=s3_mismatch,
            cpu=s3_cpu,
            kvalue=s3_kvalue,
            timeout=s3_timeout,
            force=s3_force,
        )
        st.code(" ".join(s3_cmd), language="bash")

    if st.button("运行特异性分析", key="wf_run_s3"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            with st.spinner("正在运行特异性分析..."):
                result = run_gui_command(s3_cmd, timeout=s3_timeout)
                st.session_state["wf_s3_result"] = result
    _render_step_result(st.session_state.get("wf_s3_result"))

    st.divider()

    # ── Step 4: obipcr Run ────────────────────────────────────────────

    st.subheader("步骤 4：obipcr 全库模拟 PCR")
    st.caption("在参考数据库中批量模拟引物扩增。")

    s4_col1, s4_col2 = st.columns(2)
    with s4_col1:
        s4_primers = st.text_input(
            "引物文件 (primers.tsv)",
            value="example_data/primers.tsv",
            key="wf_s4_primers",
        )
        s4_database = st.text_input(
            "参考数据库 (normalized FASTA)",
            value="qc_spec_results/index/database.fasta",
            key="wf_s4_database",
        )
    with s4_col2:
        s4_taxonomy = st.text_input(
            "分类信息 (taxonomy.tsv)",
            value="example_data/taxonomy.tsv",
            key="wf_s4_taxonomy",
        )
        s4_outdir = st.text_input(
            "obipcr 输出目录",
            value="obipcr_results",
            key="wf_s4_outdir",
        )

    s4_mismatches = st.text_input(
        "mismatches",
        value="0,1,2",
        key="wf_s4_mismatches",
        help="Comma-separated mismatch levels.",
    )

    s4_flags_col, s4_timeout_col = st.columns([2, 1])
    with s4_flags_col:
        s4_circular = st.checkbox("Circular（环状基因组）", value=True, key="wf_s4_circular")
        s4_summarize = st.checkbox("Summarize（汇总统计）", value=True, key="wf_s4_summarize")
        s4_report = st.checkbox("Report（生成报告）", value=True, key="wf_s4_report")
        s4_force = st.checkbox("Force（覆盖已有结果）", value=True, key="wf_s4_force")
    with s4_timeout_col:
        s4_timeout = st.number_input("timeout (s)", value=300, key="wf_s4_timeout")

    with st.expander("查看实际执行命令"):
        s4_cmd = build_obipcr_run_command(
            primers=s4_primers,
            database=s4_database,
            outdir=s4_outdir,
            taxonomy=s4_taxonomy,
            mismatches=s4_mismatches,
            circular=s4_circular,
            summarize=s4_summarize,
            report=s4_report,
            force=s4_force,
            timeout=s4_timeout,
        )
        st.code(" ".join(s4_cmd), language="bash")

    if st.button("运行全库模拟 PCR", key="wf_run_s4"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            with st.spinner("正在运行 obipcr 全库模拟 PCR..."):
                result = run_gui_command(s4_cmd, timeout=s4_timeout)
                st.session_state["wf_s4_result"] = result
    _render_step_result(st.session_state.get("wf_s4_result"))

    st.divider()

    # ── Step 5: Final Report ──────────────────────────────────────────

    st.subheader("步骤 5：生成最终综合报告")
    st.caption("整合 obipcr、引物质控和特异性分析结果。")

    s5_col1, s5_col2 = st.columns(2)
    with s5_col1:
        s5_obipcr_dir = st.text_input(
            "obipcr 结果目录",
            value="obipcr_results",
            key="wf_s5_obipcr_dir",
        )
        s5_qc_dir = st.text_input(
            "质控结果目录",
            value="qc_results",
            key="wf_s5_qc_dir",
        )
    with s5_col2:
        s5_spec_dir = st.text_input(
            "特异性分析结果目录",
            value="qc_spec_results",
            key="wf_s5_spec_dir",
        )
        s5_outdir = st.text_input(
            "最终报告输出目录",
            value="final_results",
            key="wf_s5_outdir",
        )

    with st.expander("查看实际执行命令"):
        s5_cmd = build_final_report_command(
            obipcr_dir=s5_obipcr_dir,
            qc_dir=s5_qc_dir,
            spec_dir=s5_spec_dir,
            outdir=s5_outdir,
        )
        st.code(" ".join(s5_cmd), language="bash")

    if st.button("生成最终报告", key="wf_run_s5"):
        if dry_run:
            st.info("仅预览模式：命令未实际执行。")
        else:
            with st.spinner("正在生成最终综合报告..."):
                result = run_gui_command(s5_cmd)
                st.session_state["wf_s5_result"] = result
    _render_step_result(st.session_state.get("wf_s5_result"))

elif page == "结果总览":
    st.header("结果总览")
    st.markdown("查看引物综合排名、物种覆盖率和质控状态。")

    # ── directory inputs ───────────────────────────────────────────────

    col1, col2 = st.columns(2)
    with col1:
        final_results_dir = st.text_input(
            "final_results 目录",
            value="final_results",
            key="res_final_dir",
            help="Directory containing primer_rank.tsv.",
        )
        obipcr_results_dir = st.text_input(
            "obipcr_results 目录",
            value="obipcr_results",
            key="res_obipcr_dir",
            help="Directory containing combined_summary.tsv.",
        )
    with col2:
        qc_results_dir = st.text_input(
            "qc_results 目录",
            value="qc_results",
            key="res_qc_dir",
            help="Directory containing primer_qc_summary.tsv.",
        )
        qc_spec_results_dir = st.text_input(
            "qc_spec_results 目录",
            value="qc_spec_results",
            key="res_spec_dir",
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

elif page == "报告查看":
    st.header("报告查看")
    st.markdown("查看最终综合报告和 obipcr 分析报告。")

    # ── file path inputs ──────────────────────────────────────────────

    col1, col2 = st.columns(2)
    with col1:
        final_report_path = st.text_input(
            "最终报告路径",
            value="final_results/final_report.md",
            key="rpt_final_path",
            help="Path to final_report.md.",
        )
    with col2:
        obipcr_report_path = st.text_input(
            "obipcr 报告路径",
            value="obipcr_results/report.md",
            key="rpt_obipcr_path",
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
