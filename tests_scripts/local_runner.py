"""Shared bubblewrap execution, patch export, and replay for the local runners."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from assignment.agent import CodeAgent
from assignment.eval.harness import EvaluationSpec, Report, _grade, find_testbed_python
from assignment.eval.instances import Instance


DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_TIMEOUT = 600


def bubblewrap_path() -> str:
    binary = shutil.which("bwrap")
    if binary is None:
        raise RuntimeError("Install bubblewrap (bwrap) to run the local testbed.")
    return binary


class BubblewrapEnvironment:
    """Execute commands in fresh namespaces with writable testbed mounts."""

    def __init__(self, bwrap: str, mounts: list[str], env: dict[str, str], cwd: str = "/testbed"):
        platform = os.uname()
        self.system = platform.sysname
        self.release = platform.release
        self.version = platform.version
        self.machine = platform.machine
        self.cwd = cwd
        self.sandbox = [
            bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
            *mounts, "--dev", "/dev", "--proc", "/proc",
        ]
        self.env = env

    def command_line(
        self,
        command: str | list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        shell: bool | None = True,
    ) -> list[str]:
        argv = [command] if isinstance(command, str) else command
        if shell is not False:
            argv = ["/bin/bash", "-c", *argv]

        invocation = [*self.sandbox, "--chdir", cwd or self.cwd]
        for key, value in {**self.env, **(env or {})}.items():
            invocation.extend(["--setenv", key, value])
        return [*invocation, "--", *argv]

    def execute(
        self,
        command: str | list[str],
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        shell: bool | None = True,
    ) -> dict[str, str | int]:
        invocation = self.command_line(command, cwd=cwd, env=env, shell=shell)
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


def require_model_settings() -> None:
    missing = [name for name in ("OPENAI_BASE_URL", "OPENAI_API_KEY") if not os.environ.get(name)]
    if missing:
        raise ValueError(f"Set {', '.join(missing)} in the environment or in .env.")


def generate_patch(
    environment: BubblewrapEnvironment,
    *,
    task: str,
    model: str | None,
    step_limit: int,
    skills_path: Path,
    trajectory: Path,
    patch_output: Path,
    compact_threshold_tokens: int | None = None,
) -> None:
    agent = CodeAgent(
        task=task,
        environment=environment,
        model=model or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL,
        logs_save_path=str(trajectory),
        step_limit=step_limit,
        skills_path=str(skills_path),
        auto_stop_environment=False,
        compact_threshold_tokens=compact_threshold_tokens,
    )
    agent.run()
    result = environment.execute(["cat", "patch.txt"], shell=False)
    if result["returncode"] != 0:
        raise RuntimeError(f"Could not read the agent's patch.txt.\n{result['stderr']}")
    patch = result["stdout"]
    if not patch.strip():
        raise RuntimeError("Agent finished without a non-empty patch.")

    patch_output.parent.mkdir(parents=True, exist_ok=True)
    patch_output.write_text(patch, encoding="utf-8")
    print(f"Patch: {patch_output}\nTrajectory: {trajectory}")


def replay_patch(
    environment: BubblewrapEnvironment,
    spec: EvaluationSpec | Instance,
    patch: str,
    timeout: float,
) -> Report:
    test_cmd = spec.test_cmd
    if "{python}" in test_cmd:
        test_cmd = test_cmd.replace("{python}", find_testbed_python(environment))
    return _grade(
        environment,
        Report(task_id=spec.task_id, patch_applied=False),
        test_patch=spec.test_patch,
        test_cmd=test_cmd,
        fail_to_pass=spec.fail_to_pass,
        pass_to_pass=spec.pass_to_pass,
        patch=patch,
        timeout=timeout,
        framework=spec.framework,
    )
