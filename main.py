"""main.py - command-line interface: parses arguments and routes them to db.py and analytics.py."""
import argparse
import sys
from datetime import date
from typing import Callable, Dict

import analytics
import db
from habit import Break, Build, Habit, Periodicity, TimePeriod
from helper import get_current_time_period, get_now, get_today, make_output_safe

RED = "\033[91m"
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RESET = "\033[0m"


# ---------------------------------------------------------------------
# Small output helpers
# ---------------------------------------------------------------------

def _ok(message: str) -> None:
    """Print a green success message."""
    print(f"\n{GREEN}✔ Success: {message}{RESET}")


def _error(message: str) -> None:
    """Print a red error message."""
    print(f"\n{RED}❌ Error: {message}{RESET}")


def _info(message: str) -> None:
    """Print a yellow informational message."""
    print(f"\n{YELLOW}ℹ {message}{RESET}")


# ---------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Create the argparse parser with every subcommand."""
    parser = argparse.ArgumentParser(description="My Habit Tracker Dashboard")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    subparsers.add_parser("view", aliases=["summary", "list"], help="Display your dynamic colored dashboard queue")

    check_parser = subparsers.add_parser("checkoff", help="Mark a habit as completed by ID")
    check_parser.add_argument('--id', type=int, required=True, help="Habit database ID")

    checkin_parser = subparsers.add_parser("checkin", help="Mark a habit as completed by name")
    checkin_parser.add_argument('--name', type=str, required=True, help="Habit name")

    undo_parser = subparsers.add_parser("uncomplete", help="Undo today's completion of a habit")
    undo_parser.add_argument('--name', type=str, required=True, help="Habit name")

    create_parser = subparsers.add_parser("create", aliases=["add"], help="Create a new habit track")
    create_parser.add_argument('--name', type=str, required=True, help="The name of the habit")
    create_parser.add_argument('--type', type=str, required=True, choices=['build', 'break'],
                               help="Habit type: 'build' or 'break'")
    create_parser.add_argument('--periodicity', type=str, required=True, choices=['daily', 'weekly'],
                               help="The periodicity ('daily' or 'weekly')")
    create_parser.add_argument('--time_period', type=str, required=True,
                               choices=['morning', 'afternoon', 'evening', 'night'], help="The time period")
    create_parser.add_argument('--action', type=str, default="Default action", help="Micro action to perform")
    create_parser.add_argument('--replacement', type=str, help="Replacement action (REQUIRED if type is 'break')")

    delete_parser = subparsers.add_parser("delete", help="Delete a habit and all its data")
    delete_parser.add_argument('--name', type=str, required=True, help="Name of the habit to delete")

    urge_parser = subparsers.add_parser("urge", help="Log an urge for a break habit")
    urge_parser.add_argument('--name', type=str, required=True, help="Name of the break habit")
    urge_parser.add_argument('--replaced', type=str, required=True, choices=['yes', 'no'],
                             help="Did you do the replacement? (yes/no)")

    micro_parser = subparsers.add_parser("micro", help="Log a micro-action for a build habit")
    micro_parser.add_argument('--name', type=str, required=True, help="Name of the build habit")
    micro_parser.add_argument('--did_it', type=str, required=True, choices=['yes', 'no'],
                              help="Did you do the micro-action? (yes/no)")

    history_parser = subparsers.add_parser("history", help="Show when a habit was completed (date and time)")
    history_parser.add_argument('--name', type=str, required=True, help="Habit name")
    history_parser.add_argument('--limit', type=int, default=10,
                                help="How many of the newest completions to show (default 10; 0 = all)")

    analyze_parser = subparsers.add_parser("analyze", help="Run functional analytics")
    analyze_parser.add_argument('--list-all', action='store_true', help="List all current habits")
    analyze_parser.add_argument('--by-period', type=str, choices=['daily', 'weekly'], help="List habits by periodicity")
    analyze_parser.add_argument('--by-type', type=str, choices=['build', 'break'], help="List habits by type")
    analyze_parser.add_argument('--streak-all', action='store_true', help="Return longest streak of ALL habits")
    analyze_parser.add_argument('--streak-habit', type=str, help="Return longest streak for a GIVEN habit name")
    analyze_parser.add_argument('--ranking', action='store_true', help="View streak leaderboard")
    analyze_parser.add_argument('--struggled', action='store_true', help="View the habit you struggled with most")
    return parser


# ---------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------

def _complete_today(target: Habit, label: str) -> None:
    """Complete a habit for today, stamped with the current date and time, unless already done."""
    now = get_now()
    today = now.date()
    if today in target.completion_dates:
        _info(f"{label} is already complete today.")
        return
    target.record_completion(today, now)
    db.add_completion(target.id, today, now)
    db.update_habit(target)
    _ok(f"{label} has been marked complete for today!")


def cmd_checkoff(args: argparse.Namespace) -> None:
    """Handle `checkoff --id`: complete a habit by database ID."""
    target = next((h for h in db.load_habits_from_db() if h.id == args.id), None)
    if target is None:
        _error(f"Habit {args.id} not found.")
        return
    _complete_today(target, f"Habit {args.id}")


def cmd_checkin(args: argparse.Namespace) -> None:
    """Handle `checkin --name`: complete a habit by name."""
    target = db.get_habit_by_name(args.name)
    if target is None:
        _error(f"Habit '{args.name}' not found.")
        return
    _complete_today(target, f"'{target.name}'")


def cmd_uncomplete(args: argparse.Namespace) -> None:
    """Handle `uncomplete --name`: remove today's completion only."""
    target = db.get_habit_by_name(args.name)
    if target is None:
        _error(f"Habit '{args.name}' not found.")
        return
    if not target.uncomplete():
        _info(f"Nothing to undo: '{target.name}' has no completion for today.")
        return
    db.remove_completion(target.id, get_today())
    db.update_habit(target)
    _ok(f"Today's completion of '{target.name}' has been removed.")


def cmd_urge(args: argparse.Namespace) -> None:
    """Handle `urge`: log an urge for a Break habit."""
    target = db.get_habit_by_name(args.name)
    if target is None or not isinstance(target, Break):
        _error(f"Break habit '{args.name}' not found.")
        return
    replaced = args.replaced.lower() == 'yes'
    target.log_urge(get_today(), replaced)
    db.add_urge(target.id, get_today(), 1 if replaced else 0)
    db.update_habit(target)
    _ok(f"Urge logged for '{target.name}'. Replaced: {args.replaced}")


def cmd_micro(args: argparse.Namespace) -> None:
    """Handle `micro`: log a micro-action for a Build habit."""
    target = db.get_habit_by_name(args.name)
    if target is None or not isinstance(target, Build):
        _error(f"Build habit '{args.name}' not found.")
        return
    target.log_micro_action(args.did_it.lower() == 'yes')
    db.update_habit(target)
    _ok(f"Micro-action logged for '{target.name}'. Success rate: {target.get_micro_success_rate():.1f}%")


def cmd_create(args: argparse.Namespace) -> None:
    """Handle `create`/`add`: validate input and store a new Build or Break habit."""
    name = args.name.strip()
    if not name:
        _error("The habit name must not be empty.")
        return
    if args.type == 'break' and not args.replacement:
        _error("Habit type 'break' requires the --replacement argument.")
        return
    if db.get_habit_by_name(name):
        _error(f"A habit named '{name}' already exists.")
        return

    periodicity = Periodicity(args.periodicity)
    time_period = TimePeriod(args.time_period)
    if args.type == 'build':
        new_habit = Build(name, None, get_today(), periodicity, time_period,
                          duration=30, stop_condition="Forever", micro_action=args.action)
    else:
        new_habit = Break(name, None, get_today(), periodicity, time_period, replacement=args.replacement)

    db.add_habit(new_habit)
    _ok(f"Created new {args.type} habit '{name}'!")


def cmd_delete(args: argparse.Namespace) -> None:
    """Handle `delete`: remove a habit and all its data."""
    target = db.get_habit_by_name(args.name)
    if target is None:
        _error(f"Habit '{args.name}' not found.")
        return
    db.delete_habit(target.id)
    _ok(f"Habit '{args.name}' and all associated data deleted.")


def _count(number: int, word: str) -> str:
    """Return e.g. '1 day' or '3 days'."""
    return f"{number} {word}" if number == 1 else f"{number} {word}s"


def cmd_history(args: argparse.Namespace) -> None:
    """Handle `history`: list a habit's completions with date and time, newest first."""
    target = db.get_habit_by_name(args.name)
    if target is None:
        _error(f"Habit '{args.name}' not found.")
        return
    unit = "week" if target.periodicity == Periodicity.WEEKLY else "day"
    log = list(reversed(target.completion_log()))  # newest first
    print(f"\n{BLUE}[ Completion History: '{target.name}' ]{RESET}")
    print(f"  Current streak: {_count(target.get_streak(), unit)} | "
          f"Longest streak: {_count(target.get_longest_streak(), unit)} | Completions: {len(log)}")
    if not log:
        print("  No completions yet.")
        return
    shown = log[:args.limit] if args.limit > 0 else log
    for day, moment in shown:
        print(f"  {day.isoformat()}  {moment.strftime('%H:%M') if moment else '(time not recorded)'}")
    if len(log) > len(shown):
        print(f"  ... {_count(len(log) - len(shown), 'older completion')} not shown (use --limit 0 to see all)")


def cmd_analyze(args: argparse.Namespace) -> None:
    """Handle `analyze`: run one of the pure functions from analytics.py on the stored habits."""
    all_habits = db.load_habits_from_db()

    if args.list_all:
        print(f"\n{BLUE}[ All Tracked Habits ]{RESET}")
        for name in analytics.list_all_habits(all_habits):
            print(f"  • {name}")
    elif args.by_period:
        filtered = analytics.filter_by_period(all_habits, Periodicity(args.by_period.lower()))
        print(f"\n{BLUE}[ Habits by Period: {args.by_period.upper()} ]{RESET}")
        for h in filtered:
            print(f"  • {h.name}")
    elif args.by_type:
        filtered = analytics.filter_by_type(all_habits, args.by_type.lower())
        print(f"\n{BLUE}[ Habits by Type: {args.by_type.upper()} ]{RESET}")
        for h in filtered:
            print(f"  • {h.name}")
    elif args.streak_all:
        longest = analytics.longest_streak_all_habits(all_habits)
        if longest:
            print(f"\n{BLUE}[ Global Longest Streak ]{RESET}")
            print(f"  🏆 {longest.name} ({longest.get_longest_streak()} streak)")
        else:
            print("No habits tracked.")
    elif args.streak_habit:
        target = next((h for h in all_habits if h.name.lower() == args.streak_habit.lower()), None)
        if target:
            print(f"\n{BLUE}[ Longest Streak for '{target.name}' ]{RESET}")
            print(f"  🔥 {analytics.get_longest_streak_for_habit(target)}")
        else:
            _error(f"Habit '{args.streak_habit}' not found.")
    elif args.ranking:
        print(f"\n{BLUE}[ Streak Leaderboard ]{RESET}")
        for i, h in enumerate(analytics.streak_leaderboard(all_habits), 1):
            print(f"  {i}. {h.name} - {h.get_longest_streak()} streak")
    elif args.struggled:
        struggled = analytics.most_struggled_habit(all_habits)
        if struggled:
            print(f"\n{BLUE}[ Most Struggled Habit ]{RESET}")
            print(f"  ⚠️ {struggled.name} (Max Streak: {struggled.get_longest_streak()})")
        else:
            print("No habits tracked.")
    else:
        _error("Please provide an analysis flag (e.g., --list-all, --ranking).")


def _done_at(habit: Habit, day: date) -> str:
    """Return ' at HH:MM' when the completion time of ``day`` is known, else an empty string."""
    moment = habit.completion_times.get(day)
    return f" at {moment.strftime('%H:%M')}" if moment else ""


def display_dashboard() -> None:
    """Render the dashboard: habits due now, missed/later today, and weekly progress."""
    all_habits = db.load_habits_from_db()
    current_period = get_current_time_period()
    today = get_today()

    print("\n" + "=" * 50)
    print(f"      {BLUE}★ MY CURRENT HABIT QUEUE ★{RESET} ({current_period.upper()})")
    print("=" * 50)

    print(f"\n{YELLOW}[ DUE RIGHT NOW ]{RESET}")
    due_count = 0
    for habit in all_habits:
        if habit.periodicity.value == "daily" and habit.is_now_due():
            if today in habit.completion_dates:
                print(f"  ✓ ID: {habit.id} | {GREEN}{habit.name}{RESET} (Done{_done_at(habit, today)}!)")
            else:
                print(f"  → ID: {habit.id} | {YELLOW}{habit.name}{RESET} ({habit.time_period.value})")
            due_count += 1
    if due_count == 0:
        print("  None scheduled for this time frame.")

    print(f"\n{RED}[ MISSED OR LATER TODAY ]{RESET}")
    missed_count = 0
    for habit in all_habits:
        if habit.periodicity.value == "daily" and not habit.is_now_due():
            if today in habit.completion_dates:
                print(f"  ✓ ID: {habit.id} | {GREEN}{habit.name}{RESET} (Completed{_done_at(habit, today)})")
            else:
                print(f"  • ID: {habit.id} | {RED}{habit.name}{RESET} (Pending/Missed)")
            missed_count += 1
    if missed_count == 0:
        print("  No other daily habits tracked.")

    print(f"\n{BLUE}[ WEEKLY HABITS PROGRESS ]{RESET}")
    weekly_count = 0
    for habit in all_habits:
        if habit.periodicity.value == "weekly":
            print(f"  🗲 ID: {habit.id} | {BLUE}{habit.name}{RESET} "
                  f"(Longest Streak: {habit.get_longest_streak()} weeks)")
            weekly_count += 1
    if weekly_count == 0:
        print("  No weekly habits created yet.")

    print("\n" + "=" * 50)


def _view(args: argparse.Namespace) -> None:
    """Handle `view`/`summary`/`list`: show the dashboard."""
    display_dashboard()


COMMANDS: Dict[str, Callable[[argparse.Namespace], None]] = {
    "view": _view, "summary": _view, "list": _view,
    "checkoff": cmd_checkoff, "checkin": cmd_checkin, "uncomplete": cmd_uncomplete, "history": cmd_history,
    "create": cmd_create, "add": cmd_create, "delete": cmd_delete,
    "urge": cmd_urge, "micro": cmd_micro, "analyze": cmd_analyze,
}


def main() -> None:
    """Parse the command line, make sure the tables exist, and run the chosen command."""
    make_output_safe()
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return

    try:
        db.init_db()  # first run: create the tables so no seeding is needed
        COMMANDS[args.command](args)
    except db.DatabaseError as exc:
        _error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
