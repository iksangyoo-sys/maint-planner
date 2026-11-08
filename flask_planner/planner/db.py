"""SQLite 저장소 (표준 라이브러리 sqlite3)."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    manager TEXT DEFAULT '',
    description TEXT DEFAULT '',
    start_date TEXT NOT NULL,
    status_date TEXT,
    skip_weekends INTEGER DEFAULT 1,
    holidays TEXT DEFAULT '',
    baseline_saved_at TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS task (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    row INTEGER NOT NULL,
    level INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL DEFAULT '',
    duration REAL NOT NULL DEFAULT 1,
    constraint_start TEXT,
    actual_start TEXT,
    actual_finish TEXT,
    pct REAL DEFAULT 0,
    notes TEXT DEFAULT '',
    baseline_start TEXT,
    baseline_finish TEXT,
    baseline_duration REAL
);
CREATE TABLE IF NOT EXISTS dependency (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    pred_id INTEGER NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    succ_id INTEGER NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    type TEXT NOT NULL DEFAULT 'FS',
    lag REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS resource (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT '인력',
    grp TEXT DEFAULT '',
    max_units REAL DEFAULT 100,
    rate REAL DEFAULT 0,
    email TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS assignment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    resource_id INTEGER NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
    units REAL NOT NULL DEFAULT 100
);
CREATE TABLE IF NOT EXISTS report (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    source TEXT,
    notes TEXT DEFAULT '',
    content TEXT NOT NULL
);
"""


def db_path() -> str:
    path = current_app.config["DATABASE"]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(db_path())
    return g.db


def close_db(_=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_db(app) -> None:
    with app.app_context():
        con = connect(db_path())
        con.executescript(SCHEMA)
        con.commit()
        con.close()
    app.teardown_appcontext(close_db)


def query(sql: str, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql: str, args=()) -> int:
    con = get_db()
    cur = con.execute(sql, args)
    con.commit()
    return cur.lastrowid
