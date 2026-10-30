"""SQLite persistence for extracted rows (v3 `budget` + `pages` schema)."""

import os
import sqlite3

from .model import AMOUNT_FIELDS, CODE_FIELDS, BudgetRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS budget (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page INTEGER,
    code TEXT,
    section TEXT,
    budget_table TEXT,
    description TEXT,
    source TEXT,
    nikasa_vidhi TEXT,
    year_actual REAL,
    year_revised REAL,
    year_estimate REAL,
    total REAL,
    current_exp REAL,
    capital_exp REAL,
    financial REAL,
    baideshik_anudan REAL,
    baideshik_rin REAL,
    prathamikta_sanket TEXT,
    raniti_sanket TEXT,
    laigik_sanket TEXT,
    is_total INTEGER DEFAULT 0,
    row_type TEXT DEFAULT 'budget'
);

CREATE TABLE IF NOT EXISTS pages (
    page INTEGER PRIMARY KEY,
    content TEXT
);
"""


def write_db(rows: list[BudgetRow], page_texts: list[str] | None,
             db_path: str) -> None:
    """Write rows (and optional per-page raw text) to a fresh SQLite DB."""
    if os.path.exists(db_path):
        os.remove(db_path)
    parent = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA)

    for row in rows:
        cur.execute(
            f"""
            INSERT INTO budget (
                page, code, section, budget_table, description, source, nikasa_vidhi,
                {", ".join(AMOUNT_FIELDS)},
                {", ".join(CODE_FIELDS)},
                is_total, row_type
            ) VALUES ({", ".join(["?"] * (7 + len(AMOUNT_FIELDS) + len(CODE_FIELDS) + 2))})
            """,
            (row.page, row.code, row.section, row.budget_table,
             row.description, row.source, row.nikasa_vidhi,
             *(row.amount(c) for c in AMOUNT_FIELDS),
             *(getattr(row, c) for c in CODE_FIELDS),
             1 if row.is_total else 0, row.row_type),
        )

    if page_texts:
        for pno, text in enumerate(page_texts, start=1):
            cur.execute("INSERT OR REPLACE INTO pages (page, content) VALUES (?, ?)",
                        (pno, text))

    conn.commit()
    conn.close()


def read_rows(db_path: str) -> list[BudgetRow]:
    """Load all budget rows from a v3-schema DB."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    columns = {r[1] for r in cur.execute("PRAGMA table_info(budget)")}
    if "budget_table" not in columns:
        cur.execute("ALTER TABLE budget ADD COLUMN budget_table TEXT DEFAULT ''")
        conn.commit()
    cur.execute(
        f"""
        SELECT page, code, section, budget_table,
               description, source, nikasa_vidhi,
               {", ".join(AMOUNT_FIELDS)},
               {", ".join(CODE_FIELDS)},
               is_total, row_type
        FROM budget ORDER BY id
        """
    )
    rows = []
    for r in cur.fetchall():
        row = BudgetRow(page=r["page"], code=r["code"], section=r["section"] or "",
                        budget_table=r["budget_table"] or "",
                        description=r["description"],
                        source=r["source"], nikasa_vidhi=r["nikasa_vidhi"],
                        is_total=bool(r["is_total"]), row_type=r["row_type"])
        for c in AMOUNT_FIELDS:
            setattr(row, c, float(r[c] or 0))
        for c in CODE_FIELDS:
            setattr(row, c, r[c] or "")
        rows.append(row)
    conn.close()
    return rows
