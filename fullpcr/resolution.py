"""Species resolution analysis for in silico PCR amplicons.

Determine whether amplified sequences can distinguish between species —
a critical metric for metabarcoding marker evaluation.
"""

from __future__ import annotations

from collections import defaultdict

# ── constants ──────────────────────────────────────────────────────────

RESOLUTION_FIELDNAMES = [
    "total_records",
    "matched_records",
    "unique_sequences",
    "unique_species",
    "resolved_sequence_count",
    "ambiguous_sequence_count",
    "ambiguous_species_count",
    "missing_species_count",
    "missing_sequence_count",
    "species_level_unique_resolution_rate",
]

AMBIGUOUS_GROUP_FIELDNAMES = [
    "sequence",
    "species_count",
    "species_list",
    "taxid_list",
    "record_count",
]


# ── species resolution ─────────────────────────────────────────────────


def calculate_species_resolution(records: list[dict]) -> dict:
    """Compute per-sequence species resolution.

    Returns a dict keyed by sequence with:
    * ``resolved`` — bool (True if only one species)
    * ``species_set`` — set of species names
    * ``taxid_set`` — set of taxids
    * ``record_count`` — number of records with this sequence
    """
    seq_groups: dict[str, dict] = defaultdict(
        lambda: {"species_set": set(), "taxid_set": set(), "record_count": 0}
    )

    for rec in records:
        seq = (rec.get("sequence") or "").strip().upper()
        if not seq:
            continue

        sp = _get_effective_species(rec)
        tid = (rec.get("taxid") or "").strip()

        grp = seq_groups[seq]
        grp["record_count"] += 1
        if sp:
            grp["species_set"].add(sp)
        if tid:
            grp["taxid_set"].add(tid)

    result: dict[str, dict] = {}
    for seq, grp in seq_groups.items():
        result[seq] = {
            "resolved": len(grp["species_set"]) <= 1,
            "species_set": grp["species_set"],
            "taxid_set": grp["taxid_set"],
            "record_count": grp["record_count"],
        }

    return result


# ── ambiguous groups ───────────────────────────────────────────────────


def find_ambiguous_species_groups(records: list[dict]) -> list[dict]:
    """Find sequences that map to multiple species.

    Returns a list of dicts with keys from ``AMBIGUOUS_GROUP_FIELDNAMES``,
    sorted by ``species_count`` descending (most ambiguous first).
    """
    resolution = calculate_species_resolution(records)

    ambiguous: list[dict] = []
    for seq, info in resolution.items():
        if not info["resolved"] and len(info["species_set"]) > 1:
            ambiguous.append({
                "sequence": seq,
                "species_count": len(info["species_set"]),
                "species_list": ";".join(sorted(info["species_set"])),
                "taxid_list": ";".join(sorted(info["taxid_set"])),
                "record_count": info["record_count"],
            })

    ambiguous.sort(key=lambda x: (-x["species_count"], x["sequence"]))
    return ambiguous


# ── summarise ──────────────────────────────────────────────────────────


def summarize_resolution(records: list[dict]) -> dict:
    """Produce a summary dict of species resolution statistics.

    Keys match ``RESOLUTION_FIELDNAMES``.
    """
    matched = [r for r in records if r.get("taxonomy_status") == "matched"]
    total = len(records)

    # Count missing species / sequence (only among matched records)
    missing_species = 0
    missing_sequence = 0
    valid_matched: list[dict] = []

    for rec in matched:
        sp = _get_effective_species(rec)
        seq = (rec.get("sequence") or "").strip()
        if not seq:
            missing_sequence += 1
            continue
        if not sp:
            missing_species += 1
            continue
        valid_matched.append(rec)

    if not valid_matched:
        return {
            "total_records": total,
            "matched_records": len(matched),
            "unique_sequences": 0,
            "unique_species": 0,
            "resolved_sequence_count": 0,
            "ambiguous_sequence_count": 0,
            "ambiguous_species_count": 0,
            "missing_species_count": missing_species,
            "missing_sequence_count": missing_sequence,
            "species_level_unique_resolution_rate": 0.0,
        }

    # Group by sequence
    seq_to_species: dict[str, set[str]] = defaultdict(set)
    species_seqs: dict[str, set[str]] = defaultdict(set)
    species_set: set[str] = set()

    for rec in valid_matched:
        seq = (rec.get("sequence") or "").strip().upper()
        sp = _get_effective_species(rec)

        seq_to_species[seq].add(sp)
        species_seqs[sp].add(seq)
        species_set.add(sp)

    unique_sequences = len(seq_to_species)
    unique_species = len(species_set)

    # Count resolved vs ambiguous sequences
    resolved_seq_count = 0
    ambiguous_seq_count = 0
    for seq, spp in seq_to_species.items():
        if len(spp) <= 1:
            resolved_seq_count += 1
        else:
            ambiguous_seq_count += 1

    # Species-level resolution: a species is resolved if NONE of its
    # sequences are shared with any other species.
    resolved_species_count = 0
    ambiguous_species_count = 0
    for sp in sorted(species_set):
        seqs = species_seqs[sp]
        is_resolved = True
        for s in seqs:
            if len(seq_to_species[s]) > 1:
                is_resolved = False
                break
        if is_resolved:
            resolved_species_count += 1
        else:
            ambiguous_species_count += 1

    rate = resolved_species_count / unique_species if unique_species > 0 else 0.0

    return {
        "total_records": total,
        "matched_records": len(matched),
        "unique_sequences": unique_sequences,
        "unique_species": unique_species,
        "resolved_sequence_count": resolved_seq_count,
        "ambiguous_sequence_count": ambiguous_seq_count,
        "ambiguous_species_count": ambiguous_species_count,
        "missing_species_count": missing_species,
        "missing_sequence_count": missing_sequence,
        "species_level_unique_resolution_rate": round(rate, 6),
    }


# ── helpers ────────────────────────────────────────────────────────────


def _get_effective_species(rec: dict) -> str:
    """Return the effective species name for a record.

    Uses ``species`` field first, falls back to ``scientific_name``.
    """
    sp = (rec.get("species") or "").strip()
    if sp:
        return sp
    return (rec.get("scientific_name") or "").strip()
