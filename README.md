# End-to-End Triage Script

A command line tool that ingests a queue of raw support tickets, scores each one
against a transparent set of rules, assigns a priority band and an owning team,
persists the results, and produces a summary report and chart.

The problem it solves: on a busy service desk, tickets arrive with a severity
the *reporter* chose, which is rarely the severity the *business* would choose.
This tool re-scores every ticket consistently so nobody has to eyeball a
spreadsheet at 9am.

## Quick start

```bash
git clone <your-fork-url>
cd capstone_project

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m src.main triage        # score the sample dataset
python -m src.main report        # summarise it
python -m src.main interactive   # menu-driven mode
```

Run it from the project root so that `python -m src.main` can find the package.

## Commands

| Command | What it does |
| --- | --- |
| `triage` | Scores every untriaged ticket, prints the queue, writes `data/triaged_tickets.csv` |
| `report` | Prints a priority breakdown and category summary, writes a CSV report and a PNG chart |
| `add` | Prompts for a new ticket, validates each field, triages it and appends it to the dataset |
| `interactive` | Menu wrapper around the three commands above (also the default with no arguments) |

Useful flags: `--input`, `--output`, `--report`, `--chart`, `--limit`,
and `--retriage` to re-score tickets that were already processed.

```bash
python -m src.main triage --input data/sample_data.csv --limit 5
python -m src.main report --input data/triaged_tickets.csv
```

## How the scoring works

```
score = (severity × category_weight) + keyword_bonus + age_bonus
```

- **Category weight** — security 3.0, network 2.0, hardware/billing 1.5,
  software 1.0, other 0.5.
- **Keyword bonus** — phrases like `outage`, `breach`, `data loss` and
  `production` add points; `typo` and `cosmetic` subtract them.
- **Age bonus** — one point per day waiting, capped at three so a stale
  cosmetic ticket never outranks a live outage.

Bands: **P1** ≥ 12, **P2** ≥ 8, **P3** ≥ 4, **P4** below that. Routing maps the
category to a team (security → Security Response, billing → Finance Ops, and so on).

Every weight and threshold lives at the top of `src/logic.py`, so the policy can
be changed without touching any of the code that applies it.

Sample output:

```
Triage queue (top 5)
ID        Priority  Score  Category  Owner              Title
TCK-0010  P1        18.27  security  Security Response  Data loss in nightly backup
TCK-0003  P1        15.37  security  Security Response  Suspicious login attempts
TCK-0001  P1        13.57  software  Application Team   Checkout service outage
TCK-0007  P2        9.00   hardware  IT Support         Laptop will not boot
TCK-0005  P2        8.46   network   Infrastructure     VPN is slow for remote staff
```

## Project layout

```
capstone_project/
├── data/
│   └── sample_data.csv      # 10 sample tickets to run against
├── src/
│   ├── __init__.py
│   ├── main.py              # CLI entry point: argparse + interactive menu
│   ├── models.py            # Ticket class, validation, state machine
│   ├── logic.py             # Scoring, classification, routing, pandas reports
│   ├── data_handler.py      # CSV/JSON load and save
│   └── utils.py             # Input validation, prompting, table rendering
├── tests/
│   └── test_logic.py        # 22 unit tests
├── .gitignore
├── requirements.txt
└── README.md
```

## Design notes

- **Ticket lifecycle.** `new → triaged → in_progress → resolved → closed`.
  `Ticket.transition_to()` refuses illegal jumps and appends each change to an
  in-object history list, which is what makes historical reporting possible.
- **Layer separation.** `logic.py` never reads a file and `data_handler.py`
  never scores a ticket, so the rules can be unit tested with no I/O at all.
- **Failure handling.** A missing dataset returns an empty list with a warning
  rather than a traceback; a malformed row is skipped and reported while the
  rest of the file still loads; unwritable paths raise `StorageError`, which
  `main()` converts into a clean exit code.
- **Optional dependencies.** `rich` and `matplotlib` improve the output but the
  tool detects their absence and falls back to plain text, so a grader with a
  bare Python install can still run everything.

## Tests

```bash
python -m pytest -v
# or, with no third-party packages installed:
python -m unittest discover tests -v
```

The suite covers field validation, illegal state transitions, serialisation
round trips, the relative ordering of the scoring rules, the age cap, the
pandas summaries, and the storage failure paths.

## Requirements mapping

| Requirement | Where |
| --- | --- |
| Modular architecture | `src/` split into `main`, `models`, `logic`, `data_handler`, `utils` |
| OOP | `Ticket` class with encapsulated state, properties and a state machine |
| Data persistence | `data_handler.py` reads and writes CSV and JSON |
| Error handling & validation | `ValidationError`, `InvalidTransitionError`, `StorageError`; retry prompts in `utils.prompt` |
| Third-party packages | `pandas` for reporting, `matplotlib` for the chart, `rich` for the console, `pytest` for tests |
| Clean code | PEP 8, type hints, docstrings on every public function and class |
| Unit tests | `tests/test_logic.py` |

## Possible extensions

SQLite persistence behind the same `data_handler` interface, an SLA clock per
priority band, and pulling live tickets from a REST API instead of a CSV.
