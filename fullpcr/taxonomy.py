"""Merge taxonomy information with amplicon records."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# ── constants ──────────────────────────────────────────────────────────

TAXONOMY_REQUIRED_COLUMNS = ["taxid"]

TAXONOMY_OPTIONAL_COLUMNS = [
    "scientific_name",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
]

TAXONOMIC_RANKS = [
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
]

MERGED_FIELDNAMES = [
    "record_id",
    "accession",
    "taxid",
    "scientific_name",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
    "taxonomy_status",
    "sequence",
    "amplicon_length",
    "forward_error",
    "reverse_error",
]


# ── read ───────────────────────────────────────────────────────────────


def read_taxonomy(path: str | Path) -> list[dict]:
    """Read a taxonomy TSV file.

    Required columns: ``taxid``.

    Optional columns (filled with ``""`` if missing):
    ``scientific_name``, ``kingdom``, ``phylum``, ``class``, ``order``,
    ``family``, ``genus``, ``species``.

    taxid is always converted to string.

    Raises:
        FileNotFoundError: if *path* does not exist.
        ValueError: if required columns are missing.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"taxonomy 文件不存在: {path}")

    df = pd.read_csv(str(path), sep="\t", dtype=str)

    # Validate required columns
    missing = [c for c in TAXONOMY_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"taxonomy.tsv 缺少必需列: {', '.join(missing)}"
            f"。必需列: {', '.join(TAXONOMY_REQUIRED_COLUMNS)}"
        )

    # Fill missing optional columns with ""
    for col in TAXONOMY_OPTIONAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    # Keep only expected columns
    keep_cols = TAXONOMY_REQUIRED_COLUMNS + TAXONOMY_OPTIONAL_COLUMNS
    df = df[keep_cols]

    # Convert to list[dict]
    return df.to_dict(orient="records")


# ── merge ──────────────────────────────────────────────────────────────


def merge_taxonomy(
    amplicons: list[dict], taxonomy: list[dict]
) -> list[dict]:
    """Merge amplicon records with taxonomy information.

    Merge strategy (in order):
    1. Match by ``taxid`` (primary key).
    2. If taxid is empty or not matched, fall back to ``scientific_name``
       (or ``species`` field from taxonomy).
    3. Taxonomy values override amplicon header values.
    4. Records that cannot be matched are **not** dropped — they get
       ``taxonomy_status = "missing"``.

    Returns a *new* list of dicts (immutable pattern).
    """
    # Build lookup dicts from taxonomy
    by_taxid: dict[str, dict] = {
        t["taxid"]: t
        for t in taxonomy
        if t.get("taxid")
    }
    by_scientific_name: dict[str, dict] = {
        t.get("scientific_name", ""): t
        for t in taxonomy
        if t.get("scientific_name")
    }
    by_species: dict[str, dict] = {
        t.get("species", ""): t
        for t in taxonomy
        if t.get("species")
    }

    merged: list[dict] = []

    for rec in amplicons:
        tax_entry: dict | None = None
        match_method = ""

        # 1. Match by taxid
        tid = rec.get("taxid", "")
        if tid and tid in by_taxid:
            tax_entry = by_taxid[tid]
            match_method = "taxid"

        # 2. Fallback: scientific_name then species
        if tax_entry is None:
            sci = rec.get("scientific_name", "")
            if sci and sci in by_scientific_name:
                tax_entry = by_scientific_name[sci]
                match_method = "scientific_name"
            elif sci and sci in by_species:
                tax_entry = by_species[sci]
                match_method = "species"

        # Build merged record
        if tax_entry is not None:
            merged.append({
                "record_id": rec.get("record_id", ""),
                "accession": rec.get("accession", ""),
                "taxid": tax_entry.get("taxid", tid),
                "scientific_name": tax_entry.get("scientific_name", "")
                                    or tax_entry.get("species", "")
                                    or rec.get("scientific_name", ""),
                "kingdom": tax_entry.get("kingdom", ""),
                "phylum": tax_entry.get("phylum", ""),
                "class": tax_entry.get("class", ""),
                "order": tax_entry.get("order", ""),
                "family": tax_entry.get("family", ""),
                "genus": tax_entry.get("genus", ""),
                "species": tax_entry.get("species", ""),
                "taxonomy_status": "matched",
                "sequence": rec.get("sequence", ""),
                "amplicon_length": rec.get("amplicon_length", 0),
                "forward_error": rec.get("forward_error", ""),
                "reverse_error": rec.get("reverse_error", ""),
            })
        else:
            # Unmatched record — keep with original fields
            merged.append({
                "record_id": rec.get("record_id", ""),
                "accession": rec.get("accession", ""),
                "taxid": tid,
                "scientific_name": rec.get("scientific_name", ""),
                "kingdom": "",
                "phylum": "",
                "class": "",
                "order": "",
                "family": "",
                "genus": "",
                "species": "",
                "taxonomy_status": "missing",
                "sequence": rec.get("sequence", ""),
                "amplicon_length": rec.get("amplicon_length", 0),
                "forward_error": rec.get("forward_error", ""),
                "reverse_error": rec.get("reverse_error", ""),
            })

    return merged


# ── summarise ──────────────────────────────────────────────────────────


def summarize_taxonomic_coverage(merged: list[dict]) -> list[dict]:
    """Compute per-rank taxonomic coverage statistics.

    For each rank (kingdom → species), returns a row with:
    * rank
    * name
    * amplicon_count
    * unique_taxid_count
    * unique_species_count

    Unclassified entries (empty string at that rank) are grouped as
    ``"(unclassified)"``.
    """
    if not merged:
        return []

    result: list[dict] = []

    for rank in TAXONOMIC_RANKS:
        # Group by rank value
        groups: dict[str, dict[str, set]] = {}
        for rec in merged:
            # Include both matched and missing records for coverage stats
            name = rec.get(rank, "").strip() or "(unclassified)"
            if name not in groups:
                groups[name] = {"taxids": set(), "species": set(), "count": 0}
            groups[name]["count"] += 1
            tid = rec.get("taxid", "").strip()
            if tid:
                groups[name]["taxids"].add(tid)
            sp = rec.get("species", "").strip()
            if sp:
                groups[name]["species"].add(sp)

        for name, stats in sorted(groups.items()):
            result.append({
                "rank": rank,
                "name": name,
                "amplicon_count": stats["count"],
                "unique_taxid_count": len(stats["taxids"]),
                "unique_species_count": len(stats["species"]),
            })

    return result
