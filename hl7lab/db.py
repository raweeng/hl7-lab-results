"""Store lab reports in a SQL database (SQLite)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .lab import LabReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    control_id        TEXT PRIMARY KEY,
    message_type      TEXT NOT NULL,
    hl7_version       TEXT,
    sending_app       TEXT,
    sending_facility  TEXT,
    message_datetime  TEXT,
    received_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patients (
    patient_id   TEXT PRIMARY KEY,
    family_name  TEXT,
    given_name   TEXT,
    dob          TEXT,
    sex          TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    control_id           TEXT NOT NULL REFERENCES messages(control_id),
    patient_id           TEXT NOT NULL REFERENCES patients(patient_id),
    placer_order_number  TEXT,
    filler_order_number  TEXT,
    test_code            TEXT,
    test_name            TEXT,
    observed_at          TEXT,
    status               TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id         INTEGER NOT NULL REFERENCES orders(id),
    set_id           TEXT,
    loinc_code       TEXT,
    test_name        TEXT,
    value            TEXT,
    numeric_value    REAL,
    units            TEXT,
    reference_range  TEXT,
    flag             TEXT NOT NULL,
    flag_source      TEXT NOT NULL,
    status           TEXT
);

CREATE INDEX IF NOT EXISTS idx_results_flag ON results(flag);
CREATE INDEX IF NOT EXISTS idx_orders_patient ON orders(patient_id);
"""


def connect(path: str = "lab.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def store(conn: sqlite3.Connection, report: LabReport) -> bool:
    """Save a report in one transaction. Returns False if it was a duplicate.

    Duplicate detection uses the message control ID (MSH-10), the same way
    interface engines avoid processing a resent message twice.
    """
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                report.control_id,
                report.message_type,
                report.version,
                report.sending_app,
                report.sending_facility,
                report.message_datetime,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        if cur.rowcount == 0:
            return False

        p = report.patient
        conn.execute(
            """INSERT INTO patients VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(patient_id) DO UPDATE SET
                 family_name = excluded.family_name,
                 given_name  = excluded.given_name,
                 dob         = excluded.dob,
                 sex         = excluded.sex""",
            (p.patient_id, p.family_name, p.given_name, p.dob, p.sex),
        )

        for order in report.orders:
            order_id = conn.execute(
                """INSERT INTO orders (control_id, patient_id, placer_order_number,
                       filler_order_number, test_code, test_name, observed_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report.control_id,
                    p.patient_id,
                    order.placer_order_number,
                    order.filler_order_number,
                    order.test_code,
                    order.test_name,
                    order.observed_at,
                    order.status,
                ),
            ).lastrowid
            conn.executemany(
                """INSERT INTO results (order_id, set_id, loinc_code, test_name, value,
                       numeric_value, units, reference_range, flag, flag_source, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        order_id,
                        r.set_id,
                        r.code,
                        r.name,
                        r.value,
                        r.numeric_value,
                        r.units,
                        r.reference_range,
                        r.flag.code if r.flag else "N",
                        r.flag.source if r.flag else "reference-range",
                        r.status,
                    )
                    for r in order.results
                ],
            )
    return True


ABNORMAL_QUERY = """
SELECT p.patient_id,
       p.family_name || ', ' || p.given_name AS patient,
       o.filler_order_number,
       r.test_name,
       r.value,
       r.units,
       r.reference_range,
       r.flag,
       r.flag_source
FROM results r
JOIN orders o   ON o.id = r.order_id
JOIN patients p ON p.patient_id = o.patient_id
WHERE r.flag <> 'N'
ORDER BY CASE WHEN r.flag IN ('HH', 'LL', 'AA') THEN 0 ELSE 1 END,
         p.patient_id, r.test_name
"""


def abnormal_results(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(ABNORMAL_QUERY).fetchall()


def summary(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """SELECT (SELECT COUNT(*) FROM messages) AS messages,
                  (SELECT COUNT(*) FROM patients) AS patients,
                  (SELECT COUNT(*) FROM results)  AS results,
                  (SELECT COUNT(*) FROM results WHERE flag <> 'N') AS abnormal,
                  (SELECT COUNT(*) FROM results WHERE flag IN ('HH','LL','AA')) AS critical"""
    ).fetchone()
    return dict(row)
