"""Generate and grade the Part 1 patch in a local Linux sandbox."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import io
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from tempfile import TemporaryDirectory
from typing import Iterator

from assignment.agent import CodeAgent
from assignment.eval.harness import EvaluationSpec, Report, _grade
from assignment.task import Task
from assignment.utils.image import SourceMismatch, verify_source


DEFAULT_TASK = "tasks/chess-terminal-move"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_TIMEOUT = 600


class LocalTestbed:
    """Run commands in fresh namespaces that share a disposable checkout."""

    cwd = "/testbed"

    def __init__(self, bwrap: str, checkout: Path, venv: Path, scratch: Path):
        platform = os.uname()
        self.system = platform.sysname
        self.release = platform.release
        self.version = platform.version
        self.machine = platform.machine

        # uv's Python symlink can target a minor-version alias such as 3.12.
        config = (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines()
        python_bin = next(
            Path(line.removeprefix("home = ")) for line in config if line.startswith("home = ")
        )
        python_root = python_bin.parent
        self.sandbox = [
            bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind-try", "/bin", "/bin",
            "--ro-bind-try", "/lib", "/lib",
            "--ro-bind-try", "/lib64", "/lib64",
            "--dev", "/dev", "--proc", "/proc",
            "--bind", str(scratch), "/tmp",
            "--bind", str(checkout), self.cwd,
            # Preserve the absolute paths used by the virtualenv and editable install.
            "--bind", str(checkout), str(checkout),
            "--ro-bind", str(python_root.resolve()), str(python_root),
            "--ro-bind", str(venv), str(venv),
        ]
        self.env = {"PATH": f"{venv / 'bin'}:/usr/bin:/bin", "LANG": "C.UTF-8"}

    def execute(
        self,
        command: str | list[str],
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        shell: bool | None = True,
    ) -> dict[str, str | int]:
        argv = [command] if isinstance(command, str) else command
        if shell is not False:
            argv = ["/bin/bash", "-c", *argv]

        invocation = [*self.sandbox, "--chdir", cwd or self.cwd]
        for key, value in {**self.env, **(env or {})}.items():
            invocation.extend(["--setenv", key, value])
        invocation.extend(["--", *argv])

        seconds = DEFAULT_TIMEOUT if timeout is None else timeout
        exception_info = ""
        try:
            result = subprocess.run(
                invocation, stdin=subprocess.DEVNULL, capture_output=True, timeout=seconds
            )
            stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, returncode = exc.stdout or b"", exc.stderr or b"", -1
            exception_info = f"Command timed out after {seconds} seconds."

        stdout_text = stdout.decode("utf-8", errors="backslashreplace")
        stderr_text = stderr.decode("utf-8", errors="backslashreplace")
        return {
            "stdout": stdout_text,
            "stderr": stderr_text,
            "output": stdout_text + stderr_text,
            "returncode": returncode,
            "exception_info": exception_info,
        }


@contextmanager
def local_testbed(task: Task) -> Iterator[LocalTestbed]:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise RuntimeError("Install bubblewrap (bwrap) to run the local testbed.")
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
        subprocess.run(
            ["uv", "venv", "--managed-python", "--python", "3.12", str(venv)], check=True
        )
        subprocess.run(
            [
                "uv", "pip", "install", "--python", str(venv / "bin/python"),
                "--no-deps", "--editable", str(checkout), *task.pins,
            ],
            check=True,
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
    missing = [name for name in ("OPENAI_BASE_URL", "OPENAI_API_KEY") if not os.environ.get(name)]
    if missing:
        raise ValueError(f"Set {', '.join(missing)} in the environment or in .env.")

    task = Task.load(args.task)
    model = args.model or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
    with local_testbed(task) as environment:
        agent = CodeAgent(
            task=task.problem_statement,
            environment=environment,
            model=model,
            logs_save_path=str(args.trajectory),
            step_limit=args.step_limit,
            skills_path=str(args.skills_path),
            auto_stop_environment=False,
        )
        agent.run()
        result = environment.execute(["cat", "patch.txt"], shell=False)
        if result["returncode"] != 0:
            raise RuntimeError(f"Could not read the agent's patch.txt.\n{result['stderr']}")
        patch = result["stdout"]

    if not patch.strip():
        raise RuntimeError("Agent finished without a non-empty patch.")
    args.patch_output.parent.mkdir(parents=True, exist_ok=True)
    args.patch_output.write_text(patch, encoding="utf-8")
    print(f"Patch: {args.patch_output}\nTrajectory: {args.trajectory}")
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
        report = _grade(
            environment,
            Report(task_id=task.id, patch_applied=False),
            test_patch=spec.test_patch,
            test_cmd=spec.test_cmd,
            fail_to_pass=spec.fail_to_pass,
            pass_to_pass=spec.pass_to_pass,
            patch=patch,
            timeout=args.timeout,
            framework=spec.framework,
        )
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
