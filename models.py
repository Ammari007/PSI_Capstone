"""Domain models for the triage system.

Defines the :class:`Ticket` entity, its allowed lifecycle states and the
errors raised when an invalid state transition is attempted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

# Allowed lifecycle states and the transitions permitted from each one.
STATUS_TRANSITIONS: dict[str, set[str]] = {
    "new": {"triaged", "closed"},
    "triaged": {"in_progress", "closed"},
    "in_progress": {"resolved", "closed"},
    "resolved": {"closed", "in_progress"},
    "closed": set(),
}

VALID_STATUSES = tuple(STATUS_TRANSITIONS)
VALID_CATEGORIES = ("network", "hardware", "software", "security", "billing", "other")

_ID_PATTERN = re.compile(r"^TCK-\d{4}$")


class TicketError(Exception):
    """Base class for all ticket related errors."""


class InvalidTransitionError(TicketError):
    """Raised when a ticket is moved to a state it cannot legally reach."""


class ValidationError(TicketError):
    """Raised when ticket field values fail validation."""


@dataclass
class Ticket:
    """A single support ticket awaiting or undergoing triage.

    Attributes:
        ticket_id: Unique identifier in the form ``TCK-0001``.
        title: Short human readable summary.
        description: Free text detail supplied by the reporter.
        reporter: Name or email of the person who raised the ticket.
        category: One of :data:`VALID_CATEGORIES`.
        severity: Reporter-declared severity from 1 (cosmetic) to 5 (outage).
        created_at: UTC timestamp of creation.
        status: Current lifecycle state, see :data:`VALID_STATUSES`.
        assignee: Team the ticket was routed to, or ``None`` before triage.
        priority: Computed priority label (``P1``-``P4``), or ``None``.
        score: Computed numeric triage score, or ``None``.
        history: Append-only log of state changes for reporting.
    """

    ticket_id: str
    title: str
    description: str
    reporter: str
    category: str
    severity: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "new"
    assignee: str | None = None
    priority: str | None = None
    score: float | None = None
    history: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate the ticket immediately after construction."""
        self.validate()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate(self) -> None:
        """Check every field and raise :class:`ValidationError` on failure."""
        if not _ID_PATTERN.match(self.ticket_id):
            raise ValidationError(f"Ticket id must look like TCK-0001, got {self.ticket_id!r}")
        if not self.title.strip():
            raise ValidationError("Title must not be empty")
        if self.category not in VALID_CATEGORIES:
            raise ValidationError(
                f"Category {self.category!r} is not one of {', '.join(VALID_CATEGORIES)}"
            )
        if not isinstance(self.severity, int) or not 1 <= self.severity <= 5:
            raise ValidationError(f"Severity must be an integer 1-5, got {self.severity!r}")
        if self.status not in VALID_STATUSES:
            raise ValidationError(f"Unknown status {self.status!r}")

    # ------------------------------------------------------------------
    # Behaviour
    # ------------------------------------------------------------------
    @property
    def age_hours(self) -> float:
        """Hours elapsed since the ticket was created."""
        created = self.created_at
        if created.tzinfo is None:  # treat naive timestamps as UTC
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).total_seconds() / 3600

    @property
    def is_open(self) -> bool:
        """``True`` while the ticket still needs work."""
        return self.status not in ("resolved", "closed")

    def transition_to(self, new_status: str) -> None:
        """Move the ticket to ``new_status`` if the transition is allowed.

        Args:
            new_status: The target lifecycle state.

        Raises:
            InvalidTransitionError: If the move is not permitted.
        """
        if new_status not in VALID_STATUSES:
            raise InvalidTransitionError(f"Unknown status {new_status!r}")
        allowed = STATUS_TRANSITIONS[self.status]
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot move {self.ticket_id} from {self.status!r} to {new_status!r}"
            )
        self.history.append(f"{self.status} -> {new_status}")
        self.status = new_status

    def apply_triage(self, priority: str, score: float, assignee: str) -> None:
        """Record the outcome of triage and advance the ticket state."""
        self.priority = priority
        self.score = round(score, 2)
        self.assignee = assignee
        if self.status == "new":
            self.transition_to("triaged")

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/CSV friendly dictionary of the ticket."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["history"] = ";".join(self.history)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Ticket":
        """Rebuild a ticket from a dictionary produced by :meth:`to_dict`.

        Raises:
            ValidationError: If required keys are missing or malformed.
        """
        try:
            raw_history = data.get("history") or ""
            history = raw_history.split(";") if isinstance(raw_history, str) else list(raw_history)
            return cls(
                ticket_id=str(data["ticket_id"]).strip(),
                title=str(data["title"]).strip(),
                description=str(data.get("description", "")).strip(),
                reporter=str(data.get("reporter", "unknown")).strip(),
                category=str(data["category"]).strip().lower(),
                severity=int(data["severity"]),
                created_at=_parse_timestamp(data.get("created_at")),
                status=str(data.get("status", "new")).strip().lower(),
                assignee=data.get("assignee") or None,
                priority=data.get("priority") or None,
                score=float(data["score"]) if data.get("score") not in (None, "") else None,
                history=[item for item in history if item],
            )
        except KeyError as exc:
            raise ValidationError(f"Missing required column: {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Malformed ticket row: {exc}") from exc

    def __str__(self) -> str:
        priority = self.priority or "-"
        return f"[{priority}] {self.ticket_id} {self.title} ({self.status})"


def _parse_timestamp(value: Any) -> datetime:
    """Parse an ISO timestamp, defaulting to now when absent or unreadable."""
    if isinstance(value, datetime):
        return value
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
