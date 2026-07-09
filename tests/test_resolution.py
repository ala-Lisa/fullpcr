"""Tests for resolution module."""

import pytest

from fullpcr.resolution import (
    AMBIGUOUS_GROUP_FIELDNAMES,
    RESOLUTION_FIELDNAMES,
    calculate_species_resolution,
    find_ambiguous_species_groups,
    summarize_resolution,
)


# ── helpers ────────────────────────────────────────────────────────────


def _matched_record(
    record_id="amp_001",
    taxid="9606",
    species="Homo sapiens",
    scientific_name="Homo sapiens",
    sequence="ATCG",
    **overrides,
) -> dict:
    """Build a minimal matched record."""
    rec = {
        "record_id": record_id,
        "accession": "NC_001",
        "taxid": taxid,
        "species": species,
        "scientific_name": scientific_name,
        "kingdom": "Animalia",
        "phylum": "",
        "class": "",
        "order": "",
        "family": "",
        "genus": "",
        "taxonomy_status": "matched",
        "sequence": sequence,
        "amplicon_length": len(sequence),
        "forward_error": "",
        "reverse_error": "",
    }
    rec.update(overrides)
    return rec


def _missing_record(
    record_id="amp_999", sequence="XXXX", **overrides,
) -> dict:
    """Build a minimal missing (unmatched) record."""
    rec = {
        "record_id": record_id,
        "accession": "NC_999",
        "taxid": "",
        "species": "",
        "scientific_name": "",
        "kingdom": "",
        "phylum": "",
        "class": "",
        "order": "",
        "family": "",
        "genus": "",
        "taxonomy_status": "missing",
        "sequence": sequence,
        "amplicon_length": len(sequence) if sequence else 0,
        "forward_error": "",
        "reverse_error": "",
    }
    rec.update(overrides)
    return rec


# ── calculate_species_resolution ───────────────────────────────────────


class TestCalculateSpeciesResolution:
    def test_single_species_resolved(self):
        """One sequence → one species → resolved."""
        records = [
            _matched_record(sequence="ATCG", species="Homo sapiens"),
            _matched_record(sequence="ATCG", species="Homo sapiens"),
        ]
        result = calculate_species_resolution(records)

        assert "ATCG" in result
        assert result["ATCG"]["resolved"] is True
        assert result["ATCG"]["species_set"] == {"Homo sapiens"}
        assert result["ATCG"]["taxid_set"] == {"9606"}
        assert result["ATCG"]["record_count"] == 2

    def test_multiple_species_ambiguous(self):
        """Same sequence → multiple species → ambiguous."""
        records = [
            _matched_record(
                record_id="amp_001", sequence="ATCG",
                species="Homo sapiens", taxid="9606",
            ),
            _matched_record(
                record_id="amp_002", sequence="ATCG",
                species="Bos taurus", taxid="9913",
            ),
            _matched_record(
                record_id="amp_003", sequence="ATCG",
                species="Mus musculus", taxid="10090",
            ),
        ]
        result = calculate_species_resolution(records)

        assert result["ATCG"]["resolved"] is False
        assert result["ATCG"]["species_set"] == {
            "Homo sapiens", "Bos taurus", "Mus musculus",
        }
        assert result["ATCG"]["taxid_set"] == {"9606", "9913", "10090"}
        assert result["ATCG"]["record_count"] == 3

    def test_different_sequences_independent(self):
        """Different sequences each get their own resolution entry."""
        records = [
            _matched_record(sequence="AAAA", species="Homo sapiens"),
            _matched_record(sequence="CCCC", species="Bos taurus"),
        ]
        result = calculate_species_resolution(records)

        assert len(result) == 2
        assert result["AAAA"]["resolved"] is True
        assert result["CCCC"]["resolved"] is True

    def test_empty_sequence_skipped(self):
        """Records with empty sequence are excluded from result."""
        records = [_matched_record(sequence="")]
        result = calculate_species_resolution(records)
        assert result == {}

    def test_empty_species_falls_back_to_scientific_name(self):
        """When species is empty, _get_effective_species uses scientific_name."""
        records = [
            _matched_record(
                sequence="ATCG", species="", scientific_name="Bos taurus",
            ),
            _matched_record(sequence="ATCG", species="Homo sapiens"),
        ]
        result = calculate_species_resolution(records)
        # Bos taurus (from fallback) vs Homo sapiens → ambiguous
        assert result["ATCG"]["resolved"] is False
        assert len(result["ATCG"]["species_set"]) == 2

    def test_case_insensitive_sequence(self):
        """Sequence comparison should be case-insensitive."""
        records = [
            _matched_record(sequence="atcg", species="Homo sapiens"),
            _matched_record(sequence="ATCG", species="Bos taurus"),
        ]
        result = calculate_species_resolution(records)

        assert len(result) == 1
        assert result["ATCG"]["resolved"] is False


# ── find_ambiguous_species_groups ──────────────────────────────────────


class TestFindAmbiguousSpeciesGroups:
    def test_no_ambiguity_returns_empty(self):
        records = [
            _matched_record(sequence="AAAA", species="Homo sapiens"),
            _matched_record(sequence="CCCC", species="Bos taurus"),
        ]
        groups = find_ambiguous_species_groups(records)
        assert groups == []

    def test_finds_ambiguous_groups(self):
        records = [
            _matched_record(sequence="ATCG", species="Homo sapiens"),
            _matched_record(sequence="ATCG", species="Bos taurus"),
            _matched_record(sequence="ATCG", species="Mus musculus"),
        ]
        groups = find_ambiguous_species_groups(records)

        assert len(groups) == 1
        assert groups[0]["sequence"] == "ATCG"
        assert groups[0]["species_count"] == 3
        assert "Homo sapiens" in groups[0]["species_list"]
        assert "Bos taurus" in groups[0]["species_list"]
        assert "Mus musculus" in groups[0]["species_list"]
        assert groups[0]["record_count"] == 3

    def test_sorted_by_species_count_descending(self):
        records = [
            _matched_record(sequence="AAAA", species="A", taxid="1"),
            _matched_record(sequence="AAAA", species="B", taxid="2"),
            _matched_record(sequence="CCCC", species="C", taxid="3"),
            _matched_record(sequence="CCCC", species="D", taxid="4"),
            _matched_record(sequence="CCCC", species="E", taxid="5"),
        ]
        groups = find_ambiguous_species_groups(records)

        assert len(groups) == 2
        # CCCC has 3 species, AAAA has 2 → CCCC first
        assert groups[0]["species_count"] == 3
        assert groups[1]["species_count"] == 2

    def test_output_keys_match_schema(self):
        records = [
            _matched_record(sequence="ATCG", species="A", taxid="1"),
            _matched_record(sequence="ATCG", species="B", taxid="2"),
        ]
        groups = find_ambiguous_species_groups(records)

        for g in groups:
            for key in AMBIGUOUS_GROUP_FIELDNAMES:
                assert key in g

    def test_species_list_sorted(self):
        records = [
            _matched_record(sequence="ATCG", species="Zebra"),
            _matched_record(sequence="ATCG", species="Alpha"),
        ]
        groups = find_ambiguous_species_groups(records)

        assert groups[0]["species_list"] == "Alpha;Zebra"


# ── summarize_resolution ───────────────────────────────────────────────


class TestSummarizeResolution:
    def test_all_resolved(self):
        records = [
            _matched_record(
                record_id="amp_001", sequence="AAAA",
                species="Homo sapiens", taxid="9606",
            ),
            _matched_record(
                record_id="amp_002", sequence="CCCC",
                species="Bos taurus", taxid="9913",
            ),
        ]
        s = summarize_resolution(records)

        assert s["total_records"] == 2
        assert s["matched_records"] == 2
        assert s["unique_sequences"] == 2
        assert s["unique_species"] == 2
        assert s["resolved_sequence_count"] == 2
        assert s["ambiguous_sequence_count"] == 0
        assert s["ambiguous_species_count"] == 0
        assert s["missing_species_count"] == 0
        assert s["missing_sequence_count"] == 0
        assert s["species_level_unique_resolution_rate"] == 1.0

    def test_mixed_resolved_and_ambiguous(self):
        records = [
            # Shared sequence → 2 species ambiguous
            _matched_record(
                record_id="amp_001", sequence="SHARED",
                species="Homo sapiens", taxid="9606",
            ),
            _matched_record(
                record_id="amp_002", sequence="SHARED",
                species="Bos taurus", taxid="9913",
            ),
            # Unique sequence → resolved
            _matched_record(
                record_id="amp_003", sequence="UNIQUE",
                species="Homo sapiens", taxid="9606",
            ),
        ]
        s = summarize_resolution(records)

        assert s["total_records"] == 3
        assert s["unique_sequences"] == 2
        assert s["unique_species"] == 2
        assert s["resolved_sequence_count"] == 1  # UNIQUE
        assert s["ambiguous_sequence_count"] == 1  # SHARED

        # Both Homo sapiens (SHARED shared with Bos) and Bos taurus (SHARED shared
        # with Homo) are ambiguous — no species is fully resolved.
        assert s["ambiguous_species_count"] == 2
        assert s["species_level_unique_resolution_rate"] == 0.0

    def test_missing_records_ignored_for_resolution(self):
        """Records with taxonomy_status=missing don't participate."""
        records = [
            _matched_record(
                sequence="ATCG", species="Homo sapiens", taxid="9606",
            ),
            _missing_record(sequence="ATCG"),
        ]
        s = summarize_resolution(records)

        assert s["total_records"] == 2
        assert s["matched_records"] == 1
        assert s["unique_sequences"] == 1
        assert s["unique_species"] == 1
        assert s["resolved_sequence_count"] == 1
        assert s["ambiguous_sequence_count"] == 0
        assert s["species_level_unique_resolution_rate"] == 1.0

    def test_species_fallback_to_scientific_name(self):
        """When species="" , use scientific_name."""
        records = [
            _matched_record(
                species="", scientific_name="Homo sapiens",
                sequence="ATCG", taxid="9606",
            ),
        ]
        s = summarize_resolution(records)

        assert s["matched_records"] == 1
        assert s["unique_species"] == 1
        assert s["missing_species_count"] == 0

    def test_missing_sequence_counted(self):
        """Matched record with empty sequence → missing_sequence_count."""
        records = [
            _matched_record(species="Homo sapiens", sequence=""),
        ]
        s = summarize_resolution(records)

        assert s["matched_records"] == 1
        assert s["missing_sequence_count"] == 1
        assert s["unique_sequences"] == 0
        assert s["unique_species"] == 0

    def test_missing_species_counted(self):
        """Matched record with empty species+scientific_name → missing_species."""
        records = [
            _matched_record(
                species="", scientific_name="", sequence="ATCG",
            ),
        ]
        s = summarize_resolution(records)

        assert s["matched_records"] == 1
        assert s["missing_species_count"] == 1
        assert s["unique_sequences"] == 0
        assert s["unique_species"] == 0

    def test_empty_input(self):
        s = summarize_resolution([])
        assert s["total_records"] == 0
        assert s["unique_sequences"] == 0
        assert s["unique_species"] == 0
        assert s["species_level_unique_resolution_rate"] == 0.0

    def test_all_missing_records(self):
        """All records are missing → zero resolution stats."""
        records = [
            _missing_record(sequence="ATCG"),
            _missing_record(sequence="GCTA"),
        ]
        s = summarize_resolution(records)

        assert s["total_records"] == 2
        assert s["matched_records"] == 0
        assert s["unique_sequences"] == 0
        assert s["unique_species"] == 0
        assert s["resolved_sequence_count"] == 0
        assert s["ambiguous_sequence_count"] == 0
        assert s["species_level_unique_resolution_rate"] == 0.0

    def test_species_level_resolution_rate_all_ambiguous(self):
        """When all species share sequences, rate = 0."""
        records = [
            _matched_record(sequence="SHARED", species="A", taxid="1"),
            _matched_record(sequence="SHARED", species="B", taxid="2"),
            _matched_record(sequence="SHARED", species="C", taxid="3"),
        ]
        s = summarize_resolution(records)

        assert s["unique_species"] == 3
        assert s["ambiguous_species_count"] == 3
        assert s["species_level_unique_resolution_rate"] == 0.0

    def test_species_with_both_shared_and_unique_is_ambiguous(self):
        """A species with any shared sequence is ambiguous at species level."""
        records = [
            # Species A: one unique + one shared
            _matched_record(sequence="A_ONLY", species="A", taxid="1"),
            _matched_record(sequence="SHARED", species="A", taxid="1"),
            _matched_record(sequence="SHARED", species="B", taxid="2"),
            # Species C: all unique → resolved
            _matched_record(sequence="C_ONLY", species="C", taxid="3"),
        ]
        s = summarize_resolution(records)

        assert s["unique_species"] == 3
        # A is ambiguous (SHARED), B is ambiguous (SHARED), C is resolved
        assert s["ambiguous_species_count"] == 2
        assert s["species_level_unique_resolution_rate"] == round(1 / 3, 6)

    def test_all_keys_in_output(self):
        records = [
            _matched_record(sequence="ATCG", species="Homo sapiens", taxid="9606"),
        ]
        s = summarize_resolution(records)

        for key in RESOLUTION_FIELDNAMES:
            assert key in s, f"Missing key {key!r}"

    def test_unique_sequences_count(self):
        """unique_sequences counts distinct sequences, not records."""
        records = [
            _matched_record(record_id="amp_001", sequence="ATCG", species="A", taxid="1"),
            _matched_record(record_id="amp_002", sequence="ATCG", species="A", taxid="1"),
            _matched_record(record_id="amp_003", sequence="GCTA", species="A", taxid="1"),
        ]
        s = summarize_resolution(records)

        assert s["unique_sequences"] == 2

    def test_same_species_different_taxids(self):
        """Same species name from different taxids → deduplicated."""
        records = [
            _matched_record(sequence="AAAA", species="Homo sapiens", taxid="9606"),
            _matched_record(sequence="CCCC", species="Homo sapiens", taxid="9999"),
        ]
        s = summarize_resolution(records)

        assert s["unique_species"] == 1
        assert s["resolved_sequence_count"] == 2
        assert s["ambiguous_sequence_count"] == 0
        assert s["species_level_unique_resolution_rate"] == 1.0
