"""SQLite round-trip for the redbook persistence layer."""

from redbook_parser.db import read_rows, write_db
from redbook_parser.model import BudgetRow


def test_section_survives_sqlite_round_trip(tmp_path):
    row = BudgetRow(page=1, code="21112", section="101",
                    description="पारिश्रमिक", total=123.0)
    db = tmp_path / "nested" / "out.db"
    write_db([row], ["page one"], str(db))

    [loaded] = read_rows(str(db))
    assert loaded.section == "101"
    assert loaded.code == "21112"
    assert loaded.total == 123.0
