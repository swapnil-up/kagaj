"""Tests for redbook_parser.pipeline — section inference and extract_pdf."""

from redbook_parser.model import BudgetRow
from redbook_parser.pipeline import infer_sections


def row(code="", page=17, section="", **kw):
    r = BudgetRow(code=code, page=page, section=section, **kw)
    return r


class TestInferSections:
    def test_ministry_code_sets_section(self):
        rows = [
            row(code="101", description="राष्ट्रपति"),
            row(code="10100", description="राष्ट्रपति"),
            row(code="21112", description="पारिश्रमिक"),
        ]
        infer_sections(rows)
        assert rows[0].section == "101"
        assert rows[1].section == "101"
        assert rows[2].section == "101"

    def test_multiple_ministries(self):
        rows = [
            row(code="101", description="राष्ट्रपति"),
            row(code="21112", description="पारिश्रमिक"),
            row(code="102", description="उपराष्ट्रपति"),
            row(code="21112", description="पारिश्रमिक"),
        ]
        infer_sections(rows)
        assert rows[0].section == "101"
        assert rows[1].section == "101"
        assert rows[2].section == "102"
        assert rows[3].section == "102"

    def test_headings_get_no_section(self):
        rows = [
            row(code="", description="शीर्षक", row_type="heading"),
            row(code="", description="स्रोत", row_type="heading"),
            row(code="101", description="राष्ट्रपति"),
        ]
        infer_sections(rows)
        assert rows[0].section == ""
        assert rows[1].section == ""
        assert rows[2].section == "101"

    def test_heading_after_ministry_gets_previous_section(self):
        rows = [
            row(code="101", description="राष्ट्रपति"),
            row(code="", description="शीर्षक", row_type="heading"),
            row(code="21112", description="पारिश्रमिक"),
        ]
        infer_sections(rows)
        assert rows[0].section == "101"
        assert rows[1].section == "101"
        assert rows[2].section == "101"

    def test_total_row_gets_section(self):
        rows = [
            row(code="101", description="राष्ट्रपति"),
            row(code="21112", description="पारिश्रमिक"),
            row(is_total=True, total=1000),
        ]
        infer_sections(rows)
        assert rows[0].section == "101"
        assert rows[1].section == "101"
        assert rows[2].section == "101"

    def test_empty_rows_before_first_ministry(self):
        rows = [
            row(code="", description="शीर्षक"),
            row(code="", description="स्रोत"),
            row(code="101", description="राष्ट्रपति"),
        ]
        infer_sections(rows)
        assert rows[0].section == ""
        assert rows[1].section == ""
        assert rows[2].section == "101"

    def test_cross_page_section_inheritance(self):
        """Sections persist across pages — ministry 101 on page 17
        still applies to rows on page 18 until a new ministry appears."""
        rows = [
            row(code="101", page=17, description="राष्ट्रपति"),
            row(code="21112", page=18, description="पारिश्रमिक"),
            row(code="102", page=19, description="उपराष्ट्रपति"),
        ]
        infer_sections(rows)
        assert rows[0].section == "101"
        assert rows[1].section == "101"
        assert rows[2].section == "102"

    def test_four_digit_code_does_not_set_section(self):
        """4-digit codes (years like 2081) should not be treated as ministry codes."""
        rows = [
            row(code="101", description="राष्ट्रपति"),
            row(code="2081", description="वर्ष"),
            row(code="21112", description="पारिश्रमिक"),
        ]
        infer_sections(rows)
        assert rows[0].section == "101"
        assert rows[1].section == "101"  # inherits, not new section
        assert rows[2].section == "101"

    def test_five_digit_code_does_not_set_section(self):
        """5-digit codes starting with 2 (line items) should not set section."""
        rows = [
            row(code="101", description="राष्ट्रपति"),
            row(code="21112", description="पारिश्रमिक"),
            row(code="22211", description="इन्धन"),
        ]
        infer_sections(rows)
        assert rows[0].section == "101"
        assert rows[1].section == "101"
        assert rows[2].section == "101"


class TestTableInference:
    def test_section_resets_when_table_changes(self):
        rows = [
            row(code="101", page=13, description="राष्ट्रपति"),
            row(code="21112", page=17, description="पारिश्रमिक"),
            row(code="101", page=36, description="राष्ट्रपति"),
            row(code="21112", page=73, description="पारिश्रमिक"),
        ]
        for r in rows[:2]:
            r.budget_table = "expenditure"
        for r in rows[2:]:
            r.budget_table = "allocation"
        infer_sections(rows)
        assert [r.section for r in rows] == ["101", "101", "101", "101"]
