"""Degenerate primer expansion for MFEprimer QC.

Phase 3: detect IUPAC degenerate bases, count theoretical variants,
expand within a configurable threshold, and generate summary outputs.
"""

from __future__ import annotations

import csv
from itertools import product
from pathlib import Path

# ── IUPAC degenerate base tables ───────────────────────────────────────────

IUPAC_CODES: dict[str, list[str]] = {
    "A": ["A"],
    "T": ["T"],
    "C": ["C"],
    "G": ["G"],
    "R": ["A", "G"],
    "Y": ["C", "T"],
    "M": ["A", "C"],
    "K": ["G", "T"],
    "S": ["G", "C"],
    "W": ["A", "T"],
    "H": ["A", "C", "T"],
    "B": ["C", "G", "T"],
    "V": ["A", "C", "G"],
    "D": ["A", "G", "T"],
    "N": ["A", "C", "G", "T"],
}

VALID_BASES: set[str] = set(IUPAC_CODES.keys())

DEGENERATE_BASES: set[str] = {
    b for b, opts in IUPAC_CODES.items() if len(opts) > 1
}

# ── field names ────────────────────────────────────────────────────────────

DEGEN_SUMMARY_FIELDNAMES = [
    "primer_id",
    "primer_side",
    "original_sequence",
    "has_degenerate_bases",
    "variant_count",
    "expanded_count",
    "status",
    "reason",
]

# ── detection / counting ───────────────────────────────────────────────────


def has_degenerate_bases(sequence: str) -> bool:
    """Return True if *sequence* contains any IUPAC degenerate bases.

    >>> has_degenerate_bases("ACGT")
    False
    >>> has_degenerate_bases("ACRYGT")
    True
    """
    if not sequence:
        return False
    return any(base in DEGENERATE_BASES for base in sequence.upper())


def _validate_sequence(sequence: str) -> list[str]:
    """Validate every base and return a list of invalid characters found."""
    invalid: list[str] = []
    for ch in sequence.upper():
        if ch not in VALID_BASES:
            invalid.append(ch)
    return invalid


def count_degenerate_variants(sequence: str) -> int:
    """Return the theoretical number of expanded variants for *sequence*.

    >>> count_degenerate_variants("ACGT")
    1
    >>> count_degenerate_variants("R")
    2
    >>> count_degenerate_variants("RY")
    4
    >>> count_degenerate_variants("NNNN")
    256
    """
    if not sequence:
        return 0
    total = 1
    for base in sequence.upper():
        opts = IUPAC_CODES.get(base, [base])
        total *= len(opts)
    return total


# ── expansion ──────────────────────────────────────────────────────────────


def expand_degenerate_sequence(
    sequence: str, max_variants: int,
) -> tuple[list[str], str, str]:
    """Expand a degenerate sequence into all unambiguous variants.

    Args:
        sequence: DNA sequence possibly containing IUPAC degenerate codes.
        max_variants: Maximum allowed number of expanded variants.

    Returns:
        (variants, status, reason) where *status* is one of
        ``"NO_DEGENERACY"``, ``"EXPANDED"``, ``"FAIL_DEGENERATE_EXPLOSION"``,
        or ``"INVALID_BASE"``.

    >>> expand_degenerate_sequence("ACGT", 256)
    (['ACGT'], 'NO_DEGENERACY', '')
    >>> expand_degenerate_sequence("R", 256)
    (['A', 'G'], 'EXPANDED', 'R->A/G')
    >>> expand_degenerate_sequence("NNNNN", 256)
    ([], 'FAIL_DEGENERATE_EXPLOSION', 'variant_count=1024 > max=256')
    >>> expand_degenerate_sequence("ACXGT", 256)
    ([], 'INVALID_BASE', "非法字符: ['X']")
    """
    if not sequence:
        return [], "NO_DEGENERACY", ""

    seq = sequence.upper()

    # Validate bases
    invalid = _validate_sequence(seq)
    if invalid:
        return [], "INVALID_BASE", f"非法字符: {invalid!r}"

    # Count variants
    variant_count = count_degenerate_variants(seq)

    # No degenerate bases
    if variant_count == 1:
        return [seq], "NO_DEGENERACY", ""

    # Check threshold
    if variant_count > max_variants:
        return (
            [],
            "FAIL_DEGENERATE_EXPLOSION",
            f"variant_count={variant_count} > max={max_variants}",
        )

    # Expand
    bases_per_pos = [IUPAC_CODES[b] for b in seq]
    variants = ["".join(combo) for combo in product(*bases_per_pos)]

    # Build reason showing which positions expanded
    expanded_positions: list[str] = []
    for i, base in enumerate(seq, 1):
        if base in DEGENERATE_BASES:
            opts = "/".join(IUPAC_CODES[base])
            expanded_positions.append(f"pos{i}:{base}->{opts}")
    reason = "; ".join(expanded_positions) if expanded_positions else ""

    return variants, "EXPANDED", reason


# ── summary ────────────────────────────────────────────────────────────────


def summarize_degenerate_primers(
    primers, max_variants: int,
) -> list[dict]:
    """Summarize degenerate expansion for all primers.

    Args:
        primers: List of ``Primer`` named tuples from ``read_primers()``.
        max_variants: Threshold for degenerate explosion.

    Returns:
        List of dicts with keys from ``DEGEN_SUMMARY_FIELDNAMES``.
    """
    rows: list[dict] = []

    for primer in primers:
        for side, seq in [("F", primer.forward), ("R", primer.reverse)]:
            variant_count = count_degenerate_variants(seq)
            has_deg = has_degenerate_bases(seq)
            variants, status, reason = expand_degenerate_sequence(
                seq, max_variants,
            )

            rows.append(
                {
                    "primer_id": primer.primer_id,
                    "primer_side": side,
                    "original_sequence": seq,
                    "has_degenerate_bases": has_deg,
                    "variant_count": variant_count,
                    "expanded_count": len(variants),
                    "status": status,
                    "reason": reason,
                }
            )

    return rows


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


def write_degen_outputs(
    primers, outdir: str | Path, max_variants: int,
) -> dict[str, Path]:
    """Expand degenerate primers and write outputs.

    Generates:
    - ``degen/expanded_primers.fasta``
    - ``degen/degen_summary.tsv``

    For primers with ``NO_DEGENERACY`` status the original sequence is
    emitted as a single variant so downstream tools always consume the
    same FASTA format.

    Returns:
        Dict mapping logical name to written path.
    """
    outdir = Path(outdir)
    degen_dir = outdir / "degen"
    degen_dir.mkdir(parents=True, exist_ok=True)

    # Build summary
    summary_rows = summarize_degenerate_primers(primers, max_variants)

    # Build expanded FASTA
    fasta_lines: list[str] = []
    for primer in primers:
        for side, seq in [("F", primer.forward), ("R", primer.reverse)]:
            variants, status, _reason = expand_degenerate_sequence(
                seq, max_variants,
            )

            if status in ("NO_DEGENERACY", "EXPANDED"):
                for idx, variant in enumerate(variants, 1):
                    fasta_lines.append(
                        f">{primer.primer_id}__{side}__variant_{idx}"
                    )
                    fasta_lines.append(variant)
            # FAIL_DEGENERATE_EXPLOSION / INVALID_BASE: skip

    fasta_path = degen_dir / "expanded_primers.fasta"
    fasta_path.write_text("\n".join(fasta_lines) + "\n", encoding="utf-8")

    # Write summary TSV
    summary_path = _write_tsv(
        degen_dir / "degen_summary.tsv",
        DEGEN_SUMMARY_FIELDNAMES,
        summary_rows,
    )

    return {
        "expanded_primers": fasta_path,
        "degen_summary": summary_path,
    }
