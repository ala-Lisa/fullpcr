"""Tests for summarize module."""

import textwrap
from pathlib import Path
from unittest import mock

import pytest

from fullpcr.summarize import (
    COMBINED_SUMMARY_FIELDNAMES,
    COVERAGE_FIELDNAMES,
    LENGTH_DIST_FIELDNAMES,
    MISMATCH_DIST_FIELDNAMES,
    SPECIES_RESOLUTION_FIELDNAMES,
    OUTPUT_FILES,
    build_coverage_by_taxon,
    build_length_distribution,
    build_mismatch_distribution,
    build_species_resolution,
    combine_summaries,
    summarize_amplicons,
    summarize_result_dir,
    write_summary_outputs,
)


# ── helpers ────────────────────────────────────────────────────────────


def _write_amplicons_tsv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _write_taxonomy(tmp_path: Path) -> str:
    path = tmp_path / "taxonomy.tsv"
    content = """\
        taxid\tscientific_name\tkingdom\tphylum\tclass\torder\tfamily\tgenus\tspecies
        9606\tHomo sapiens\tAnimalia\tChordata\tMammalia\tPrimates\tHominidae\tHomo\tHomo sapiens
        9913\tBos taurus\tAnimalia\tChordata\tMammalia\tCetartiodactyla\tBovidae\tBos\tBos taurus
        7227\tDrosophila melanogaster\tAnimalia\tArthropoda\tInsecta\tDiptera\tDrosophilidae\tDrosophila\tDrosophila melanogaster
    """
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return str(path)


def _build_mock_result_dir(tmp_path: Path) -> str:
    """Create a results/ dir with 2 primers × 2 mismatches."""
    result_dir = tmp_path / "results"

    # COI_short / mismatch_0
    _write_amplicons_tsv(
        result_dir / "COI_short" / "mismatch_0" / "amplicons.tsv",
        """\
        record_id\taccession\tdefinition\ttaxid\tscientific_name\tdirection\tforward_error\treverse_error\tforward_match\treverse_match\tamplicon_length\tsequence
        amplicon_0001\tNC_012920\t_sub[1..100]\t9606\tHomo sapiens\tforward\t0\t0\tGGTCA\tTAAAC\t200\tATCGATCGATCG
        amplicon_0002\tNC_002083\t_sub[1..100]\t9913\tBos taurus\tforward\t1\t0\t\t\t180\tGCTAGCTAGCTA
        amplicon_0003\tNC_005089\t\t\tDrosophila melanogaster\tforward\t0\t1\t\t\t150\tTATATATATATA
        """,
    )

    # COI_short / mismatch_1
    _write_amplicons_tsv(
        result_dir / "COI_short" / "mismatch_1" / "amplicons.tsv",
        """\
        record_id\taccession\tdefinition\ttaxid\tscientific_name\tdirection\tforward_error\treverse_error\tforward_match\treverse_match\tamplicon_length\tsequence
        amplicon_0004\tNC_012920\t_sub[1..100]\t9606\tHomo sapiens\tforward\t0\t0\tGGTCA\tTAAAC\t210\tGGGGGGGGGG
        """,
    )

    # 16S / mismatch_0
    _write_amplicons_tsv(
        result_dir / "16S" / "mismatch_0" / "amplicons.tsv",
        """\
        record_id\taccession\tdefinition\ttaxid\tscientific_name\tdirection\tforward_error\treverse_error\tforward_match\treverse_match\tamplicon_length\tsequence
        amplicon_0005\tNC_005089\t\t\tDrosophila melanogaster\tforward\t0\t0\t\t\t300\tCCCCCCCCCC
        amplicon_0006\tNC_006789\t\t\t\tforward\t2\t1\t\t\t160\tAAAAAAAAAA
        """,
    )

    # 16S / mismatch_1 (empty — header only)
    _write_amplicons_tsv(
        result_dir / "16S" / "mismatch_1" / "amplicons.tsv",
        "record_id\taccession\tdefinition\ttaxid\tscientific_name\tdirection\tforward_error\treverse_error\tforward_match\treverse_match\tamplicon_length\tsequence\n",
    )

    return str(result_dir)


# ── summarize_amplicons ────────────────────────────────────────────────


class TestSummarizeAmplicons:
    def test_basic_stats(self):
        records = [
            {
                "record_id": "amp_001",
                "taxid": "9606",
                "species": "Homo sapiens",
                "scientific_name": "Homo sapiens",
                "sequence": "ATCG",
                "amplicon_length": "200",
                "forward_error": "0",
                "reverse_error": "1",
                "taxonomy_status": "matched",
            },
            {
                "record_id": "amp_002",
                "taxid": "9913",
                "species": "Bos taurus",
                "scientific_name": "Bos taurus",
                "sequence": "GCTA",
                "amplicon_length": "180",
                "forward_error": "1",
                "reverse_error": "0",
                "taxonomy_status": "matched",
            },
        ]
        s = summarize_amplicons(records, primer_id="COI", mismatch=0)

        assert s["primer_id"] == "COI"
        assert s["mismatch"] == 0
        assert s["amplicon_count"] == 2
        assert s["unique_taxid_count"] == 2
        assert s["unique_species_count"] == 2
        assert s["unique_sequence_count"] == 2
        assert s["matched_taxonomy_count"] == 2
        assert s["missing_taxonomy_count"] == 0
        assert s["min_amplicon_length"] == 180
        assert s["max_amplicon_length"] == 200
        assert s["mean_amplicon_length"] == 190.0
        assert s["forward_error_mean"] == 0.5
        assert s["reverse_error_mean"] == 0.5

    def test_counts_missing_taxonomy(self):
        records = [
            {
                "record_id": "amp_001",
                "taxid": "",
                "sequence": "ATCG",
                "amplicon_length": "100",
                "taxonomy_status": "missing",
            },
        ]
        s = summarize_amplicons(records, primer_id="TEST", mismatch=0)
        assert s["matched_taxonomy_count"] == 0
        assert s["missing_taxonomy_count"] == 1

    def test_empty_records(self):
        s = summarize_amplicons([], primer_id="TEST", mismatch=0)
        assert s["amplicon_count"] == 0
        assert s["unique_taxid_count"] == 0
        assert s["min_amplicon_length"] == 0
        assert s["max_amplicon_length"] == 0
        assert s["mean_amplicon_length"] == 0.0

    def test_no_primer_id(self):
        s = summarize_amplicons([], mismatch=0)
        assert s["primer_id"] == ""

    def test_zero_length_ignored(self):
        records = [
            {
                "record_id": "amp_001",
                "taxid": "9606",
                "sequence": "ATCG",
                "amplicon_length": "0",
                "taxonomy_status": "matched",
                "species": "Homo sapiens",
                "scientific_name": "Homo sapiens",
            },
        ]
        s = summarize_amplicons(records)
        # 0-length is filtered out, so no valid lengths
        assert s["min_amplicon_length"] == 0
        assert s["max_amplicon_length"] == 0

    def test_all_keys_present(self):
        s = summarize_amplicons([], primer_id="X", mismatch=1)
        for key in COMBINED_SUMMARY_FIELDNAMES:
            assert key in s, f"Missing key {key!r}"


# ── summarize_result_dir ───────────────────────────────────────────────


class TestSummarizeResultDir:
    def test_discovers_all_pairs(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        tax_path = _write_taxonomy(tmp_path)
        summaries = summarize_result_dir(result_dir, tax_path)

        assert len(summaries) == 4  # 2 primers × 2 mismatches
        primer_ids = {s["primer_id"] for s in summaries}
        assert primer_ids == {"COI_short", "16S"}
        mismatches = {s["mismatch"] for s in summaries}
        assert mismatches == {0, 1}

    def test_with_taxonomy_merge(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        tax_path = _write_taxonomy(tmp_path)
        summaries = summarize_result_dir(result_dir, tax_path)

        coi_m0 = [
            s for s in summaries
            if s["primer_id"] == "COI_short" and s["mismatch"] == 0
        ][0]
        assert coi_m0["amplicon_count"] == 3
        # 9606 matched by taxid, 9913 matched by taxid,
        # NC_005089 matched by scientific_name (Drosophila melanogaster)
        assert coi_m0["matched_taxonomy_count"] == 3

    def test_without_taxonomy(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        summaries = summarize_result_dir(result_dir, taxonomy_path=None)

        assert len(summaries) == 4
        for s in summaries:
            assert s["matched_taxonomy_count"] == 0

    def test_nonexistent_dir(self):
        assert summarize_result_dir("/nonexistent/path") == []

    def test_missing_taxonomy_path_does_not_crash(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        summaries = summarize_result_dir(
            result_dir, taxonomy_path="/nonexistent/tax.tsv",
        )
        assert len(summaries) == 4


# ── length distribution ────────────────────────────────────────────────


class TestLengthDistribution:
    def test_builds_correct_distribution(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        dist = build_length_distribution(result_dir)

        # COI_short/m0: 200, 180, 150 (3 distinct)
        # COI_short/m1: 210 (1 distinct)
        # 16S/m0: 300, 160 (2 distinct)
        # 16S/m1: empty (0)
        assert len(dist) == 6

        row_200 = [
            r for r in dist
            if r["primer_id"] == "COI_short" and r["mismatch"] == 0
            and r["amplicon_length"] == 200
        ]
        assert len(row_200) == 1
        assert row_200[0]["count"] == 1

    def test_output_keys_match_schema(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        dist = build_length_distribution(result_dir)
        for row in dist:
            for key in LENGTH_DIST_FIELDNAMES:
                assert key in row

    def test_empty_result_dir(self, tmp_path):
        empty_dir = tmp_path / "empty_results"
        empty_dir.mkdir()
        dist = build_length_distribution(str(empty_dir))
        assert dist == []


# ── mismatch distribution ──────────────────────────────────────────────


class TestMismatchDistribution:
    def test_builds_correct_distribution(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        dist = build_mismatch_distribution(result_dir)

        # Per primer×mismatch: COI_short/m0=3, COI_short/m1=1, 16S/m0=2
        assert len(dist) == 6

        # Check (0,0) count across all: amp1 + amp4 + amp5 = 3
        fw0_rv0 = [
            r for r in dist
            if r["forward_error"] == "0" and r["reverse_error"] == "0"
        ]
        total_count = sum(r["count"] for r in fw0_rv0)
        assert total_count == 3

    def test_output_keys_match_schema(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        dist = build_mismatch_distribution(result_dir)
        for row in dist:
            for key in MISMATCH_DIST_FIELDNAMES:
                assert key in row


# ── coverage by taxon ──────────────────────────────────────────────────


class TestCoverageByTaxon:
    def test_with_taxonomy(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        tax_path = _write_taxonomy(tmp_path)
        coverage = build_coverage_by_taxon(result_dir, tax_path)

        assert len(coverage) > 0
        for row in coverage:
            assert row["primer_id"] in ("COI_short", "16S")
            assert row["mismatch"] in (0, 1)
            for key in COVERAGE_FIELDNAMES:
                assert key in row

    def test_without_taxonomy(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        coverage = build_coverage_by_taxon(result_dir, taxonomy_path=None)
        assert coverage == []

    def test_missing_taxonomy_file(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        coverage = build_coverage_by_taxon(
            result_dir, taxonomy_path="/no/such/file.tsv",
        )
        assert coverage == []


# ── species resolution ────────────────────────────────────────────────


class TestSpeciesResolution:
    def test_with_taxonomy(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        tax_path = _write_taxonomy(tmp_path)
        res = build_species_resolution(result_dir, tax_path)

        assert len(res) == 4  # one per primer × mismatch
        for row in res:
            assert row["primer_id"] in ("COI_short", "16S")
            for key in SPECIES_RESOLUTION_FIELDNAMES:
                assert key in row

    def test_without_taxonomy(self, tmp_path):
        result_dir = _build_mock_result_dir(tmp_path)
        res = build_species_resolution(result_dir, taxonomy_path=None)
        assert len(res) == 4
        for row in res:
            assert row["total_records"] >= 0

    def test_matches_standalone_resolution(self, tmp_path):
        """Integration: values match standalone summarize_resolution()."""
        from fullpcr.resolution import summarize_resolution
        from fullpcr.taxonomy import merge_taxonomy, read_taxonomy
        from fullpcr.summarize import _read_amplicons_tsv

        result_dir = _build_mock_result_dir(tmp_path)
        tax_path = _write_taxonomy(tmp_path)

        amplicon_path = (
            Path(result_dir) / "COI_short" / "mismatch_0" / "amplicons.tsv"
        )
        records = _read_amplicons_tsv(amplicon_path)
        taxonomy = read_taxonomy(tax_path)
        merged = merge_taxonomy(records, taxonomy)
        expected = summarize_resolution(merged)

        all_res = build_species_resolution(result_dir, tax_path)
        coi_m0 = [
            r for r in all_res
            if r["primer_id"] == "COI_short" and r["mismatch"] == 0
        ][0]

        assert coi_m0["total_records"] == expected["total_records"]
        assert coi_m0["unique_species"] == expected["unique_species"]
        assert coi_m0["species_level_unique_resolution_rate"] == pytest.approx(
            expected["species_level_unique_resolution_rate"]
        )


# ── write_summary_outputs ─────────────────────────────────────────────


class TestWriteSummaryOutputs:
    def test_writes_files_with_correct_columns(self, tmp_path):
        clean_dir = tmp_path / "results"
        _write_amplicons_tsv(
            clean_dir / "COI" / "mismatch_0" / "amplicons.tsv",
            """\
            record_id\taccession\tdefinition\ttaxid\tscientific_name\tdirection\tforward_error\treverse_error\tforward_match\treverse_match\tamplicon_length\tsequence
            amplicon_0001\tNC_012920\t\t9606\tHomo sapiens\tforward\t0\t1\t\t\t200\tATCGATCG
            """,
        )
        tax_path = _write_taxonomy(tmp_path)
        written = write_summary_outputs(clean_dir, tax_path)

        # All 5 files exist
        for key, filename in OUTPUT_FILES.items():
            assert key in written
            assert Path(written[key]).is_file(), f"{filename} not written"

        # Check columns for each file
        expected_headers = {
            "combined_summary": COMBINED_SUMMARY_FIELDNAMES,
            "coverage_by_taxon": COVERAGE_FIELDNAMES,
            "length_distribution": LENGTH_DIST_FIELDNAMES,
            "mismatch_distribution": MISMATCH_DIST_FIELDNAMES,
            "species_resolution": SPECIES_RESOLUTION_FIELDNAMES,
        }
        for key, expected in expected_headers.items():
            with open(written[key]) as fh:
                header = fh.readline().strip().split("\t")
            assert header == expected, f"{key}: header mismatch"

    def test_without_taxonomy_still_writes(self, tmp_path):
        clean_dir = tmp_path / "results"
        _write_amplicons_tsv(
            clean_dir / "COI" / "mismatch_0" / "amplicons.tsv",
            """\
            record_id\taccession\tdefinition\ttaxid\tscientific_name\tdirection\tforward_error\treverse_error\tforward_match\treverse_match\tamplicon_length\tsequence
            amplicon_0001\tNC_012920\t\t9606\tHomo sapiens\tforward\t0\t0\t\t\t200\tATCGATCG
            """,
        )
        written = write_summary_outputs(clean_dir, taxonomy_path=None)

        for key in OUTPUT_FILES:
            assert Path(written[key]).is_file()

    def test_empty_result_dir(self, tmp_path):
        empty_dir = tmp_path / "empty_results"
        empty_dir.mkdir()
        written = write_summary_outputs(empty_dir)

        for key in OUTPUT_FILES:
            assert Path(written[key]).is_file()


# ── combine_summaries ──────────────────────────────────────────────────


class TestCombineSummaries:
    def test_reads_back_written_file(self, tmp_path):
        clean_dir = tmp_path / "results"
        _write_amplicons_tsv(
            clean_dir / "COI" / "mismatch_0" / "amplicons.tsv",
            """\
            record_id\taccession\tdefinition\ttaxid\tscientific_name\tdirection\tforward_error\treverse_error\tforward_match\treverse_match\tamplicon_length\tsequence
            amplicon_0001\tNC_012920\t\t9606\tHomo sapiens\tforward\t0\t0\t\t\t200\tATCG
            """,
        )
        write_summary_outputs(clean_dir)
        rows = combine_summaries(clean_dir)

        assert len(rows) == 1
        assert rows[0]["primer_id"] == "COI"
        assert rows[0]["mismatch"] == "0"
        assert rows[0]["amplicon_count"] == "1"

    def test_missing_file_returns_empty(self, tmp_path):
        rows = combine_summaries(str(tmp_path / "nonexistent"))
        assert rows == []


# ── OSError warning ────────────────────────────────────────────────────


class TestOSErrorWarning:
    def test_oserror_on_result_dir_warns(self, tmp_path, monkeypatch):
        """When result_dir can't be read, a warning is emitted."""
        from fullpcr.summarize import _discover_primer_mismatch_pairs

        result_dir = tmp_path / "results"
        result_dir.mkdir()

        # Patch Path.iterdir on the class to raise OSError
        monkeypatch.setattr(Path, "iterdir", lambda self: (_ for _ in ()).throw(
            OSError("Permission denied")
        ))

        with pytest.warns(RuntimeWarning, match="无法读取结果目录"):
            pairs = _discover_primer_mismatch_pairs(result_dir)

        assert pairs == []

    def test_oserror_on_primer_subdir_warns(self, tmp_path, monkeypatch):
        """When a primer subdir can't be read, a warning is emitted."""
        from fullpcr.summarize import _discover_primer_mismatch_pairs

        result_dir = tmp_path / "results"
        primer_dir = result_dir / "COI_short" / "mismatch_0"
        primer_dir.mkdir(parents=True)
        (primer_dir / "amplicons.tsv").write_text(
            "record_id\taccession\namp_0001\tNC_001\n",
            encoding="utf-8",
        )

        # Patch iterdir to succeed on first call, raise OSError on second
        call_count = 0

        def _iterdir_with_fallback(self_path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: result_dir → return [COI_short] subdir
                return [primer_dir.parent]
            else:
                # Second call: primer subdir → raise OSError
                raise OSError("Permission denied")

        monkeypatch.setattr(Path, "iterdir", _iterdir_with_fallback)

        with pytest.warns(RuntimeWarning, match="无法读取 primer 子目录"):
            pairs = _discover_primer_mismatch_pairs(result_dir)

        assert pairs == []
