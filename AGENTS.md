# Repository Guidelines

## Project Structure

- `src/assignment/` contains the Python harness. `agent/` holds the shared ReAct loop and the coding and chess agents. `cli.py` provides the entry points, and `eval/` contains the evaluation harness used by `scripts/`.
- `tests/` holds the public pytest suite. `tasks/` contains task definitions, agent skills, and evaluation fixtures. `chess_app/` is the pinned submodule used by the chess task. Agent runs write patches, trajectories, and results under `artifacts/` by default.

## Setup and Development Commands

- `make setup` uses `uv` to install dependencies for Python 3.11 or later, initializes `chess_app/`, and verifies its revision.
- `make doctor` checks the source checkout, Modal authentication, and model endpoint before a billable run.
- `make run-code-agent` generates the Part 1 patch. `make run-swebench-agent` runs the coding agent on the pinned Django task. `make run-chess-agent` plays chess using the Part 1 patch.
- `make check-part1` and `make check-swebench` replay generated patches and run the corresponding evaluation tests.

## Coding Style and Assignment Rules

Use four spaces for Python indentation, `snake_case` for modules and functions, and `PascalCase` for classes. Follow the surrounding code for type annotations. Keep the ReAct loop in the shared `Agent` and preserve the supplied logging and cleanup. Treat `tests/`, `tasks/`, and `chess_app/` as read-only for assignment work.

## Testing

Run `make test` for the offline pytest suite or `uv run pytest tests/test_agent.py -k compaction` for a focused check. Test files use `test_*.py`, and test functions start with `test_`. Expect tests for unfinished TODOs to fail in the starter. Use the grading criteria in `ASSIGNMENT.md` to check which behaviors need coverage. The default suite excludes tests marked `modal`. Run `make test-modal` for billable integration tests or `make test-chess-modal` for the chess sandbox subset.

## Commits, Pull Requests, and Submissions

Use short, imperative commit subjects such as `Add missing task files`. In a pull request, summarize the change, report the checks you ran, and link a relevant issue if one exists. For course submissions, follow the ZIP checklist in `ASSIGNMENT.md`. Keep credentials in your local `.env`, using `.env.example` as a template.
