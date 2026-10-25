"""habit.py - the object-oriented core: Habit (abstract), Build and Break.

Every completion is stored with its date (used for streaks and the one-per-day rule) and the
time of day it was done. Streak maths lives in two module-level pure functions
(compute_current_streak and compute_longest_streak). They depend only on their arguments, so
the Habit methods that call them never modify the object.
"""
from abc import ABC, abstractmethod
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple

from helper import get_current_time_period, get_now, get_today


class Periodicity(Enum):
    """How often a habit must be completed."""

    DAILY = "daily"
    WEEKLY = "weekly"


class TimePeriod(Enum):
    """The part of the day a habit is meant to be done in."""

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


# =====================================================================
# PURE STREAK FUNCTIONS (no object state, no clock, no I/O)
# =====================================================================

def _week_number(d: date) -> int:
    """Return a running Monday-based week count; consecutive ISO weeks always differ by 1.

    Counting weeks this way (instead of comparing ISO week numbers) makes 52- and 53-week
    years work with no special case: 2020-W53 -> 2021-W01 differs by 1, while 2020-W52 ->
    2021-W01 (a skipped week) differs by 2.
    """
    return (d.toordinal() - d.weekday()) // 7


def _period_number(d: date, periodicity: Periodicity) -> int:
    """Map a date to the number of the day or ISO calendar week that contains it."""
    return d.toordinal() if periodicity == Periodicity.DAILY else _week_number(d)


def _distinct_periods(dates: Iterable[date], periodicity: Periodicity) -> List[int]:
    """Return the sorted, de-duplicated period numbers that contain at least one date."""
    return sorted({_period_number(d, periodicity) for d in dates})


def compute_current_streak(completion_dates: Iterable[date], periodicity: Periodicity,
                           as_of: date) -> int:
    """Return the run of consecutive days/ISO weeks that is still alive on ``as_of``."""
    periods = _distinct_periods((d for d in completion_dates if d <= as_of), periodicity)
    if not periods:
        return 0
    if _period_number(as_of, periodicity) - periods[-1] > 1:
        return 0  # a whole day/week was skipped, so the streak is broken
    streak = 1
    for i in range(len(periods) - 1, 0, -1):
        if periods[i] - periods[i - 1] != 1:
            break
        streak += 1
    return streak


def compute_longest_streak(completion_dates: Iterable[date], periodicity: Periodicity) -> int:
    """Return the longest run of consecutive days/ISO weeks anywhere in the history."""
    periods = _distinct_periods(completion_dates, periodicity)
    longest = run = 0
    previous = None
    for p in periods:
        run = run + 1 if previous is not None and p - previous == 1 else 1
        longest = max(longest, run)
        previous = p
    return longest


def _times_to_dict(times: Dict[date, datetime]) -> Dict[str, str]:
    """Serialize {day: datetime} to {ISO day: ISO datetime to the second}."""
    return {d.isoformat(): t.isoformat(timespec="seconds") for d, t in sorted(times.items())}


def _times_from_dict(raw: Optional[Dict[str, str]], days: Iterable[date]) -> Dict[date, datetime]:
    """Rebuild {day: datetime}, keeping only entries for days that really are completions."""
    wanted = set(days)
    restored = {}
    for day_text, time_text in (raw or {}).items():
        day = date.fromisoformat(day_text)
        if day in wanted and time_text:
            restored[day] = datetime.fromisoformat(time_text)
    return restored


# =====================================================================
# HABIT CLASSES
# =====================================================================

class Habit(ABC):
    """Abstract base class holding what Build and Break habits share."""

    def __init__(self, name: str, id: Optional[int], creation_date: date,
                 periodicity: Periodicity, time_period: TimePeriod) -> None:
        """Create a habit with an empty completion history."""
        self._name = name
        self._id = id
        self._creation_date = creation_date
        self._periodicity = periodicity
        self._time_period = time_period
        self._completion_dates: List[date] = []          # one date per completed day (drives streaks)
        self._completion_times: Dict[date, datetime] = {}  # when on that day it was done

    @property
    def name(self) -> str:
        """The habit's unique name."""
        return self._name

    @property
    def id(self) -> Optional[int]:
        """The database id, or None until the habit has been saved."""
        return self._id

    @id.setter
    def id(self, value: Optional[int]) -> None:
        """Set the database id (done by db.add_habit after the INSERT)."""
        self._id = value

    @property
    def creation_date(self) -> date:
        """The day the habit was created."""
        return self._creation_date

    @property
    def periodicity(self) -> Periodicity:
        """Whether the habit is daily or weekly."""
        return self._periodicity

    @property
    def time_period(self) -> TimePeriod:
        """The part of the day the habit belongs to."""
        return self._time_period

    @property
    def completion_dates(self) -> List[date]:
        """The sorted days on which the habit was completed."""
        return self._completion_dates

    @property
    def completion_times(self) -> Dict[date, datetime]:
        """A copy of {day: date and time of day} for completions that have a recorded time."""
        return dict(self._completion_times)

    @property
    def longest_streak(self) -> int:
        """The longest streak, always computed from the completion history."""
        return self.get_longest_streak()

    def is_now_due(self) -> bool:
        """Return True while the current time of day matches this habit's time period."""
        return get_current_time_period() == self._time_period.value

    def record_completion(self, on: date, at: Optional[datetime] = None) -> bool:
        """Record a completion on ``on`` (kept sorted); return False if it was already there.

        ``at`` is the exact date and time it was done. It must fall on the day ``on``. The first
        completion of a day wins, so a second one never replaces the stored time.
        """
        if at is not None and at.date() != on:
            raise ValueError("completion time {} is not on {}".format(at.isoformat(), on.isoformat()))
        if on in self._completion_dates:
            return False
        self._completion_dates.append(on)
        self._completion_dates.sort()
        if at is not None:
            self._completion_times[on] = at
        return True

    def complete(self) -> bool:
        """Mark the habit complete right now (date and time); return False if today was already done."""
        now = get_now()
        return self.record_completion(now.date(), now)

    def uncomplete(self) -> bool:
        """Remove today's completion only; return True if one was removed, else False."""
        today = get_today()
        if today in self._completion_dates:
            self._completion_dates.remove(today)
            self._completion_times.pop(today, None)
            return True
        return False

    def completion_log(self) -> List[Tuple[date, Optional[datetime]]]:
        """Return (day, datetime or None) for every completion, oldest first.

        The datetime is None only for completions stored without a time (old databases).
        """
        return [(d, self._completion_times.get(d)) for d in self._completion_dates]

    def get_lifetime_progress(self) -> int:
        """Return the total number of completions ever recorded."""
        return len(self._completion_dates)

    def get_streak(self, as_of: Optional[date] = None) -> int:
        """Return the current streak as of a date (default today) without changing the object."""
        return compute_current_streak(self._completion_dates, self._periodicity,
                                      as_of if as_of is not None else get_today())

    def get_longest_streak(self) -> int:
        """Return the longest streak in the full history without changing the object."""
        return compute_longest_streak(self._completion_dates, self._periodicity)

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Serialize the habit to a plain dictionary."""

    @classmethod
    @abstractmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Habit":
        """Rebuild a habit from a dictionary made by to_dict()/the database layer."""


class Build(Habit):
    """A positive behaviour to adopt, with micro-action tracking."""

    def __init__(self, name: str, id: Optional[int], creation_date: date, periodicity: Periodicity,
                 time_period: TimePeriod, duration: int, stop_condition: str,
                 micro_action: str) -> None:
        """Create a Build habit with zero micro-action attempts."""
        super().__init__(name, id, creation_date, periodicity, time_period)
        self._duration = duration
        self._stop_condition = stop_condition
        self._micro_action = micro_action
        self._total_micro_attempts = 0
        self._successful_micro_actions = 0

    @property
    def duration(self) -> int:
        """How many periods the habit is meant to be kept up."""
        return self._duration

    @property
    def stop_condition(self) -> str:
        """When the habit is considered finished."""
        return self._stop_condition

    @property
    def micro_action(self) -> str:
        """The tiny first step that makes starting easy."""
        return self._micro_action

    @property
    def total_micro_attempts(self) -> int:
        """How many micro-action attempts have been logged."""
        return self._total_micro_attempts

    @property
    def successful_micro_actions(self) -> int:
        """How many logged micro-action attempts were actually done."""
        return self._successful_micro_actions

    def log_micro_action(self, did_it: bool) -> None:
        """Record one micro-action attempt and whether it was done."""
        self._total_micro_attempts += 1
        if did_it:
            self._successful_micro_actions += 1

    def get_micro_success_rate(self) -> float:
        """Return the percentage of micro-action attempts that were done."""
        if self._total_micro_attempts == 0:
            return 0
        return (self._successful_micro_actions / self._total_micro_attempts) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the Build habit to a dictionary."""
        return {
            "id": self._id,
            "name": self._name,
            "creation_date": self._creation_date.isoformat(),
            "periodicity": self._periodicity.value,
            "time_period": self._time_period.value,
            "longest_streak": self.get_longest_streak(),
            "completion_dates": [d.isoformat() for d in self._completion_dates],
            "completed_at": _times_to_dict(self._completion_times),
            "type": "build",
            "duration": self._duration,
            "stop_condition": self._stop_condition,
            "micro_action": self._micro_action,
            "total_micro_attempts": self._total_micro_attempts,
            "successful_micro_actions": self._successful_micro_actions
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Build":
        """Deserialize a dictionary into a live Build object."""
        new_habit = cls(
            name=data["name"],
            id=data["id"],
            creation_date=date.fromisoformat(data["creation_date"]),
            periodicity=Periodicity(data["periodicity"]),
            time_period=TimePeriod(data["time_period"]),
            duration=data["duration"],
            stop_condition=data["stop_condition"],
            micro_action=data["micro_action"]
        )
        # The stored "longest_streak" is deliberately ignored: it is a derived value.
        new_habit._completion_dates = sorted(date.fromisoformat(d) for d in data.get("completion_dates", []))
        new_habit._completion_times = _times_from_dict(data.get("completed_at"), new_habit._completion_dates)
        new_habit._total_micro_attempts = data.get("total_micro_attempts") or 0
        new_habit._successful_micro_actions = data.get("successful_micro_actions") or 0
        return new_habit


class Break(Habit):
    """A negative behaviour to eliminate; tracks urges and healthy replacements."""

    def __init__(self, name: str, id: Optional[int], creation_date: date, periodicity: Periodicity,
                 time_period: TimePeriod, replacement: str) -> None:
        """Create a Break habit with no urges logged yet."""
        super().__init__(name, id, creation_date, periodicity, time_period)
        self._replacement = replacement
        self._urge_logs: List[Dict[str, Any]] = []
        self._total_urges_logged = 0
        self._successful_replacements = 0

    @property
    def replacement(self) -> str:
        """The healthy action to do instead of the bad habit."""
        return self._replacement

    @property
    def total_urges_logged(self) -> int:
        """How many urges have been logged."""
        return self._total_urges_logged

    @property
    def successful_replacements(self) -> int:
        """How many urges were answered with the replacement."""
        return self._successful_replacements

    @property
    def urge_logs(self) -> List[Dict[str, Any]]:
        """A copy of the urge log entries ({'logged_at': date, 'replaced': bool})."""
        return list(self._urge_logs)

    def log_urge(self, logged_at: date, did_replacement: bool) -> None:
        """Log an urge and whether the healthy replacement was performed."""
        self._urge_logs.append({"logged_at": logged_at, "replaced": did_replacement})
        self._total_urges_logged += 1
        if did_replacement:
            self._successful_replacements += 1

    def replacement_rate(self) -> float:
        """Return the percentage of urges that were answered with the replacement."""
        if self._total_urges_logged == 0:
            return 0
        return (self._successful_replacements / self._total_urges_logged) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the Break habit (including urge logs) to a dictionary."""
        serialized_urges = []
        for urge in self._urge_logs:
            logged_at = urge["logged_at"]
            if isinstance(logged_at, date):
                logged_at = logged_at.isoformat()
            serialized_urges.append({"logged_at": logged_at, "replaced": urge["replaced"]})

        return {
            "id": self._id,
            "name": self._name,
            "creation_date": self._creation_date.isoformat(),
            "periodicity": self._periodicity.value,
            "time_period": self._time_period.value,
            "longest_streak": self.get_longest_streak(),
            "completion_dates": [d.isoformat() for d in self._completion_dates],
            "completed_at": _times_to_dict(self._completion_times),
            "type": "break",
            "replacement": self._replacement,
            "urge_logs": serialized_urges,
            "total_urges_logged": self._total_urges_logged,
            "successful_replacements": self._successful_replacements
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Break":
        """Deserialize a dictionary into a live Break object."""
        new_habit = cls(
            name=data["name"],
            id=data["id"],
            creation_date=date.fromisoformat(data["creation_date"]),
            periodicity=Periodicity(data["periodicity"]),
            time_period=TimePeriod(data["time_period"]),
            replacement=data["replacement"]
        )
        new_habit._completion_dates = sorted(date.fromisoformat(d) for d in data.get("completion_dates", []))
        new_habit._completion_times = _times_from_dict(data.get("completed_at"), new_habit._completion_dates)
        new_habit._total_urges_logged = data.get("total_urges_logged") or 0
        new_habit._successful_replacements = data.get("successful_replacements") or 0

        restored_urges = []
        for urge in data.get("urge_logs", []):
            logged_date = urge["logged_at"]
            if isinstance(logged_date, str):
                logged_date = date.fromisoformat(logged_date)
            restored_urges.append({"logged_at": logged_date, "replaced": bool(urge["replaced"])})
        new_habit._urge_logs = restored_urges
        return new_habit
