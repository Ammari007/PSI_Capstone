"""Business logic: the triage engine and the reporting functions.

The engine turns a ticket's severity, category, wording and age into a numeric
score, then maps that score onto a priority band and an owning team. Reporting
uses pandas to summarise a batch of triaged tickets.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .models import Ticket

# Words that escalate a ticket regardless of the severity the reporter chose.
URGENCY_KEYWORDS: dict[str, float] = {
    "outage": 3.0,
    "down": 2.5,
    "breach": 3.0,
    "data loss": 3.0,
    "cannot login": 2.0,
    "payment": 1.5,
    "production": 2.0,
    "urgent": 1.0,
    "slow": 0.5,
    "typo": -1.0,
    "cosmetic": -1.0,
}

# Category weighting: security problems outrank cosmetic software requests.
CATEGORY_WEIGHTS: dict[str, float] = {
    "security": 3.0,
    "network": 2.0,
    "hardware": 1.5,
    "software": 1.0,
    "billing": 1.5,
    "other": 0.5,
}

ROUTING: dict[str, str] = {
    "security": "Security Response",
    "network": "Infrastructure",
    "hardware": "IT Support",
    "software": "Application Team",
    "billing": "Finance Ops",
    "other": "Service Desk",
}

# Lower bound of each priority band, checked from the top down.
PRIORITY_BANDS: tuple[tuple[str, float], ...] = (
    ("P1", 12.0),
    ("P2", 8.0),
    ("P3", 4.0),
    ("P4", 0.0),
)


def keyword_bonus(text: str) -> float:
    """Sum the weights of every urgency keyword found in ``text``."""
    lowered = text.lower()
    return sum(weight for word, weight in URGENCY_KEYWORDS.items() if word in lowered)


def age_bonus(hours: float) -> float:
    """Escalate tickets that have been waiting a long time.

    One point per full day waiting, capped at three so an old cosmetic
    ticket never outranks a live outage.
    """
    return min(hours / 24.0, 3.0)


def score_ticket(ticket: Ticket) -> float:
    """Compute the numeric triage score for a single ticket.

    The score combines reporter severity, the category weight, urgency
    keywords in the title and description, and how long it has waited.
    """
    base = ticket.severity * 2.0
    weighted = base * CATEGORY_WEIGHTS.get(ticket.category, 1.0) / 2.0
    text = f"{ticket.title} {ticket.description}"
    total = weighted + keyword_bonus(text) + age_bonus(ticket.age_hours)
    return max(total, 0.0)


def classify(score: float) -> str:
    """Map a numeric score onto a ``P1``-``P4`` priority label."""
    for label, threshold in PRIORITY_BANDS:
        if score >= threshold:
            return label
    return "P4"


def route(ticket: Ticket) -> str:
    """Return the team that should own this ticket."""
    return ROUTING.get(ticket.category, "Service Desk")


def triage_ticket(ticket: Ticket) -> Ticket:
    """Score, classify and route one ticket in place."""
    score = score_ticket(ticket)
    ticket.apply_triage(priority=classify(score), score=score, assignee=route(ticket))
    return ticket


def triage_all(tickets: list[Ticket], only_new: bool = True) -> list[Ticket]:
    """Triage a batch of tickets.

    Args:
        tickets: The tickets to process.
        only_new: When ``True``, skip anything already triaged.

    Returns:
        The tickets that were actually processed, highest priority first.
    """
    processed = [
        triage_ticket(ticket)
        for ticket in tickets
        if not (only_new and ticket.priority is not None)
    ]
    return sort_by_urgency(processed)


def sort_by_urgency(tickets: list[Ticket]) -> list[Ticket]:
    """Sort tickets so the most urgent appear first."""
    return sorted(tickets, key=lambda t: (t.priority or "P9", -(t.score or 0.0)))


def to_dataframe(tickets: list[Ticket]) -> pd.DataFrame:
    """Build a pandas DataFrame from a list of tickets."""
    if not tickets:
        return pd.DataFrame(columns=["ticket_id", "category", "severity", "priority", "score"])
    frame = pd.DataFrame([ticket.to_dict() for ticket in tickets])
    frame["severity"] = pd.to_numeric(frame["severity"], errors="coerce")
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce", utc=True)
    return frame


def summarise(tickets: list[Ticket]) -> pd.DataFrame:
    """Return a per-category summary: volume, mean score and open count."""
    frame = to_dataframe(tickets)
    if frame.empty:
        return frame
    summary = (
        frame.groupby("category")
        .agg(
            tickets=("ticket_id", "count"),
            avg_severity=("severity", "mean"),
            avg_score=("score", "mean"),
            p1_count=("priority", lambda values: (values == "P1").sum()),
        )
        .round(2)
        .sort_values("avg_score", ascending=False)
        .reset_index()
    )
    return summary


def priority_counts(tickets: list[Ticket]) -> pd.Series:
    """Count how many tickets fall into each priority band."""
    frame = to_dataframe(tickets)
    if frame.empty:
        return pd.Series(dtype="int64")
    order = [label for label, _ in PRIORITY_BANDS]
    counts = frame["priority"].value_counts()
    return counts.reindex(order, fill_value=0)


def export_report(tickets: list[Ticket], path: str | Path) -> Path:
    """Write the category summary to a CSV file and return its path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    summarise(tickets).to_csv(path, index=False)
    return path


def save_priority_chart(tickets: list[Ticket], path: str | Path) -> Path | None:
    """Save a bar chart of priority counts.

    Returns ``None`` when matplotlib is unavailable or there is nothing to
    plot, so the CLI can carry on without a chart.
    """
    counts = priority_counts(tickets)
    if counts.empty or counts.sum() == 0:
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")  # headless backend, safe on servers
        import matplotlib.pyplot as plt
    except ImportError:
        print("[warn] matplotlib is not installed - skipping the chart.")
        return None

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(6, 4))
    axis.bar(counts.index, counts.values, color="#3b6ea5")
    axis.set_title("Tickets by priority")
    axis.set_xlabel("Priority")
    axis.set_ylabel("Tickets")
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return path
