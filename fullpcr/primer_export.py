"""Export primers to formats compatible with MFEprimer.

Phase 1: FASTA and TSV export for MFEprimer input.
"""

from __future__ import annotations

from pathlib import Path

from fullpcr.primers import Primer


def export_primers_to_fasta(
    primers: list[Primer],
    output_path: str | Path,
) -> Path:
    """Export primer sequences to FASTA format for MFEprimer input.

    Each primer pair generates two FASTA records:

    - ``>primer_id_F`` → forward sequence
    - ``>primer_id_R`` → reverse sequence

    Args:
        primers: List of Primer records to export.
        output_path: Path where the FASTA file should be written.

    Returns:
        The resolved output Path.

    Raises:
        ValueError: If *primers* is empty.
    """
    if not primers:
        raise ValueError("primers 列表不能为空。")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for p in primers:
        lines.append(f">{p.primer_id}_F")
        lines.append(p.forward)
        lines.append(f">{p.primer_id}_R")
        lines.append(p.reverse)

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def export_primer_pairs_to_tsv(
    primers: list[Primer],
    output_path: str | Path,
) -> Path:
    """Export primer pairs as a 3-column TSV for MFEprimer pair input.

    Columns: ``primer_id``, ``forward``, ``reverse``.

    Args:
        primers: List of Primer records to export.
        output_path: Path where the TSV file should be written.

    Returns:
        The resolved output Path.

    Raises:
        ValueError: If *primers* is empty.
    """
    if not primers:
        raise ValueError("primers 列表不能为空。")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = ["primer_id\tforward\treverse"]
    for p in primers:
        lines.append(f"{p.primer_id}\t{p.forward}\t{p.reverse}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
