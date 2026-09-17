"""Persistence layer.

Reads and writes tickets as CSV or JSON. Every public function degrades
gracefully: a missing file yields an empty list rather than a crash, and a
malformed row is skipped with a warning instead of aborting the whole load.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Ticket, ValidationError

CSV_COLUMNS = [
    "ticket_id",
    "title",
    "description",
    "reporter",
    "category",
    "severity",
    "created_at",
    "status",
    "assignee",
    "priority",
    "score",
    "history",
]


class StorageError(Exception):
    """Raised when a file cannot be read or written at all."""


def load_tickets(path: str | Path) -> list[Ticket]:
    """Load tickets from a ``.csv`` or ``.json`` file.

    Args:
        path: Location of the dataset.

    Returns:
        Every ticket that could be parsed. An empty list if the file does
        not exist yet, which is the normal state on a first run.

    Raises:
        StorageError: If the file exists but cannot be read or parsed.
    """
    path = Path(path)
    if not path.exists():
        print(f"[warn] {path} not found - starting with an empty ticket list.")
        return []

    try:
        if path.suffix.lower() == ".json":
            rows = _read_json(path)
        elif path.suffix.lower() == ".csv":
            rows = _read_csv(path)
        else:
            raise StorageError(f"Unsupported file type: {path.suffix or 'none'}")
    except (OSError, UnicodeDecodeError) as exc:
        raise StorageError(f"Could not read {path}: {exc}") from exc

    tickets: list[Ticket] = []
    for line_no, row in enumerate(rows, start=2):
        try:
            tickets.append(Ticket.from_dict(row))
        except ValidationError as exc:
            print(f"[warn] Skipping row {line_no} in {path.name}: {exc}")
    return tickets


def save_tickets(tickets: list[Ticket], path: str | Path) -> Path:
    """Write tickets to ``.csv`` or ``.json``, creating parent folders.

    Returns:
        The path written to.

    Raises:
        StorageError: If the file cannot be written.
    """
    path = Path(path)
    records = [ticket.to_dict() for ticket in tickets]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".json":
            path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        elif path.suffix.lower() == ".csv":
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(records)
        else:
            raise StorageError(f"Unsupported file type: {path.suffix or 'none'}")
    except OSError as exc:
        raise StorageError(f"Could not write {path}: {exc}") from exc
    return path


def next_ticket_id(tickets: list[Ticket]) -> str:
    """Return the next free identifier, e.g. ``TCK-0007``."""
    numbers = []
    for ticket in tickets:
        try:
            numbers.append(int(ticket.ticket_id.split("-")[1]))
        except (IndexError, ValueError):
            continue
    return f"TCK-{max(numbers, default=0) + 1:04d}"


def _read_csv(path: Path) -> list[dict]:
    """Read a CSV file into a list of dictionaries."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise StorageError(f"{path.name} is empty or has no header row")
        return list(reader)


def _read_json(path: Path) -> list[dict]:
    """Read a JSON file that holds a list of ticket objects."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise StorageError(f"{path.name} must contain a list of tickets")
    return payload
