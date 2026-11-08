from pathlib import Path
import pytest

from govweb.website_discovery import (
    parse_directory_html,
    normalize_name,
    map_roster,
    build_coverage,
)

SOURCE = 'https://mofaga.gov.np/local-contact'
FIXTURE = Path(__file__).parent / 'fixtures' / 'govweb' / 'mofaga_local_contact_sample.html'


def sample_roster():
    return [
        {'municipality_id': '1', 'name': 'Biratnagar Metropolitan City', 'district': 'Morang'},
        {'municipality_id': '2', 'name': 'Urlabari Municipality', 'district': 'Morang'},
        {'municipality_id': '3', 'name': 'Missing Municipality', 'district': 'Morang'},
        {'municipality_id': '4', 'name': 'Same Name Municipality', 'district': 'District Two'},
    ]


def test_parse_directory_table_and_resolve_relative_links():
    rows = parse_directory_html(FIXTURE.read_text(encoding='utf-8'), SOURCE)
    assert len(rows) == 4
    assert rows[0] == {
        'name': 'Biratnagar Metropolitan City',
        'district': 'Morang',
        'website_url': 'https://biratnagarmun.gov.np',
    }


def test_unicode_normalization_collapses_whitespace_and_casefolds():
    assert normalize_name('  BIRATNAGAR   Metropolitan City ') == normalize_name('Biratnagar Metropolitan City')
    assert normalize_name('काठमाडौँ  महानगरपालिका') == normalize_name('काठमाडौँ महानगरपालिका')


def test_exact_name_and_district_maps_with_high_confidence():
    rows = parse_directory_html(FIXTURE.read_text(encoding='utf-8'), SOURCE)
    item = map_roster(sample_roster(), rows, SOURCE)[0]
    assert item['status'] == 'mapped'
    assert item['domain'] == 'biratnagarmun.gov.np'
    assert item['mapping_confidence'] == 'high'
    assert item['mapping_method'] == 'exact_name_and_district'


def test_exact_match_without_website_is_no_known_website():
    rows = parse_directory_html(FIXTURE.read_text(encoding='utf-8'), SOURCE)
    item = map_roster(sample_roster(), rows, SOURCE)[1]
    assert item['status'] == 'no_known_website'
    assert item['website_url'] == ''


def test_same_name_in_other_district_does_not_cross_match():
    roster = [{'municipality_id': 'x', 'name': 'Same Name Municipality', 'district': 'District Three'}]
    rows = parse_directory_html(FIXTURE.read_text(encoding='utf-8'), SOURCE)
    item = map_roster(roster, rows, SOURCE)[0]
    assert item['status'] == 'unresolved'
    assert item['candidate_count'] == 0


def test_missing_exact_match_is_unresolved_not_fuzzy_matched():
    item = map_roster(sample_roster(), [], SOURCE)[2]
    assert item['status'] == 'unresolved'
    assert item['mapping_confidence'] == 'none'
    assert item['mapping_method'] == 'no_exact_match'


def test_coverage_counts_partition_the_entire_roster():
    roster = sample_roster()
    rows = parse_directory_html(FIXTURE.read_text(encoding='utf-8'), SOURCE)
    coverage = build_coverage(roster, map_roster(roster, rows, SOURCE))
    assert coverage['total_roster_entries'] == 4
    assert coverage['accounted_for'] == 4
    assert coverage['mapped'] == 2
    assert coverage['no_known_website'] == 1
    assert coverage['unresolved'] == 1
    assert coverage['mapped'] + coverage['no_known_website'] + coverage['unresolved'] == 4


def test_ambiguous_exact_rows_are_unresolved():
    roster = [{'municipality_id': '1', 'name': 'Biratnagar Metropolitan City', 'district': 'Morang'}]
    rows = [
        {'name': roster[0]['name'], 'district': roster[0]['district'], 'website_url': 'https://one.example.np'},
        {'name': roster[0]['name'], 'district': roster[0]['district'], 'website_url': 'https://two.example.np'},
    ]
    item = map_roster(roster, rows, SOURCE)[0]
    assert item['status'] == 'unresolved'
    assert item['candidate_count'] == 2
    assert item['website_url'] == ''
    assert item['mapping_method'] == 'ambiguous_exact_match'


def test_parser_rejects_unrecognized_directory_table():
    with pytest.raises(ValueError, match='No directory table'):
        parse_directory_html(
            '<table><tr><th>Foo</th><th>Bar</th></tr><tr><td>a</td><td>b</td></tr></table>',
            SOURCE,
        )


def test_name_only_match_requires_missing_roster_district_and_unique_directory_name():
    roster = [{'municipality_id': 'x', 'name': 'Biratnagar Metropolitan City'}]
    rows = [{'name': 'Biratnagar Metropolitan City', 'district': 'Morang', 'website_url': 'https://biratnagarmun.gov.np'}]
    item = map_roster(roster, rows, SOURCE)[0]
    assert item['status'] == 'mapped'
    assert item['mapping_confidence'] == 'medium'
    assert item['mapping_method'] == 'unique_exact_name'
