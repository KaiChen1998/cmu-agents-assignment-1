"""Generate and grade the Part 1 patch in a local Linux sandbox."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import io
import logging
import os
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory, gettempdir
from typing import Iterator

from assignment.eval.harness import EvaluationSpec
from assignment.task import Task
from assignment.utils.image import SourceMismatch, verify_source
from tests_scripts.local_runner import (
    DEFAULT_TIMEOUT,
    BubblewrapEnvironment,
    bubblewrap_path,
    generate_patch,
    replay_patch,
    require_model_settings,
)


DEFAULT_TASK = "tasks/chess-terminal-move"


class LocalTestbed(BubblewrapEnvironment):
    """Run commands in fresh namespaces that share a disposable checkout."""

    cwd = "/testbed"

    def __init__(self, bwrap: str, checkout: Path, venv: Path, scratch: Path):
        self.scratch = scratch
        # uv's Python symlink can target a minor-version alias such as 3.12.
        config = (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines()
        python_bin = next(
            Path(line.removeprefix("home = ")) for line in config if line.startswith("home = ")
        )
        python_root = python_bin.parent
        mounts = [
            "--ro-bind", "/usr", "/usr",
            "--ro-bind-try", "/bin", "/bin",
            "--ro-bind-try", "/lib", "/lib",
            "--ro-bind-try", "/lib64", "/lib64",
            "--bind", str(scratch), "/tmp",
            "--bind", str(checkout), self.cwd,
            # Preserve the absolute paths used by the virtualenv and editable install.
            "--bind", str(checkout), str(checkout),
            "--ro-bind", str(python_root.resolve()), str(python_root),
            "--ro-bind", str(venv), str(venv),
        ]
        env = {"PATH": f"{venv / 'bin'}:/usr/bin:/bin", "LANG": "C.UTF-8"}
        super().__init__(bwrap, mounts, env)


@contextmanager
def local_testbed(task: Task) -> Iterator[LocalTestbed]:
    bwrap = bubblewrap_path()
    verify_source(task)

    with TemporaryDirectory(prefix="assignment-part1-") as directory:
        root = Path(directory).resolve()
        checkout, venv, scratch = root / "checkout", root / "venv", root / "scratch"
        checkout.mkdir()
        scratch.mkdir()
        archive = subprocess.check_output(
            ["git", "-C", str(task.source), "archive", "--format=tar", task.base_commit]
        )
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(checkout, filter="data")

        # Match the task Dockerfile's Python version and editable installation.
        uv_env = os.environ.copy()
        if "UV_CACHE_DIR" not in uv_env:
            cache = Path(gettempdir()) / f"cmu-agents-uv-{os.getuid()}"
            cache.mkdir(mode=0o700, exist_ok=True)
            if cache.stat().st_uid != os.getuid():
                raise RuntimeError(f"The uv cache at {cache} must be owned by the current user.")
            uv_env["UV_CACHE_DIR"] = str(cache)
        subprocess.run(
            ["uv", "venv", "--managed-python", "--python", "3.12", str(venv)],
            check=True,
            env=uv_env,
        )
        subprocess.run(
            [
                "uv", "pip", "install", "--python", str(venv / "bin/python"),
                "--no-deps", "--editable", str(checkout), *task.pins,
            ],
            check=True,
            env=uv_env,
        )

        environment = LocalTestbed(bwrap, checkout, venv, scratch)
        result = environment.execute(
            "python -c 'import sys; assert sys.version_info[:2] == (3, 12); import chess_app' && "
            "git init -q -b main && git add -A && "
            "git -c user.email=harness@localhost -c user.name=harness commit -q -m 'base commit'"
        )
        if result["returncode"] != 0:
            raise RuntimeError(f"Could not initialize the local testbed.\n{result['output']}")
        yield environment


def run_code_agent(args: argparse.Namespace) -> int:
    require_model_settings()
    task = Task.load(args.task)
    with local_testbed(task) as environment:
        generate_patch(
            environment,
            task=task.problem_statement,
            model=args.model,
            trajectory=args.trajectory,
            step_limit=args.step_limit,
            skills_path=args.skills_path,
            patch_output=args.patch_output,
        )
    return 0


def check_part1(args: argparse.Namespace) -> int:
    if not args.patch.is_file():
        raise FileNotFoundError(
            f"Patch not found at {args.patch}. Run tests_scripts/run-code-agent.sh first."
        )
    patch = args.patch.read_text(encoding="utf-8")
    if not patch.strip():
        raise ValueError(f"Patch at {args.patch} is empty.")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    task = Task.load(args.task)
    spec = EvaluationSpec.load(args.evaluation or task.root / "public_tests")
    if spec.task_id != task.id:
        raise ValueError(f"Evaluation is for {spec.task_id!r}, expected {task.id!r}.")
    with local_testbed(task) as environment:
        report = replay_patch(environment, spec, patch, args.timeout)
    print(report.summary())
    return 0 if report.resolved else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)
    run = commands.add_parser("run-code-agent", help="Generate the Part 1 patch locally")
    check = commands.add_parser("check-part1", help="Replay the Part 1 patch locally")
    for command in (run, check):
        command.add_argument("--task", type=Path, default=os.environ.get("TASK", DEFAULT_TASK))

    patch = os.environ.get("PATCH", "artifacts/fix.patch")
    run.add_argument("--model", default=os.environ.get("MODEL"))
    run.add_argument("--step-limit", type=int, default=os.environ.get("STEPS", "200"))
    run.add_argument(
        "--skills-path", type=Path, default=os.environ.get("CODE_SKILLS", "tasks/code-skills")
    )
    run.add_argument(
        "--trajectory", type=Path,
        default=os.environ.get("PART1_TRAJECTORY", "artifacts/part1-trajectory.json"),
    )
    run.add_argument("--patch-output", type=Path, default=patch)
    run.set_defaults(action=run_code_agent)

    check.add_argument("--patch", type=Path, default=patch)
    check.add_argument("--evaluation", type=Path, default=os.environ.get("PUBLIC_EVAL"))
    check.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    check.set_defaults(action=check_part1)

    args = parser.parse_args()
    try:
        return args.action(args)
    except (OSError, SourceMismatch, subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
