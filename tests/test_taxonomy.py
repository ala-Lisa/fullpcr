"""Tests for taxonomy module."""

import copy
import textwrap
from pathlib import Path

import pytest

from fullpcr.taxonomy import (
    MERGED_FIELDNAMES,
    TAXONOMIC_RANKS,
    merge_taxonomy,
    read_taxonomy,
    summarize_taxonomic_coverage,
)


# ── helpers ────────────────────────────────────────────────────────────


def _write_taxonomy_tsv(tmp_path: Path, content: str) -> str:
    path = tmp_path / "taxonomy.tsv"
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return str(path)


def _sample_taxonomy(tmp_path: Path) -> str:
    content = """\
        taxid\tscientific_name\tkingdom\tphylum\tclass\torder\tfamily\tgenus\tspecies
        9606\tHomo sapiens\tAnimalia\tChordata\tMammalia\tPrimates\tHominidae\tHomo\tHomo sapiens
        9913\tBos taurus\tAnimalia\tChordata\tMammalia\tCetartiodactyla\tBovidae\tBos\tBos taurus
        7227\tDrosophila melanogaster\tAnimalia\tArthropoda\tInsecta\tDiptera\tDrosophilidae\tDrosophila\tDrosophila melanogaster
    """
    return _write_taxonomy_tsv(tmp_path, content)


def _sample_amplicons() -> list[dict]:
    return [
        {
            "record_id": "amplicon_0001",
            "accession": "NC_012920",
            "definition": "_sub[5342..5907]",
            "taxid": "9606",
            "scientific_name": "Homo sapiens",
            "direction": "forward",
            "forward_error": "0",
            "reverse_error": "0",
            "forward_match": "GGTCA",
            "reverse_match": "TAAAC",
            "amplicon_length": 200,
            "sequence": "ATCGATCG",
        },
        {
            "record_id": "amplicon_0002",
            "accession": "NC_002083",
            "definition": "_sub[100..500]",
            "taxid": "9913",
            "scientific_name": "Bos taurus",
            "direction": "forward",
            "forward_error": "1",
            "reverse_error": "0",
            "forward_match": "",
            "reverse_match": "",
            "amplicon_length": 180,
            "sequence": "GCTAGCTA",
        },
        {
            "record_id": "amplicon_0003",
            "accession": "NC_005089",
            "definition": "",
            "taxid": "",
            "scientific_name": "Drosophila melanogaster",
            "direction": "",
            "forward_error": "",
            "reverse_error": "",
            "forward_match": "",
            "reverse_match": "",
            "amplicon_length": 150,
            "sequence": "TATATATA",
        },
        {
            "record_id": "amplicon_0004",
            "accession": "NC_006789",
            "definition": "",
            "taxid": "",
            "scientific_name": "",
            "direction": "",
            "forward_error": "",
            "reverse_error": "",
            "forward_match": "",
            "reverse_match": "",
            "amplicon_length": 100,
            "sequence": "CGCGCGCG",
        },
    ]


# ── read_taxonomy ──────────────────────────────────────────────────────


class TestReadTaxonomy:
    def test_reads_valid_tsv(self, tmp_path):
        content = """\
            taxid\tscientific_name\tkingdom\tphylum\tspecies
            9606\tHomo sapiens\tAnimalia\tChordata\tHomo sapiens
            9913\tBos taurus\tAnimalia\tChordata\tBos taurus
        """
        path = _write_taxonomy_tsv(tmp_path, content)
        result = read_taxonomy(path)

        assert len(result) == 2
        assert result[0]["taxid"] == "9606"
        assert result[0]["scientific_name"] == "Homo sapiens"
        assert result[0]["kingdom"] == "Animalia"
        assert result[0]["species"] == "Homo sapiens"

    def test_taxid_string_conversion(self, tmp_path):
        """taxid should always be converted to string."""
        content = """\
            taxid\tscientific_name
            9606\tHomo sapiens
            9913\tBos taurus
        """
        path = _write_taxonomy_tsv(tmp_path, content)
        result = read_taxonomy(path)

        assert all(isinstance(r["taxid"], str) for r in result)
        assert result[0]["taxid"] == "9606"

    def test_missing_optional_columns_filled(self, tmp_path):
        """Missing optional columns should be filled with empty string."""
        content = """\
            taxid
            9606
            9913
        """
        path = _write_taxonomy_tsv(tmp_path, content)
        result = read_taxonomy(path)

        assert result[0]["scientific_name"] == ""
        assert result[0]["kingdom"] == ""
        assert result[0]["species"] == ""

    def test_some_optional_columns_missing(self, tmp_path):
        """Mix of present and missing optional columns."""
        content = """\
            taxid\tscientific_name\tkingdom
            9606\tHomo sapiens\tAnimalia
        """
        path = _write_taxonomy_tsv(tmp_path, content)
        result = read_taxonomy(path)

        assert result[0]["scientific_name"] == "Homo sapiens"
        assert result[0]["kingdom"] == "Animalia"
        assert result[0]["species"] == ""
        assert result[0]["phylum"] == ""

    def test_raises_on_missing_taxid_column(self, tmp_path):
        content = """\
            scientific_name\tkingdom
            Homo sapiens\tAnimalia
        """
        path = _write_taxonomy_tsv(tmp_path, content)

        with pytest.raises(ValueError, match="缺少必需列"):
            read_taxonomy(path)

    def test_raises_on_file_not_found(self, tmp_path):
        nonexistent = str(tmp_path / "no_such_file.tsv")
        with pytest.raises(FileNotFoundError, match="不存在"):
            read_taxonomy(nonexistent)

    def test_empty_taxonomy_tsv(self, tmp_path):
        """Empty file (only header) should return empty list."""
        content = "taxid\tscientific_name\n"
        path = _write_taxonomy_tsv(tmp_path, content)
        result = read_taxonomy(path)
        assert result == []


# ── merge_taxonomy ─────────────────────────────────────────────────────


class TestMergeTaxonomy:
    def test_merge_by_taxid(self, tmp_path):
        path = _sample_taxonomy(tmp_path)
        taxonomy = read_taxonomy(path)
        amplicons = _sample_amplicons()

        merged = merge_taxonomy(amplicons, taxonomy)

        # amplicon_0001: taxid 9606 → matched
        assert merged[0]["taxid"] == "9606"
        assert merged[0]["scientific_name"] == "Homo sapiens"
        assert merged[0]["kingdom"] == "Animalia"
        assert merged[0]["species"] == "Homo sapiens"
        assert merged[0]["taxonomy_status"] == "matched"

        # amplicon_0002: taxid 9913 → matched
        assert merged[1]["taxid"] == "9913"
        assert merged[1]["scientific_name"] == "Bos taurus"
        assert merged[1]["kingdom"] == "Animalia"
        assert merged[1]["taxonomy_status"] == "matched"

    def test_merge_by_scientific_name_fallback(self, tmp_path):
        """When taxid is empty, merge by scientific_name."""
        path = _sample_taxonomy(tmp_path)
        taxonomy = read_taxonomy(path)
        amplicons = _sample_amplicons()

        merged = merge_taxonomy(amplicons, taxonomy)

        # amplicon_0003: taxid="" but name=Drosophila melanogaster → matched
        assert merged[2]["taxid"] == "7227"
        assert merged[2]["scientific_name"] == "Drosophila melanogaster"
        assert merged[2]["kingdom"] == "Animalia"
        assert merged[2]["taxonomy_status"] == "matched"

    def test_merge_by_species_fallback(self, tmp_path):
        """Species column in taxonomy can match amplicon scientific_name."""
        content = """\
            taxid\tscientific_name\tspecies
            7227\tDrosophila melanogaster\tDrosophila melanogaster
        """
        path = _write_taxonomy_tsv(tmp_path, content)
        taxonomy = read_taxonomy(path)

        amplicons = [
            {
                "record_id": "amp_001",
                "accession": "NC_001",
                "definition": "",
                "taxid": "",
                "scientific_name": "Drosophila melanogaster",
                "direction": "",
                "forward_error": "",
                "reverse_error": "",
                "forward_match": "",
                "reverse_match": "",
                "amplicon_length": 100,
                "sequence": "ATCG",
            },
        ]
        merged = merge_taxonomy(amplicons, taxonomy)

        assert merged[0]["taxonomy_status"] == "matched"
        assert merged[0]["taxid"] == "7227"

    def test_unmatched_records_preserved(self, tmp_path):
        """Records with no taxonomy match must not be dropped."""
        path = _sample_taxonomy(tmp_path)
        taxonomy = read_taxonomy(path)
        amplicons = _sample_amplicons()

        merged = merge_taxonomy(amplicons, taxonomy)

        # amplicon_0004: no taxid, no scientific_name → missing
        assert merged[3]["taxonomy_status"] == "missing"
        assert merged[3]["record_id"] == "amplicon_0004"
        assert merged[3]["accession"] == "NC_006789"
        assert merged[3]["sequence"] == "CGCGCGCG"
        assert merged[3]["kingdom"] == ""
        assert merged[3]["species"] == ""

    def test_taxonomy_species_overrides_header(self, tmp_path):
        """Taxonomy scientific_name overrides amplicon header value."""
        content = """\
            taxid\tscientific_name\tkingdom\tspecies
            9606\tHomo sapiens\tAnimalia\tHomo sapiens
        """
        path = _write_taxonomy_tsv(tmp_path, content)
        taxonomy = read_taxonomy(path)

        amplicons = [
            {
                "record_id": "amp_001",
                "accession": "NC_001",
                "definition": "",
                "taxid": "9606",
                "scientific_name": "Human",
                "direction": "",
                "forward_error": "",
                "reverse_error": "",
                "forward_match": "",
                "reverse_match": "",
                "amplicon_length": 100,
                "sequence": "ATCG",
            },
        ]
        merged = merge_taxonomy(amplicons, taxonomy)

        assert merged[0]["scientific_name"] == "Homo sapiens"

    def test_multiple_amplicons_same_taxid(self, tmp_path):
        """Multiple amplicons with the same taxid should all merge."""
        path = _sample_taxonomy(tmp_path)
        taxonomy = read_taxonomy(path)

        amplicons = [
            {
                "record_id": "amp_001",
                "accession": "NC_001",
                "definition": "",
                "taxid": "9606",
                "scientific_name": "",
                "direction": "",
                "forward_error": "",
                "reverse_error": "",
                "forward_match": "",
                "reverse_match": "",
                "amplicon_length": 100,
                "sequence": "ATCG",
            },
            {
                "record_id": "amp_002",
                "accession": "NC_002",
                "definition": "",
                "taxid": "9606",
                "scientific_name": "",
                "direction": "",
                "forward_error": "",
                "reverse_error": "",
                "forward_match": "",
                "reverse_match": "",
                "amplicon_length": 200,
                "sequence": "GCTA",
            },
        ]
        merged = merge_taxonomy(amplicons, taxonomy)

        assert len(merged) == 2
        assert merged[0]["taxonomy_status"] == "matched"
        assert merged[1]["taxonomy_status"] == "matched"
        assert merged[0]["kingdom"] == "Animalia"
        assert merged[1]["kingdom"] == "Animalia"

    def test_does_not_mutate_input(self, tmp_path):
        """Merge must return new records, not modify originals."""
        path = _sample_taxonomy(tmp_path)
        taxonomy = read_taxonomy(path)

        amplicons = _sample_amplicons()
        original = copy.deepcopy(amplicons)

        merge_taxonomy(amplicons, taxonomy)

        for i, orig in enumerate(original):
            for key in orig:
                assert amplicons[i][key] == orig[key], (
                    f"amplicon {i} key {key!r} was mutated"
                )

    def test_all_output_keys_present(self, tmp_path):
        """Every merged record should have all MERGED_FIELDNAMES keys."""
        path = _sample_taxonomy(tmp_path)
        taxonomy = read_taxonomy(path)
        amplicons = _sample_amplicons()

        merged = merge_taxonomy(amplicons, taxonomy)

        for rec in merged:
            for key in MERGED_FIELDNAMES:
                assert key in rec, f"Missing key {key!r} in merged record"

    def test_empty_amplicons_returns_empty_list(self, tmp_path):
        path = _sample_taxonomy(tmp_path)
        taxonomy = read_taxonomy(path)
        merged = merge_taxonomy([], taxonomy)
        assert merged == []

    def test_empty_taxonomy_all_missing(self, tmp_path):
        """When taxonomy is empty, all records marked missing."""
        amplicons = _sample_amplicons()
        merged = merge_taxonomy(amplicons, [])

        assert len(merged) == len(amplicons)
        for rec in merged:
            assert rec["taxonomy_status"] == "missing"
            assert rec["kingdom"] == ""

    def test_taxid_not_in_taxonomy_falls_back(self, tmp_path):
        """When taxid doesn't match, try scientific_name."""
        path = _sample_taxonomy(tmp_path)
        taxonomy = read_taxonomy(path)

        amplicons = [
            {
                "record_id": "amp_001",
                "accession": "NC_001",
                "definition": "",
                "taxid": "9999",
                "scientific_name": "Bos taurus",
                "direction": "",
                "forward_error": "",
                "reverse_error": "",
                "forward_match": "",
                "reverse_match": "",
                "amplicon_length": 100,
                "sequence": "ATCG",
            },
        ]
        merged = merge_taxonomy(amplicons, taxonomy)

        assert merged[0]["taxonomy_status"] == "matched"
        assert merged[0]["taxid"] == "9913"
        assert merged[0]["scientific_name"] == "Bos taurus"


# ── summarize_taxonomic_coverage ───────────────────────────────────────


class TestSummarizeTaxonomicCoverage:
    def _make_merged(self, records: list[dict] | None = None) -> list[dict]:
        if records is not None:
            return records
        return [
            {
                "record_id": "amp_001",
                "accession": "NC_001",
                "taxid": "9606",
                "scientific_name": "Homo sapiens",
                "kingdom": "Animalia",
                "phylum": "Chordata",
                "class": "Mammalia",
                "order": "Primates",
                "family": "Hominidae",
                "genus": "Homo",
                "species": "Homo sapiens",
                "taxonomy_status": "matched",
                "sequence": "ATCG",
                "amplicon_length": 100,
                "forward_error": "0",
                "reverse_error": "0",
            },
            {
                "record_id": "amp_002",
                "accession": "NC_002",
                "taxid": "9913",
                "scientific_name": "Bos taurus",
                "kingdom": "Animalia",
                "phylum": "Chordata",
                "class": "Mammalia",
                "order": "Cetartiodactyla",
                "family": "Bovidae",
                "genus": "Bos",
                "species": "Bos taurus",
                "taxonomy_status": "matched",
                "sequence": "GCTA",
                "amplicon_length": 200,
                "forward_error": "1",
                "reverse_error": "0",
            },
        ]

    def test_outputs_all_ranks(self):
        merged = self._make_merged()
        summary = summarize_taxonomic_coverage(merged)

        ranks = {r["rank"] for r in summary}
        for rank in TAXONOMIC_RANKS:
            assert rank in ranks, f"Missing rank {rank}"

    def test_kingdom_coverage(self):
        merged = self._make_merged()
        summary = summarize_taxonomic_coverage(merged)

        kingdom_rows = [r for r in summary if r["rank"] == "kingdom"]
        assert len(kingdom_rows) == 1
        assert kingdom_rows[0]["name"] == "Animalia"
        assert kingdom_rows[0]["amplicon_count"] == 2
        assert kingdom_rows[0]["unique_taxid_count"] == 2
        assert kingdom_rows[0]["unique_species_count"] == 2

    def test_species_coverage(self):
        merged = self._make_merged()
        summary = summarize_taxonomic_coverage(merged)

        species_rows = [r for r in summary if r["rank"] == "species"]
        names = {r["name"] for r in species_rows}
        assert "Homo sapiens" in names
        assert "Bos taurus" in names
        for r in species_rows:
            assert r["amplicon_count"] >= 1

    def test_unclassified_grouping(self):
        """Records with empty rank values grouped as (unclassified)."""
        merged = [
            {
                "record_id": "amp_001",
                "accession": "NC_001",
                "taxid": "9606",
                "scientific_name": "",
                "kingdom": "",
                "phylum": "",
                "class": "",
                "order": "",
                "family": "",
                "genus": "",
                "species": "",
                "taxonomy_status": "missing",
                "sequence": "ATCG",
                "amplicon_length": 100,
                "forward_error": "",
                "reverse_error": "",
            },
        ]
        summary = summarize_taxonomic_coverage(merged)

        kingdom_rows = [r for r in summary if r["rank"] == "kingdom"]
        assert len(kingdom_rows) == 1
        assert kingdom_rows[0]["name"] == "(unclassified)"
        assert kingdom_rows[0]["amplicon_count"] == 1

    def test_empty_input_returns_empty_list(self):
        summary = summarize_taxonomic_coverage([])
        assert summary == []

    def test_multiple_unclassified(self):
        """Multiple unclassified records should be aggregated."""
        merged = [
            {
                "record_id": f"amp_{i:03d}",
                "accession": f"NC_{i:03d}",
                "taxid": "",
                "scientific_name": "",
                "kingdom": "",
                "phylum": "",
                "class": "",
                "order": "",
                "family": "",
                "genus": "",
                "species": "",
                "taxonomy_status": "missing",
                "sequence": "ATCG",
                "amplicon_length": 100,
                "forward_error": "",
                "reverse_error": "",
            }
            for i in range(5)
        ]
        summary = summarize_taxonomic_coverage(merged)

        kingdom_rows = [r for r in summary if r["rank"] == "kingdom"]
        assert len(kingdom_rows) == 1
        assert kingdom_rows[0]["name"] == "(unclassified)"
        assert kingdom_rows[0]["amplicon_count"] == 5

    def test_different_orders_same_class(self):
        """Two records in same class but different orders."""
        merged = self._make_merged()
        summary = summarize_taxonomic_coverage(merged)

        class_rows = [r for r in summary if r["rank"] == "class"]
        mammalia = [r for r in class_rows if r["name"] == "Mammalia"]
        assert len(mammalia) == 1
        assert mammalia[0]["amplicon_count"] == 2
        assert mammalia[0]["unique_species_count"] == 2

        order_rows = [r for r in summary if r["rank"] == "order"]
        orders = {r["name"] for r in order_rows}
        assert "Primates" in orders
        assert "Cetartiodactyla" in orders

    def test_result_is_sorted(self):
        """Results should be sorted by name within each rank."""
        merged = self._make_merged()
        summary = summarize_taxonomic_coverage(merged)

        kingdom_rows = [r for r in summary if r["rank"] == "kingdom"]
        names = [r["name"] for r in kingdom_rows]
        assert names == sorted(names)

    def test_unique_species_count_correct(self):
        """Two amplicons of same species → 1 unique_species."""
        merged = [
            {
                "record_id": "amp_001",
                "accession": "NC_001",
                "taxid": "9606",
                "scientific_name": "Homo sapiens",
                "kingdom": "Animalia",
                "phylum": "Chordata",
                "class": "Mammalia",
                "order": "Primates",
                "family": "Hominidae",
                "genus": "Homo",
                "species": "Homo sapiens",
                "taxonomy_status": "matched",
                "sequence": "ATCG",
                "amplicon_length": 100,
                "forward_error": "",
                "reverse_error": "",
            },
            {
                "record_id": "amp_002",
                "accession": "NC_002",
                "taxid": "9606",
                "scientific_name": "Homo sapiens",
                "kingdom": "Animalia",
                "phylum": "Chordata",
                "class": "Mammalia",
                "order": "Primates",
                "family": "Hominidae",
                "genus": "Homo",
                "species": "Homo sapiens",
                "taxonomy_status": "matched",
                "sequence": "GCTA",
                "amplicon_length": 200,
                "forward_error": "",
                "reverse_error": "",
            },
        ]
        summary = summarize_taxonomic_coverage(merged)

        species_rows = [r for r in summary if r["rank"] == "species"]
        hs = [r for r in species_rows if r["name"] == "Homo sapiens"]
        assert len(hs) == 1
        assert hs[0]["amplicon_count"] == 2
        assert hs[0]["unique_species_count"] == 1
        assert hs[0]["unique_taxid_count"] == 1

    def test_reads_example_data(self):
        """Integration: read real example taxonomy.tsv."""
        import os

        project_root = os.path.dirname(os.path.dirname(__file__))
        example = os.path.join(project_root, "example_data", "taxonomy.tsv")

        taxonomy = read_taxonomy(example)

        assert len(taxonomy) == 6
        assert taxonomy[0]["taxid"] == "9606"
        assert taxonomy[0]["scientific_name"] == "Homo sapiens"
        assert taxonomy[0]["kingdom"] == "Animalia"
        for col in ["taxid", "scientific_name", "kingdom", "phylum",
                     "class", "order", "family", "genus", "species"]:
            assert col in taxonomy[0]
