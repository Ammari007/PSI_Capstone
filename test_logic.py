"""Unit tests for the triage engine, the Ticket model and the storage layer.

Run with either::

    python -m pytest
    python -m unittest discover tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import data_handler, logic  # noqa: E402
from src.models import (  # noqa: E402
    InvalidTransitionError,
    Ticket,
    ValidationError,
)


def make_ticket(**overrides) -> Ticket:
    """Build a valid ticket, overriding any field for the test at hand."""
    defaults = dict(
        ticket_id="TCK-0001",
        title="Printer jams",
        description="The office printer jams",
        reporter="tester@example.com",
        category="hardware",
        severity=2,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Ticket(**defaults)


class TestTicketModel(unittest.TestCase):
    """Validation and state machine behaviour."""

    def test_rejects_bad_id(self):
        with self.assertRaises(ValidationError):
            make_ticket(ticket_id="oops")

    def test_rejects_out_of_range_severity(self):
        with self.assertRaises(ValidationError):
            make_ticket(severity=9)

    def test_rejects_unknown_category(self):
        with self.assertRaises(ValidationError):
            make_ticket(category="astrology")

    def test_allowed_transition(self):
        ticket = make_ticket()
        ticket.transition_to("triaged")
        self.assertEqual(ticket.status, "triaged")
        self.assertEqual(ticket.history, ["new -> triaged"])

    def test_forbidden_transition(self):
        ticket = make_ticket()
        with self.assertRaises(InvalidTransitionError):
            ticket.transition_to("resolved")

    def test_round_trip_serialisation(self):
        original = make_ticket()
        restored = Ticket.from_dict(original.to_dict())
        self.assertEqual(restored.ticket_id, original.ticket_id)
        self.assertEqual(restored.severity, original.severity)


class TestScoring(unittest.TestCase):
    """The scoring, classification and routing rules."""

    def test_outage_beats_cosmetic(self):
        outage = make_ticket(
            ticket_id="TCK-0002",
            title="Production outage",
            description="Everything is down",
            category="software",
            severity=5,
        )
        cosmetic = make_ticket(
            ticket_id="TCK-0003",
            title="Typo in footer",
            description="Cosmetic typo",
            category="other",
            severity=1,
        )
        self.assertGreater(logic.score_ticket(outage), logic.score_ticket(cosmetic))

    def test_security_outranks_same_severity_software(self):
        security = make_ticket(ticket_id="TCK-0004", category="security", severity=3)
        software = make_ticket(ticket_id="TCK-0005", category="software", severity=3)
        self.assertGreater(logic.score_ticket(security), logic.score_ticket(software))

    def test_age_bonus_is_capped(self):
        self.assertEqual(logic.age_bonus(24 * 30), 3.0)
        self.assertAlmostEqual(logic.age_bonus(48), 2.0)

    def test_classify_bands(self):
        self.assertEqual(logic.classify(20), "P1")
        self.assertEqual(logic.classify(9), "P2")
        self.assertEqual(logic.classify(5), "P3")
        self.assertEqual(logic.classify(0), "P4")

    def test_routing(self):
        self.assertEqual(logic.route(make_ticket(category="security")), "Security Response")
        self.assertEqual(logic.route(make_ticket(category="billing")), "Finance Ops")

    def test_triage_sets_fields_and_state(self):
        ticket = logic.triage_ticket(make_ticket())
        self.assertIsNotNone(ticket.priority)
        self.assertIsNotNone(ticket.score)
        self.assertEqual(ticket.status, "triaged")
        self.assertEqual(ticket.assignee, "IT Support")

    def test_triage_all_skips_already_triaged(self):
        done = make_ticket(ticket_id="TCK-0006")
        logic.triage_ticket(done)
        fresh = make_ticket(ticket_id="TCK-0007")
        processed = logic.triage_all([done, fresh])
        self.assertEqual([t.ticket_id for t in processed], ["TCK-0007"])

    def test_old_ticket_scores_higher_than_identical_new_one(self):
        old = make_ticket(
            ticket_id="TCK-0008",
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        new = make_ticket(ticket_id="TCK-0009")
        self.assertGreater(logic.score_ticket(old), logic.score_ticket(new))


class TestReporting(unittest.TestCase):
    """pandas-backed summaries."""

    def test_summary_has_one_row_per_category(self):
        tickets = [
            logic.triage_ticket(make_ticket(ticket_id="TCK-0010", category="network")),
            logic.triage_ticket(make_ticket(ticket_id="TCK-0011", category="network")),
            logic.triage_ticket(make_ticket(ticket_id="TCK-0012", category="billing")),
        ]
        summary = logic.summarise(tickets)
        self.assertEqual(len(summary), 2)
        self.assertIn("avg_score", summary.columns)

    def test_summary_of_empty_list_is_empty(self):
        self.assertTrue(logic.summarise([]).empty)

    def test_priority_counts_cover_all_bands(self):
        counts = logic.priority_counts([logic.triage_ticket(make_ticket())])
        self.assertEqual(list(counts.index), ["P1", "P2", "P3", "P4"])
        self.assertEqual(counts.sum(), 1)


class TestStorage(unittest.TestCase):
    """Loading and saving, including the failure paths."""

    def test_missing_file_returns_empty_list(self):
        self.assertEqual(data_handler.load_tickets("does/not/exist.csv"), [])

    def test_csv_round_trip(self):
        tickets = [logic.triage_ticket(make_ticket())]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            data_handler.save_tickets(tickets, path)
            reloaded = data_handler.load_tickets(path)
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0].priority, tickets[0].priority)

    def test_json_round_trip(self):
        tickets = [make_ticket()]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            data_handler.save_tickets(tickets, path)
            reloaded = data_handler.load_tickets(path)
        self.assertEqual(reloaded[0].ticket_id, "TCK-0001")

    def test_bad_rows_are_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.csv"
            path.write_text(
                "ticket_id,title,description,reporter,category,severity,created_at,status\n"
                "TCK-0001,Good,ok,a@b.c,network,3,2026-01-01T00:00:00+00:00,new\n"
                "BROKEN,Bad,ok,a@b.c,network,3,2026-01-01T00:00:00+00:00,new\n",
                encoding="utf-8",
            )
            tickets = data_handler.load_tickets(path)
        self.assertEqual(len(tickets), 1)

    def test_next_ticket_id_increments(self):
        tickets = [make_ticket(ticket_id="TCK-0004")]
        self.assertEqual(data_handler.next_ticket_id(tickets), "TCK-0005")
        self.assertEqual(data_handler.next_ticket_id([]), "TCK-0001")


if __name__ == "__main__":
    unittest.main()
