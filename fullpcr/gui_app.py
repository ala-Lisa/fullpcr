"""fullpcr Streamlit GUI — Phase 4: Environment + Inputs + Workflow + Results + Reports.

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

    if not path:
        st.info(f"**{label}** — Not provided")
        return

    if status == "PASS":
        st.success(f"✓ **{label}** — PASS — `{path}`")
    elif status == "WARN":
        st.warning(f"⚠ **{label}** — WARN — `{path}`")
    else:
        st.error(f"✗ **{label}** — FAIL — `{path}`")

    error = result.get("error")
    if error:
        st.caption(f"Error: {error}")

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
            st.caption(f"Columns: {', '.join(preview_rows[0])}")


# ── page config ──────────────────────────────────────────────────────────

st.set_page_config(
    page_title="fullpcr",
    page_icon="🧬",
    layout="wide",
)

# ── sidebar navigation ───────────────────────────────────────────────────

st.sidebar.title("🧬 fullpcr")

page = st.sidebar.radio(
    "Navigation",
    ["Environment", "Inputs", "Workflow", "Results", "Reports"],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.caption("Phase 4 — Results & Reports")

# ── Environment page ─────────────────────────────────────────────────────

if page == "Environment":
    st.title("Environment Check")
    st.markdown("Verify that all external dependencies are available.")

    # Python info
    st.header("Python")
    py_info = get_python_info()
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Status", "✓ Available")
    with col2:
        st.metric("Executable", py_info["executable"])
    with st.expander("Details"):
        st.code(py_info["version"], language=None)

    st.divider()

    # fullpcr info
    st.header("fullpcr")
    fp_info = get_fullpcr_info()
    if fp_info["importable"]:
        st.success("fullpcr is importable")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Version", fp_info.get("version", "N/A"))
        with col2:
            st.metric("Path", fp_info.get("path", "N/A"))
    else:
        st.error(f"fullpcr import failed: {fp_info['error']}")

    st.divider()

    # obipcr
    st.header("obipcr")
    obi = check_command_available(["obipcr", "--version"])
    if obi["available"]:
        st.success("obipcr is available")
        if obi["version"]:
            st.caption(obi["version"])
    else:
        st.error(obi["error"] or "obipcr is not available")

    st.divider()

    # mfeprimer
    st.header("mfeprimer")
    mfe = check_command_available(["mfeprimer", "version"])
    if mfe["available"]:
        st.success("mfeprimer is available")
        if mfe["version"]:
            st.caption(mfe["version"])
    else:
        st.error(mfe["error"] or "mfeprimer is not available")

    st.divider()

    # working directory
    st.header("Working Directory")
    st.code(os.getcwd(), language=None)

# ── placeholder pages ────────────────────────────────────────────────────

elif page == "Inputs":
    st.title("Inputs")
    st.markdown("Configure input files and output directory for the analysis pipeline.")

    # ── file path inputs ──────────────────────────────────────────────

    col_left, col_right = st.columns(2)

    with col_left:
        primers_path = st.text_input(
            "primers.tsv",
            value="example_data/primers.tsv",
            help="Path to the primers file (Tab-separated).",
            key="inputs_primers_path",
        )
        database_path = st.text_input(
            "database.fasta",
            value="example_data/real_mito_small.fasta",
            help="Path to the FASTA database (.fasta, .fa, .fasta.gz, .fa.gz).",
            key="inputs_database_path",
        )

    with col_right:
        taxonomy_path = st.text_input(
            "taxonomy.tsv",
            value="example_data/taxonomy.tsv",
            help="Path to the taxonomy file (Tab-separated).",
            key="inputs_taxonomy_path",
        )
        output_dir = st.text_input(
            "Output root directory",
            value="results",
            help="Root directory for all output files.",
            key="inputs_output_dir",
        )

    st.divider()

    # ── validate button ───────────────────────────────────────────────

    if st.button("Validate inputs", type="primary", key="inputs_validate_btn"):
        st.subheader("Validation Results")

        # -- primers ---------------------------------------------------
        st.markdown("#### primers.tsv")
        _render_file_validation(
            label="primers.tsv",
            result=validate_primers_file(primers_path),
            show_preview=True,
            preview_caption="First 10 rows (including header)",
        )

        # -- database ---------------------------------------------------
        st.markdown("#### database.fasta")
        db_result = validate_database_file(database_path)
        _render_file_validation(
            label="database",
            result=db_result,
            show_preview=False,
        )
        if db_result.get("record_count") is not None:
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("Record count", db_result["record_count"])
            with col_b:
                st.metric(
                    "Total bases",
                    f"{db_result['total_bases']:,}" if db_result.get("total_bases") else "N/A",
                )

        # -- taxonomy ---------------------------------------------------
        st.markdown("#### taxonomy.tsv")
        tax_result = validate_taxonomy_file(taxonomy_path)
        _render_file_validation(
            label="taxonomy.tsv",
            result=tax_result,
            show_preview=True,
            preview_caption="First 10 rows (including header)",
        )
        if tax_result.get("record_count") is not None:
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("Record count", tax_result["record_count"])
            with col_b:
                st.metric(
                    "Unique species",
                    tax_result["unique_species"]
                    if tax_result.get("unique_species") is not None
                    else "N/A",
                )

        # -- output directory -------------------------------------------
        st.markdown("#### Output directory")
        out_result = validate_output_directory(output_dir)
        if out_result["status"] == "PASS":
            st.success(f"✓ Directory exists: `{out_result['path']}`")
        elif out_result.get("will_create"):
            st.warning(f"Directory will be created: `{out_result['path']}`")
        else:
            st.error(out_result.get("error", "Unknown error"))

        # -- suggested output structure ---------------------------------
        st.markdown("#### Suggested output structure")
        st.code(
            f"{output_dir or 'results'}/\n"
            f"├── qc_results/\n"
            f"├── qc_spec_results/\n"
            f"├── obipcr_results/\n"
            f"└── final_results/\n",
            language=None,
        )

    # ── show suggestions even before validation ───────────────────────
    else:
        st.info("Click **Validate inputs** to check all input files and paths.")

elif page == "Workflow":
    st.title("Workflow")
    st.markdown(
        "Run the full in silico PCR pipeline step by step: "
        "**qc-pre → qc-summary → qc-spec → obipcr run → final-report**."
    )

    # ── dry-run toggle ────────────────────────────────────────────────

    dry_run = st.toggle(
        "Dry run (show commands only, do not execute)",
        value=False,
        key="workflow_dry_run",
        help="When enabled, commands are previewed but NOT executed.",
    )

    if dry_run:
        st.info("🔍 **Dry-run mode** — commands will be displayed but not executed.")

    st.divider()

    # ── helper: render a step section ──────────────────────────────────

    def _render_step_result(run_result: dict | None) -> None:
        """Display the result of a command execution."""
        if run_result is None:
            return

        status = run_result["status"]
        if status == "PASS":
            st.success(run_result["message"])
        elif status == "TIMEOUT":
            st.error(run_result["message"])
        else:
            st.error(run_result["message"])

        if run_result.get("returncode") is not None:
            st.metric("Return code", run_result["returncode"])

        col_out, col_err = st.columns(2)
        with col_out:
            stdout_text = run_result.get("stdout", "")
            st.text_area(
                "stdout",
                value=stdout_text if stdout_text else "(empty)",
                height=200,
                key=f"stdout_{id(run_result)}",
            )
        with col_err:
            stderr_text = run_result.get("stderr", "")
            st.text_area(
                "stderr",
                value=stderr_text if stderr_text else "(empty)",
                height=200,
                key=f"stderr_{id(run_result)}",
            )

    # ── Step 1: MFEprimer QC ──────────────────────────────────────────

    st.header("Step 1: MFEprimer QC (qc-pre)")
    st.caption("Run MFEprimer thermo, dimer, hairpin, and degen analysis.")

    step1_col1, step1_col2 = st.columns(2)
    with step1_col1:
        s1_primers = st.text_input(
            "primers.tsv",
            value="example_data/primers.tsv",
            key="wf_s1_primers",
        )
    with step1_col2:
        s1_outdir = st.text_input(
            "QC output directory",
            value="qc_results",
            key="wf_s1_outdir",
        )

    s1_col_flags, s1_col_params = st.columns([1, 2])
    with s1_col_flags:
        s1_thermo = st.checkbox("Thermo", value=True, key="wf_s1_thermo")
        s1_dimer = st.checkbox("Dimer", value=True, key="wf_s1_dimer")
        s1_hairpin = st.checkbox("Hairpin", value=True, key="wf_s1_hairpin")
        s1_degen = st.checkbox("Degen", value=True, key="wf_s1_degen")
    with s1_col_params:
        s1_max_deg = st.number_input("max_degenerate_variants", value=256, key="wf_s1_maxdeg")
        s1_score = st.number_input("score", value=5, key="wf_s1_score")
        s1_mismatch = st.number_input("mismatch", value=2, key="wf_s1_mismatch")
        s1_dg = st.number_input("dg", value=-5.0, key="wf_s1_dg")
        s1_tm = st.number_input("tm", value=50.0, key="wf_s1_tm")
        s1_timeout = st.number_input("timeout (s)", value=60, key="wf_s1_timeout")

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

    if st.button("Run qc-pre", key="wf_run_s1"):
        if dry_run:
            st.info("Dry-run: command not executed.")
        else:
            with st.spinner("Running qc-pre..."):
                result = run_gui_command(s1_cmd, timeout=s1_timeout)
                st.session_state["wf_s1_result"] = result
    _render_step_result(st.session_state.get("wf_s1_result"))

    st.divider()

    # ── Step 2: QC Summary ────────────────────────────────────────────

    st.header("Step 2: QC Summary (qc-summary)")
    st.caption("Parse MFEprimer raw outputs and generate QC summary TSVs.")

    s2_qc_dir = st.text_input(
        "QC results directory",
        value="qc_results",
        key="wf_s2_qcdir",
    )
    s2_cmd = build_qc_summary_command(qc_dir=s2_qc_dir)
    st.code(" ".join(s2_cmd), language="bash")

    if st.button("Run qc-summary", key="wf_run_s2"):
        if dry_run:
            st.info("Dry-run: command not executed.")
        else:
            with st.spinner("Running qc-summary..."):
                result = run_gui_command(s2_cmd)
                st.session_state["wf_s2_result"] = result
    _render_step_result(st.session_state.get("wf_s2_result"))

    st.divider()

    # ── Step 3: MFEprimer Spec ────────────────────────────────────────

    st.header("Step 3: MFEprimer Spec (qc-spec)")
    st.caption("Build database index and run MFEprimer specificity screening.")

    s3_col1, s3_col2 = st.columns(2)
    with s3_col1:
        s3_primers = st.text_input(
            "primers.tsv",
            value="example_data/primers.tsv",
            key="wf_s3_primers",
        )
        s3_database = st.text_input(
            "database.fasta",
            value="example_data/real_mito_small.fasta",
            key="wf_s3_database",
        )
    with s3_col2:
        s3_outdir = st.text_input(
            "Spec output directory",
            value="qc_spec_results",
            key="wf_s3_outdir",
        )

    s3_col_params1, s3_col_params2 = st.columns(2)
    with s3_col_params1:
        s3_min_size = st.number_input("min_size", value=80, key="wf_s3_minsize")
        s3_max_size = st.number_input("max_size", value=500, key="wf_s3_maxsize")
        s3_tm = st.number_input("tm", value=50.0, key="wf_s3_tm")
    with s3_col_params2:
        s3_max_tm = st.number_input("max_tm", value=75.0, key="wf_s3_maxtm")
        s3_mismatch = st.number_input("mismatch", value=2, key="wf_s3_mismatch")
        s3_cpu = st.number_input("cpu", value=4, key="wf_s3_cpu")
        s3_kvalue = st.number_input("kvalue", value=9, key="wf_s3_kvalue")
        s3_timeout = st.number_input("timeout (s)", value=300, key="wf_s3_timeout")
        s3_force = st.checkbox("Force", value=True, key="wf_s3_force")

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

    if st.button("Run qc-spec", key="wf_run_s3"):
        if dry_run:
            st.info("Dry-run: command not executed.")
        else:
            with st.spinner("Running qc-spec..."):
                result = run_gui_command(s3_cmd, timeout=s3_timeout)
                st.session_state["wf_s3_result"] = result
    _render_step_result(st.session_state.get("wf_s3_result"))

    st.divider()

    # ── Step 4: obipcr Run ────────────────────────────────────────────

    st.header("Step 4: obipcr Run")
    st.caption("Batch in silico PCR using OBITools4 obipcr.")

    s4_col1, s4_col2 = st.columns(2)
    with s4_col1:
        s4_primers = st.text_input(
            "primers.tsv",
            value="example_data/primers.tsv",
            key="wf_s4_primers",
        )
        s4_database = st.text_input(
            "Normalized database",
            value="qc_spec_results/index/database.fasta",
            key="wf_s4_database",
        )
    with s4_col2:
        s4_taxonomy = st.text_input(
            "taxonomy.tsv",
            value="example_data/taxonomy.tsv",
            key="wf_s4_taxonomy",
        )
        s4_outdir = st.text_input(
            "obipcr output directory",
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
        s4_circular = st.checkbox("Circular", value=True, key="wf_s4_circular")
        s4_summarize = st.checkbox("Summarize", value=True, key="wf_s4_summarize")
        s4_report = st.checkbox("Report", value=True, key="wf_s4_report")
        s4_force = st.checkbox("Force", value=True, key="wf_s4_force")
    with s4_timeout_col:
        s4_timeout = st.number_input("timeout (s)", value=300, key="wf_s4_timeout")

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

    if st.button("Run obipcr", key="wf_run_s4"):
        if dry_run:
            st.info("Dry-run: command not executed.")
        else:
            with st.spinner("Running obipcr..."):
                result = run_gui_command(s4_cmd, timeout=s4_timeout)
                st.session_state["wf_s4_result"] = result
    _render_step_result(st.session_state.get("wf_s4_result"))

    st.divider()

    # ── Step 5: Final Report ──────────────────────────────────────────

    st.header("Step 5: Final Report")
    st.caption("Integrate obipcr, QC, and spec results into unified primer evaluation.")

    s5_col1, s5_col2 = st.columns(2)
    with s5_col1:
        s5_obipcr_dir = st.text_input(
            "obipcr results directory",
            value="obipcr_results",
            key="wf_s5_obipcr_dir",
        )
        s5_qc_dir = st.text_input(
            "QC results directory",
            value="qc_results",
            key="wf_s5_qc_dir",
        )
    with s5_col2:
        s5_spec_dir = st.text_input(
            "Spec results directory",
            value="qc_spec_results",
            key="wf_s5_spec_dir",
        )
        s5_outdir = st.text_input(
            "Final report output directory",
            value="final_results",
            key="wf_s5_outdir",
        )

    s5_cmd = build_final_report_command(
        obipcr_dir=s5_obipcr_dir,
        qc_dir=s5_qc_dir,
        spec_dir=s5_spec_dir,
        outdir=s5_outdir,
    )
    st.code(" ".join(s5_cmd), language="bash")

    if st.button("Run final-report", key="wf_run_s5"):
        if dry_run:
            st.info("Dry-run: command not executed.")
        else:
            with st.spinner("Running final-report..."):
                result = run_gui_command(s5_cmd)
                st.session_state["wf_s5_result"] = result
    _render_step_result(st.session_state.get("wf_s5_result"))

elif page == "Results":
    st.title("Results")
    st.markdown("Browse and visualize fullpcr analysis results.")

    # ── directory inputs ───────────────────────────────────────────────

    col1, col2 = st.columns(2)
    with col1:
        final_results_dir = st.text_input(
            "final_results directory",
            value="final_results",
            key="res_final_dir",
            help="Directory containing primer_rank.tsv.",
        )
        obipcr_results_dir = st.text_input(
            "obipcr_results directory",
            value="obipcr_results",
            key="res_obipcr_dir",
            help="Directory containing combined_summary.tsv.",
        )
    with col2:
        qc_results_dir = st.text_input(
            "qc_results directory",
            value="qc_results",
            key="res_qc_dir",
            help="Directory containing primer_qc_summary.tsv.",
        )
        qc_spec_results_dir = st.text_input(
            "qc_spec_results directory",
            value="qc_spec_results",
            key="res_spec_dir",
            help="Directory containing spec/primer_spec.tsv.",
        )

    st.divider()

    if st.button("Load Results", type="primary", key="res_load_btn"):
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

        st.header("Primer Ranking")
        if rank_result["status"] == "PASS" and rank_result["df"] is not None:
            rank_df = rank_result["df"]
            rank_summary = summarize_primer_rank(rank_df)

            # -- metric cards --
            st.subheader("Summary")
            mc1, mc2, mc3, mc4 = st.columns(4)
            with mc1:
                top = rank_summary.get("top_primer")
                st.metric("Top Primer", top if top else "N/A")
            with mc2:
                score = rank_summary.get("top_final_score")
                st.metric(
                    "Top final_score",
                    f"{score:.4f}" if score is not None else "N/A",
                )
            with mc3:
                st.metric(
                    "Recommended",
                    rank_summary.get("recommended_count", 0),
                )
            with mc4:
                st.metric(
                    "Not Recommended",
                    rank_summary.get("not_recommended_count", 0),
                )

            # -- final_status counts --
            statuses = rank_summary.get("final_statuses", {})
            if statuses:
                st.markdown("**final_status distribution**")
                status_cols = st.columns(len(statuses))
                for i, (status_name, count) in enumerate(sorted(statuses.items())):
                    with status_cols[i]:
                        st.metric(status_name, count)

            # -- full table --
            st.subheader("Full Ranking Table")
            st.dataframe(
                rank_df,
                use_container_width=True,
                hide_index=True,
            )

            # -- bar charts --
            st.subheader("Charts")

            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                st.markdown("**final_score by primer**")
                if "primer_id" in rank_df.columns and "final_score" in rank_df.columns:
                    chart_df = rank_df[["primer_id", "final_score"]].copy()
                    chart_df["final_score"] = pd.to_numeric(
                        chart_df["final_score"], errors="coerce"
                    ).fillna(0)
                    chart_df = chart_df.set_index("primer_id")
                    st.bar_chart(chart_df, use_container_width=True)
                else:
                    st.info("final_score column not available for chart.")

            with chart_col2:
                st.markdown("**obipcr_unique_species_count by primer**")
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
                    st.info(
                        "obipcr_unique_species_count column not available for chart."
                    )

            # -- download button --
            primer_rank_path = Path(final_results_dir) / "primer_rank.tsv"
            if primer_rank_path.is_file():
                st.download_button(
                    label="Download primer_rank.tsv",
                    data=primer_rank_path.read_bytes(),
                    file_name="primer_rank.tsv",
                    mime="text/tab-separated-values",
                    key="dl_primer_rank",
                )

        else:
            st.warning(
                f"primer_rank.tsv not available: {rank_result.get('error', 'Unknown error')}"
            )

        st.divider()

        # ── QC / Spec status table ────────────────────────────────────

        st.header("QC & Spec Status")
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
                st.dataframe(
                    rank_df[available],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No status columns available in primer_rank.tsv.")
        else:
            st.info("Load primer_rank.tsv to see QC & spec status.")

        st.divider()

        # ── combined_summary.tsv ──────────────────────────────────────

        st.header("obipcr Combined Summary")
        if combined_result["status"] == "PASS" and combined_result["df"] is not None:
            st.caption(
                f"{combined_result['row_count']} rows, "
                f"{len(combined_result['columns'])} columns"
            )
            with st.expander("Show combined_summary.tsv", expanded=False):
                st.dataframe(
                    combined_result["df"],
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.info(
                f"combined_summary.tsv not available: "
                f"{combined_result.get('error', 'Unknown error')}"
            )

        # ── primer_qc_summary.tsv ─────────────────────────────────────

        st.header("MFEprimer QC Summary")
        if qc_result["status"] == "PASS" and qc_result["df"] is not None:
            st.caption(
                f"{qc_result['row_count']} rows, "
                f"{len(qc_result['columns'])} columns"
            )
            with st.expander("Show primer_qc_summary.tsv", expanded=False):
                st.dataframe(
                    qc_result["df"],
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.info(
                f"primer_qc_summary.tsv not available: "
                f"{qc_result.get('error', 'Unknown error')}"
            )

        # ── primer_spec.tsv ───────────────────────────────────────────

        st.header("MFEprimer Spec Summary")
        if spec_result["status"] == "PASS" and spec_result["df"] is not None:
            st.caption(
                f"{spec_result['row_count']} rows, "
                f"{len(spec_result['columns'])} columns"
            )
            with st.expander("Show primer_spec.tsv", expanded=False):
                st.dataframe(
                    spec_result["df"],
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.info(
                f"primer_spec.tsv not available: "
                f"{spec_result.get('error', 'Unknown error')}"
            )

    else:
        st.info("Click **Load Results** to browse and visualize analysis outputs.")

elif page == "Reports":
    st.title("Reports")
    st.markdown("View final evaluation and obipcr run reports.")

    # ── file path inputs ──────────────────────────────────────────────

    col1, col2 = st.columns(2)
    with col1:
        final_report_path = st.text_input(
            "Final report path",
            value="final_results/final_report.md",
            key="rpt_final_path",
            help="Path to final_report.md.",
        )
    with col2:
        obipcr_report_path = st.text_input(
            "obipcr report path",
            value="obipcr_results/report.md",
            key="rpt_obipcr_path",
            help="Path to obipcr_results/report.md.",
        )

    st.divider()

    if st.button("Load Reports", type="primary", key="rpt_load_btn"):
        # ── load reports ──────────────────────────────────────────────

        final_rpt = load_markdown_file(final_report_path)
        obi_rpt = load_markdown_file(obipcr_report_path)

        st.session_state["rpt_final"] = final_rpt
        st.session_state["rpt_obipcr"] = obi_rpt

        # ── display in tabs ───────────────────────────────────────────

        tab1, tab2 = st.tabs(["Final Report", "obipcr Report"])

        with tab1:
            st.markdown(f"**Source:** `{final_report_path}`")

            if final_rpt["status"] == "PASS" and final_rpt["content"]:
                st.markdown(final_rpt["content"])
                # Download button
                st.download_button(
                    label="Download final_report.md",
                    data=final_rpt["content"],
                    file_name="final_report.md",
                    mime="text/markdown",
                    key="dl_final_report",
                )
            elif final_rpt["status"] == "WARN":
                st.warning(final_rpt.get("error", "File is empty"))
            else:
                st.info(
                    f"Report not available: {final_rpt.get('error', 'Unknown error')}"
                )

        with tab2:
            st.markdown(f"**Source:** `{obipcr_report_path}`")

            if obi_rpt["status"] == "PASS" and obi_rpt["content"]:
                st.markdown(obi_rpt["content"])
                # Download button
                st.download_button(
                    label="Download obipcr report.md",
                    data=obi_rpt["content"],
                    file_name="obipcr_report.md",
                    mime="text/markdown",
                    key="dl_obipcr_report",
                )
            elif obi_rpt["status"] == "WARN":
                st.warning(obi_rpt.get("error", "File is empty"))
            else:
                st.info(
                    f"Report not available: {obi_rpt.get('error', 'Unknown error')}"
                )

    else:
        st.info("Click **Load Reports** to view generated reports.")
