"""CLI entry point for fullpcr — batch in silico PCR analysis."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from fullpcr.obipcr_runner import (
    FAILED_JOBS_FIELDNAMES,
    build_obipcr_command,
    run_obipcr_job,
)
from fullpcr.primers import read_primers
from fullpcr.degen import write_degen_outputs
from fullpcr.mfeprimer_runner import (
    QC_FAILED_JOBS_FIELDNAMES as QC_FIELDNAMES,
    build_mfeprimer_degen_command,
    build_mfeprimer_dimer_command,
    build_mfeprimer_hairpin_command,
    build_mfeprimer_spec_command,
    build_mfeprimer_thermo_command,
    check_mfeprimer_available,
    run_mfeprimer_degen,
    run_mfeprimer_dimer,
    run_mfeprimer_hairpin,
    run_mfeprimer_spec,
    run_mfeprimer_thermo,
)
from fullpcr.primer_export import (
    export_primer_pairs_to_tsv,
    export_primers_to_fasta,
)
from fullpcr.qc import write_qc_outputs
from fullpcr.qc_spec import (
    parse_spec_tsv,
    prepare_spec_database,
    write_spec_outputs,
    write_spec_primer_pairs,
)
from fullpcr.report import generate_report
from fullpcr.final_report import write_final_outputs
from fullpcr.summarize import write_summary_outputs


def _parse_mismatches(raw: str) -> list[int]:
    """Parse a comma-separated mismatch string into a sorted list of ints.

    Example: "0,1,2,3" -> [0, 1, 2, 3]
    """
    if not raw or not raw.strip():
        raise ValueError("--mismatches 不能为空")

    parts = [p.strip() for p in raw.split(",")]
    result: list[int] = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError as exc:
            raise ValueError(
                f"--mismatches 包含非整数值: {p!r}"
            ) from exc
    return result


def _validate_files(*, primers: str, database: str) -> None:
    """Validate that input files exist. Exits with message if not."""
    errors: list[str] = []

    if not Path(primers).is_file():
        errors.append(f"primers 文件不存在: {primers}")

    if not Path(database).is_file():
        errors.append(f"database 文件不存在: {database}")

    if errors:
        for err in errors:
            print(f"错误: {err}", file=sys.stderr)
        sys.exit(1)


def _build_output_path(
    outdir: str | Path, primer_id: str, mismatch: int
) -> Path:
    """Return the expected output FASTA path for a primer/mismatch pair."""
    return (
        Path(outdir)
        / primer_id
        / f"mismatch_{mismatch}"
        / "obipcr_amplicons.fasta"
    )


# ── run command ──────────────────────────────────────────────────────────


def run_dry_run(args: argparse.Namespace) -> list[dict]:
    """Execute a dry-run: print commands without calling obipcr.

    Returns a list of dicts with keys ``primer_id``, ``mismatch``,
    ``command``, and ``output`` for verification in tests.
    """
    primers = read_primers(args.primers)
    mismatches = _parse_mismatches(args.mismatches)

    jobs: list[dict] = []

    for primer in primers:
        for m in mismatches:
            output_path = _build_output_path(
                args.outdir, primer.primer_id, m
            )
            config = build_obipcr_command(
                forward=primer.forward,
                reverse=primer.reverse,
                min_length=primer.min_length,
                max_length=primer.max_length,
                allowed_mismatches=m,
                database=args.database,
                output=str(output_path),
                circular=args.circular,
            )

            cmd_str = " ".join(config.command)
            print(f"[DRY-RUN] {cmd_str}")
            print(f"[DRY-RUN] output → {config.output}")

            jobs.append(
                {
                    "primer_id": primer.primer_id,
                    "mismatch": m,
                    "command": config.command,
                    "output": config.output,
                }
            )

    total = len(primers) * len(mismatches)
    print(
        f"\n合计: {len(primers)} primer × {len(mismatches)} "
        f"mismatch = {total} jobs"
    )

    return jobs


def _write_tsv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """Write a list of dicts to a TSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def run_real(args: argparse.Namespace) -> None:
    """Execute obipcr jobs for real, parse results, write outputs."""
    primers = read_primers(args.primers)
    mismatches = _parse_mismatches(args.mismatches)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    total = len(primers) * len(mismatches)
    jobs_done = 0
    failed_jobs: list[dict] = []

    print(
        f"开始执行 {total} 个任务 "
        f"({len(primers)} primer × {len(mismatches)} mismatch)..."
    )

    for primer in primers:
        for m in mismatches:
            output_path = _build_output_path(outdir, primer.primer_id, m)
            config = build_obipcr_command(
                forward=primer.forward,
                reverse=primer.reverse,
                min_length=primer.min_length,
                max_length=primer.max_length,
                allowed_mismatches=m,
                database=args.database,
                output=str(output_path),
                circular=args.circular,
            )

            result = run_obipcr_job(
                primer_id=primer.primer_id,
                mismatch=m,
                config=config,
                resume=args.resume,
                force=args.force,
                timeout=args.timeout,
            )

            jobs_done += 1
            status = result["status"]
            marker = {"success": "✓", "failed": "✗", "skipped": "○"}.get(
                status, "?"
            )
            print(
                f"  [{jobs_done}/{total}] {marker} "
                f"{primer.primer_id} mismatch={m} — {status}"
            )

            if status == "failed":
                failed_jobs.append(result)
                if result.get("error_message"):
                    print(
                        f"      错误: {result['error_message']}",
                        file=sys.stderr,
                    )

    # Write failed_jobs.tsv (always writes, even with no failures)
    failed_path = outdir / "failed_jobs.tsv"
    _write_tsv(failed_path, FAILED_JOBS_FIELDNAMES, failed_jobs)
    if failed_jobs:
        print(
            f"\n失败任务已写入: {failed_path} ({len(failed_jobs)} 个)"
        )
    else:
        print("\n所有任务成功完成。")

    # ── optional post-run steps ──────────────────────────────────────
    if args.summarize or args.report:
        taxonomy = getattr(args, "taxonomy", None)
        if args.summarize:
            print("生成 summary 文件...")
            write_summary_outputs(outdir, taxonomy_path=taxonomy)
        if args.report:
            report_path = outdir / "report.md"
            print("生成 report...")
            generate_report(outdir, output_path=report_path)
            print(f"Report 已写入: {report_path}")


# ── summarize command ────────────────────────────────────────────────────


def run_summarize(args: argparse.Namespace) -> None:
    """Standalone summarize: generate all 5 summary TSV files."""
    indir = Path(args.indir)
    if not indir.is_dir():
        print(f"错误: 目录不存在: {indir}", file=sys.stderr)
        sys.exit(1)

    taxonomy_path = getattr(args, "taxonomy", None)
    if taxonomy_path and not Path(taxonomy_path).is_file():
        print(f"错误: taxonomy 文件不存在: {taxonomy_path}", file=sys.stderr)
        sys.exit(1)

    print(f"从 {indir} 生成 summary 文件...")
    written = write_summary_outputs(indir, taxonomy_path=taxonomy_path)
    for key, path in written.items():
        print(f"  ✓ {path}")


# ── report command ───────────────────────────────────────────────────────


def run_report(args: argparse.Namespace) -> None:
    """Standalone report: generate report.md from summary TSV files."""
    indir = Path(args.indir)
    if not indir.is_dir():
        print(f"错误: 目录不存在: {indir}", file=sys.stderr)
        sys.exit(1)

    report_path = indir / "report.md"
    print(f"从 {indir} 生成 report...")
    generate_report(indir, output_path=report_path)
    print(f"  ✓ {report_path}")


# ── qc-pre command ─────────────────────────────────────────────────────


def run_qc_pre(args: argparse.Namespace) -> None:
    """QC pre-check with optional thermo / dimer / hairpin execution.

    Phase 1: validates inputs, exports primers to FASTA/TSV.
    Phase 2: runs selected MFEprimer QC modules and writes raw outputs.
    """
    primers = read_primers(args.primers)
    outdir = Path(args.outdir)
    mfeprimer_ok = check_mfeprimer_available()

    fasta_path = outdir / "primer_input.fasta"
    tsv_path = outdir / "primer_pairs.tsv"

    status_icon = "✓" if mfeprimer_ok else "✗ (未安装)"
    print(f"Primer 数量: {len(primers)}")
    print(f"输出目录: {outdir}")
    print(f"MFEprimer 可用: {status_icon}")

    # Determine which modules the user selected
    selected_modules: list[str] = []
    if args.thermo:
        selected_modules.append("thermo")
    if args.dimer:
        selected_modules.append("dimer")
    if args.hairpin:
        selected_modules.append("hairpin")

    if args.dry_run:
        print(f"\n[DRY-RUN] 将执行以下操作：")
        print(f"  1. 导出 primers → {fasta_path}")
        print(f"  2. 导出 primer pairs → {tsv_path}")

        if args.degen:
            print(
                f"  3. 简并引物展开 → "
                f"{outdir / 'degen' / 'expanded_primers.fasta'}"
            )
            print(
                f"     max_variants = "
                f"{args.max_degenerate_variants}"
            )

        if selected_modules:
            for mod in selected_modules:
                if mod == "thermo":
                    cfg = build_mfeprimer_thermo_command(
                        primer_fasta=str(fasta_path)
                    )
                elif mod == "dimer":
                    cfg = build_mfeprimer_dimer_command(
                        primer_fasta=str(fasta_path),
                        score=args.score,
                        mismatch=args.mismatch,
                        dg=args.dg,
                    )
                elif mod == "hairpin":
                    cfg = build_mfeprimer_hairpin_command(
                        primer_fasta=str(fasta_path),
                        tm=args.tm,
                        dg=args.dg,
                        score=args.score,
                    )
                else:
                    continue
                print(
                    f"  [{mod}] {' '.join(cfg.command)}"
                )
                print(
                    f"  [{mod}] stdout → "
                    f"{outdir / mod / f'{mod}_raw.txt'}"
                )
        else:
            print("  (未选择 QC 模块，仅导出 primers)")

        if not mfeprimer_ok and selected_modules:
            print("\n⚠️  MFEprimer 未安装，真实执行时会失败。")
        return

    # ── Real mode ────────────────────────────────────────────────────
    outdir.mkdir(parents=True, exist_ok=True)

    fasta_result = export_primers_to_fasta(primers, fasta_path)
    print(f"  ✓ {fasta_result}")

    tsv_result = export_primer_pairs_to_tsv(primers, tsv_path)
    print(f"  ✓ {tsv_result}")

    # ── degen (pure Python, no mfeprimer needed) ─────────────────────
    if args.degen:
        print("\n  简并引物展开...")
        degen_written = write_degen_outputs(
            primers, outdir, max_variants=args.max_degenerate_variants,
        )
        for key, path in degen_written.items():
            print(f"  ✓ {path}")

    if not selected_modules:
        print(
            "\n未选择 QC 模块（--thermo / --dimer / --hairpin）。"
            " 仅完成 primer 导出。"
        )
        return

    if not mfeprimer_ok:
        print("\n⚠️  MFEprimer 未安装。QC 模块无法执行。")
        failed_jobs: list[dict] = []
        for mod in selected_modules:
            failed_jobs.append(
                {
                    "module": mod,
                    "command": f"mfeprimer {mod} ...",
                    "output": str(
                        outdir / mod / f"{mod}_raw.txt"
                    ),
                    "status": "failed",
                    "error_message": (
                        "MFEprimer 未找到。"
                        " 请确认 MFEprimer 已安装且在 PATH 中。"
                    ),
                }
            )
        _write_tsv(
            outdir / "qc_failed_jobs.tsv",
            QC_FIELDNAMES,
            failed_jobs,
        )
        print(f"失败任务已写入: {outdir / 'qc_failed_jobs.tsv'}")
        return

    # ── Execute selected modules ──────────────────────────────────────
    failed_jobs: list[dict] = []
    done = 0
    total = len(selected_modules)

    for mod in selected_modules:
        print(f"\n  [{mod}] 运行中...")

        if mod == "thermo":
            result = run_mfeprimer_thermo(
                primer_fasta=str(fasta_path),
                outdir=str(outdir),
                resume=args.resume,
                force=args.force,
                timeout=args.timeout,
            )
        elif mod == "dimer":
            result = run_mfeprimer_dimer(
                primer_fasta=str(fasta_path),
                outdir=str(outdir),
                score=args.score,
                mismatch=args.mismatch,
                dg=args.dg,
                resume=args.resume,
                force=args.force,
                timeout=args.timeout,
            )
        elif mod == "hairpin":
            result = run_mfeprimer_hairpin(
                primer_fasta=str(fasta_path),
                outdir=str(outdir),
                tm=args.tm,
                dg=args.dg,
                score=args.score,
                resume=args.resume,
                force=args.force,
                timeout=args.timeout,
            )
        else:
            continue

        done += 1
        status = result["status"]
        marker = {"success": "✓", "failed": "✗", "skipped": "○"}.get(
            status, "?"
        )
        print(f"  [{done}/{total}] {marker} {mod} — {status}")

        if status == "failed":
            failed_jobs.append(result)
            if result.get("error_message"):
                print(
                    f"      错误: {result['error_message']}",
                    file=sys.stderr,
                )

    # Write qc_failed_jobs.tsv
    failed_path = outdir / "qc_failed_jobs.tsv"
    _write_tsv(failed_path, QC_FIELDNAMES, failed_jobs)
    if failed_jobs:
        print(
            f"\n失败任务已写入: {failed_path} ({len(failed_jobs)} 个)"
        )
    else:
        print("\n所有 QC 模块成功完成。")


# ── qc-summary command ──────────────────────────────────────────────────


def run_qc_summary(args: argparse.Namespace) -> None:
    """Parse MFEprimer raw outputs and generate structured QC TSVs."""
    qc_dir = Path(args.qc_dir)
    if not qc_dir.is_dir():
        print(f"错误: 目录不存在: {qc_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"从 {qc_dir} 解析 QC raw 输出...")
    written = write_qc_outputs(qc_dir)
    for key, path in written.items():
        print(f"  ✓ {path}")


# ── qc-spec command ──────────────────────────────────────────────────────


def run_qc_spec(args: argparse.Namespace) -> None:
    """Run MFEprimer spec specificity analysis on primer pairs.

    Copies the database, indexes it, runs spec, and generates
    ``primer_spec.tsv``.
    """
    import shutil

    primers = read_primers(args.primers)
    outdir = Path(args.outdir)
    mfeprimer_ok = check_mfeprimer_available()

    print(f"Primer 数量: {len(primers)}")
    print(f"数据库: {args.database}")
    print(f"输出目录: {outdir}")
    print(f"MFEprimer 可用: {'✓' if mfeprimer_ok else '✗ (未安装)'}")
    print(f"Amplicon size: {args.min_size or 'default'} – {args.max_size}")
    print(f"Tm range: {args.tm} – {args.max_tm}")
    if args.mismatch is not None:
        print(f"Mismatch: {args.mismatch}")
    print(f"CPU: {args.cpu}, K-value: {args.kvalue}")

    # ── dry-run ─────────────────────────────────────────────────────────
    if args.dry_run:
        print("\n[DRY-RUN] 将执行以下操作：")
        print(f"  1. 导出 primer pairs → {outdir / 'spec' / 'spec_primer_pairs.tsv'}")
        print(
            f"  2. FASTA 规范化 (wrap 80bp) → "
            f"{outdir / 'index' / Path(args.database).name}"
        )
        print(f"  3. 验证源/目标 record count 一致")
        print(
            f"  4. 建索引: mfeprimer index "
            f"-i {outdir / 'index' / Path(args.database).name} "
            f"-k {args.kvalue} -c {args.cpu}"
        )
        print(f"  5. 验证索引输出文件完整性")
        # Use the real builder so the printed command always matches what
        # a real run would execute — no drift between dry-run and live.
        spec_prefix = outdir / "spec" / "spec_output.txt"
        spec_cfg = build_mfeprimer_spec_command(
            primer_pairs_tsv=str(outdir / "spec" / "spec_primer_pairs.tsv"),
            database_path=str(outdir / "index" / Path(args.database).name),
            out_prefix=str(spec_prefix),
            min_size=args.min_size,
            max_size=args.max_size,
            tm=args.tm,
            max_tm=args.max_tm,
            mismatch=args.mismatch,
            mis_start=args.mis_start,
            mis_end=args.mis_end,
            cpu=args.cpu,
            kvalue=args.kvalue,
            max_amp_count=10000,
            bind=args.bind,
            cut_primer=args.cut_primer,
            mono=args.mono,
            diva=args.diva,
            dntp=args.dntp,
            oligo=args.oligo,
        )
        print(f"  6. 运行 spec: {' '.join(spec_cfg.command)}")
        print(f"  7. 解析 {spec_prefix}.spec.tsv → primer_spec.tsv")
        print(f"  8. 写入 database_stats.tsv")
        if not mfeprimer_ok:
            print("\n⚠️  MFEprimer 未安装，真实执行时会失败。")
        return

    # ── real mode ───────────────────────────────────────────────────────
    if not mfeprimer_ok:
        print(
            "\n⚠️  MFEprimer 未找到。请确认 MFEprimer 已安装且在 PATH 中。"
        )
        # Write failed_jobs with FAIL_INDEX status
        failed = [
            {
                "module": "index",
                "command": "mfeprimer index ...",
                "output": "",
                "status": "failed",
                "error_message": "MFEprimer 未找到。",
            },
            {
                "module": "spec",
                "command": "mfeprimer spec ...",
                "output": "",
                "status": "failed",
                "error_message": "MFEprimer 未找到。",
            },
        ]
        outdir.mkdir(parents=True, exist_ok=True)
        _write_tsv(
            outdir / "qc_spec_failed_jobs.tsv",
            list(QC_FIELDNAMES),
            failed,
        )
        print(f"失败任务已写入: {outdir / 'qc_spec_failed_jobs.tsv'}")
        # Still write primer_spec with FAIL_INDEX status
        from fullpcr.qc_spec import summarize_spec_records

        summary = summarize_spec_records([], primer_pairs=primers)
        for row in summary:
            row["status"] = "FAIL_INDEX"
            row["reason"] = "MFEprimer 未安装"
        written = write_spec_outputs(
            outdir, records=[], primer_pairs=primers,
        )
        # Overwrite the auto-generated PASS rows with FAIL_INDEX
        from fullpcr.qc_spec import PRIMER_SPEC_FIELDNAMES, _write_tsv as _wtsv

        _wtsv(
            outdir / "spec" / "primer_spec.tsv",
            PRIMER_SPEC_FIELDNAMES,
            summary,
        )
        for key, path in written.items():
            print(f"  ✓ {path}")
        return

    outdir.mkdir(parents=True, exist_ok=True)
    failed_jobs: list[dict] = []

    # ── Step 1: export primer pairs TSV ──────────────────────────────────
    pairs_path = outdir / "spec" / "spec_primer_pairs.tsv"
    pairs_path.parent.mkdir(parents=True, exist_ok=True)
    write_spec_primer_pairs(primers, pairs_path)
    print(f"  ✓ primer pairs → {pairs_path}")

    # ── Step 2-3: prepare database + index ───────────────────────────────
    index_dir = outdir / "index"
    print(f"\n  准备数据库索引 ({index_dir})...")
    index_result, db_stats = prepare_spec_database(
        database_path=args.database,
        index_dir=index_dir,
        force=args.force,
        kvalue=args.kvalue,
        cpu=args.cpu,
        timeout=args.timeout,
    )

    idx_status = index_result["status"]
    idx_marker = {"success": "✓", "failed": "✗", "skipped": "○"}.get(
        idx_status, "?"
    )
    print(f"  {idx_marker} index — {idx_status}")
    if idx_status == "failed":
        failed_jobs.append(index_result)
        if index_result.get("error_message"):
            print(
                f"      错误: {index_result['error_message']}",
                file=sys.stderr,
            )

    database_ref_count = db_stats.get("prepared_record_count", 0)
    print(
        f"  数据库: {db_stats.get('source_record_count', '?')}"
        f" → {database_ref_count} 条序列"
        f" (status={db_stats.get('status', '?')})"
    )

    # ── Step 4: run spec (skip if DB prep failed) ────────────────────────
    db_copy = index_dir / Path(args.database).name
    spec_result: dict = {
        "module": "spec",
        "command": "",
        "output": "",
        "status": "skipped",
        "error_message": "",
    }

    if idx_status == "failed":
        spec_result["status"] = "failed"
        spec_result["error_message"] = "index 失败，跳过 spec"
    else:
        print(f"\n  运行 spec (数据库: {db_copy})...")
        spec_result = run_mfeprimer_spec(
            primer_pairs_tsv=str(pairs_path),
            database_path=str(db_copy),
            outdir=str(outdir),
            min_size=args.min_size,
            max_size=args.max_size,
            tm=args.tm,
            max_tm=args.max_tm,
            mismatch=args.mismatch,
            mis_start=args.mis_start,
            mis_end=args.mis_end,
            cpu=args.cpu,
            kvalue=args.kvalue,
            max_amp_count=10000,
            bind=args.bind,
            cut_primer=args.cut_primer,
            mono=args.mono,
            diva=args.diva,
            dntp=args.dntp,
            oligo=args.oligo,
            resume=args.resume,
            force=args.force,
            timeout=args.timeout,
        )

    spec_status = spec_result["status"]
    spec_marker = {"success": "✓", "failed": "✗", "skipped": "○"}.get(
        spec_status, "?"
    )
    print(f"  {spec_marker} spec — {spec_status}")
    if spec_status == "failed":
        failed_jobs.append(spec_result)
        if spec_result.get("error_message"):
            print(
                f"      错误: {spec_result['error_message']}",
                file=sys.stderr,
            )

    # ── Step 5: parse and summarise ──────────────────────────────────────
    print("\n  解析 spec 结果...")
    spec_tsv_path = outdir / "spec" / "spec_output.txt.spec.tsv"
    records = parse_spec_tsv(spec_tsv_path)

    # If spec failed AND index failed, mark all primers
    if spec_status == "failed" and idx_status == "failed":
        for row in summarize_spec_records(
            [], primer_pairs=primers,
            database_reference_count=database_ref_count,
        ):
            row["status"] = "FAIL_INDEX; FAIL_SPEC"
            row["reason"] = "index 和 spec 均失败"
    elif idx_status == "failed":
        pass  # write_spec_outputs handles it
        pass  # write_spec_outputs handles it

    written = write_spec_outputs(
        outdir,
        records=records,
        primer_pairs=primers,
        failed_jobs=failed_jobs,
        max_amp_count=10000,
        database_reference_count=database_ref_count,
        db_stats=db_stats,
    )
    for key, path in written.items():
        print(f"  ✓ {path}")

    # Print summary
    if records:
        from fullpcr.qc_spec import summarize_spec_records

        summary_rows = summarize_spec_records(
            records, primer_pairs=primers,
            database_reference_count=database_ref_count,
        )
        print(f"\n  primer_spec 摘要:")
        for row in summary_rows:
            print(
                f"    {row['primer_id']}: "
                f"{row['spec_amplicon_count']} amplicons, "
                f"{row['unique_reference_count']} refs, "
                f"{row['unique_species_count']} spp — "
                f"{row['status']}"
            )

    # Write failed jobs
    if failed_jobs:
        print(
            f"\n失败任务已写入: "
            f"{outdir / 'qc_spec_failed_jobs.tsv'} "
            f"({len(failed_jobs)} 个)"
        )
    else:
        print("\n所有任务成功完成。")


# ── main entry point ─────────────────────────────────────────────────────


def run_final_report(args: argparse.Namespace) -> None:
    """Integrate obipcr, QC, and spec results into final primer evaluation."""
    print("Generating final report ...")
    outdir = Path(args.outdir)
    written = write_final_outputs(
        obipcr_dir=args.obipcr_dir,
        qc_dir=args.qc_dir,
        spec_dir=args.spec_dir,
        outdir=outdir,
    )
    for key, path in written.items():
        print(f"  ✓ {path}")
    print("Done.")


def run_gui(
    host: str = "127.0.0.1",
    port: int = 8501,
    data_dir: str | None = None,
) -> None:
    """Launch the Streamlit GUI app.

    Args:
        host: Server bind address (default 127.0.0.1).  Use ``0.0.0.0``
            to accept connections from other LAN devices.
        port: TCP port (default 8501, range 1-65535).
        data_dir: Optional persistent data directory for uploads and run
            results.  When provided it is created if missing, normalised
            to an absolute path, and passed to the Streamlit subprocess
            via the ``FULLPCR_DATA_DIR`` environment variable.  When
            omitted the existing ``FULLPCR_DATA_DIR`` env var (if set)
            is inherited; otherwise ``web_workspace`` falls back to
            ``./data``.
    """
    import os as _os
    import shutil
    import subprocess

    if shutil.which("streamlit") is None:
        print(
            "错误: streamlit 未安装。\n"
            "Please install GUI dependencies with:\n"
            '  pip install -e ".[gui]"',
            file=sys.stderr,
        )
        sys.exit(1)

    gui_app_path = Path(__file__).resolve().parent / "gui_app.py"
    if not gui_app_path.is_file():
        print(
            f"错误: GUI app 文件不存在: {gui_app_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── resolve and validate data_dir ─────────────────────────────────
    resolved_data_dir: str | None = None
    if data_dir is not None:
        p = Path(data_dir).expanduser().resolve()
        if p.exists() and not p.is_dir():
            print(
                f"错误: --data-dir 路径已存在但不是目录: {p}",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(
                f"错误: 无法创建 --data-dir 目录: {p}\n{exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        resolved_data_dir = str(p)

    # ── build subprocess environment ──────────────────────────────────
    env = _os.environ.copy()
    if resolved_data_dir is not None:
        env["FULLPCR_DATA_DIR"] = resolved_data_dir
    # When data_dir is None, inherit any existing FULLPCR_DATA_DIR from
    # the parent environment; web_workspace falls back to ./data if the
    # variable is absent or empty.

    cmd: list[str] = [
        "streamlit", "run", str(gui_app_path),
        "--server.address", host,
        "--server.port", str(port),
        "--client.toolbarMode", "minimal",
        "--theme.base", "light",
        "--theme.primaryColor", "#2eae7b",
        "--theme.backgroundColor", "#f7f9f5",
        "--theme.secondaryBackgroundColor", "#ffffff",
        "--theme.textColor", "#102a43",
    ]

    try:
        completed = subprocess.run(cmd, env=env, check=False)
    except FileNotFoundError:
        print(
            "错误: streamlit 未找到。\n"
            "Please install GUI dependencies with:\n"
            '  pip install -e ".[gui]"',
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nGUI 已停止。")
    else:
        if completed.returncode != 0:
            raise SystemExit(completed.returncode)


def _port_type(value: str) -> int:
    """Argparse type: reject ports outside 1-65535."""
    try:
        p = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"端口号必须是整数: '{value}'"
        ) from None
    if p < 1 or p > 65535:
        raise argparse.ArgumentTypeError(
            f"端口号必须在 1-65535 之间: {p}"
        )
    return p


def main(argv: list[str] | None = None) -> None:
    """Parse CLI args and dispatch to the appropriate subcommand."""
    parser = argparse.ArgumentParser(
        prog="fullpcr",
        description="Batch in silico PCR analysis using OBITools4 obipcr.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # ── run ────────────────────────────────────────────────────────────
    run_parser = subparsers.add_parser("run", help="Run in silico PCR")
    run_parser.add_argument(
        "--primers",
        required=True,
        help="Path to primers.tsv",
    )
    run_parser.add_argument(
        "--database",
        required=True,
        help="Path to FASTA database (.fasta / .fasta.gz)",
    )
    run_parser.add_argument(
        "--outdir",
        required=True,
        help="Output directory root",
    )
    run_parser.add_argument(
        "--mismatches",
        required=True,
        help='Comma-separated mismatch levels, e.g. "0,1,2,3"',
    )
    run_parser.add_argument(
        "--circular",
        action="store_true",
        help="Use circular DNA mode",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing obipcr",
    )
    run_parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip jobs where output files already exist",
    )
    run_parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-run even when --resume would skip",
    )
    run_parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Number of parallel jobs (default: 1, serial)",
    )
    run_parser.add_argument(
        "--summarize",
        action="store_true",
        help="Run write_summary_outputs() after execution",
    )
    run_parser.add_argument(
        "--report",
        action="store_true",
        help="Generate report.md after execution",
    )
    run_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout in seconds for each obipcr invocation (default: no timeout)",
    )
    run_parser.add_argument(
        "--taxonomy",
        default=None,
        help="Path to taxonomy.tsv (used with --summarize / --report)",
    )

    # ── summarize ──────────────────────────────────────────────────────
    summarize_parser = subparsers.add_parser(
        "summarize", help="Generate summary TSV files from results"
    )
    summarize_parser.add_argument(
        "--indir",
        required=True,
        help="Path to results directory containing primer/mismatch_N/ subdirs",
    )
    summarize_parser.add_argument(
        "--taxonomy",
        default=None,
        help="Path to taxonomy.tsv (optional)",
    )

    # ── report ─────────────────────────────────────────────────────────
    report_parser = subparsers.add_parser(
        "report", help="Generate Markdown report from summary TSV files"
    )
    report_parser.add_argument(
        "--indir",
        required=True,
        help="Path to results directory containing summary TSV files",
    )

    # ── qc-pre ─────────────────────────────────────────────────────────
    qc_pre_parser = subparsers.add_parser(
        "qc-pre",
        help="Pre-QC: export primers, check MFEprimer, run QC modules",
    )
    qc_pre_parser.add_argument(
        "--primers",
        required=True,
        help="Path to primers.tsv",
    )
    qc_pre_parser.add_argument(
        "--outdir",
        required=True,
        help="Output directory for QC results",
    )
    qc_pre_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check inputs and print plan without executing",
    )
    qc_pre_parser.add_argument(
        "--thermo",
        action="store_true",
        help="Run MFEprimer thermo analysis",
    )
    qc_pre_parser.add_argument(
        "--dimer",
        action="store_true",
        help="Run MFEprimer dimer analysis",
    )
    qc_pre_parser.add_argument(
        "--hairpin",
        action="store_true",
        help="Run MFEprimer hairpin analysis",
    )
    qc_pre_parser.add_argument(
        "--score",
        type=int,
        default=5,
        help="Alignment score threshold for dimer/hairpin (default: 5)",
    )
    qc_pre_parser.add_argument(
        "--mismatch",
        type=int,
        default=2,
        help="Allowed mismatches for dimer (default: 2)",
    )
    qc_pre_parser.add_argument(
        "--dg",
        type=float,
        default=-5.0,
        help="Free energy threshold kcal/mol for dimer/hairpin (default: -5.0)",
    )
    qc_pre_parser.add_argument(
        "--tm",
        type=float,
        default=50.0,
        help="Melting temperature threshold for hairpin (default: 50.0)",
    )
    qc_pre_parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip QC jobs where output files already exist",
    )
    qc_pre_parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-run even when --resume would skip",
    )
    qc_pre_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout in seconds for each MFEprimer invocation",
    )
    qc_pre_parser.add_argument(
        "--degen",
        action="store_true",
        help="Expand degenerate primers (IUPAC codes) and write degen outputs",
    )
    qc_pre_parser.add_argument(
        "--max-degenerate-variants",
        type=int,
        default=256,
        help="Maximum allowed expanded variants per primer (default: 256)",
    )

    # ── qc-summary ─────────────────────────────────────────────────────
    qc_summary_parser = subparsers.add_parser(
        "qc-summary",
        help="Parse MFEprimer raw outputs and generate QC summary TSVs",
    )
    qc_summary_parser.add_argument(
        "--qc-dir",
        required=True,
        help="Path to QC results directory (contains thermo/, dimer/, hairpin/)",
    )

    # ── qc-spec ─────────────────────────────────────────────────────────
    qc_spec_parser = subparsers.add_parser(
        "qc-spec",
        help="Run MFEprimer spec specificity analysis on primer pairs",
    )
    qc_spec_parser.add_argument(
        "--primers",
        required=True,
        help="Path to primers.tsv",
    )
    qc_spec_parser.add_argument(
        "--database",
        required=True,
        help="Path to FASTA database for specificity check",
    )
    qc_spec_parser.add_argument(
        "--outdir",
        required=True,
        help="Output directory for spec results",
    )
    qc_spec_parser.add_argument(
        "--min-size",
        type=int,
        default=None,
        help="Min amplicon size in bp (default: no min)",
    )
    qc_spec_parser.add_argument(
        "--max-size",
        type=int,
        default=2000,
        help="Max amplicon size in bp (default: 2000)",
    )
    qc_spec_parser.add_argument(
        "--tm",
        type=float,
        default=30.0,
        help="Minimum Tm cutoff in °C (default: 30)",
    )
    qc_spec_parser.add_argument(
        "--max-tm",
        type=float,
        default=100.0,
        help="Maximum Tm cutoff in °C (default: 100)",
    )
    qc_spec_parser.add_argument(
        "--mismatch",
        type=int,
        default=None,
        help="Max allowed mismatches for k-mer binding (--misMatch)",
    )
    qc_spec_parser.add_argument(
        "--cpu",
        type=int,
        default=4,
        help="Number of CPU threads (default: 4)",
    )
    qc_spec_parser.add_argument(
        "--kvalue",
        type=int,
        default=9,
        help="k-mer size for indexing/spec (default: 9)",
    )
    qc_spec_parser.add_argument(
        "--mis-start",
        type=int,
        default=None,
        help="Mismatch start position from 3' end (--misStart, default: 1)",
    )
    qc_spec_parser.add_argument(
        "--mis-end",
        type=int,
        default=None,
        help="Mismatch end position from 3' end (--misEnd, default: 9)",
    )
    qc_spec_parser.add_argument(
        "-b", "--bind",
        action="store_true",
        help="Print specific and nonspecific binding sites for each primer",
    )
    qc_spec_parser.add_argument(
        "--cut-primer",
        action="store_true",
        help="Cut primer from amplicons (--cutprimer)",
    )
    qc_spec_parser.add_argument(
        "--mono",
        type=float,
        default=None,
        help="Monovalent cation concentration in mM (default: 50)",
    )
    qc_spec_parser.add_argument(
        "--diva",
        type=float,
        default=None,
        help="Divalent cation concentration in mM (default: 1.5)",
    )
    qc_spec_parser.add_argument(
        "--dntp",
        type=float,
        default=None,
        help="dNTP concentration in mM (default: 0.25)",
    )
    qc_spec_parser.add_argument(
        "--oligo",
        type=float,
        default=None,
        help="Annealing oligo concentration in nM (default: 50)",
    )
    qc_spec_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout in seconds for each MFEprimer invocation",
    )
    qc_spec_parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-copy database, re-index, and re-run spec",
    )
    qc_spec_parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip index/spec if output already exists",
    )
    qc_spec_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan and commands without executing",
    )

    # -- final-report --------------------------------------------------
    final_report_parser = subparsers.add_parser(
        "final-report",
        help="Integrate obipcr, QC, and spec results into unified primer evaluation",
    )
    final_report_parser.add_argument(
        "--obipcr-dir", required=True,
        help="Path to obipcr results directory (contains combined_summary.tsv)",
    )
    final_report_parser.add_argument(
        "--qc-dir", required=True,
        help="Path to MFEprimer QC directory (contains primer_qc_summary.tsv)",
    )
    final_report_parser.add_argument(
        "--spec-dir", required=True,
        help="Path to MFEprimer spec directory (contains spec/primer_spec.tsv)",
    )
    final_report_parser.add_argument(
        "--outdir", required=True,
        help="Output directory for final report files",
    )

    # -- gui -----------------------------------------------------------
    gui_parser = subparsers.add_parser(
        "gui",
        help="Launch the fullpcr Streamlit GUI",
    )
    gui_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Server bind address (default: 127.0.0.1).  Use 0.0.0.0 for LAN access.",
    )
    gui_parser.add_argument(
        "--port",
        type=_port_type,
        default=8501,
        help="TCP port (default: 8501, range 1-65535).",
    )
    gui_parser.add_argument(
        "--data-dir",
        default=None,
        help=(
            "Persistent data directory for uploaded files and run results.  "
            "Created if missing.  When omitted, the FULLPCR_DATA_DIR "
            "environment variable is inherited; otherwise falls back to ./data."
        ),
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "run":
        _validate_files(primers=args.primers, database=args.database)
        if args.dry_run:
            run_dry_run(args)
        else:
            run_real(args)
    elif args.command == "summarize":
        run_summarize(args)
    elif args.command == "report":
        run_report(args)
    elif args.command == "qc-pre":
        run_qc_pre(args)
    elif args.command == "qc-summary":
        run_qc_summary(args)
    elif args.command == "qc-spec":
        _validate_files(primers=args.primers, database=args.database)
        run_qc_spec(args)
    elif args.command == "final-report":
        run_final_report(args)
    elif args.command == "gui":
        run_gui(host=args.host, port=args.port, data_dir=args.data_dir)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
