"""Parse FASTA / FASTA.GZ files (including obipcr JSON metadata headers)."""

from __future__ import annotations

import csv
import gzip
import json
import re
from pathlib import Path

# ── constants ──────────────────────────────────────────────────────────

VALID_SUFFIXES = {".fasta", ".fa", ".fasta.gz", ".fa.gz"}

TSV_FIELDNAMES = [
    "record_id",
    "accession",
    "definition",
    "taxid",
    "scientific_name",
    "direction",
    "forward_error",
    "reverse_error",
    "forward_match",
    "reverse_match",
    "amplicon_length",
    "sequence",
]


# ── header parsing ─────────────────────────────────────────────────────


def parse_fasta_header(header: str) -> dict:
    """Parse a single FASTA header line (without the leading ``>``).

    Handles three header styles:

    * **OBITools JSON** — extracts ``taxid``, ``scientific_name``,
      ``forward_error``, ``reverse_error``, ``direction``,
      ``forward_match``, ``reverse_match`` from the embedded JSON.
      ``definition`` is taken from JSON if present, otherwise from the
      header text after the accession.
    * **NCBI-style** — ``>NC_001234 Homo sapiens mitochondrion``
      ``accession`` = ``NC_001234``, ``definition`` = the rest,
      ``scientific_name`` = ``""`` (conservative).
    * **Accession-only** — ``>NC_001234`` — all fields default to ``""``.

    Returns a dict with keys matching ``TSV_FIELDNAMES`` (minus
    ``record_id``, ``amplicon_length``, ``sequence`` which are filled
    later).
    """
    result: dict = {
        "accession": "",
        "definition": "",
        "taxid": "",
        "scientific_name": "",
        "direction": "",
        "forward_error": "",
        "reverse_error": "",
        "forward_match": "",
        "reverse_match": "",
    }

    # ── try JSON metadata ──────────────────────────────────────────
    json_match = re.search(r"\{.*\}", header)
    json_has_definition = False
    if json_match:
        try:
            metadata = json.loads(json_match.group())
            result["taxid"] = str(metadata.get("taxid", ""))
            result["scientific_name"] = str(
                metadata.get("scientific_name", "")
            )
            result["direction"] = str(metadata.get("direction", ""))
            result["forward_error"] = _to_str(
                metadata.get("forward_error")
            )
            result["reverse_error"] = _to_str(
                metadata.get("reverse_error")
            )
            result["forward_match"] = str(
                metadata.get("forward_match", "")
            )
            result["reverse_match"] = str(
                metadata.get("reverse_match", "")
            )
            if "definition" in metadata:
                result["definition"] = str(metadata["definition"])
                json_has_definition = True
        except (json.JSONDecodeError, TypeError):
            # Corrupt JSON → keep defaults, don't crash
            pass

    # ── extract accession and header-based definition ──────────────
    # Take everything before JSON (if present) or the whole header.
    prefix = header.split("{")[0].strip() if "{" in header else header

    # Split into first token (raw accession) and the rest.
    parts = prefix.split(None, 1) if prefix else [""]
    first_token = parts[0] if parts else ""

    # Clean _sub suffix from first token to get the real accession.
    acc = re.sub(r"_sub.*$", "", first_token)
    result["accession"] = acc

    # Fill definition from header text if JSON didn't provide one.
    if not json_has_definition:
        # Everything after the curated accession inside the first token
        # (e.g. "_sub[5342..5907]") plus any remaining description text.
        after_acc = first_token[len(acc) :]
        rest = (" " + parts[1]) if len(parts) > 1 else ""
        result["definition"] = (after_acc + rest).strip()

    return result


def _to_str(value) -> str:
    """Convert a value to string, returning '' for None."""
    if value is None:
        return ""
    return str(value)


# ── FASTA I/O ──────────────────────────────────────────────────────────


def parse_obipcr_fasta(path: str | Path) -> list[dict]:
    """Read a FASTA (or .fasta.gz) file and return a list of amplicon records.

    Each record is a dict with all keys from ``TSV_FIELDNAMES``.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the file suffix is not a recognised FASTA extension.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"FASTA 文件不存在: {path}")

    suffix = _detect_suffix(path)
    if suffix not in VALID_SUFFIXES:
        raise ValueError(
            f"不支持的文件格式: {path.suffix!r}。"
            f" 支持: {', '.join(sorted(VALID_SUFFIXES))}"
        )

    open_fn = gzip.open if suffix.endswith(".gz") else open
    records: list[dict] = []

    current_header: str | None = None
    seq_parts: list[str] = []

    with open_fn(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(">"):
                # flush previous record
                if current_header is not None:
                    records.append(
                        _build_record(
                            current_header,
                            "".join(seq_parts),
                            len(records),
                        )
                    )
                current_header = stripped[1:]  # drop '>'
                seq_parts = []
            else:
                if current_header is not None:
                    seq_parts.append(stripped)

    # flush last record
    if current_header is not None:
        records.append(
            _build_record(current_header, "".join(seq_parts), len(records))
        )

    return records


def write_amplicons_tsv(
    records: list[dict], output_path: str | Path
) -> None:
    """Write amplicon records to a TSV file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=TSV_FIELDNAMES, delimiter="\t"
        )
        writer.writeheader()
        for rec in records:
            row = {k: rec.get(k, "") for k in TSV_FIELDNAMES}
            writer.writerow(row)


# ── helpers ────────────────────────────────────────────────────────────


def _build_record(header: str, sequence: str, index: int) -> dict:
    """Assemble a full amplicon record from a header and sequence."""
    parsed = parse_fasta_header(header)
    return {
        **parsed,
        "record_id": f"amplicon_{index + 1:04d}",
        "amplicon_length": len(sequence),
        "sequence": sequence,
    }


def _detect_suffix(path: Path) -> str:
    """Return the canonical FASTA suffix accounting for ``.gz``."""
    name = path.name.lower()
    if name.endswith(".fasta.gz"):
        return ".fasta.gz"
    if name.endswith(".fa.gz"):
        return ".fa.gz"
    if name.endswith(".fasta"):
        return ".fasta"
    if name.endswith(".fa"):
        return ".fa"
    return path.suffix.lower()
