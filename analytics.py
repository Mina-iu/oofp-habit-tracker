"""analytics.py - the functional-programming analytics engine for the Habit Tracker.

Every function here is pure: it never changes a Habit, and the same input always gives the
same output. Streaks come from Habit.get_longest_streak(), which itself only reads the
completion history. The tools used are map(), filter(), max(), min() and sorted().
"""
from typing import List, Optional

from habit import Break, Build, Habit, Periodicity


def list_all_habits(habits: List[Habit]) -> List[str]:
    """Return the names of all habits (map + lambda)."""
    return list(map(lambda h: h.name, habits))


def filter_by_period(habits: List[Habit], target_periodicity: Periodicity) -> List[Habit]:
    """Return only the habits with the given periodicity (filter + lambda)."""
    return list(filter(lambda h: h.periodicity == target_periodicity, habits))


def filter_by_type(habits: List[Habit], target_type: str) -> List[Habit]:
    """Return only 'build' or 'break' habits (filter + isinstance); unknown types give []."""
    if target_type.lower() == "build":
        return list(filter(lambda h: isinstance(h, Build), habits))
    if target_type.lower() == "break":
        return list(filter(lambda h: isinstance(h, Break), habits))
    return []


def longest_streak_all_habits(habits: List[Habit]) -> Optional[Habit]:
    """Return the habit with the highest longest streak, or None if there are no habits (max)."""
    return max(habits, key=lambda h: h.get_longest_streak(), default=None)


def get_longest_streak_for_habit(habit: Habit) -> int:
    """Return the longest streak of one habit."""
    return habit.get_longest_streak()


def most_struggled_habit(habits: List[Habit]) -> Optional[Habit]:
    """Return the habit with the lowest longest streak, or None if there are no habits (min)."""
    return min(habits, key=lambda h: h.get_longest_streak(), default=None)


def streak_leaderboard(habits: List[Habit]) -> List[Habit]:
    """Return a new list of habits sorted from highest to lowest longest streak (sorted)."""
    return sorted(habits, key=lambda h: h.get_longest_streak(), reverse=True)
