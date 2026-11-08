from __future__ import annotations

import json
from pathlib import Path

import pytest

from govweb.ct_discovery import (
    build_outputs,
    extract_hostnames,
    match_hostnames,
    normalize_hostname,
    normalize_name,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / 'fixtures' / 'govweb' / 'crtsh_sample.json'


@pytest.fixture
def roster():
    return [
        {
            'province_id': '1', 'province': 'Province One',
            'district_id': '11', 'district': 'District One',
            'municipality_id': '101', 'name': 'Rural Municipality',
            'normalized_name': 'rural municipality',
        },
        {
            'province_id': '1', 'province': 'Province One',
            'district_id': '22', 'district': 'District Two',
            'municipality_id': '202', 'name': 'Township',
            'normalized_name': 'township',
        },
        {
            'province_id': '1', 'province': 'Province One',
            'district_id': '33', 'district': 'District Three',
            'municipality_id': '303', 'name': 'Rural Municipality',
            'normalized_name': 'rural municipality',
        },
        {
            'province_id': '1', 'province': 'Province One',
            'district_id': '', 'district': '',
            'municipality_id': '404', 'name': 'Unique Local Level',
            'normalized_name': 'unique local level',
        },
    ]


def test_normalization_collapses_whitespace_and_casefolds():
    assert normalize_name('  RURAL   Municipality ') == 'rural municipality'


def test_hostname_normalization_accepts_gov_np_and_wildcard():
    assert normalize_hostname('*.Township.District-Two.GOV.NP.') == 'township.district-two.gov.np'
    assert normalize_hostname('example.com') is None
    assert normalize_hostname('bad/name.gov.np') is None


def test_extract_hostnames_deduplicates_and_filters():
    records = json.loads(FIXTURE.read_text(encoding='utf-8'))
    names = extract_hostnames(records)
    assert names == [
        'rural-municipality.district-one.gov.np',
        'rural-municipality.district-three.gov.np',
        'township.district-two.gov.np',
        'www.rural-municipality.district-one.gov.np',
        'www.township.district-two.gov.np',
    ]


def test_exact_municipality_and_district_mapping(roster):
    records = json.loads(FIXTURE.read_text(encoding='utf-8'))
    mappings, coverage = match_hostnames(roster, extract_hostnames(records))
    by_id = {item['municipality_id']: item for item in mappings}
    assert by_id['101']['domains'] == ['rural-municipality.district-one.gov.np']
    assert by_id['202']['domains'] == ['township.district-two.gov.np']
    assert by_id['303']['domains'] == ['rural-municipality.district-three.gov.np']
    assert by_id['404']['status'] == 'unresolved'
    assert coverage['mapped_count'] == 3
    assert coverage['unresolved_count'] == 1


def test_same_municipality_name_in_other_district_does_not_cross_match(roster):
    mappings, _ = match_hostnames(roster, ['rural-municipality.district-two.gov.np'])
    assert all(item['status'] == 'unresolved' for item in mappings)


def test_name_only_matching_requires_missing_district_and_unique_name(roster):
    mappings, _ = match_hostnames(roster, ['unique-local-level.gov.np'])
    by_id = {item['municipality_id']: item for item in mappings}
    assert by_id['404']['status'] == 'mapped'
    mappings, _ = match_hostnames(roster, ['rural-municipality.gov.np'])
    assert all(item['status'] == 'unresolved' for item in mappings)


def test_substring_and_fuzzy_names_never_match(roster):
    mappings, _ = match_hostnames(roster, [
        'my-rural-municipality.district-one.gov.np',
        'rural-municipalityx.district-one.gov.np',
        'rural-municipality.district-one-extra.gov.np',
    ])
    assert all(item['status'] == 'unresolved' for item in mappings)


def test_ambiguous_hostname_is_reported_not_mapped():
    roster = [
        {'municipality_id': '1', 'name': 'Same Name', 'district': 'Same District'},
        {'municipality_id': '2', 'name': 'Same Name', 'district': 'Same District'},
    ]
    mappings, coverage = match_hostnames(roster, ['same-name.same-district.gov.np'])
    assert all(item['status'] == 'unresolved' for item in mappings)
    assert coverage['ambiguous_hostname_count'] == 1
    assert coverage['ambiguous_hostnames'][0]['municipality_ids'] == ['1', '2']


def test_build_outputs_contains_provenance_and_hash(roster):
    records = json.loads(FIXTURE.read_text(encoding='utf-8'))
    mapping, coverage = build_outputs(
        roster, records, fetched_at='2026-01-01T00:00:00+00:00', cache_status='fixture'
    )
    assert mapping['source'] == 'crt.sh'
    assert mapping['fetched_at'] == '2026-01-01T00:00:00+00:00'
    assert len(mapping['source_sha256']) == 64
    assert len(mapping['mappings']) == len(roster)
    assert coverage['source_sha256'] == mapping['source_sha256']


def test_invalid_roster_record_is_rejected():
    with pytest.raises(ValueError):
        match_hostnames([{'name': 'Missing ID', 'district': 'D'}], [])


def test_output_has_one_record_per_canonical_municipality(roster):
    records = json.loads(FIXTURE.read_text(encoding='utf-8'))
    mapping, _ = build_outputs(roster, records, fetched_at='2026-01-01T00:00:00Z')
    ids = [item['municipality_id'] for item in mapping['mappings']]
    assert ids == ['101', '202', '303', '404']
    assert len(ids) == len(set(ids))
