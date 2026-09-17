"""Helper functions: input validation, prompting and console formatting.

Nothing in this module knows about triage rules; it only deals with turning
untrusted text into clean values and printing tables to the terminal.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence, TypeVar

from .models import VALID_CATEGORIES, ValidationError

T = TypeVar("T")

# ``rich`` makes the output nicer but the tool must still run without it.
try:  # pragma: no cover - depends on the environment
    from rich.console import Console
    from rich.table import Table

    _CONSOLE: "Console | None" = Console()
except ImportError:  # pragma: no cover
    _CONSOLE = None


def clean_text(value: str, field_name: str, max_length: int = 200) -> str:
    """Strip and length-check a free text field.

    Args:
        value: Raw user input.
        field_name: Used in the error message.
        max_length: Maximum accepted number of characters.

    Returns:
        The trimmed string.

    Raises:
        ValidationError: If the field is blank or too long.
    """
    cleaned = " ".join(str(value).split())
    if not cleaned:
        raise ValidationError(f"{field_name} must not be empty")
    if len(cleaned) > max_length:
        raise ValidationError(f"{field_name} must be {max_length} characters or fewer")
    return cleaned


def parse_severity(value: str) -> int:
    """Convert user input into a severity between 1 and 5.

    Raises:
        ValidationError: If the value is not an integer in range.
    """
    try:
        severity = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Severity must be a whole number, got {value!r}") from exc
    if not 1 <= severity <= 5:
        raise ValidationError("Severity must be between 1 and 5")
    return severity


def parse_category(value: str) -> str:
    """Normalise and validate a category name.

    Raises:
        ValidationError: If the category is unknown.
    """
    category = str(value).strip().lower()
    if category not in VALID_CATEGORIES:
        raise ValidationError(
            f"Category must be one of: {', '.join(VALID_CATEGORIES)}"
        )
    return category


def prompt(
    message: str,
    parser: Callable[[str], T],
    attempts: int = 3,
    default: T | None = None,
) -> T:
    """Ask the user for a value until it parses or the attempts run out.

    Args:
        message: Prompt shown to the user.
        parser: Callable that converts the raw string or raises ValidationError.
        attempts: How many tries the user gets.
        default: Returned when the user submits an empty line.

    Returns:
        The parsed value.

    Raises:
        ValidationError: When every attempt failed.
    """
    for remaining in range(attempts, 0, -1):
        try:
            raw = input(f"{message}: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise ValidationError("Input cancelled by user") from None
        if not raw and default is not None:
            return default
        try:
            return parser(raw)
        except ValidationError as exc:
            say(f"  {exc}" + (f" ({remaining - 1} attempts left)" if remaining > 1 else ""))
    raise ValidationError(f"Could not read a valid value for: {message}")


def say(message: str) -> None:
    """Print a line through rich when available, otherwise plain stdout."""
    if _CONSOLE is not None:  # pragma: no cover - cosmetic
        _CONSOLE.print(message)
    else:
        print(message)


def render_table(title: str, columns: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    """Print a table, using rich if installed and a text fallback otherwise."""
    rows = [[("" if cell is None else str(cell)) for cell in row] for row in rows]
    if not rows:
        say(f"{title}: no rows to show.")
        return

    if _CONSOLE is not None:  # pragma: no cover - cosmetic
        table = Table(title=title)
        for column in columns:
            table.add_column(column)
        for row in rows:
            table.add_row(*row)
        _CONSOLE.print(table)
        return

    widths = [
        max(len(str(columns[i])), *(len(row[i]) for row in rows))
        for i in range(len(columns))
    ]
    line = "  ".join(str(col).ljust(widths[i]) for i, col in enumerate(columns))
    print(f"\n{title}")
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(columns))))
    print()
