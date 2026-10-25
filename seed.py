"""seed.py - fill habits.db with 5 predefined habits and 4 weeks of sample tracking data.

It reuses db.py for everything (schema, inserts), never deletes a database file, and uses
random.Random(42) so the sample data is identical on every run. Every sample completion has a
date AND a time of day inside the habit's time period (morning 06-11, afternoon 12-17, evening
18-23, night 00-05); the times come from a second seeded generator, so they never change which
days were completed. If the database already holds habits, seeding aborts and changes nothing.
"""
import random
from datetime import date, datetime, time, timedelta
from typing import List, Optional

import db
from habit import Break, Build, Habit, Periodicity, TimePeriod
from helper import get_today, make_output_safe

SEED = 42
DAYS = 28
PERIOD_START_HOUR = {TimePeriod.MORNING: 6, TimePeriod.AFTERNOON: 12,
                     TimePeriod.EVENING: 18, TimePeriod.NIGHT: 0}  # each period lasts 6 hours


def _completion_time(time_rng: random.Random, day: date, period: TimePeriod) -> datetime:
    """Return a random time on ``day`` inside the 6-hour window of ``period`` (to the minute)."""
    start = PERIOD_START_HOUR[period] * 60
    minute_of_day = time_rng.randrange(start, start + 6 * 60)
    return datetime.combine(day, time(minute_of_day // 60, minute_of_day % 60))


def _daily_completions(rng: random.Random, start: date, successes_per_week: List[int]) -> List[date]:
    """Return completion dates for 4 weeks, picking which days succeed with the seeded RNG."""
    dates = []
    for week, successes in enumerate(successes_per_week):
        days_pool = [True] * successes + [False] * (7 - successes)
        rng.shuffle(days_pool)
        dates.extend(start + timedelta(days=week * 7 + offset)
                     for offset, done in enumerate(days_pool) if done)
    return dates


def _micro_actions(habit: Build, attempts: int, successes: int) -> None:
    """Log ``attempts`` micro-actions of which ``successes`` were done."""
    for i in range(attempts):
        habit.log_micro_action(i < successes)


def build_sample_habits(today: date, rng: random.Random,
                        time_rng: Optional[random.Random] = None) -> List[Habit]:
    """Create the 5 predefined habits (4 daily, 1 weekly) with their history, in memory only."""
    start = today - timedelta(days=DAYS)
    time_rng = time_rng or random.Random(SEED + 1)  # separate generator: times never move the dates

    h1 = Build("Wake Anchor", None, start, Periodicity.DAILY, TimePeriod.MORNING, 30, "30 days",
               "Feet on floor within 60 seconds")
    h2 = Build("Morning Protein", None, start, Periodicity.DAILY, TimePeriod.MORNING, 30, "30 days",
               "Eggs, meat, or dairy within 30 mins")
    h3 = Build("Idea Capture", None, start, Periodicity.DAILY, TimePeriod.AFTERNOON, 30, "30 days",
               "Write off-task thought in notes app")
    h4 = Build("Study Block", None, start, Periodicity.WEEKLY, TimePeriod.AFTERNOON, 30, "30 days",
               "Set visible 45-min timer")
    h5 = Break("Fast Dopamine", None, start, Periodicity.DAILY, TimePeriod.EVENING,
               "Pause. Open app. Log urge. Do panoramic gaze 20 seconds.")

    daily_targets = {h1: [4, 5, 6, 7], h2: [5, 6, 7, 7], h3: [3, 4, 6, 6], h5: [2, 3, 3, 3]}
    for habit, per_week in daily_targets.items():
        for d in _daily_completions(rng, start, per_week):
            habit.record_completion(d, _completion_time(time_rng, d, habit.time_period))

    # Weekly habit: at most ONE completion per week; week 1 missed, weeks 2-4 done.
    for week in (1, 2, 3):
        done_on = start + timedelta(days=week * 7)
        h4.record_completion(done_on, _completion_time(time_rng, done_on, h4.time_period))

    _micro_actions(h1, 4, 3)
    _micro_actions(h2, 2, 2)
    _micro_actions(h3, 6, 5)
    _micro_actions(h4, 5, 3)

    # Fast Dopamine: 20 urges, 11 replaced - real log rows, so the counters match them.
    replaced_flags = [True] * 11 + [False] * 9
    rng.shuffle(replaced_flags)
    urge_days = sorted(rng.randrange(DAYS) for _ in replaced_flags)
    for day, replaced in zip(urge_days, replaced_flags):
        h5.log_urge(start + timedelta(days=day), replaced)

    return [h1, h2, h3, h4, h5]


def seed_database(today: Optional[date] = None) -> bool:
    """Seed the database; return False (changing nothing) if it already contains habits."""
    db.init_db()
    if db.get_all_habits():
        print("\n❌ Seeding aborted: the database already contains habit data.")
        print("   (Nothing was changed. To start over, delete habits.db yourself and run again.)")
        return False

    habits = build_sample_habits(today or get_today(), random.Random(SEED))
    for habit in habits:
        db.add_habit(habit)
        for completion_date in habit.completion_dates:
            db.add_completion(habit.id, completion_date, habit.completion_times.get(completion_date))
        if isinstance(habit, Break):
            for urge in habit.urge_logs:
                db.add_urge(habit.id, urge["logged_at"], 1 if urge["replaced"] else 0)

    print("✔ Database seeding completed successfully! {} habits created in {}".format(len(habits), db.DB_PATH.name))
    return True


if __name__ == "__main__":
    make_output_safe()
    seed_database()
