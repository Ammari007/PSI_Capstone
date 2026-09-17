"""Command line entry point for the triage tool.

Run it as a module from the project root::

    python -m src.main --help
    python -m src.main triage --input data/sample_data.csv
    python -m src.main interactive
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import data_handler, logic, utils
from .data_handler import StorageError
from .models import Ticket, TicketError, ValidationError

DEFAULT_INPUT = Path("data/sample_data.csv")
DEFAULT_OUTPUT = Path("data/triaged_tickets.csv")
DEFAULT_REPORT = Path("data/category_report.csv")
DEFAULT_CHART = Path("data/priority_chart.png")


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------
def cmd_triage(args: argparse.Namespace) -> int:
    """Triage every untriaged ticket in the input file and save the results."""
    tickets = data_handler.load_tickets(args.input)
    if not tickets:
        utils.say("Nothing to triage.")
        return 1

    processed = logic.triage_all(tickets, only_new=not args.retriage)
    utils.say(f"Triaged {len(processed)} of {len(tickets)} tickets.")
    _show_queue(logic.sort_by_urgency(tickets), limit=args.limit)

    data_handler.save_tickets(tickets, args.output)
    utils.say(f"Saved tickets to {args.output}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Print and export a summary of the tickets in the input file."""
    tickets = data_handler.load_tickets(args.input)
    if not tickets:
        utils.say("Nothing to report on.")
        return 1

    counts = logic.priority_counts(tickets)
    utils.render_table(
        "Priority breakdown",
        ["Priority", "Tickets"],
        [[label, int(value)] for label, value in counts.items()],
    )

    summary = logic.summarise(tickets)
    utils.render_table(
        "Category summary",
        list(summary.columns),
        summary.values.tolist(),
    )

    report_path = logic.export_report(tickets, args.report)
    utils.say(f"Report written to {report_path}")

    chart_path = logic.save_priority_chart(tickets, args.chart)
    if chart_path:
        utils.say(f"Chart written to {chart_path}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Prompt for a new ticket, triage it and append it to the dataset."""
    tickets = data_handler.load_tickets(args.input)
    try:
        ticket = Ticket(
            ticket_id=data_handler.next_ticket_id(tickets),
            title=utils.prompt("Title", lambda v: utils.clean_text(v, "Title")),
            description=utils.prompt(
                "Description", lambda v: utils.clean_text(v, "Description", 500)
            ),
            reporter=utils.prompt("Reporter", lambda v: utils.clean_text(v, "Reporter", 80)),
            category=utils.prompt("Category", utils.parse_category),
            severity=utils.prompt("Severity (1-5)", utils.parse_severity),
        )
    except ValidationError as exc:
        utils.say(f"Ticket not created: {exc}")
        return 1

    logic.triage_ticket(ticket)
    tickets.append(ticket)
    data_handler.save_tickets(tickets, args.input)
    utils.say(f"Created {ticket} -> {ticket.assignee} (score {ticket.score})")
    return 0


def cmd_interactive(args: argparse.Namespace) -> int:
    """Run the menu-driven interface until the user quits."""
    menu = {
        "1": ("Triage new tickets", cmd_triage),
        "2": ("Show report", cmd_report),
        "3": ("Add a ticket", cmd_add),
    }
    while True:
        utils.say("\n=== Triage console ===")
        for key, (label, _) in menu.items():
            utils.say(f"  {key}. {label}")
        utils.say("  q. Quit")
        try:
            choice = input("Choose an option: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            utils.say("\nBye.")
            return 0
        if choice in ("q", "quit", "exit"):
            utils.say("Bye.")
            return 0
        if choice not in menu:
            utils.say("Please choose 1, 2, 3 or q.")
            continue
        try:
            menu[choice][1](args)
        except (TicketError, StorageError) as exc:
            utils.say(f"Something went wrong: {exc}")


# ----------------------------------------------------------------------
# Helpers and wiring
# ----------------------------------------------------------------------
def _show_queue(tickets: list[Ticket], limit: int) -> None:
    """Render the top of the triage queue as a table."""
    rows = [
        [t.ticket_id, t.priority, t.score, t.category, t.assignee, t.title[:40]]
        for t in tickets[:limit]
    ]
    utils.render_table(
        f"Triage queue (top {min(limit, len(tickets))})",
        ["ID", "Priority", "Score", "Category", "Owner", "Title"],
        rows,
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with one subcommand per action."""
    # Shared options live on a parent parser so they are accepted both before
    # and after the subcommand name.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input CSV or JSON file")
    common.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Where to save results")
    common.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Summary CSV path")
    common.add_argument("--chart", type=Path, default=DEFAULT_CHART, help="Chart image path")
    common.add_argument("--limit", type=int, default=10, help="Rows shown in the queue table")
    common.add_argument(
        "--retriage", action="store_true", help="Re-score tickets that were already triaged"
    )

    parser = argparse.ArgumentParser(
        prog="triage",
        parents=[common],
        description="Score, prioritise and route support tickets end to end.",
    )
    subparsers = parser.add_subparsers(dest="command")
    for name, help_text, handler in (
        ("triage", "Triage untriaged tickets", cmd_triage),
        ("report", "Summarise the dataset", cmd_report),
        ("add", "Add a ticket interactively", cmd_add),
        ("interactive", "Menu-driven mode", cmd_interactive),
    ):
        subparsers.add_parser(name, parents=[common], help=help_text).set_defaults(func=handler)

    parser.set_defaults(func=cmd_interactive)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch, converting known errors into exit codes."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except StorageError as exc:
        utils.say(f"Storage error: {exc}")
        return 2
    except TicketError as exc:
        utils.say(f"Ticket error: {exc}")
        return 3
    except KeyboardInterrupt:
        utils.say("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
