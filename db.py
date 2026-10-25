"""db.py - the SQLite persistence layer (part of the object-oriented side of the app)."""
import pathlib
import sqlite3
from datetime import date, datetime
from typing import Any, List, Optional, Sequence, Tuple

from habit import Break, Build, Habit

# Resolved next to this file so the app works from any working directory.
DB_PATH = pathlib.Path(__file__).resolve().parent / "habits.db"

# Module-level connection and cursor (tests swap these for an in-memory database).
conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_keys = ON;")  # deleting a habit also deletes its completions and urge logs


class DatabaseError(Exception):
    """A database write failed; the message is short enough to show to the user."""


def _write(query: str, values: Sequence[Any] = ()) -> int:
    """Run one INSERT/UPDATE/DELETE and commit; roll back and raise DatabaseError on failure."""
    try:
        cursor.execute(query, values)
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error as exc:
        _rollback()
        raise DatabaseError("Could not save your changes to the database ({}).".format(exc)) from exc


def _rollback() -> None:
    """Roll back the open transaction, ignoring a connection that is already unusable."""
    try:
        conn.rollback()
    except sqlite3.Error:
        pass


def init_db() -> None:
    """Create the habits, completions and urge_logs tables if they do not exist yet (and upgrade old ones)."""
    create_table_queries = """
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            creation_date TEXT,
            periodicity TEXT,
            time_period TEXT,
            longest_streak INTEGER,
            type TEXT NOT NULL,
            duration INTEGER,
            stop_condition TEXT,
            micro_action TEXT,
            total_micro_attempts INTEGER,
            successful_micro_actions INTEGER,
            replacement TEXT,
            total_urges_logged INTEGER,
            successful_replacements INTEGER
        );

        CREATE TABLE IF NOT EXISTS completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER,
            completion_date TEXT,
            completed_at TEXT,
            FOREIGN KEY (habit_id) REFERENCES habits (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS urge_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER,
            logged_at TEXT,
            replaced INTEGER,
            FOREIGN KEY (habit_id) REFERENCES habits (id) ON DELETE CASCADE
        );
    """
    try:
        cursor.executescript(create_table_queries)
        _add_missing_columns()
        conn.commit()
    except sqlite3.Error as exc:
        _rollback()
        raise DatabaseError("Could not set up the database ({}).".format(exc)) from exc


def _add_missing_columns() -> None:
    """Upgrade a database made by an older version: add completions.completed_at if it is missing."""
    columns = [row[1] for row in cursor.execute("PRAGMA table_info(completions)").fetchall()]
    if "completed_at" not in columns:
        cursor.execute("ALTER TABLE completions ADD COLUMN completed_at TEXT")


def _name_exists(name: str) -> bool:
    """Return True if a habit with this name exists (case-insensitive)."""
    cursor.execute("SELECT 1 FROM habits WHERE name COLLATE NOCASE = ?;", (name,))
    return cursor.fetchone() is not None


def add_habit(habit: Habit) -> None:
    """Insert a Build or Break habit, set habit.id, and reject duplicate names (case-insensitive)."""
    if _name_exists(habit.name):
        raise DatabaseError("A habit named '{}' already exists.".format(habit.name))

    if isinstance(habit, Build):
        query = """INSERT INTO habits (name, creation_date, periodicity, time_period, longest_streak, type,
                                       duration, stop_condition, micro_action, total_micro_attempts,
                                       successful_micro_actions, replacement, total_urges_logged,
                                       successful_replacements)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)"""
        values: Tuple[Any, ...] = (
            habit.name, habit.creation_date.isoformat(), habit.periodicity.value,
            habit.time_period.value, habit.get_longest_streak(), "build", habit.duration,
            habit.stop_condition, habit.micro_action, habit.total_micro_attempts,
            habit.successful_micro_actions
        )
    elif isinstance(habit, Break):
        query = """INSERT INTO habits (name, creation_date, periodicity, time_period, longest_streak, type,
                                       duration, stop_condition, micro_action, total_micro_attempts,
                                       successful_micro_actions, replacement, total_urges_logged,
                                       successful_replacements)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, ?)"""
        values = (
            habit.name, habit.creation_date.isoformat(), habit.periodicity.value,
            habit.time_period.value, habit.get_longest_streak(), "break", habit.replacement,
            habit.total_urges_logged, habit.successful_replacements
        )
    else:
        raise TypeError("Unsupported habit type: {}".format(type(habit).__name__))

    habit.id = _write(query, values)


def add_completion(habit_id: int, completion_date: date, completed_at: Optional[datetime] = None) -> bool:
    """Record a completion with its date and time; idempotent (one row per habit per day).

    ``completed_at`` is the exact moment it was done (stored as an ISO datetime to the second).
    Returns True if a row was added, False if that day was already recorded.
    """
    try:
        cursor.execute("SELECT 1 FROM completions WHERE habit_id = ? AND completion_date = ?",
                       (habit_id, completion_date.isoformat()))
        if cursor.fetchone():
            return False
    except sqlite3.Error as exc:
        raise DatabaseError("Could not read the database ({}).".format(exc)) from exc
    stamp = completed_at.isoformat(timespec="seconds") if completed_at is not None else None
    _write("INSERT INTO completions (habit_id, completion_date, completed_at) VALUES (?, ?, ?)",
           (habit_id, completion_date.isoformat(), stamp))
    return True


def remove_completion(habit_id: int, completion_date: date) -> bool:
    """Delete the completion row for exactly one habit and day; True if a row was removed."""
    try:
        cursor.execute("DELETE FROM completions WHERE habit_id = ? AND completion_date = ?",
                       (habit_id, completion_date.isoformat()))
        removed = cursor.rowcount > 0
        conn.commit()
        return removed
    except sqlite3.Error as exc:
        _rollback()
        raise DatabaseError("Could not save your changes to the database ({}).".format(exc)) from exc


def update_habit(habit: Habit) -> None:
    """Save a habit's derived longest streak and its Build/Break counters."""
    if isinstance(habit, Build):
        query = "UPDATE habits SET longest_streak=?, total_micro_attempts=?, successful_micro_actions=? WHERE id=?"
        values: Tuple[Any, ...] = (habit.get_longest_streak(), habit.total_micro_attempts,
                                   habit.successful_micro_actions, habit.id)
    elif isinstance(habit, Break):
        query = "UPDATE habits SET longest_streak=?, total_urges_logged=?, successful_replacements=? WHERE id=?"
        values = (habit.get_longest_streak(), habit.total_urges_logged,
                  habit.successful_replacements, habit.id)
    else:
        raise TypeError("Unsupported habit type: {}".format(type(habit).__name__))
    _write(query, values)


def get_all_habits() -> List[tuple]:
    """Return every raw row of the habits table, oldest first."""
    cursor.execute("SELECT * FROM habits ORDER BY id ASC;")
    return cursor.fetchall()


def get_habit(habit_id: int) -> Optional[tuple]:
    """Return the raw habits row with this id, or None."""
    cursor.execute("SELECT * FROM habits WHERE id = ?;", (habit_id,))
    return cursor.fetchone()


def get_completions_for_habit(habit_id: int) -> List[tuple]:
    """Return a habit's completions as (completion_date, completed_at) rows, oldest first."""
    cursor.execute("SELECT completion_date, completed_at FROM completions WHERE habit_id = ? "
                   "ORDER BY completion_date ASC;", (habit_id,))
    return cursor.fetchall()


def delete_habit(habit_id: int) -> None:
    """Delete a habit; its completions and urge logs are removed by ON DELETE CASCADE."""
    _write("DELETE FROM habits WHERE id = ?;", (habit_id,))


def add_urge(habit_id: int, logged_at: date, replaced: int) -> None:
    """Record one urge log row (replaced is 1 or 0)."""
    _write("INSERT INTO urge_logs (habit_id, logged_at, replaced) VALUES (?, ?, ?)",
           (habit_id, logged_at.isoformat(), replaced))


def get_urges_for_habit(habit_id: int) -> List[tuple]:
    """Return a habit's urge logs as (logged_at, replaced) rows, in chronological order."""
    cursor.execute("SELECT logged_at, replaced FROM urge_logs WHERE habit_id = ? ORDER BY logged_at ASC;",
                   (habit_id,))
    return cursor.fetchall()


# ==========================================
# ROW -> OBJECT BRIDGE
# ==========================================

def _row_to_habit(row: tuple) -> Optional[Habit]:
    """Turn one raw habits row (plus its completions and urge logs) into a Build or Break object."""
    habit_id = row[0]
    habit_type = row[6]  # "build" or "break"
    completions = get_completions_for_habit(habit_id)

    habit_dict = {
        "id": habit_id,
        "name": row[1],
        "creation_date": row[2],
        "periodicity": row[3],
        "time_period": row[4],
        "longest_streak": row[5],
        "duration": row[7],
        "stop_condition": row[8],
        "micro_action": row[9],
        "total_micro_attempts": row[10],
        "successful_micro_actions": row[11],
        "replacement": row[12],
        "total_urges_logged": row[13],
        "successful_replacements": row[14],
        "completion_dates": [c[0] for c in completions],
        "completed_at": {c[0]: c[1] for c in completions if c[1]},
    }

    if habit_type == "build":
        return Build.from_dict(habit_dict)
    if habit_type == "break":
        habit_dict["urge_logs"] = [{"logged_at": u[0], "replaced": u[1]}
                                   for u in get_urges_for_habit(habit_id)]
        return Break.from_dict(habit_dict)
    return None


def get_habit_by_name(name: str) -> Optional[Habit]:
    """Return the habit with this name (case-insensitive) as an object, or None."""
    cursor.execute("SELECT * FROM habits WHERE name COLLATE NOCASE = ?;", (name,))
    row = cursor.fetchone()
    return _row_to_habit(row) if row else None


def load_habits_from_db() -> List[Habit]:
    """Return every stored habit as a live Build/Break object."""
    habits = (_row_to_habit(row) for row in get_all_habits())
    return [h for h in habits if h is not None]
