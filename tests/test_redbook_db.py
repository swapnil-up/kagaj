"""SQLite round-trip for the redbook persistence layer."""

from redbook_parser.db import read_rows, write_db
from redbook_parser.model import BudgetRow


def test_section_survives_sqlite_round_trip(tmp_path):
    row = BudgetRow(page=1, code="21112", section="101",
                    budget_table="expenditure",
                    description="पारिश्रमिक", total=123.0)
    db = tmp_path / "nested" / "out.db"
    write_db([row], ["page one"], str(db))

    [loaded] = read_rows(str(db))
    assert loaded.section == "101"
    assert loaded.budget_table == "expenditure"
    assert loaded.code == "21112"
    assert loaded.total == 123.0


def test_old_schema_gains_budget_table_on_read(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE budget (
            id INTEGER PRIMARY KEY AUTOINCREMENT, page INTEGER, code TEXT,
            section TEXT, description TEXT, source TEXT, nikasa_vidhi TEXT,
            year_actual REAL, year_revised REAL, year_estimate REAL,
            total REAL, current_exp REAL, capital_exp REAL, financial REAL,
            baideshik_anudan REAL, baideshik_rin REAL,
            prathamikta_sanket TEXT, raniti_sanket TEXT, laigik_sanket TEXT,
            is_total INTEGER DEFAULT 0, row_type TEXT DEFAULT 'budget'
        );
        INSERT INTO budget (page, code, section, total)
        VALUES (1, '21112', '101', 5);
    """)
    conn.commit()
    conn.close()
    [loaded] = read_rows(str(db))
    assert loaded.budget_table == ""
