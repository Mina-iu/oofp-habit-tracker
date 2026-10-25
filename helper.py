"""helper.py - small clock helpers, kept in one place so tests can replace them."""
import sys
from datetime import date, datetime


def get_current_time_period() -> str:
    """Return 'morning', 'afternoon', 'evening' or 'night' for the current local hour."""
    current_hour = datetime.now().hour
    if 6 <= current_hour < 12:
        return "morning"
    elif 12 <= current_hour < 18:
        return "afternoon"
    elif 18 <= current_hour < 24:
        return "evening"
    return "night"  # hours 0-5


def get_today() -> date:
    """Return today's local date."""
    return date.today()


def make_output_safe() -> None:
    """Make printing never crash on special characters such as the check mark or the star.

    On Windows, output that is redirected or piped (``> file.txt``, a test runner, a pipe) often uses
    a codepage like cp1252 that cannot encode those symbols. Instead of raising UnicodeEncodeError,
    anything that cannot be encoded is replaced by a question mark. A normal terminal is unaffected.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def get_now() -> datetime:
    """Return the current local date and time to the second (the clock used to stamp completions)."""
    return datetime.now().replace(microsecond=0)
