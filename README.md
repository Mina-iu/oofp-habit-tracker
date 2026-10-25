# Command-Line Habit Tracker

A small Python command-line app for tracking habits you want to **build** (e.g. "Wake Anchor") and habits you want to **break** (e.g. "Fast Dopamine"). Data lives in a local SQLite file, `habits.db`.

**Design in two sentences:** the object-oriented layer (`habit.py`, `db.py`) owns state - habits are `Build`/`Break` objects (`habit.py`) that `db.py` saves to and loads from SQLite - while the functional layer (`analytics.py`) is a set of pure `map`/`filter`/`max`/`min`/`sorted` functions that only read habits and never change them. Streak maths is pure too (module-level functions in `habit.py`), so asking for a streak can never alter a habit.

**What is tracked:** when each habit was created, and the **date and time** (to the second) of every completion.

---

## Quick start (fresh clone)

**Requirements:** Python **3.7 or newer**. The app itself uses only the standard library; `pytest` is needed only to run the tests.

```bash
pip install -r requirements.txt     # installs pytest (only needed for the tests)
python seed.py                      # optional: creates habits.db with 5 sample habits
python main.py view                 # show the dashboard
```

You do **not** have to seed. Every command creates the database tables on first use, so this works in a brand-new clone:

```bash
python main.py create --name X --type build --periodicity daily --time_period morning
```
```text
✔ Success: Created new build habit 'X'!
```

> **About the example output below.** It is real output from running each command in order against a freshly seeded database (terminal colours removed). Dates, habit IDs and the `(AFTERNOON)` / "due right now" section depend on the day and the time of day you run it. Use `python main.py ...` or `python3 main.py ...`, whichever your system calls Python 3.

---

## Commands

All commands are run as `python main.py <command> [options]`.

### `seed.py` - load the 5 sample habits

Creates 4 daily habits and 1 weekly habit (`Study Block`) with 4 weeks of history, plus 20 logged urges (11 replaced) for `Fast Dopamine`. Every sample completion has a date **and a time of day** inside its habit's time period (morning 06:00-11:59, afternoon 12:00-17:59, evening 18:00-23:59, night 00:00-05:59). The data is generated with `random.Random(42)`, so the sample pattern is identical on every run (dates are relative to the day you seed). If the database already contains habits, seeding aborts and changes nothing; to start over, delete `habits.db` yourself and run it again.

```bash
$ python seed.py
```
```text
✔ Database seeding completed successfully! 5 habits created in habits.db
```

Running it a second time:

```bash
$ python seed.py
```
```text
❌ Seeding aborted: the database already contains habit data.
   (Nothing was changed. To start over, delete habits.db yourself and run again.)
```

### `view` - dashboard (aliases: `summary`, `list`)

Shows daily habits due in the current time of day, the other daily habits (done / pending), and weekly habits.

```bash
$ python main.py view
```
```text
==================================================
      ★ MY CURRENT HABIT QUEUE ★ (AFTERNOON)
==================================================

[ DUE RIGHT NOW ]
  → ID: 3 | Idea Capture (afternoon)

[ MISSED OR LATER TODAY ]
  • ID: 1 | Wake Anchor (Pending/Missed)
  • ID: 2 | Morning Protein (Pending/Missed)
  • ID: 5 | Fast Dopamine (Pending/Missed)

[ WEEKLY HABITS PROGRESS ]
  🗲 ID: 4 | Study Block (Longest Streak: 3 weeks)

==================================================
```

### `history` - when was a habit completed? (date and time)

Lists a habit's completions with the date and the time of day, newest first, plus its current and longest streak (in days for daily habits, weeks for weekly ones). `--limit N` shows the newest N (default 10, `0` = all). Completions saved by an older version without a time show `(time not recorded)`.

```bash
$ python main.py history --name "Wake Anchor" --limit 5
```
```text
[ Completion History: 'Wake Anchor' ]
  Current streak: 8 days | Longest streak: 8 days | Completions: 22
  2026-10-24  09:21
  2026-10-23  09:42
  2026-10-22  10:40
  2026-10-21  11:19
  2026-10-20  09:10
  ... 17 older completions not shown (use --limit 0 to see all)
```

### `checkin` - mark a habit done today, by name

```bash
$ python main.py checkin --name "Wake Anchor"
```
```text
✔ Success: 'Wake Anchor' has been marked complete for today!
```

The check-in stores today's date and the exact time (see `history`). Checking in again the same day is harmless: no second row is written, the first time is kept and the streak does not grow.

```bash
$ python main.py checkin --name "Wake Anchor"
```
```text
ℹ 'Wake Anchor' is already complete today.
```

### `checkoff` - mark a habit done today, by ID

```bash
$ python main.py checkoff --id 5
```
```text
✔ Success: Habit 5 has been marked complete for today!
```

```bash
$ python main.py checkoff --id 99
```
```text
❌ Error: Habit 99 not found.
```

### `uncomplete` - undo today's completion

Removes **only today's** completion (never past days) from the habit and from the database.

```bash
$ python main.py uncomplete --name "Wake Anchor"
```
```text
✔ Success: Today's completion of 'Wake Anchor' has been removed.
```

If there is nothing to undo you get a clear message:

```bash
$ python main.py uncomplete --name "Wake Anchor"
```
```text
ℹ Nothing to undo: 'Wake Anchor' has no completion for today.
```

### `create` - add a habit (alias: `add`)

`--type` is `build` or `break`; `--periodicity` is `daily` or `weekly`; `--time_period` is `morning`, `afternoon`, `evening` or `night`. A `break` habit also needs `--replacement`. Names must be unique (case-insensitive).

```bash
$ python main.py create --name Yoga --type build --periodicity daily --time_period morning --action "Roll mat out"
```
```text
✔ Success: Created new build habit 'Yoga'!
```
```bash
$ python main.py create --name D --type break --periodicity daily --time_period evening
```
```text
❌ Error: Habit type 'break' requires the --replacement argument.
```
```bash
$ python main.py create --name D --type break --periodicity daily --time_period evening --replacement "Walk 5 minutes"
```
```text
✔ Success: Created new break habit 'D'!
```
```bash
$ python main.py create --name yoga --type build --periodicity daily --time_period morning
```
```text
❌ Error: A habit named 'yoga' already exists.
```

### `urge` - log an urge for a Break habit

```bash
$ python main.py urge --name D --replaced yes
```
```text
✔ Success: Urge logged for 'D'. Replaced: yes
```

### `micro` - log a micro-action for a Build habit

```bash
$ python main.py micro --name "Wake Anchor" --did_it yes
```
```text
✔ Success: Micro-action logged for 'Wake Anchor'. Success rate: 80.0%
```

### `delete` - delete a habit and everything attached to it

Its completions and urge logs are removed too (cascading delete).

```bash
$ python main.py delete --name Yoga
```
```text
✔ Success: Habit 'Yoga' and all associated data deleted.
```

### `analyze` - functional analytics

```bash
$ python main.py analyze --list-all
```
```text
[ All Tracked Habits ]
  • Wake Anchor
  • Morning Protein
  • Idea Capture
  • Study Block
  • Fast Dopamine
  • D
```
```bash
$ python main.py analyze --by-period weekly
```
```text
[ Habits by Period: WEEKLY ]
  • Study Block
```
```bash
$ python main.py analyze --by-type break
```
```text
[ Habits by Type: BREAK ]
  • Fast Dopamine
  • D
```
```bash
$ python main.py analyze --streak-all
```
```text
[ Global Longest Streak ]
  🏆 Morning Protein (15 streak)
```
```bash
$ python main.py analyze --streak-habit "Wake Anchor"
```
```text
[ Longest Streak for 'Wake Anchor' ]
  🔥 8
```
```bash
$ python main.py analyze --ranking
```
```text
[ Streak Leaderboard ]
  1. Morning Protein - 15 streak
  2. Wake Anchor - 8 streak
  3. Idea Capture - 6 streak
  4. Study Block - 3 streak
  5. Fast Dopamine - 3 streak
  6. D - 0 streak
```
```bash
$ python main.py analyze --struggled
```
```text
[ Most Struggled Habit ]
  ⚠️ D (Max Streak: 0)
```

`--struggled` returns the habit with the lowest *longest-streak record of all time* (on a tie, the one created first). Daily streaks count days and weekly streaks count weeks, so those two numbers are not directly comparable.

---

## Completion date and time

Each row of the `completions` table keeps two values: `completion_date` (the day, `YYYY-MM-DD`, which drives streaks and the "one completion per habit per day" rule) and `completed_at` (the full moment, `YYYY-MM-DDTHH:MM:SS`). The clock is read in one place, `helper.get_now()`. **Upgrading:** an older `habits.db` without `completed_at` is upgraded automatically the next time you run any command; its existing completions simply show `(time not recorded)`.

## How streaks work

* **Daily:** a streak is a run of consecutive calendar days. It is still alive today if the last completion was today or yesterday.
* **Weekly:** a streak is a run of consecutive ISO calendar weeks (Monday-Sunday). Several completions in one week count once. It is still alive during the week after the last completion. Weeks are counted so that 52- and 53-week years work: 2020-W53 -> 2021-W01 is consecutive, while 2020-W52 -> 2021-W01 skips a week.
* `Habit.get_streak()` and `Habit.get_longest_streak()` only read the completion days; they never change the habit. The `longest_streak` column in the database is written when a habit is saved. The current streak is shown by `history`.

## Running the tests

```bash
pip install -r requirements.txt
pytest -q
```

> **Windows:** if `pytest` is "not recognized", run `python -m pytest -q` instead. To delete the database use `del habits.db` (Windows) or `rm habits.db` (macOS/Linux).
```text
97 passed
```

The tests use an in-memory SQLite database and a frozen "today" and "now" (09:30), so they never modify your real `habits.db` and give the same result at any time of day. They cover habit creation, completion (date and time), streaks, every `analyze` flag, the dashboard, the database upgrade and output that is redirected on Windows (cp1252). The end-to-end tests copy the source files into an empty temporary folder and run `seed.py` / `main.py` there, exactly like a fresh clone.

## Project layout

| File | Role |
|---|---|
| `habit.py` | OOP core: abstract `Habit`, `Build`, `Break`, plus the pure streak functions. |
| `db.py` | SQLite layer: schema (`habits`, `completions` with `completion_date` + `completed_at`, `urge_logs`), saving, loading, `remove_completion`, automatic upgrade of older databases. The database is `habits.db` next to the code, so it works from any folder. |
| `analytics.py` | Functional analytics (pure functions using `map`, `filter`, `max`, `min`, `sorted`). |
| `main.py` | `argparse` command-line interface (10 subcommands) and dashboard. Creates the tables on startup. |
| `seed.py` | Sample data. Reuses `db.py` for the schema and inserts. |
| `helper.py` | Clock helpers (`get_current_time_period`, `get_today`, `get_now`). |
| `test_habits.py` | pytest suite. |
| `requirements.txt` | `pytest>=7` (tests only). |
| `.gitignore` | Keeps `__pycache__/` and `.pytest_cache/` out of the repository. |
| `habits.db` | The SQLite database (created on first run; this copy is seeded). |
