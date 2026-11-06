"""SQLite 저장소: 스키마 정의와 기본 CRUD 도우미."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "maint.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    site TEXT DEFAULT '',
    manager TEXT DEFAULT '',
    description TEXT DEFAULT '',
    start_date TEXT NOT NULL,
    status_date TEXT,
    skip_weekends INTEGER DEFAULT 1,
    holidays TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    discipline TEXT DEFAULT '전기',
    location TEXT DEFAULT '',
    criticality TEXT DEFAULT 'B',
    maker TEXT DEFAULT '',
    install_date TEXT,
    status TEXT DEFAULT '가동',
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    rtype TEXT DEFAULT '인력',
    skill TEXT DEFAULT '',
    max_units REAL DEFAULT 1.0,
    cost_per_day REAL DEFAULT 0,
    phone TEXT DEFAULT '',
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    wbs TEXT NOT NULL,
    name TEXT NOT NULL,
    duration REAL DEFAULT 1,
    discipline TEXT DEFAULT '공통',
    equipment_id INTEGER REFERENCES equipment(id) ON DELETE SET NULL,
    constraint_start TEXT,
    percent_complete REAL DEFAULT 0,
    actual_start TEXT,
    actual_finish TEXT,
    baseline_start TEXT,
    baseline_finish TEXT,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    pred_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    succ_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    dep_type TEXT DEFAULT 'FS',
    lag REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    resource_id INTEGER NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    units REAL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS pm_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    pm_type TEXT DEFAULT '예방정비(PM)',
    interval_days INTEGER DEFAULT 30,
    last_done TEXT,
    est_hours REAL DEFAULT 2,
    resource_id INTEGER REFERENCES resources(id) ON DELETE SET NULL,
    checklist TEXT DEFAULT '',
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS work_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wo_no TEXT NOT NULL,
    title TEXT NOT NULL,
    equipment_id INTEGER REFERENCES equipment(id) ON DELETE SET NULL,
    wo_type TEXT DEFAULT '예방정비(PM)',
    priority TEXT DEFAULT '보통',
    status TEXT DEFAULT '요청',
    requested_date TEXT,
    due_date TEXT,
    completed_date TEXT,
    resource_id INTEGER REFERENCES resources(id) ON DELETE SET NULL,
    est_hours REAL DEFAULT 0,
    actual_hours REAL DEFAULT 0,
    pm_plan_id INTEGER REFERENCES pm_plans(id) ON DELETE SET NULL,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    description TEXT DEFAULT '',
    result TEXT DEFAULT ''
);
"""

# 테이블별 편집 가능한 컬럼 (id 제외)
TABLE_COLUMNS: dict[str, list[str]] = {}

# 백업/복원 순서 (외래키 의존 순서)
TABLE_ORDER = [
    "projects", "equipment", "resources", "tasks", "dependencies",
    "assignments", "pm_plans", "work_orders",
]


def db_path() -> Path:
    return Path(os.environ.get("MAINT_DB", DEFAULT_DB))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
    for t in TABLE_ORDER:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({t})")]
        TABLE_COLUMNS[t] = [c for c in cols if c != "id"]


def is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0


def query_df(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=list(params))


def table_df(conn: sqlite3.Connection, table: str, where: str = "", params: Iterable[Any] = ()) -> pd.DataFrame:
    sql = f"SELECT * FROM {table}"
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY id"
    return query_df(conn, sql, params)


def insert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> int:
    cols = [c for c in row if c in TABLE_COLUMNS[table]]
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    cur = conn.execute(sql, [_clean(row[c]) for c in cols])
    conn.commit()
    return int(cur.lastrowid)


def update(conn: sqlite3.Connection, table: str, row_id: int, row: dict[str, Any]) -> None:
    cols = [c for c in row if c in TABLE_COLUMNS[table]]
    if not cols:
        return
    sql = f"UPDATE {table} SET {', '.join(c + '=?' for c in cols)} WHERE id=?"
    conn.execute(sql, [_clean(row[c]) for c in cols] + [int(row_id)])
    conn.commit()


def delete(conn: sqlite3.Connection, table: str, row_id: int) -> None:
    conn.execute(f"DELETE FROM {table} WHERE id=?", [int(row_id)])
    conn.commit()


def _clean(v: Any) -> Any:
    """pandas/numpy 값을 SQLite가 받는 파이썬 기본형으로 변환."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "isoformat"):
        # date / datetime / Timestamp -> 'YYYY-MM-DD'
        return v.isoformat()[:10]
    if hasattr(v, "item"):
        return v.item()
    return v


def sync_table(
    conn: sqlite3.Connection,
    table: str,
    edited: pd.DataFrame,
    original_ids: Iterable[int],
    fixed: dict[str, Any] | None = None,
) -> tuple[int, int, int]:
    """data_editor 결과를 DB에 반영. (추가, 수정, 삭제) 건수를 반환."""
    fixed = fixed or {}
    original_ids = {int(i) for i in original_ids}
    kept: set[int] = set()
    n_add = n_upd = 0
    for _, r in edited.iterrows():
        row = {c: r[c] for c in edited.columns if c in TABLE_COLUMNS[table]}
        row.update(fixed)
        rid = r.get("id")
        if rid is not None and not pd.isna(rid) and int(rid) in original_ids:
            update(conn, table, int(rid), row)
            kept.add(int(rid))
            n_upd += 1
        else:
            insert(conn, table, row)
            n_add += 1
    removed = original_ids - kept
    for rid in removed:
        delete(conn, table, rid)
    return n_add, n_upd, len(removed)


# ---------- 백업 / 복원 ----------

def export_json(conn: sqlite3.Connection) -> str:
    data = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in TABLE_ORDER}
    return json.dumps({"app": "maint-planner", "version": 1, "data": data}, ensure_ascii=False, indent=2)


def import_json(conn: sqlite3.Connection, text: str) -> None:
    payload = json.loads(text)
    data = payload.get("data", payload)
    clear_all(conn)
    for t in TABLE_ORDER:
        for row in data.get(t, []):
            cols = [c for c in row if c == "id" or c in TABLE_COLUMNS[t]]
            conn.execute(
                f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [row[c] for c in cols],
            )
    conn.commit()


def clear_all(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    for t in reversed(TABLE_ORDER):
        conn.execute(f"DELETE FROM {t}")
    try:
        conn.execute("DELETE FROM sqlite_sequence")
    except sqlite3.OperationalError:
        pass
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
