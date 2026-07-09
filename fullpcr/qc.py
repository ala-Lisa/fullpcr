"""MFEprimer raw output parser and QC summary builder.

Phase 2.5: parse thermo / dimer / hairpin raw outputs into structured TSVs
and generate primer_qc_summary.tsv.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

# ── constants ──────────────────────────────────────────────────────────────

THERMO_FIELDNAMES = [
    "primer_name",
    "primer_id",
    "primer_side",
    "sequence",
    "size",
    "gc",
    "tm",
    "delta_g",
    "reverse_complement",
    "note",
]

DIMER_FIELDNAMES = [
    "primer_id",
    "primer_a",
    "primer_b",
    "dimer_count",
    "max_score",
    "min_delta_g",
    "has_3prime_dimer",
    "raw_block",
    "parse_status",
]

HAIRPIN_FIELDNAMES = [
    "primer_id",
    "primer_name",
    "hairpin_count",
    "max_score",
    "min_delta_g",
    "raw_block",
    "parse_status",
]

SUMMARY_FIELDNAMES = [
    "primer_id",
    "forward_tm",
    "reverse_tm",
    "tm_difference",
    "forward_gc",
    "reverse_gc",
    "forward_delta_g",
    "reverse_delta_g",
    "dimer_count",
    "dimer_max_score",
    "dimer_min_delta_g",
    "has_3prime_dimer",
    "forward_hairpin_count",
    "reverse_hairpin_count",
    "forward_hairpin_max_score",
    "reverse_hairpin_max_score",
    "qc_status",
    "qc_reason",
]

_NA = "NA"

# ── helpers ────────────────────────────────────────────────────────────────


def parse_primer_name(name: str) -> tuple[str, str]:
    """Split a primer FASTA name into (primer_id, primer_side).

    Handles both single-underscore (``COI_short_F``) and
    double-underscore (``COI_short__F``) delimiters.

    Returns:
        (primer_id, primer_side) where side is ``"F"``, ``"R"``, or
        ``"UNKNOWN"``.
    """
    if not name or not name.strip():
        return "", "UNKNOWN"

    name = name.strip()

    if name.endswith("__F"):
        return name[:-3], "F"
    if name.endswith("__R"):
        return name[:-3], "R"
    if name.endswith("_F"):
        return name[:-2], "F"
    if name.endswith("_R"):
        return name[:-2], "R"

    return name, "UNKNOWN"


def _safe_float(value: str) -> float | str:
    """Convert *value* to float, returning ``"NA"`` on failure."""
    if not value or not value.strip():
        return _NA
    try:
        return float(value.strip())
    except (ValueError, TypeError):
        return _NA


def _safe_int(value: str) -> int | str:
    """Convert *value* to int, returning ``"NA"`` on failure."""
    if not value or not value.strip():
        return _NA
    try:
        return int(value.strip())
    except (ValueError, TypeError):
        return _NA


def _count_from_header(text: str, label: str) -> int:
    """Extract count from a header line like ``"Dimer List (3)"``.

    Returns 0 if the line says "No dimer found" / "No hairpins found".
    """
    m = re.search(rf"{re.escape(label)}\s*\(\s*(\d+)\s*\)", text)
    if m:
        return int(m.group(1))
    return 0


def _parse_primer_table_lines(lines: list[str]) -> list[dict]:
    """Parse MFEprimer fixed-width primer table into a list of dicts.

    Each dict contains: primer_name, sequence, length, gc, tm, dg.
    """
    primers: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 6:
            primers.append(
                {
                    "primer_name": parts[0],
                    "sequence": parts[1],
                    "length": _safe_int(parts[2]),
                    "gc": _safe_float(parts[3]),
                    "tm": _safe_float(parts[4]),
                    "dg": _safe_float(parts[5]),
                }
            )
    return primers


def _parse_dimer_hairpin_common(
    raw_text: str, list_label: str, no_result_line: str,
) -> tuple[list[dict], list[dict], int, str]:
    """Common parsing logic for dimer and hairpin raw outputs.

    Args:
        raw_text: Full raw output text.
        list_label: Section label, e.g. ``"Dimer List"``.
        no_result_line: Text indicating no results, e.g. ``"No dimer found"``.

    Returns:
        (primer_table, entries, count, parse_status)
    """
    text = raw_text.strip()
    primer_table: list[dict] = []
    entries: list[dict] = []
    parse_status = "OK"

    list_marker = f"{list_label} ("
    count = _count_from_header(text, list_label)

    lines = text.split("\n")

    # Locate primer table between header and list section
    table_start = -1
    table_end = -1
    header_found = False
    for i, line in enumerate(lines):
        if "Primer ID" in line and "Sequence" in line:
            header_found = True
            continue
        if header_found and table_start < 0:
            stripped = line.strip()
            if stripped.startswith("(") and "bp" in stripped:
                continue
            if stripped and not stripped.startswith("("):
                table_start = i
                continue
        if table_start >= 0 and table_end < 0:
            stripped = line.strip()
            if not stripped or list_marker in stripped:
                table_end = i
                break

    if table_start >= 0 and table_end >= 0:
        primer_table = _parse_primer_table_lines(lines[table_start:table_end])

    if count > 0:
        parse_status = "PARSE_WARN"

    return primer_table, entries, count, parse_status


# ── thermo parser ──────────────────────────────────────────────────────────


def parse_thermo_output(path: str | Path) -> list[dict]:
    """Parse MFEprimer thermo TSV output.

    The thermo output is tab-separated with a header starting with ``"# Name"``.

    Returns:
        List of dicts with keys from ``THERMO_FIELDNAMES``.
        Empty list if the file is missing.
    """
    path = Path(path)
    if not path.is_file():
        return []

    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            if line.startswith("#"):
                continue

            parts = line.split("\t")
            # Need at least 7 fields: Name, Seq, Size, GC, Tm, DeltaG, RevComp
            # Note (field 8) is optional
            if len(parts) < 7:
                continue

            primer_name = parts[0].strip()
            primer_id, primer_side = parse_primer_name(primer_name)

            rows.append(
                {
                    "primer_name": primer_name,
                    "primer_id": primer_id,
                    "primer_side": primer_side,
                    "sequence": parts[1].strip() if len(parts) > 1 else "",
                    "size": _safe_int(parts[2]) if len(parts) > 2 else _NA,
                    "gc": _safe_float(parts[3]) if len(parts) > 3 else _NA,
                    "tm": _safe_float(parts[4]) if len(parts) > 4 else _NA,
                    "delta_g": _safe_float(parts[5]) if len(parts) > 5 else _NA,
                    "reverse_complement": (
                        parts[6].strip() if len(parts) > 6 else ""
                    ),
                    "note": parts[7].strip() if len(parts) > 7 else "",
                }
            )

    return rows


# ── dimer parser ───────────────────────────────────────────────────────────


def parse_dimer_output(path: str | Path) -> list[dict]:
    """Parse MFEprimer dimer text output.

    Extracts primer table, dimer count, and per-dimer entries when available.
    When entries cannot be fully parsed, ``parse_status`` is ``"PARSE_WARN"``
    and the raw text block is preserved.

    Returns:
        List of dicts with keys from ``DIMER_FIELDNAMES``.
        Empty list if the file is missing.
    """
    path = Path(path)
    if not path.is_file():
        return []

    raw_text = path.read_text(encoding="utf-8")
    primer_table, _entries, count, parse_status = _parse_dimer_hairpin_common(
        raw_text, "Dimer List", "No dimer found",
    )

    rows: list[dict] = []

    # Collect unique primer_ids from primer table
    primer_ids: set[str] = set()
    for p in primer_table:
        pid, _ = parse_primer_name(p["primer_name"])
        primer_ids.add(pid)

    if count == 0:
        for pid in sorted(primer_ids):
            rows.append(
                {
                    "primer_id": pid,
                    "primer_a": _NA,
                    "primer_b": _NA,
                    "dimer_count": 0,
                    "max_score": _NA,
                    "min_delta_g": _NA,
                    "has_3prime_dimer": _NA,
                    "raw_block": "",
                    "parse_status": parse_status,
                }
            )
    else:
        block_match = re.search(
            r"Dimer List\s*\(\d+\)\s*\n(.*?)(?=\n\s*\nParameters|\Z)",
            raw_text,
            re.DOTALL,
        )
        raw_block = block_match.group(1).strip() if block_match else ""

        for pid in sorted(primer_ids):
            rows.append(
                {
                    "primer_id": pid,
                    "primer_a": _NA,
                    "primer_b": _NA,
                    "dimer_count": count,
                    "max_score": _NA,
                    "min_delta_g": _NA,
                    "has_3prime_dimer": _NA,
                    "raw_block": raw_block,
                    "parse_status": parse_status,
                }
            )

    return rows


# ── hairpin parser ─────────────────────────────────────────────────────────


def parse_hairpin_output(path: str | Path) -> list[dict]:
    """Parse MFEprimer hairpin text output.

    Extracts primer table, hairpin count, and per-hairpin entries when
    available.  When entries cannot be fully parsed, ``parse_status`` is
    ``"PARSE_WARN"`` and the raw text block is preserved.

    Returns:
        List of dicts with keys from ``HAIRPIN_FIELDNAMES``.
        Empty list if the file is missing.
    """
    path = Path(path)
    if not path.is_file():
        return []

    raw_text = path.read_text(encoding="utf-8")
    primer_table, _entries, count, parse_status = _parse_dimer_hairpin_common(
        raw_text, "Hairpin List", "No hairpins found",
    )

    rows: list[dict] = []

    if count == 0:
        for p in primer_table:
            pid, _ = parse_primer_name(p["primer_name"])
            rows.append(
                {
                    "primer_id": pid,
                    "primer_name": p["primer_name"],
                    "hairpin_count": 0,
                    "max_score": _NA,
                    "min_delta_g": _NA,
                    "raw_block": "",
                    "parse_status": parse_status,
                }
            )
    else:
        block_match = re.search(
            r"Hairpin List\s*\(\d+\)\s*\n(.*?)(?=\n\s*\nParameters|\Z)",
            raw_text,
            re.DOTALL,
        )
        raw_block = block_match.group(1).strip() if block_match else ""

        for p in primer_table:
            pid, _ = parse_primer_name(p["primer_name"])
            rows.append(
                {
                    "primer_id": pid,
                    "primer_name": p["primer_name"],
                    "hairpin_count": count,
                    "max_score": _NA,
                    "min_delta_g": _NA,
                    "raw_block": raw_block,
                    "parse_status": parse_status,
                }
            )

    return rows


# ── QC summary builder ─────────────────────────────────────────────────────


def _read_primer_pairs(qc_dir: Path) -> dict[str, dict]:
    """Read primer_pairs.tsv, return {primer_id: {forward, reverse}}."""
    pairs_path = qc_dir / "primer_pairs.tsv"
    if not pairs_path.is_file():
        return {}

    pairs: dict[str, dict] = {}
    with open(pairs_path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            pid = row.get("primer_id", "").strip()
            if pid:
                pairs[pid] = {
                    "forward": row.get("forward", "").strip(),
                    "reverse": row.get("reverse", "").strip(),
                }
    return pairs


def build_primer_qc_summary(qc_dir: str | Path) -> list[dict]:
    """Build per-primer QC summary from thermo, dimer, and hairpin results.

    Reads raw outputs from *qc_dir*, combines per-primer metrics, and
    applies QC rules (PASS / WARN_TM_DIFF / WARN_DIMER / WARN_HAIRPIN /
    PARSE_WARN / FAIL_PARSE).

    Returns:
        List of dicts with keys from ``SUMMARY_FIELDNAMES``.
    """
    qc_dir = Path(qc_dir)
    thermo_path = qc_dir / "thermo" / "thermo_raw.tsv"
    dimer_path = qc_dir / "dimer" / "dimer_raw.txt"
    hairpin_path = qc_dir / "hairpin" / "hairpin_raw.txt"

    thermo_rows = parse_thermo_output(thermo_path)
    dimer_rows = parse_dimer_output(dimer_path)
    hairpin_rows = parse_hairpin_output(hairpin_path)

    # Index thermo by (primer_id, primer_side)
    thermo_by_id_side: dict[tuple[str, str], dict] = {}
    for r in thermo_rows:
        key = (r["primer_id"], r["primer_side"])
        thermo_by_id_side[key] = r

    # Index dimer by primer_id
    dimer_by_id: dict[str, dict] = {}
    for r in dimer_rows:
        dimer_by_id[r["primer_id"]] = r

    # Index hairpin by primer_name
    hairpin_by_name: dict[str, dict] = {}
    for r in hairpin_rows:
        hairpin_by_name[r["primer_name"]] = r

    # Collect all primer_ids
    all_ids: set[str] = set()
    for r in thermo_rows:
        all_ids.add(r["primer_id"])
    for r in dimer_rows:
        all_ids.add(r["primer_id"])
    for r in hairpin_rows:
        all_ids.add(r["primer_id"])

    thermo_missing = not thermo_path.is_file()
    dimer_missing = not dimer_path.is_file()
    hairpin_missing = not hairpin_path.is_file()

    summary_rows: list[dict] = []

    for pid in sorted(all_ids):
        fwd = thermo_by_id_side.get((pid, "F"), {})
        rev = thermo_by_id_side.get((pid, "R"), {})
        dimer = dimer_by_id.get(pid, {})
        hp_fwd = hairpin_by_name.get(f"{pid}_F", {})
        hp_rev = hairpin_by_name.get(f"{pid}_R", {})

        forward_tm = fwd.get("tm", _NA) if fwd else _NA
        reverse_tm = rev.get("tm", _NA) if rev else _NA
        forward_gc = fwd.get("gc", _NA) if fwd else _NA
        reverse_gc = rev.get("gc", _NA) if rev else _NA
        forward_delta_g = fwd.get("delta_g", _NA) if fwd else _NA
        reverse_delta_g = rev.get("delta_g", _NA) if rev else _NA

        if isinstance(forward_tm, (int, float)) and isinstance(
            reverse_tm, (int, float)
        ):
            tm_difference: int | float | str = round(
                abs(forward_tm - reverse_tm), 2
            )
        else:
            tm_difference = _NA

        dimer_count = dimer.get("dimer_count", 0)
        dimer_max_score = dimer.get("max_score", _NA)
        dimer_min_delta_g = dimer.get("min_delta_g", _NA)
        has_3prime_dimer = dimer.get("has_3prime_dimer", _NA)

        forward_hairpin_count = hp_fwd.get("hairpin_count", 0)
        reverse_hairpin_count = hp_rev.get("hairpin_count", 0)
        forward_hairpin_max_score = hp_fwd.get("max_score", _NA)
        reverse_hairpin_max_score = hp_rev.get("max_score", _NA)

        # Determine qc_status and qc_reason
        statuses: list[str] = []
        reasons: list[str] = []

        parse_issues: list[str] = []
        if thermo_missing:
            parse_issues.append("thermo_missing")
        if dimer_missing:
            parse_issues.append("dimer_missing")
        if hairpin_missing:
            parse_issues.append("hairpin_missing")

        if parse_issues:
            statuses.append("FAIL_PARSE")
            reasons.append("关键文件缺失: " + ", ".join(parse_issues))

        dimer_status = dimer.get("parse_status", "")
        if dimer_status == "PARSE_WARN":
            if "PARSE_WARN" not in statuses:
                statuses.append("PARSE_WARN")
            reasons.append("dimer 输出无法完整解析")

        for hp_row in [hp_fwd, hp_rev]:
            if hp_row and hp_row.get("parse_status") == "PARSE_WARN":
                if "PARSE_WARN" not in statuses:
                    statuses.append("PARSE_WARN")
                reasons.append("hairpin 输出无法完整解析")
                break

        if isinstance(tm_difference, (int, float)) and tm_difference > 5:
            statuses.append("WARN_TM_DIFF")
            reasons.append(f"Tm 差异 {tm_difference}°C > 5°C")

        if isinstance(dimer_count, int) and dimer_count > 0:
            statuses.append("WARN_DIMER")
            reasons.append(f"dimer_count={dimer_count}")

        hp_warn = False
        hp_reason_parts: list[str] = []
        if isinstance(forward_hairpin_count, int) and forward_hairpin_count > 0:
            hp_warn = True
            hp_reason_parts.append(f"forward_hairpin={forward_hairpin_count}")
        if isinstance(reverse_hairpin_count, int) and reverse_hairpin_count > 0:
            hp_warn = True
            hp_reason_parts.append(f"reverse_hairpin={reverse_hairpin_count}")
        if hp_warn:
            statuses.append("WARN_HAIRPIN")
            reasons.append("hairpin: " + ", ".join(hp_reason_parts))

        if not statuses:
            qc_status = "PASS"
            qc_reason = ""
        else:
            qc_status = "; ".join(statuses)
            qc_reason = "; ".join(reasons)

        summary_rows.append(
            {
                "primer_id": pid,
                "forward_tm": forward_tm,
                "reverse_tm": reverse_tm,
                "tm_difference": tm_difference,
                "forward_gc": forward_gc,
                "reverse_gc": reverse_gc,
                "forward_delta_g": forward_delta_g,
                "reverse_delta_g": reverse_delta_g,
                "dimer_count": dimer_count,
                "dimer_max_score": dimer_max_score,
                "dimer_min_delta_g": dimer_min_delta_g,
                "has_3prime_dimer": has_3prime_dimer,
                "forward_hairpin_count": forward_hairpin_count,
                "reverse_hairpin_count": reverse_hairpin_count,
                "forward_hairpin_max_score": forward_hairpin_max_score,
                "reverse_hairpin_max_score": reverse_hairpin_max_score,
                "qc_status": qc_status,
                "qc_reason": qc_reason,
            }
        )

    return summary_rows


# ── output writers ─────────────────────────────────────────────────────────


def _write_tsv(
    path: Path, fieldnames: list[str], rows: list[dict],
) -> Path:
    """Write a list of dicts to a TSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return path


def write_qc_outputs(qc_dir: str | Path) -> dict[str, Path]:
    """Parse all raw QC outputs and write structured TSVs.

    Generates:
    - ``thermo/primer_thermo.tsv``
    - ``dimer/primer_dimer.tsv``
    - ``hairpin/primer_hairpin.tsv``
    - ``primer_qc_summary.tsv``

    Returns:
        Dict mapping logical name to written path.
    """
    qc_dir = Path(qc_dir)

    thermo_path = qc_dir / "thermo" / "thermo_raw.tsv"
    dimer_path = qc_dir / "dimer" / "dimer_raw.txt"
    hairpin_path = qc_dir / "hairpin" / "hairpin_raw.txt"

    written: dict[str, Path] = {}

    # Thermo
    thermo_rows = parse_thermo_output(thermo_path)
    written["primer_thermo"] = _write_tsv(
        qc_dir / "thermo" / "primer_thermo.tsv",
        THERMO_FIELDNAMES,
        thermo_rows,
    )

    # Dimer
    dimer_rows = parse_dimer_output(dimer_path)
    written["primer_dimer"] = _write_tsv(
        qc_dir / "dimer" / "primer_dimer.tsv",
        DIMER_FIELDNAMES,
        dimer_rows,
    )

    # Hairpin
    hairpin_rows = parse_hairpin_output(hairpin_path)
    written["primer_hairpin"] = _write_tsv(
        qc_dir / "hairpin" / "primer_hairpin.tsv",
        HAIRPIN_FIELDNAMES,
        hairpin_rows,
    )

    # Summary
    summary_rows = build_primer_qc_summary(qc_dir)
    written["primer_qc_summary"] = _write_tsv(
        qc_dir / "primer_qc_summary.tsv",
        SUMMARY_FIELDNAMES,
        summary_rows,
    )

    return written
