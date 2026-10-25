import copy
import inspect
import io
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime, time, timedelta

import pytest

import analytics
import db
import habit as habit_mod
import helper as helper_mod
import main as main_mod
from habit import Build, Break, Periodicity, TimePeriod

# The whole suite runs on this frozen "today" (a Wednesday), so no test depends on the real clock.
TODAY = date(2026, 3, 18)
FROZEN_NOW = datetime.combine(TODAY, time(9, 30))  # "now" is 09:30:00 on TODAY in every test


# ==========================================
# FIXTURES: frozen clock + in-memory database
# ==========================================

@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """Freeze 'today' and 'now' for habit.py and main.py so results never depend on the real clock."""
    monkeypatch.setattr(habit_mod, "get_today", lambda: TODAY)
    monkeypatch.setattr(main_mod, "get_today", lambda: TODAY)
    monkeypatch.setattr(habit_mod, "get_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(main_mod, "get_now", lambda: FROZEN_NOW)


@pytest.fixture(autouse=True)
def setup_memory_db():
    """Run every test against an isolated in-memory SQLite database, never the real habits.db."""
    old_conn = db.conn
    old_cursor = db.cursor

    db.conn = sqlite3.connect(":memory:")
    db.cursor = db.conn.cursor()
    db.cursor.execute("PRAGMA foreign_keys = ON;")
    db.init_db()

    yield

    db.conn.close()
    db.conn = old_conn
    db.cursor = old_cursor


@pytest.fixture
def build_habit():
    """A fresh daily Build habit."""
    return Build(
        name="Read Book",
        id=1,
        creation_date=TODAY - timedelta(days=10),
        periodicity=Periodicity.DAILY,
        time_period=TimePeriod.MORNING,
        duration=30,
        stop_condition="End of month",
        micro_action="Open book"
    )


@pytest.fixture
def break_habit():
    """A fresh daily Break habit."""
    return Break(
        name="Stop Scrolling",
        id=3,
        creation_date=TODAY,
        periodicity=Periodicity.DAILY,
        time_period=TimePeriod.EVENING,
        replacement="Read a book instead"
    )


def _daily_run(end, n):
    """n consecutive daily dates ending on `end`."""
    return [end - timedelta(days=i) for i in range(n - 1, -1, -1)]


def _weekly_run(end, n):
    """n dates exactly one week apart, ending on `end`."""
    return [end - timedelta(weeks=i) for i in range(n - 1, -1, -1)]


@pytest.fixture
def analytics_habits():
    """Three habits whose longest streaks come from real history: 5, 10 and 2."""
    h1 = Build("Morning Run", 1, TODAY, Periodicity.DAILY, TimePeriod.MORNING, 30, "None", "Shoes on")
    for d in _daily_run(TODAY, 5):
        h1.record_completion(d)

    h2 = Build("Weekly Review", 2, TODAY, Periodicity.WEEKLY, TimePeriod.AFTERNOON, 30, "None", "Open laptop")
    for d in _weekly_run(TODAY, 10):
        h2.record_completion(d)

    h3 = Break("No Sugar", 3, TODAY, Periodicity.DAILY, TimePeriod.NIGHT, "Drink sparkling water")
    for d in _daily_run(TODAY, 2):
        h3.record_completion(d)

    return [h1, h2, h3]


# ==========================================
# CORE HABIT TESTS (OOP)
# ==========================================

def test_habit_creation(build_habit):
    """Verifies that a Build habit is instantiated with the correct properties."""
    assert build_habit.name == "Read Book"
    assert build_habit.periodicity == Periodicity.DAILY
    assert build_habit.time_period == TimePeriod.MORNING
    assert build_habit._duration == 30
    assert build_habit._micro_action == "Open book"
    assert len(build_habit.completion_dates) == 0


def test_break_habit_creation(break_habit):
    """Verifies that a Break habit is instantiated with the correct properties."""
    assert break_habit.name == "Stop Scrolling"
    assert break_habit.periodicity == Periodicity.DAILY
    assert break_habit._replacement == "Read a book instead"
    assert len(break_habit._urge_logs) == 0


def test_complete_habit(build_habit):
    """Tests that calling complete() adds today's date to the completion tracker."""
    assert len(build_habit.completion_dates) == 0
    build_habit.complete()
    assert len(build_habit.completion_dates) == 1
    assert build_habit.completion_dates[-1] == TODAY


def test_no_duplicate_completion(build_habit):
    """Ensures a habit cannot be checked off twice on the same day."""
    build_habit.complete()
    build_habit.complete()
    assert len(build_habit.completion_dates) == 1


def test_daily_streak(build_habit):
    """Tests that consecutive daily dates accurately tally a running streak."""
    build_habit._completion_dates = [TODAY - timedelta(days=3), TODAY - timedelta(days=2),
                                     TODAY - timedelta(days=1)]
    assert build_habit.get_streak() == 3


def test_weekly_streak():
    """Tests that dates spaced a week apart calculate correctly for weekly habits."""
    weekly_habit = Build("Weekly Review", 2, TODAY - timedelta(days=30), Periodicity.WEEKLY,
                         TimePeriod.AFTERNOON, 30, "None", "Open laptop")
    weekly_habit._completion_dates = [TODAY - timedelta(days=14), TODAY - timedelta(days=7), TODAY]
    assert weekly_habit.get_streak() == 3


def test_streak_breaks_on_gap(build_habit):
    """Verifies that skipping a mandatory period resets the current streak to zero."""
    build_habit._completion_dates = [TODAY - timedelta(days=4), TODAY - timedelta(days=3)]
    assert build_habit.get_streak() == 0


def test_get_longest_streak(build_habit):
    """Tests that the algorithm correctly scans history to find the longest historical streak."""
    build_habit._completion_dates = [
        TODAY - timedelta(days=10),
        TODAY - timedelta(days=9),
        TODAY - timedelta(days=8),  # Streak of 3
        TODAY - timedelta(days=2),
        TODAY - timedelta(days=1)   # Streak of 2
    ]
    assert build_habit.get_longest_streak() == 3


def test_is_due_today(build_habit, monkeypatch):
    """is_now_due() depends only on the (patched) time period, never on the real clock."""
    monkeypatch.setattr(habit_mod, "get_current_time_period", lambda: "morning")
    assert build_habit.is_now_due() is True      # fixture habit is a MORNING habit

    monkeypatch.setattr(habit_mod, "get_current_time_period", lambda: "evening")
    assert build_habit.is_now_due() is False


def test_replacement_rate(break_habit):
    """Tests the math calculating how successfully urges were replaced with healthy actions."""
    break_habit.log_urge(TODAY, did_replacement=True)
    assert break_habit.replacement_rate() == 100
    break_habit.log_urge(TODAY, did_replacement=False)
    assert break_habit.replacement_rate() == 50


# ==========================================
# UNDO (Habit.uncomplete)
# ==========================================

def test_uncomplete_removes_today_and_returns_true(build_habit):
    """uncomplete() returns True when it removed today's completion."""
    build_habit.complete()
    assert build_habit.uncomplete() is True
    assert build_habit.completion_dates == []


def test_uncomplete_keeps_past_days_and_returns_false(build_habit):
    """uncomplete() never touches past days and always returns a bool, never a string or None."""
    yesterday = TODAY - timedelta(days=1)
    build_habit.record_completion(yesterday)
    assert build_habit.uncomplete() is False
    assert build_habit.completion_dates == [yesterday]
    assert Build("Empty", 9, TODAY, Periodicity.DAILY, TimePeriod.MORNING, 1, "x", "y").uncomplete() is False


def test_db_remove_completion_only_removes_that_day(build_habit):
    """remove_completion() deletes exactly one habit/day row."""
    db.add_habit(build_habit)
    yesterday = TODAY - timedelta(days=1)
    db.add_completion(build_habit.id, yesterday)
    db.add_completion(build_habit.id, TODAY)
    assert db.remove_completion(build_habit.id, TODAY) is True
    assert db.remove_completion(build_habit.id, TODAY) is False  # nothing left to remove
    assert [r[0] for r in db.get_completions_for_habit(build_habit.id)] == [yesterday.isoformat()]


# ==========================================
# STREAKS ARE SIDE-EFFECT FREE
# ==========================================

def test_streak_methods_do_not_modify_the_object(build_habit):
    """get_streak() and get_longest_streak() leave every attribute of the habit unchanged."""
    for d in _daily_run(TODAY, 4) + [TODAY - timedelta(days=9)]:
        build_habit.record_completion(d)
    before = copy.deepcopy(vars(build_habit))
    build_habit.get_streak()
    build_habit.get_streak(as_of=TODAY - timedelta(days=2))
    build_habit.get_longest_streak()
    assert vars(build_habit) == before


def test_streak_methods_ignore_any_stored_cache(build_habit):
    """The result depends only on completion_dates, not on a stale cached value."""
    build_habit._longest_streak = 99  # would have been returned by the old cache-reading code
    assert build_habit.get_longest_streak() == 0
    build_habit.record_completion(TODAY)
    assert build_habit.get_longest_streak() == 1


def test_streak_methods_do_not_assign_cache_attributes():
    """Source check: neither method writes self._current_streak or self._longest_streak."""
    for method in (habit_mod.Habit.get_streak, habit_mod.Habit.get_longest_streak):
        source = inspect.getsource(method)
        assert not re.search(r"self\._(current|longest)_streak\s*=", source)
        assert "self._longest_streak" not in source


def test_analytics_does_not_modify_habits(analytics_habits):
    """Calling every analytics function leaves every habit untouched (genuine purity)."""
    before = copy.deepcopy([vars(h) for h in analytics_habits])
    analytics.list_all_habits(analytics_habits)
    analytics.filter_by_period(analytics_habits, Periodicity.DAILY)
    analytics.filter_by_type(analytics_habits, "build")
    analytics.longest_streak_all_habits(analytics_habits)
    analytics.most_struggled_habit(analytics_habits)
    analytics.streak_leaderboard(analytics_habits)
    analytics.get_longest_streak_for_habit(analytics_habits[0])
    assert [vars(h) for h in analytics_habits] == before


# ==========================================
# ANALYTICS TESTS (FUNCTIONAL PROGRAMMING)
# ==========================================

def test_filter_by_period(analytics_habits):
    """Tests the filter() pure function for separating weekly vs daily habits."""
    weekly = analytics.filter_by_period(analytics_habits, Periodicity.WEEKLY)
    assert len(weekly) == 1
    assert weekly[0].name == "Weekly Review"


def test_filter_by_type(analytics_habits):
    """Tests the filter() pure function for separating build vs break habits."""
    breaks = analytics.filter_by_type(analytics_habits, "break")
    assert len(breaks) == 1
    assert breaks[0].name == "No Sugar"


def test_longest_streak_all(analytics_habits):
    """Tests the max() functional tool to find the absolute highest streak globally."""
    assert analytics.longest_streak_all_habits(analytics_habits).name == "Weekly Review"


def test_longest_streak_for(analytics_habits):
    """Tests retrieving the longest streak for a specific tracked habit."""
    assert analytics.get_longest_streak_for_habit(analytics_habits[0]) == 5


def test_list_all_habits(analytics_habits):
    """Tests the map() pure function for extracting just the names of habits."""
    assert analytics.list_all_habits(analytics_habits) == ["Morning Run", "Weekly Review", "No Sugar"]


def test_streak_leaderboard(analytics_habits):
    """Tests the sorted() functional tool to create a descending leaderboard."""
    leaderboard = analytics.streak_leaderboard(analytics_habits)
    assert [h.name for h in leaderboard] == ["Weekly Review", "Morning Run", "No Sugar"]


def test_most_struggled_and_empty_inputs(analytics_habits):
    """min() picks the lowest streak; empty input gives None instead of crashing."""
    assert analytics.most_struggled_habit(analytics_habits).name == "No Sugar"
    assert analytics.most_struggled_habit([]) is None
    assert analytics.longest_streak_all_habits([]) is None


# ==========================================
# PERSISTENCE LAYER TESTS (db.py)
# ==========================================

def test_db_roundtrip_build_habit(build_habit):
    """A Build habit with history survives save/load with every field intact."""
    for d in _daily_run(TODAY, 3):
        build_habit.record_completion(d)
    build_habit.log_micro_action(True)
    build_habit.log_micro_action(False)
    db.add_habit(build_habit)
    for d in build_habit.completion_dates:
        db.add_completion(build_habit.id, d)

    loaded = db.get_habit_by_name("Read Book")
    assert isinstance(loaded, Build)
    assert loaded.to_dict() == build_habit.to_dict()
    assert loaded.get_longest_streak() == 3


def test_db_roundtrip_break_habit_with_urges(break_habit):
    """A Break habit, its completions and its urge log rows survive a save/load cycle."""
    break_habit.log_urge(TODAY - timedelta(days=1), True)
    break_habit.log_urge(TODAY, False)
    break_habit.record_completion(TODAY)
    db.add_habit(break_habit)
    for urge in break_habit.urge_logs:
        db.add_urge(break_habit.id, urge["logged_at"], 1 if urge["replaced"] else 0)
    db.add_completion(break_habit.id, TODAY)

    loaded = db.get_habit_by_name("Stop Scrolling")
    assert isinstance(loaded, Break)
    assert loaded.replacement == "Read a book instead"
    assert len(loaded.urge_logs) == 2
    assert loaded.to_dict() == break_habit.to_dict()


def test_db_update_break_habit_persists_counters(break_habit):
    """update_habit() writes a Break habit's urge counters."""
    db.add_habit(break_habit)
    break_habit.log_urge(TODAY, True)
    break_habit.log_urge(TODAY, False)
    db.update_habit(break_habit)
    loaded = db.get_habit_by_name("Stop Scrolling")
    assert loaded.total_urges_logged == 2
    assert loaded.successful_replacements == 1
    assert loaded.replacement_rate() == 50


def test_db_update_build_habit_persists_micro_stats(build_habit):
    """update_habit() writes a Build habit's micro-action counters."""
    db.add_habit(build_habit)
    build_habit.log_micro_action(True)
    build_habit.log_micro_action(False)
    db.update_habit(build_habit)
    loaded = db.get_habit_by_name("Read Book")
    assert loaded.total_micro_attempts == 2
    assert loaded.successful_micro_actions == 1


def test_update_habit_saves_longest_streak_at_save_time(build_habit):
    """The longest_streak column is filled from the history when the habit is saved."""
    db.add_habit(build_habit)
    for d in _daily_run(TODAY, 4):
        build_habit.record_completion(d)
    db.update_habit(build_habit)
    assert db.get_habit(build_habit.id)[5] == 4


def test_db_completions_load_in_chronological_order(build_habit):
    """Completions inserted out of order still load sorted, so streaks are right."""
    db.add_habit(build_habit)
    for offset in (0, 2, 1, 4, 3):
        db.add_completion(build_habit.id, TODAY - timedelta(days=offset))
    loaded = db.get_habit_by_name("Read Book")
    assert loaded.completion_dates == sorted(loaded.completion_dates)
    assert loaded.get_streak() == 5


def test_db_urges_load_in_chronological_order(break_habit):
    """Urge logs also come back oldest first."""
    db.add_habit(break_habit)
    for offset in (0, 3, 1):
        db.add_urge(break_habit.id, TODAY - timedelta(days=offset), 1)
    dates = [r[0] for r in db.get_urges_for_habit(break_habit.id)]
    assert dates == sorted(dates)


def test_db_add_completion_is_idempotent(build_habit):
    """A second add_completion for the same day adds no row and does not inflate the streak."""
    db.add_habit(build_habit)
    assert db.add_completion(build_habit.id, TODAY) is True
    assert db.add_completion(build_habit.id, TODAY) is False
    loaded = db.get_habit_by_name("Read Book")
    assert len(loaded.completion_dates) == 1
    assert loaded.get_streak() == 1


def test_db_delete_habit_cascades(break_habit):
    """Deleting a habit also removes its completions and urge logs."""
    db.add_habit(break_habit)
    habit_id = break_habit.id
    db.add_completion(habit_id, TODAY)
    db.add_urge(habit_id, TODAY, 1)
    db.delete_habit(habit_id)
    assert db.get_habit(habit_id) is None
    assert db.get_completions_for_habit(habit_id) == []
    assert db.get_urges_for_habit(habit_id) == []


def test_db_load_all_keeps_break_urge_counters(break_habit):
    """load_habits_from_db() keeps urge counters, so writing a loaded habit back does not zero them."""
    db.add_habit(break_habit)
    break_habit.log_urge(TODAY, True)
    db.update_habit(break_habit)
    loaded = db.load_habits_from_db()[0]
    assert loaded.total_urges_logged == 1
    db.update_habit(loaded)
    assert db.get_habit_by_name("Stop Scrolling").total_urges_logged == 1


def test_db_both_loaders_agree(break_habit, build_habit):
    """get_habit_by_name() and load_habits_from_db() share one row->object helper."""
    for h in (build_habit, break_habit):
        h.record_completion(TODAY)
        db.add_habit(h)
        db.add_completion(h.id, TODAY)
    by_load = {h.name: h.to_dict() for h in db.load_habits_from_db()}
    for name, as_dict in by_load.items():
        assert db.get_habit_by_name(name).to_dict() == as_dict


def test_db_rejects_duplicate_names_case_insensitively(build_habit):
    """Two habits may not share a name, whatever the capitalisation."""
    db.add_habit(build_habit)
    twin = Build("READ book", None, TODAY, Periodicity.DAILY, TimePeriod.MORNING, 30, "x", "y")
    with pytest.raises(db.DatabaseError):
        db.add_habit(twin)
    assert len(db.get_all_habits()) == 1


def test_db_write_errors_become_database_error(build_habit):
    """A failing sqlite write surfaces as DatabaseError with a short message."""
    db.add_habit(build_habit)
    db.conn.close()
    with pytest.raises(db.DatabaseError):
        db.add_completion(build_habit.id, TODAY)


# ==========================================
# CLI TESTS (main.py, in-process, frozen clock, in-memory DB)
# ==========================================

def run_cli(monkeypatch, capsys, *args):
    """Run main.main() with the given arguments and return what it printed."""
    monkeypatch.setattr(sys, "argv", ["main.py", *args])
    main_mod.main()
    return capsys.readouterr().out


def _completion_rows(habit_id):
    db.cursor.execute("SELECT completion_date FROM completions WHERE habit_id = ? ORDER BY completion_date",
                      (habit_id,))
    return [r[0] for r in db.cursor.fetchall()]


def test_first_run_creates_tables_without_seeding(monkeypatch, capsys):
    """main() creates the tables itself, so `create` works on a brand-new empty database."""
    db.conn.close()
    db.conn = sqlite3.connect(":memory:")  # no tables at all
    db.cursor = db.conn.cursor()
    out = run_cli(monkeypatch, capsys, "create", "--name", "X", "--type", "build",
                  "--periodicity", "daily", "--time_period", "morning")
    assert "Created new build habit 'X'" in out
    assert db.get_habit_by_name("X") is not None


def test_cli_create_break_requires_replacement_and_rejects_duplicates(monkeypatch, capsys):
    """`create` validates --replacement for break habits and rejects duplicate names."""
    out = run_cli(monkeypatch, capsys, "create", "--name", "D", "--type", "break",
                  "--periodicity", "daily", "--time_period", "evening")
    assert "requires the --replacement" in out
    run_cli(monkeypatch, capsys, "create", "--name", "D", "--type", "break", "--periodicity", "daily",
            "--time_period", "evening", "--replacement", "Walk")
    out = run_cli(monkeypatch, capsys, "add", "--name", "d", "--type", "build",
                  "--periodicity", "daily", "--time_period", "morning")
    assert "already exists" in out
    assert len(db.get_all_habits()) == 1


def test_cli_urge_on_new_break_habit(monkeypatch, capsys):
    """Create a break habit, then log an urge for it."""
    run_cli(monkeypatch, capsys, "create", "--name", "D", "--type", "break", "--periodicity", "daily",
            "--time_period", "evening", "--replacement", "Walk")
    out = run_cli(monkeypatch, capsys, "urge", "--name", "D", "--replaced", "yes")
    assert "Urge logged" in out
    loaded = db.get_habit_by_name("D")
    assert (loaded.total_urges_logged, loaded.successful_replacements) == (1, 1)
    assert len(loaded.urge_logs) == 1


def test_cli_checkin_twice_gives_one_row_and_streak_one(monkeypatch, capsys, build_habit):
    """A second check-in on the same day says so, adds no row, and the streak stays 1."""
    db.add_habit(build_habit)
    run_cli(monkeypatch, capsys, "checkin", "--name", "Read Book")
    out = run_cli(monkeypatch, capsys, "checkin", "--name", "Read Book")
    assert "already complete today" in out
    assert _completion_rows(build_habit.id) == [TODAY.isoformat()]
    assert db.get_habit_by_name("Read Book").get_streak() == 1


def test_cli_checkoff_twice_gives_one_row(monkeypatch, capsys, build_habit):
    """checkoff --id behaves like checkin for duplicates."""
    db.add_habit(build_habit)
    run_cli(monkeypatch, capsys, "checkoff", "--id", str(build_habit.id))
    out = run_cli(monkeypatch, capsys, "checkoff", "--id", str(build_habit.id))
    assert "already complete today" in out
    assert len(_completion_rows(build_habit.id)) == 1


def test_cli_checkoff_keeps_break_counters(monkeypatch, capsys, break_habit):
    """checkoff --id on a Break habit must not reset its 20/11 urge counters."""
    for i in range(20):
        break_habit.log_urge(TODAY - timedelta(days=i % 5), i < 11)
    db.add_habit(break_habit)
    db.update_habit(break_habit)
    run_cli(monkeypatch, capsys, "checkoff", "--id", str(break_habit.id))
    loaded = db.get_habit_by_name("Stop Scrolling")
    assert (loaded.total_urges_logged, loaded.successful_replacements) == (20, 11)
    assert _completion_rows(break_habit.id) == [TODAY.isoformat()]


def test_cli_uncomplete_removes_only_todays_row(monkeypatch, capsys, build_habit):
    """uncomplete deletes today's row, keeps yesterday's, and a second call reports nothing to undo."""
    yesterday = TODAY - timedelta(days=1)
    db.add_habit(build_habit)
    db.add_completion(build_habit.id, yesterday)
    db.add_completion(build_habit.id, TODAY)

    out = run_cli(monkeypatch, capsys, "uncomplete", "--name", "Read Book")
    assert "removed" in out
    assert _completion_rows(build_habit.id) == [yesterday.isoformat()]

    out = run_cli(monkeypatch, capsys, "uncomplete", "--name", "Read Book")
    assert "Nothing to undo" in out
    assert _completion_rows(build_habit.id) == [yesterday.isoformat()]


def test_cli_uncomplete_unknown_habit(monkeypatch, capsys):
    """uncomplete on a missing habit prints a clear error."""
    out = run_cli(monkeypatch, capsys, "uncomplete", "--name", "Nope")
    assert "not found" in out


def test_cli_delete_cascades(monkeypatch, capsys, break_habit):
    """`delete` removes the habit and its dependent rows."""
    db.add_habit(break_habit)
    db.add_completion(break_habit.id, TODAY)
    db.add_urge(break_habit.id, TODAY, 1)
    run_cli(monkeypatch, capsys, "delete", "--name", "stop scrolling")
    assert db.get_all_habits() == []
    assert _completion_rows(break_habit.id) == []


# ==========================================
# WEEKLY STREAK EDGE CASES (ISO calendar weeks)
# ==========================================

def _weekly(dates):
    h = Build("W", 1, date(2020, 1, 1), Periodicity.WEEKLY, TimePeriod.MORNING, 30, "x", "y")
    h._completion_dates = list(dates)
    return h


def test_weekly_streak_across_year_boundary_52_week_year():
    """ISO week 52 of 2024 -> week 1 of 2025 -> week 2 of 2025 is one unbroken 3-week streak."""
    h = _weekly([date(2024, 12, 23), date(2024, 12, 30), date(2025, 1, 6)])
    assert h.get_streak(as_of=date(2025, 1, 6)) == 3
    assert h.get_longest_streak() == 3


def test_weekly_streak_across_year_boundary_53_week_year():
    """2020 has 53 ISO weeks; week 53 of 2020 -> week 1 of 2021 is consecutive."""
    h = _weekly([date(2020, 12, 28), date(2021, 1, 4)])
    assert h.get_streak(as_of=date(2021, 1, 4)) == 2
    assert h.get_longest_streak() == 2


def test_weekly_streak_full_run_through_53_week_year():
    """Weeks 52, 53 (2020) and 1 (2021) in a row count as 3."""
    h = _weekly([date(2020, 12, 21), date(2020, 12, 28), date(2021, 1, 4)])
    assert h.get_streak(as_of=date(2021, 1, 4)) == 3


def test_weekly_streak_breaks_when_53rd_week_is_skipped():
    """Week 52 of 2020 -> week 1 of 2021 skips week 53, so it is NOT a streak."""
    h = _weekly([date(2020, 12, 21), date(2021, 1, 4)])
    assert h.get_streak(as_of=date(2021, 1, 4)) == 1
    assert h.get_longest_streak() == 1


def test_weekly_streak_breaks_when_a_week_is_skipped():
    """Skipping a whole calendar week resets the weekly streak."""
    h = _weekly([date(2026, 3, 2), date(2026, 3, 16)])  # weeks 10 and 12
    assert h.get_streak(as_of=date(2026, 3, 16)) == 1


def test_weekly_same_week_completions_count_once():
    """Two completions inside one calendar week are a single week of streak."""
    h = _weekly([date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 16)])  # Mon, Tue, next Mon
    assert h.get_streak(as_of=date(2026, 3, 16)) == 2


def test_weekly_streak_alive_until_end_of_following_week():
    """A weekly streak is still alive during the week after the last completion, dead afterwards."""
    h = _weekly([date(2026, 3, 2)])
    assert h.get_streak(as_of=date(2026, 3, 13)) == 1   # following week
    assert h.get_streak(as_of=date(2026, 3, 16)) == 0   # two weeks later


# ==========================================
# END-TO-END: seed.py in an empty folder (fresh clone simulation)
# ==========================================
# These tests copy the project files into an empty temp folder and run the real scripts there.

REPO_DIR = pathlib.Path(__file__).resolve().parent
PROJECT_FILES = ["seed.py", "db.py", "habit.py", "helper.py", "main.py", "analytics.py"]


def _run_in(cwd, *args, io_encoding="utf-8"):
    """Run a script in ``cwd`` as a child process; output is encoded and decoded explicitly (never by the OS locale)."""
    env = dict(os.environ, PYTHONIOENCODING=io_encoding)
    env.pop("PYTHONPATH", None)
    return subprocess.run([sys.executable, *args], cwd=str(cwd), env=env, capture_output=True,
                          encoding=io_encoding, errors="replace")


@pytest.fixture
def project_dir(tmp_path):
    """An empty folder holding only the project's source files (no habits.db)."""
    folder = tmp_path / "clone"
    folder.mkdir()
    for name in PROJECT_FILES:
        shutil.copy(str(REPO_DIR / name), str(folder / name))
    return folder


@pytest.fixture
def seeded_dir(project_dir):
    """A fresh clone in which `python seed.py` has been run once."""
    result = _run_in(project_dir, "seed.py")
    assert result.returncode == 0, "seed.py crashed:\n" + result.stderr
    return project_dir


def _query(folder, sql):
    con = sqlite3.connect(str(folder / "habits.db"))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_seed_creates_exactly_three_tables(seeded_dir):
    """The seeded database has the habits, completions and urge_logs tables."""
    rows = _query(seeded_dir, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    assert sorted(r[0] for r in rows) == ["completions", "habits", "urge_logs"]


def test_seed_database_loads_with_daily_and_weekly_habits(seeded_dir):
    """Exactly 5 predefined habits, with both 'daily' and 'weekly' present, and the DB loads."""
    result = _run_in(seeded_dir, "-c",
                     "import db; hs = db.load_habits_from_db(); "
                     "print(len(hs)); print(sorted({h.periodicity.value for h in hs}))")
    assert result.returncode == 0, result.stderr
    count, periods = result.stdout.strip().splitlines()
    assert count == "5"
    assert periods == "['daily', 'weekly']"


def test_seed_study_block_is_weekly_with_week_one_missed(seeded_dir):
    """Study Block: at most one completion per week, week 1 missed, weeks 2-4 done."""
    start = _query(seeded_dir, "SELECT creation_date FROM habits WHERE name='Study Block'")[0][0]
    start = date.fromisoformat(start)
    rows = _query(seeded_dir, "SELECT c.completion_date FROM completions c JOIN habits h ON h.id=c.habit_id "
                              "WHERE h.name='Study Block' ORDER BY 1")
    days = [(date.fromisoformat(r[0]) - start).days for r in rows]
    assert days == [7, 14, 21]
    assert _query(seeded_dir, "SELECT periodicity FROM habits WHERE name='Study Block'") == [("weekly",)]
    assert len({(date.fromisoformat(r[0]).isocalendar()[:2]) for r in rows}) == 3


def test_seed_fast_dopamine_urge_rows_match_counters(seeded_dir):
    """Fast Dopamine has 20 real urge_logs rows, 11 replaced, matching its stored counters."""
    counters = _query(seeded_dir, "SELECT id, total_urges_logged, successful_replacements "
                                  "FROM habits WHERE name='Fast Dopamine'")[0]
    assert counters[1:] == (20, 11)
    rows = _query(seeded_dir, "SELECT COUNT(*), SUM(replaced) FROM urge_logs WHERE habit_id=%d" % counters[0])
    assert rows == [(20, 11)]


def test_seeding_twice_aborts_cleanly(seeded_dir):
    """A second `python seed.py` exits 0, says it aborted, and changes nothing."""
    before = _query(seeded_dir, "SELECT COUNT(*) FROM habits"), _query(seeded_dir, "SELECT COUNT(*) FROM completions")
    result = _run_in(seeded_dir, "seed.py")
    assert result.returncode == 0
    assert "aborted" in result.stdout.lower()
    after = _query(seeded_dir, "SELECT COUNT(*) FROM habits"), _query(seeded_dir, "SELECT COUNT(*) FROM completions")
    assert before == after and before[0] == [(5,)]


def test_seed_data_is_identical_on_every_run(tmp_path):
    """random.Random(42) makes the sample data identical (relative to the start date) on each run."""
    snapshots = []
    for i in range(2):
        folder = tmp_path / ("run%d" % i)
        folder.mkdir()
        for name in PROJECT_FILES:
            shutil.copy(str(REPO_DIR / name), str(folder / name))
        assert _run_in(folder, "seed.py").returncode == 0
        snapshots.append(_query(folder, (
            "SELECT h.name, CAST(julianday(c.completion_date) - julianday(h.creation_date) AS INT) "
            "FROM completions c JOIN habits h ON h.id=c.habit_id ORDER BY h.id, c.completion_date")) + _query(folder, (
            "SELECT h.name, CAST(julianday(u.logged_at) - julianday(h.creation_date) AS INT), u.replaced "
            "FROM urge_logs u JOIN habits h ON h.id=u.habit_id ORDER BY u.id")))
    assert snapshots[0] == snapshots[1]
    assert len(snapshots[0]) > 50


def test_seed_works_from_any_working_directory(project_dir, tmp_path):
    """habits.db is created next to the code, not in whatever folder the command was run from."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = _run_in(elsewhere, str(project_dir / "seed.py"))
    assert result.returncode == 0, result.stderr
    assert (project_dir / "habits.db").exists()
    assert not (elsewhere / "habits.db").exists()


def test_create_works_on_fresh_clone_without_seeding(project_dir):
    """`python main.py create ...` works in a folder that has never been seeded."""
    result = _run_in(project_dir, "main.py", "create", "--name", "X", "--type", "build",
                     "--periodicity", "daily", "--time_period", "morning")
    assert result.returncode == 0, result.stderr
    assert "Created new build habit 'X'" in result.stdout
    assert _query(project_dir, "SELECT name FROM habits") == [("X",)]


def test_break_habit_can_be_saved_and_updated_in_seeded_database(seeded_dir):
    """Break habits can be created, logged and updated in a database that seed.py built."""
    code = (
        "import db\n"
        "from datetime import date\n"
        "from habit import Break, Periodicity, TimePeriod\n"
        "b = Break('Doomscroll', None, date.today(), Periodicity.DAILY, TimePeriod.EVENING, 'Walk')\n"
        "db.add_habit(b)\n"
        "b.log_urge(date.today(), True)\n"
        "db.update_habit(b)\n"
        "print(db.get_habit_by_name('Doomscroll').total_urges_logged)\n"
    )
    result = _run_in(seeded_dir, "-c", code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"


# ==========================================
# COMPLETION DATE AND TIME (brief: "the date and time the habit tasks have been completed")
# ==========================================

def _plain(text):
    """Strip ANSI colour codes from CLI output."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_complete_records_date_and_time(build_habit):
    """complete() stores today's date for streaks AND the time of day it was done."""
    assert build_habit.complete() is True
    assert build_habit.completion_dates == [TODAY]
    assert build_habit.completion_times == {TODAY: FROZEN_NOW}
    assert build_habit.completion_log() == [(TODAY, FROZEN_NOW)]


def test_record_completion_rejects_a_time_on_another_day(build_habit):
    """A completion time must fall on the day it is recorded for."""
    with pytest.raises(ValueError):
        build_habit.record_completion(TODAY, FROZEN_NOW - timedelta(days=1))
    assert build_habit.completion_dates == []


def test_second_completion_on_a_day_keeps_the_first_time(build_habit):
    """The first check-in of a day wins; a later one neither adds a day nor replaces the time."""
    first = datetime.combine(TODAY, time(7, 5))
    assert build_habit.record_completion(TODAY, first) is True
    assert build_habit.record_completion(TODAY, datetime.combine(TODAY, time(21, 0))) is False
    assert build_habit.completion_times == {TODAY: first}
    assert len(build_habit.completion_dates) == 1


def test_uncomplete_also_removes_todays_time(build_habit):
    """Undoing today's completion removes its time too, and leaves yesterday's time alone."""
    yesterday = TODAY - timedelta(days=1)
    earlier = datetime.combine(yesterday, time(8, 0))
    build_habit.record_completion(yesterday, earlier)
    build_habit.complete()
    assert build_habit.uncomplete() is True
    assert build_habit.completion_times == {yesterday: earlier}


def test_completion_log_marks_a_missing_time_as_none(build_habit):
    """Completions saved without a time (old data) show up with None instead of an invented time."""
    yesterday = TODAY - timedelta(days=1)
    build_habit.record_completion(yesterday)
    build_habit.complete()
    assert build_habit.completion_log() == [(yesterday, None), (TODAY, FROZEN_NOW)]


def test_to_dict_and_from_dict_keep_completion_times(build_habit, break_habit):
    """Both habit types serialise completion times to ISO text and restore them exactly."""
    for habit in (build_habit, break_habit):
        habit.record_completion(TODAY - timedelta(days=1))          # no time
        habit.record_completion(TODAY, FROZEN_NOW)                  # with time
        data = habit.to_dict()
        assert data["completed_at"] == {TODAY.isoformat(): "2026-03-18T09:30:00"}
        restored = type(habit).from_dict(data)
        assert restored.completion_log() == habit.completion_log()


def test_helper_get_now_is_to_the_second():
    """The real clock helper returns a datetime with no microseconds."""
    assert helper_mod.get_now().microsecond == 0


@pytest.mark.parametrize("hour, expected", [(0, "night"), (5, "night"), (6, "morning"), (11, "morning"),
                                            (12, "afternoon"), (17, "afternoon"), (18, "evening"),
                                            (23, "evening")])
def test_time_period_boundaries(monkeypatch, hour, expected):
    """get_current_time_period maps every hour of the day to the right period."""
    class FakeDatetime:
        @staticmethod
        def now():
            return datetime(2026, 3, 18, hour, 0)
    monkeypatch.setattr(helper_mod, "datetime", FakeDatetime)
    assert helper_mod.get_current_time_period() == expected


def test_db_add_completion_stores_date_and_time(build_habit):
    """The completions table keeps the ISO date and the full ISO datetime, and loading restores both."""
    db.add_habit(build_habit)
    assert db.add_completion(build_habit.id, TODAY, FROZEN_NOW) is True
    db.cursor.execute("SELECT completion_date, completed_at FROM completions WHERE habit_id = ?", (build_habit.id,))
    assert db.cursor.fetchall() == [("2026-03-18", "2026-03-18T09:30:00")]
    loaded = db.get_habit_by_name("Read Book")
    assert loaded.completion_times == {TODAY: FROZEN_NOW}


def test_db_completion_without_a_time_is_stored_as_null(build_habit):
    """add_completion(habit_id, day) still works and leaves completed_at empty."""
    db.add_habit(build_habit)
    db.add_completion(build_habit.id, TODAY)
    db.cursor.execute("SELECT completed_at FROM completions WHERE habit_id = ?", (build_habit.id,))
    assert db.cursor.fetchall() == [(None,)]
    assert db.get_habit_by_name("Read Book").completion_log() == [(TODAY, None)]


def test_db_upgrades_an_old_database_without_completed_at():
    """A habits.db made before completion times existed gets the new column and keeps its data."""
    db.conn.close()
    db.conn = sqlite3.connect(":memory:")
    db.cursor = db.conn.cursor()
    db.cursor.executescript("""
        CREATE TABLE habits (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, creation_date TEXT,
            periodicity TEXT, time_period TEXT, longest_streak INTEGER, type TEXT NOT NULL, duration INTEGER,
            stop_condition TEXT, micro_action TEXT, total_micro_attempts INTEGER, successful_micro_actions INTEGER,
            replacement TEXT, total_urges_logged INTEGER, successful_replacements INTEGER);
        CREATE TABLE completions (id INTEGER PRIMARY KEY AUTOINCREMENT, habit_id INTEGER, completion_date TEXT,
            FOREIGN KEY (habit_id) REFERENCES habits (id) ON DELETE CASCADE);
        CREATE TABLE urge_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, habit_id INTEGER, logged_at TEXT,
            replaced INTEGER, FOREIGN KEY (habit_id) REFERENCES habits (id) ON DELETE CASCADE);
        INSERT INTO habits (name, creation_date, periodicity, time_period, longest_streak, type, duration,
            stop_condition, micro_action, total_micro_attempts, successful_micro_actions)
            VALUES ('Old Habit', '2026-03-01', 'daily', 'morning', 1, 'build', 30, 'x', 'y', 0, 0);
        INSERT INTO completions (habit_id, completion_date) VALUES (1, '2026-03-17');
    """)
    db.init_db()
    db.init_db()  # running it twice must be harmless
    columns = [r[1] for r in db.cursor.execute("PRAGMA table_info(completions)").fetchall()]
    assert "completed_at" in columns
    old = db.get_habit_by_name("Old Habit")
    assert old.completion_log() == [(date(2026, 3, 17), None)]
    assert db.add_completion(old.id, TODAY, FROZEN_NOW) is True
    assert db.get_habit_by_name("Old Habit").completion_times == {TODAY: FROZEN_NOW}


# ---------- CLI: check-in stores the time, `history` shows it ----------

def test_cli_checkin_and_checkoff_store_date_and_time(monkeypatch, capsys, build_habit, break_habit):
    """Both check-in commands write the exact moment, to the second, into the database."""
    db.add_habit(build_habit)
    db.add_habit(break_habit)
    run_cli(monkeypatch, capsys, "checkin", "--name", "Read Book")
    run_cli(monkeypatch, capsys, "checkoff", "--id", str(break_habit.id))
    db.cursor.execute("SELECT habit_id, completion_date, completed_at FROM completions ORDER BY habit_id")
    assert db.cursor.fetchall() == [(build_habit.id, "2026-03-18", "2026-03-18T09:30:00"),
                                    (break_habit.id, "2026-03-18", "2026-03-18T09:30:00")]


def test_cli_history_lists_newest_first_with_times(monkeypatch, capsys, build_habit):
    """`history` prints each completion's date and HH:MM, newest first, plus the streaks."""
    db.add_habit(build_habit)
    for days_ago, hour, minute in [(2, 8, 15), (1, 9, 0), (0, 9, 30)]:
        day = TODAY - timedelta(days=days_ago)
        db.add_completion(build_habit.id, day, datetime.combine(day, time(hour, minute)))
    out = _plain(run_cli(monkeypatch, capsys, "history", "--name", "read book"))
    assert "Completion History: 'Read Book'" in out
    assert "Current streak: 3 days | Longest streak: 3 days | Completions: 3" in out
    assert out.index("2026-03-18  09:30") < out.index("2026-03-17  09:00") < out.index("2026-03-16  08:15")


def test_cli_history_limit_and_rows_without_a_time(monkeypatch, capsys, build_habit):
    """--limit shows only the newest rows, and an old row with no time says so."""
    db.add_habit(build_habit)
    db.add_completion(build_habit.id, TODAY - timedelta(days=1))                       # no time
    db.add_completion(build_habit.id, TODAY, FROZEN_NOW)
    out = _plain(run_cli(monkeypatch, capsys, "history", "--name", "Read Book", "--limit", "1"))
    assert "2026-03-18  09:30" in out and "2026-03-17" not in out
    assert "1 older completion not shown" in out
    out = _plain(run_cli(monkeypatch, capsys, "history", "--name", "Read Book", "--limit", "0"))
    assert "2026-03-17  (time not recorded)" in out


def test_cli_history_weekly_uses_weeks_and_handles_empty_and_unknown(monkeypatch, capsys):
    """Weekly habits report streaks in weeks; an empty history and a missing habit give clear messages."""
    weekly = Build("Weekly Review", None, TODAY, Periodicity.WEEKLY, TimePeriod.AFTERNOON, 30, "x", "y")
    db.add_habit(weekly)
    out = _plain(run_cli(monkeypatch, capsys, "history", "--name", "Weekly Review"))
    assert "Current streak: 0 weeks" in out and "No completions yet." in out
    db.add_completion(weekly.id, TODAY, FROZEN_NOW)
    out = _plain(run_cli(monkeypatch, capsys, "history", "--name", "Weekly Review"))
    assert "Current streak: 1 week |" in out
    out = _plain(run_cli(monkeypatch, capsys, "history", "--name", "Nope"))
    assert "Habit 'Nope' not found" in out


# ---------- CLI paths that had no test: micro, analyze, view ----------

def test_cli_micro_logs_attempts_and_prints_success_rate(monkeypatch, capsys, build_habit, break_habit):
    """`micro` counts attempts for Build habits only and prints the running success rate."""
    db.add_habit(build_habit)
    db.add_habit(break_habit)
    out = _plain(run_cli(monkeypatch, capsys, "micro", "--name", "Read Book", "--did_it", "yes"))
    assert "Success rate: 100.0%" in out
    out = _plain(run_cli(monkeypatch, capsys, "micro", "--name", "Read Book", "--did_it", "no"))
    assert "Success rate: 50.0%" in out
    loaded = db.get_habit_by_name("Read Book")
    assert (loaded.total_micro_attempts, loaded.successful_micro_actions) == (2, 1)
    out = _plain(run_cli(monkeypatch, capsys, "micro", "--name", "Stop Scrolling", "--did_it", "yes"))
    assert "Build habit 'Stop Scrolling' not found" in out


@pytest.fixture
def saved_analytics_habits(analytics_habits):
    """The three analytics_habits (streaks 5, 10, 2) saved into the in-memory database."""
    for habit in analytics_habits:
        db.add_habit(habit)
        for day in habit.completion_dates:
            db.add_completion(habit.id, day)
    return analytics_habits


def test_cli_analyze_lists_and_filters(monkeypatch, capsys, saved_analytics_habits):
    """--list-all, --by-period and --by-type print the right habit names."""
    out = _plain(run_cli(monkeypatch, capsys, "analyze", "--list-all"))
    assert all(name in out for name in ("Morning Run", "Weekly Review", "No Sugar"))
    out = _plain(run_cli(monkeypatch, capsys, "analyze", "--by-period", "weekly"))
    assert "Weekly Review" in out and "Morning Run" not in out
    out = _plain(run_cli(monkeypatch, capsys, "analyze", "--by-period", "daily"))
    assert "Morning Run" in out and "No Sugar" in out and "Weekly Review" not in out
    out = _plain(run_cli(monkeypatch, capsys, "analyze", "--by-type", "break"))
    assert "No Sugar" in out and "Morning Run" not in out


def test_cli_analyze_streak_commands(monkeypatch, capsys, saved_analytics_habits):
    """--streak-all, --streak-habit, --ranking and --struggled report the 10 / 5 / 2 streaks correctly."""
    out = _plain(run_cli(monkeypatch, capsys, "analyze", "--streak-all"))
    assert "Weekly Review (10 streak)" in out
    out = _plain(run_cli(monkeypatch, capsys, "analyze", "--streak-habit", "morning RUN"))
    assert "Longest Streak for 'Morning Run'" in out and "5" in out
    out = _plain(run_cli(monkeypatch, capsys, "analyze", "--ranking"))
    assert out.index("1. Weekly Review - 10") < out.index("2. Morning Run - 5") < out.index("3. No Sugar - 2")
    out = _plain(run_cli(monkeypatch, capsys, "analyze", "--struggled"))
    assert "No Sugar (Max Streak: 2)" in out


def test_cli_analyze_error_and_empty_cases(monkeypatch, capsys):
    """No flag, an unknown habit and an empty database all give a clear message instead of crashing."""
    assert "Please provide an analysis flag" in _plain(run_cli(monkeypatch, capsys, "analyze"))
    assert "Habit 'Nope' not found" in _plain(run_cli(monkeypatch, capsys, "analyze", "--streak-habit", "Nope"))
    assert "No habits tracked." in _plain(run_cli(monkeypatch, capsys, "analyze", "--streak-all"))
    assert "No habits tracked." in _plain(run_cli(monkeypatch, capsys, "analyze", "--struggled"))


def test_cli_view_dashboard_sections_and_done_time(monkeypatch, capsys, build_habit, break_habit):
    """The dashboard splits habits into due / missed / weekly and shows the time a habit was done."""
    monkeypatch.setattr(main_mod, "get_current_time_period", lambda: "morning")
    monkeypatch.setattr(habit_mod, "get_current_time_period", lambda: "morning")
    weekly = Build("Weekly Review", None, TODAY, Periodicity.WEEKLY, TimePeriod.AFTERNOON, 30, "x", "y")
    for habit in (build_habit, break_habit, weekly):
        db.add_habit(habit)
    db.add_completion(build_habit.id, TODAY, FROZEN_NOW)          # morning habit, done at 09:30
    for weeks_ago in range(3):
        db.add_completion(weekly.id, TODAY - timedelta(weeks=weeks_ago))
    for alias in ("view", "summary", "list"):
        out = _plain(run_cli(monkeypatch, capsys, alias))
        assert "(MORNING)" in out
        assert "Read Book (Done at 09:30!)" in out                     # due now and finished
        assert "Stop Scrolling (Pending/Missed)" in out                # evening habit, not now
        assert "Weekly Review (Longest Streak: 3 weeks)" in out


def test_cli_view_on_an_empty_database(monkeypatch, capsys):
    """An empty tracker still renders every section with a friendly placeholder."""
    out = _plain(run_cli(monkeypatch, capsys, "view"))
    assert "None scheduled for this time frame." in out
    assert "No other daily habits tracked." in out
    assert "No weekly habits created yet." in out


def test_cli_without_a_command_prints_help(monkeypatch, capsys):
    """Running `python main.py` with no subcommand shows the help text."""
    out = run_cli(monkeypatch, capsys)
    assert "usage:" in out and "history" in out


# ==========================================
# END-TO-END: sample data has a date AND a time for every completion
# ==========================================

PERIOD_HOURS = {"morning": range(6, 12), "afternoon": range(12, 18), "evening": range(18, 24), "night": range(0, 6)}


def test_seed_gives_every_completion_a_time_inside_its_time_period(seeded_dir):
    """All 80 sample completions have a datetime on the same day, within their habit's time period."""
    rows = _query(seeded_dir, "SELECT h.time_period, c.completion_date, c.completed_at "
                              "FROM completions c JOIN habits h ON h.id = c.habit_id")
    assert len(rows) == 80
    for period, day, stamp in rows:
        assert stamp is not None, "completion on %s has no time" % day
        moment = datetime.fromisoformat(stamp)
        assert moment.date().isoformat() == day
        assert moment.hour in PERIOD_HOURS[period], (period, stamp)


def test_seed_times_are_identical_on_every_run(tmp_path):
    """The seeded times of day are reproducible, like the dates."""
    snapshots = []
    for i in range(2):
        folder = tmp_path / ("run%d" % i)
        folder.mkdir()
        for name in PROJECT_FILES:
            shutil.copy(str(REPO_DIR / name), str(folder / name))
        assert _run_in(folder, "seed.py").returncode == 0
        snapshots.append(_query(folder, "SELECT h.name, substr(c.completed_at, 12) FROM completions c "
                                        "JOIN habits h ON h.id = c.habit_id ORDER BY h.id, c.completion_date"))
    assert snapshots[0] == snapshots[1]
    assert len(set(snapshots[0])) > 40          # genuinely varied, not one fixed time


def test_seed_days_and_streaks_match_the_readme(seeded_dir):
    """Adding times did not move any sample day: weekly counts and longest streaks are the documented ones."""
    code = (
        "import db\n"
        "for h in db.load_habits_from_db():\n"
        "    weeks = [0, 0, 0, 0]\n"
        "    for d in h.completion_dates:\n"
        "        weeks[min((d - h.creation_date).days // 7, 3)] += 1\n"
        "    print(h.name, weeks, h.get_longest_streak())\n"
    )
    result = _run_in(seeded_dir, "-c", code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == [
        "Wake Anchor [4, 5, 6, 7] 8",
        "Morning Protein [5, 6, 7, 7] 15",
        "Idea Capture [3, 4, 6, 6] 6",
        "Study Block [0, 1, 1, 1] 3",
        "Fast Dopamine [2, 3, 3, 3] 3",
    ]


def test_history_command_shows_seeded_dates_and_times(seeded_dir):
    """End to end: `python main.py history` on the seeded database prints dates with HH:MM."""
    result = _run_in(seeded_dir, "main.py", "history", "--name", "Wake Anchor", "--limit", "3")
    assert result.returncode == 0, result.stderr
    out = _plain(result.stdout)
    assert "Longest streak: 8 days | Completions: 22" in out
    times = re.findall(r"^  \d{4}-\d{2}-\d{2}  (\d{2}):(\d{2})$", out, flags=re.M)
    assert len(times) == 3
    assert all(6 <= int(hour) < 12 for hour, _ in times)       # Wake Anchor is a morning habit


# ==========================================
# PORTABILITY: redirected output on Windows (cp1252 cannot encode the check mark or the star)
# ==========================================

def test_make_output_safe_replaces_what_the_codepage_cannot_encode(monkeypatch):
    """With a cp1252 stream, printing the symbols no longer raises; they become question marks."""
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    helper_mod.make_output_safe()
    print("\u2714 ok \u2605 \u274c")
    stream.flush()
    assert raw.getvalue() == b"? ok ? ?\r\n" or raw.getvalue() == b"? ok ? ?\n"


def test_cli_output_survives_a_windows_codepage(seeded_dir):
    """seed, view and an error message all work when stdout is a pipe using cp1252 (the Windows default)."""
    for args in (("main.py", "view"), ("main.py", "checkoff", "--id", "99"), ("seed.py",),
                 ("main.py", "analyze", "--streak-all")):
        result = _run_in(seeded_dir, *args, io_encoding="cp1252")
        assert result.returncode == 0, (args, result.stderr)
        assert "Traceback" not in result.stderr
        assert result.stdout.strip() != ""
