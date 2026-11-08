from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import unicodedata


class _DirectoryHTMLParser(HTMLParser):
    """Extract table rows and their cell text and links without network access."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None
        self._anchor_href = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table' and self._table is None:
            self._table = []
        elif self._table is not None and tag == 'tr':
            self._row = []
        elif self._row is not None and tag in ('td', 'th'):
            self._cell = {'text': '', 'hrefs': []}
        elif self._cell is not None and tag == 'a':
            self._anchor_href = attrs.get('href')

    def handle_data(self, data):
        if self._cell is not None:
            self._cell['text'] += data

    def handle_endtag(self, tag):
        if tag == 'a':
            if self._cell is not None and self._anchor_href:
                self._cell['hrefs'].append(self._anchor_href)
            self._anchor_href = None
        elif tag in ('td', 'th') and self._cell is not None:
            self._cell['text'] = ' '.join(self._cell['text'].split())
            self._row.append(self._cell)
            self._cell = None
        elif tag == 'tr' and self._row is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == 'table' and self._table is not None:
            self.tables.append(self._table)
            self._table = None
            self._row = None
            self._cell = None


def normalize_name(value):
    """Normalize Unicode and whitespace without transliteration or fuzzy edits."""
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).split()).casefold()


def _header_key(value):
    return normalize_name(value).replace('_', ' ').replace('-', ' ').strip(' :')


_NAME_HEADERS = {
    'local level', 'local level name', 'local level/municipality',
    'municipality', 'municipality name', 'name',
    'स्थानीय तह', 'स्थानीय तहको नाम', 'पालिका'
}
_DISTRICT_HEADERS = {'district', 'district name', 'जिल्ला', 'जिल्लाको नाम'}
_WEBSITE_HEADERS = {
    'website', 'web site', 'website url', 'url',
    'वेबसाइट', 'वेबसाइट ठेगाना'
}


def parse_directory_html(html, source):
    """Parse the first table with recognized name and district columns."""
    parser = _DirectoryHTMLParser()
    parser.feed(html)
    parser.close()

    for table in parser.tables:
        for header_index, header_cells in enumerate(table):
            headers = [_header_key(cell['text']) for cell in header_cells]
            name_col = next((i for i, h in enumerate(headers) if h in _NAME_HEADERS), None)
            district_col = next((i for i, h in enumerate(headers) if h in _DISTRICT_HEADERS), None)
            website_col = next((i for i, h in enumerate(headers) if h in _WEBSITE_HEADERS), None)
            if name_col is None or district_col is None:
                continue

            result = []
            for cells in table[header_index + 1:]:
                if max(name_col, district_col) >= len(cells):
                    continue
                name = cells[name_col]['text'].strip()
                district = cells[district_col]['text'].strip()
                if not name or not district:
                    continue

                website_url = ''
                if website_col is not None and website_col < len(cells):
                    website_cell = cells[website_col]
                    raw_website = website_cell['hrefs'][0] if website_cell['hrefs'] else website_cell['text'].strip()
                    if raw_website:
                        candidate_url = urljoin(source, raw_website)
                        parsed = urlparse(candidate_url)
                        if parsed.scheme in ('http', 'https') and parsed.hostname:
                            website_url = candidate_url

                result.append({
                    'name': name,
                    'district': district,
                    'website_url': website_url
                })
            return result

    raise ValueError('No directory table with recognized name and district columns')


def _field(record, *keys):
    for key in keys:
        value = record.get(key)
        if value not in (None, ''):
            return value
    return ''


def _domain(url):
    return (urlparse(url).hostname or '').casefold() if url else ''


def map_roster(roster, rows, source):
    """Map roster entries using exact normalized name+district pairs only.

    A name-only match is permitted only when the roster entry has no district
    value and exactly one directory row has that normalized name.
    """
    mappings = []
    for municipality in roster:
        name = _field(municipality, 'name', 'local_level_name', 'municipality_name')
        district = _field(municipality, 'district', 'district_name')
        name_key = normalize_name(name)
        district_key = normalize_name(district)

        if district_key:
            candidates = [
                row for row in rows
                if normalize_name(row.get('name')) == name_key
                and normalize_name(row.get('district')) == district_key
            ]
            method = 'exact_name_and_district'
            confidence = 'high'
        else:
            candidates = [row for row in rows if normalize_name(row.get('name')) == name_key]
            method = 'unique_exact_name'
            confidence = 'medium'

        website_url = ''
        evidence = {
            'candidate_rows': [
                {
                    'name': row.get('name', ''),
                    'district': row.get('district', ''),
                    'website_url': row.get('website_url', '')
                }
                for row in candidates
            ]
        }

        if len(candidates) > 1:
            status = 'unresolved'
            method = 'ambiguous_exact_match'
            confidence = 'none'
        elif not candidates:
            status = 'unresolved'
            method = 'no_exact_match'
            confidence = 'none'
        else:
            website_url = candidates[0].get('website_url') or ''
            status = 'mapped' if website_url else 'no_known_website'

        mappings.append({
            'municipality_id': _field(municipality, 'municipality_id', 'local_level_id', 'id'),
            'province_id': _field(municipality, 'province_id'),
            'province': _field(municipality, 'province', 'province_name'),
            'district_id': _field(municipality, 'district_id'),
            'district': district,
            'name': name,
            'observation_type': 'mofaga_local_contact_directory',
            'source_url': source,
            'status': status,
            'website_url': website_url,
            'domain': _domain(website_url),
            'mapping_method': method,
            'mapping_confidence': confidence,
            'evidence': evidence,
            'candidate_count': len(candidates)
        })

    return mappings


def build_coverage(roster, mappings):
    counts = {'mapped': 0, 'no_known_website': 0, 'unresolved': 0}
    for item in mappings:
        status = item.get('status')
        if status not in counts:
            raise ValueError(f'Unexpected mapping status: {status!r}')
        counts[status] += 1

    total = len(roster)
    accounted_for = sum(counts.values())
    if accounted_for != total or len(mappings) != total:
        raise ValueError('Mapping count must account for every roster entry exactly once')

    return {
        'total_roster_entries': total,
        'mapped': counts['mapped'],
        'no_known_website': counts['no_known_website'],
        'unresolved': counts['unresolved'],
        'accounted_for': accounted_for,
        'mapped_ratio': counts['mapped'] / total if total else 0.0
    }
