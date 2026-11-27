"""Play the Part 3.1 chess evaluation against a local patched testbed."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Iterator

import httpx

import assignment
from assignment.agent import ChessAgent, StepLimitError
from assignment.chess_sandbox import SANDBOX_FILES
from assignment.task import Task
from assignment.utils.image import SourceMismatch
from tests_scripts.local_runner import DEFAULT_MODEL, require_model_settings
from tests_scripts.part1_local import DEFAULT_TASK, LocalTestbed, local_testbed


def count_play_moves(history: list[dict[str, Any]]) -> dict[str, int]:
    """Count attempts and their linked observations, including the last turn."""
    counts = {"calls": 0, "accepted": 0, "illegal": 0, "other_errors": 0}
    pending: Counter[str] = Counter()
    for message in history:
        if message["role"] == "assistant":
            pending = Counter(
                call["id"] for call in message.get("tool_calls") or []
                if call.get("function", {}).get("name") == "play_move"
            )
            counts["calls"] += sum(pending.values())
        elif message["role"] == "tool" and pending[message["tool_call_id"]]:
            pending[message["tool_call_id"]] -= 1
            content = message["content"]
            if content.startswith("<chess_state>"):
                counts["accepted"] += 1
            elif content.startswith("<chess_error>"):
                detail = content.lower()
                if "not legal in the current position" in detail or "illegal move" in detail:
                    counts["illegal"] += 1
                else:
                    counts["other_errors"] += 1

    counts["unobserved"] = counts["calls"] - counts["accepted"] - counts["illegal"] - counts["other_errors"]
    return counts


@contextmanager
def local_chess_server(
    environment: LocalTestbed, patch: Path, timeout: int
) -> Iterator[httpx.Client]:
    scratch = environment.scratch
    shutil.copyfile(patch, scratch / "fix.diff")
    applied = environment.execute(["git", "apply", "-v", "/tmp/fix.diff"], shell=False)
    if applied["returncode"] != 0:
        raise RuntimeError(f"The Part 1 patch did not apply.\n{applied['output']}")

    assignment_files = scratch / "assignment"
    assignment_files.mkdir()
    for source in SANDBOX_FILES:
        shutil.copyfile(source, assignment_files / source.name)
    environment.sandbox.extend(["--ro-bind", str(assignment_files), "/opt/assignment"])
    environment.env["ASSIGNMENT_CHESS_SOCKET"] = "/tmp/chess.sock"
    socket_path = scratch / "chess.sock"
    log_path = scratch / "chess-server.log"
    command = [
        "timeout", "--foreground", "--kill-after=5s", f"{timeout}s",
        "python", "-m", "uvicorn", "chess_server:create_app", "--factory",
        "--app-dir", "/opt/assignment", "--uds", "/tmp/chess.sock",
    ]
    with log_path.open("wb") as log, subprocess.Popen(
        environment.command_line(command, shell=False),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    ) as server:
        try:
            transport = httpx.HTTPTransport(uds=str(socket_path))
            with httpx.Client(base_url="http://chess.local", transport=transport, timeout=20) as client:
                deadline = time.monotonic() + min(30, timeout)
                while server.poll() is None and time.monotonic() < deadline:
                    try:
                        response = client.get("/health", timeout=1)
                        if response.status_code == 200 and response.json() == {"status": "ok"}:
                            break
                    except (httpx.HTTPError, ValueError):
                        pass
                    time.sleep(0.1)
                else:
                    logs = log_path.read_text(encoding="utf-8", errors="replace")
                    raise RuntimeError(f"The local chess server did not become ready.\n{logs[-4000:]}")

                print(f"Chess server socket: {socket_path}", flush=True)
                yield client
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, default=os.environ.get("TASK", DEFAULT_TASK))
    parser.add_argument("--patch", type=Path, default=os.environ.get("PATCH", "artifacts/fix.patch"))
    parser.add_argument("--model", default=os.environ.get("MODEL"))
    parser.add_argument("--step-limit", type=int, default=os.environ.get("STEPS", "200"))
    parser.add_argument("--sandbox-timeout", type=int, default=os.environ.get("CHESS_TIMEOUT", "1800"))
    parser.add_argument("--omit-legal-moves", action="store_true")
    parser.add_argument("--programmatic-tools", action="store_true")
    parser.add_argument("--skills-path", type=Path, help="Directory containing chess skills")
    parser.add_argument("--summarize-moves", action="store_true", help="Print play_move counts for the observation experiment")
    parser.add_argument(
        "--trajectory", type=Path, default=os.environ.get("TRAJECTORY", "artifacts/part3-trajectory.json")
    )
    parser.add_argument("--result", type=Path, default=os.environ.get("RESULT", "artifacts/game-result.json"))
    args = parser.parse_args()
    if args.sandbox_timeout <= 0:
        parser.error("--sandbox-timeout must be positive.")
    if len({args.patch.resolve(), args.trajectory.resolve(), args.result.resolve()}) != 3:
        parser.error("--patch, --trajectory and --result must name separate files.")

    try:
        if not args.patch.is_file() or args.patch.stat().st_size == 0:
            raise ValueError(f"Part 1 patch at {args.patch} is missing or empty.")
        require_model_settings()
        task = Task.load(args.task)
        with local_testbed(task) as environment, local_chess_server(
            environment, args.patch, args.sandbox_timeout
        ) as client:
            agent = ChessAgent(
                environment=environment,
                model=args.model or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL,
                http_client=client,
                logs_save_path=str(args.trajectory),
                step_limit=args.step_limit,
                skills_path=str(args.skills_path) if args.skills_path else None,
                auto_stop_environment=False,
                programmatic_tools=args.programmatic_tools,
                include_legal_moves=not args.omit_legal_moves,
            )
            try:
                agent.run()
            finally:
                args.result.parent.mkdir(parents=True, exist_ok=True)
                args.result.write_text(json.dumps(agent.last_state, indent=2), encoding="utf-8")
                print(f"Result: {args.result}\nTrajectory: {args.trajectory}")
                if args.summarize_moves:
                    print(f"Move statistics: {json.dumps(count_play_moves(agent.message_history))}")
    except (
        OSError, SourceMismatch, StepLimitError, subprocess.CalledProcessError,
        RuntimeError, ValueError, httpx.HTTPError,
    ) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
