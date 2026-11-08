import json
from datetime import datetime, timezone

import pytest

from govweb import tls_audit


def test_select_sample_is_deterministic_sorted_and_unique():
    hostnames = [
        'z.gov.np', 'a.gov.np', 'b.gov.np', 'a.gov.np',
        '*.ignored.gov.np', 'invalid/name.gov.np', 'c.gov.np',
    ]
    assert tls_audit.select_sample(hostnames, 3) == [
        'a.gov.np', 'b.gov.np', 'c.gov.np'
    ]
    assert tls_audit.select_sample(list(reversed(hostnames)), 3) == [
        'a.gov.np', 'b.gov.np', 'c.gov.np'
    ]


def test_select_sample_rejects_invalid_size_and_empty_inventory():
    with pytest.raises(ValueError):
        tls_audit.select_sample(['a.gov.np'], 0)
    with pytest.raises(ValueError):
        tls_audit.select_sample([], 20)


@pytest.mark.parametrize('hostname', [
    'example.gov.np', 'portal.example.gov.np', 'xn--example-9d0b.gov.np'
])
def test_valid_hostname_accepts_dns_names(hostname):
    assert tls_audit.valid_hostname(hostname)


@pytest.mark.parametrize('hostname', [
    '', '-bad.gov.np', 'bad-.gov.np', 'bad/name.gov.np',
    'bad..gov.np', 'bad:443.gov.np', '*.gov.np',
])
def test_valid_hostname_rejects_invalid_names(hostname):
    assert not tls_audit.valid_hostname(hostname)


def test_discovered_hostnames_falls_back_to_real_ct_cache(tmp_path):
    mapping = tmp_path / 'mapping.json'
    cache = tmp_path / 'crtsh.json'
    mapping.write_text(json.dumps({'mappings': [
        {'municipality_id': '1', 'domains': []}
    ]}), encoding='utf-8')
    cache.write_text(json.dumps([
        {'name_value': '*.alpha.gov.np\nbeta.gov.np'},
        {'common_name': 'alpha.gov.np'},
        {'name_value': 'not-gov.example.com\ninvalid/name.gov.np'},
    ]), encoding='utf-8')
    assert tls_audit.discovered_hostnames(mapping, cache) == [
        'alpha.gov.np', 'beta.gov.np'
    ]


def test_discovered_hostnames_prefers_actual_mapping_domains(tmp_path):
    mapping = tmp_path / 'mapping.json'
    cache = tmp_path / 'crtsh.json'
    mapping.write_text(json.dumps({'mappings': [
        {'domains': ['z.gov.np', 'a.gov.np', 'a.gov.np']}
    ]}), encoding='utf-8')
    cache.write_text(json.dumps([
        {'name_value': 'other.gov.np'}
    ]), encoding='utf-8')
    assert tls_audit.discovered_hostnames(mapping, cache) == [
        'a.gov.np', 'z.gov.np'
    ]


def test_create_sample_writes_twenty_or_fewer_real_names(tmp_path):
    mapping = tmp_path / 'mapping.json'
    cache = tmp_path / 'crtsh.json'
    output = tmp_path / 'sample.json'
    records = [{'name_value': f'host{i:02d}.gov.np'} for i in range(25)]
    mapping.write_text(json.dumps({'mappings': []}), encoding='utf-8')
    cache.write_text(json.dumps(records), encoding='utf-8')

    document = tls_audit.create_sample(output, mapping, cache, 20)
    saved = json.loads(output.read_text(encoding='utf-8'))
    assert document == saved
    assert saved['inventory_count'] == 25
    assert saved['sample_count'] == 20
    assert saved['hostnames'] == [f'host{i:02d}.gov.np' for i in range(20)]
    assert saved['selection_policy'] == (
        'lexicographically first unique normalized discovered hostnames'
    )


def test_certificate_validity_checks_dates_and_hostname():
    certificate = {
        'notBefore': 'Jan 01 00:00:00 2020 GMT',
        'notAfter': 'Jan 01 00:00:00 2030 GMT',
        'subjectAltName': (('DNS', 'example.gov.np'),),
    }
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid, reasons = tls_audit.certificate_validity(
        certificate, 'example.gov.np', now
    )
    assert valid is True
    assert reasons == []

    valid, reasons = tls_audit.certificate_validity(
        certificate, 'other.gov.np', now
    )
    assert valid is False
    assert 'hostname identity mismatch' in reasons


def test_certificate_validity_detects_expired_certificate():
    certificate = {
        'notBefore': 'Jan 01 00:00:00 2010 GMT',
        'notAfter': 'Jan 01 00:00:00 2020 GMT',
        'subjectAltName': (('DNS', 'example.gov.np'),),
    }
    valid, reasons = tls_audit.certificate_validity(
        certificate,
        'example.gov.np',
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert valid is False
    assert 'certificate expired' in reasons


def test_observe_hostname_records_tls_error_without_network(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('fixture connection failure')

    monkeypatch.setattr(tls_audit.socket, 'create_connection', fail)
    result = tls_audit.observe_hostname('example.gov.np')
    assert result['hostname'] == 'example.gov.np'
    assert result['observation_type'] == 'tls'
    assert result['status'] == 'error'
    assert result['validity'] is False
    assert result['issuer'] is None
    assert result['expiration'] is None
    assert result['sans'] == []
    assert result['evidence']['method'] == 'passive TLS handshake'
    assert 'fixture connection failure' in result['error']


def test_collect_hostnames_uses_cache_and_writes_structured_dataset(tmp_path, monkeypatch):
    cache_dir = tmp_path / 'cache'
    output = tmp_path / 'observations.json'
    calls = []

    def fake_observe(hostname, timeout=10):
        calls.append(hostname)
        return {
            'hostname': hostname,
            'observation_type': 'tls',
            'observed_at': '2026-01-01T00:00:00+00:00',
            'status': 'error',
            'validity': False,
            'issuer': None,
            'subject': None,
            'expiration': None,
            'valid_from': None,
            'sans': [],
            'protocol': None,
            'cipher': None,
            'certificate_sha256': None,
            'evidence': {'method': 'passive TLS handshake'},
            'error': 'fixture failure',
        }

    monkeypatch.setattr(tls_audit, 'observe_hostname', fake_observe)
    first = tls_audit.collect_hostnames(
        ['b.gov.np', 'a.gov.np'], output, cache_dir,
        delay_seconds=0,
    )
    assert calls == ['a.gov.np', 'b.gov.np']
    assert first['requested_hostname_count'] == 2
    assert first['completed_count'] == 2
    assert [item['hostname'] for item in first['observations']] == [
        'a.gov.np', 'b.gov.np'
    ]

    calls.clear()
    second = tls_audit.collect_hostnames(
        ['a.gov.np', 'b.gov.np'], output, cache_dir,
        delay_seconds=0,
    )
    assert calls == []
    assert second['observations'] == first['observations']


def test_collect_hostnames_rejects_empty_input(tmp_path):
    with pytest.raises(ValueError):
        tls_audit.collect_hostnames(
            [], tmp_path / 'out.json', tmp_path / 'cache'
        )


def test_collect_sample_reads_sample_file(tmp_path, monkeypatch):
    sample = tmp_path / 'sample.json'
    output = tmp_path / 'output.json'
    cache = tmp_path / 'cache'
    sample.write_text(json.dumps({'hostnames': ['example.gov.np']}), encoding='utf-8')
    expected = {'schema_version': 1, 'observations': []}

    def fake_collect(hostnames, **kwargs):
        assert hostnames == ['example.gov.np']
        assert kwargs['output'] == output
        return expected

    monkeypatch.setattr(tls_audit, 'collect_hostnames', fake_collect)
    assert tls_audit.collect_sample(
        sample, output=output, cache_dir=cache
    ) == expected


def test_collect_sample_rejects_invalid_sample(tmp_path):
    sample = tmp_path / 'sample.json'
    sample.write_text(json.dumps({'hostnames': 'example.gov.np'}), encoding='utf-8')
    with pytest.raises(ValueError):
        tls_audit.collect_sample(sample)
