"""Run and replay the Part 2 SWE-bench task in its published image, locally."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import logging
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory, gettempdir
from typing import Iterator

from assignment.cli import _compact_threshold
from assignment.eval.harness import TESTBED_PYTHON
from assignment.eval.instances import Instance, available, load
from tests_scripts.local_runner import (
    BubblewrapEnvironment,
    bubblewrap_path,
    generate_patch,
    replay_patch,
    require_model_settings,
)


DEFAULT_INSTANCE = "django__django-15368"
CRANE_PACKAGE = "github.com/google/go-containerregistry/cmd/crane@v0.20.6"


def export_image(image: str, rootfs: Path, cache: Path) -> None:
    process_env = os.environ.copy()
    if crane := shutil.which("crane"):
        exporter = [crane]
    elif go := shutil.which("go"):
        exporter = [go, "run", CRANE_PACKAGE]
        process_env.setdefault("GOCACHE", str(cache / "go-build"))
        process_env.setdefault("GOMODCACHE", str(cache / "go-mod"))
    else:
        raise RuntimeError("Install crane or Go to download the published SWE-bench image.")

    print(f"Downloading and unpacking {image} for linux/amd64.", flush=True)
    with subprocess.Popen(
        [*exporter, "export", "--platform", "linux/amd64", image, "-"],
        stdout=subprocess.PIPE,
        env=process_env,
    ) as download:
        unpacked = subprocess.run(
            [
                "tar", "-xf", "-", "-C", str(rootfs), "--no-same-owner",
                "--no-same-permissions", "--exclude=dev", "--exclude=./dev",
            ],
            stdin=download.stdout,
        )
        download.stdout.close()
        if download.wait() != 0 or unpacked.returncode != 0:
            raise RuntimeError(f"Could not unpack the published SWE-bench image {image}.")


def cached_rootfs(instance: Instance) -> Path:
    default_cache = Path(gettempdir()) / f"cmu-agents-swebench-{os.getuid()}"
    cache = Path(os.environ.get("SWEBENCH_CACHE_DIR") or default_cache)
    cache = cache.resolve()
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    if cache.stat().st_uid != os.getuid():
        raise RuntimeError(f"The SWE-bench cache at {cache} must be owned by the current user.")
    rootfs = cache / instance.instance_id
    with (cache / f"{instance.instance_id}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not rootfs.is_dir():
            with TemporaryDirectory(dir=cache, prefix="image-") as directory:
                staging = Path(directory) / "rootfs"
                staging.mkdir()
                export_image(instance.image, staging, cache)
                for mountpoint in ("dev", "proc", "tmp"):
                    (staging / mountpoint).mkdir(exist_ok=True)
                if not (staging / instance.cwd.lstrip("/") / ".git").exists():
                    raise RuntimeError(f"The image has no Git checkout at {instance.cwd}.")
                staging.rename(rootfs)
    return rootfs


@contextmanager
def local_swebench(instance: Instance) -> Iterator[BubblewrapEnvironment]:
    if os.uname().machine != "x86_64":
        raise RuntimeError("The published SWE-bench image requires a Linux x86-64 host.")
    bwrap = bubblewrap_path()
    rootfs = cached_rootfs(instance)
    with TemporaryDirectory(prefix="assignment-swebench-") as directory:
        root = Path(directory).resolve()
        checkout, scratch = root / "checkout", root / "scratch"
        shutil.copytree(rootfs / instance.cwd.lstrip("/"), checkout, symlinks=True)
        scratch.mkdir()
        environment = BubblewrapEnvironment(
            bwrap,
            [
                "--ro-bind", str(rootfs), "/",
                "--bind", str(checkout), instance.cwd,
                "--bind", str(scratch), "/tmp",
            ],
            {
                "PATH": f"{Path(TESTBED_PYTHON).parent}:/opt/miniconda3/bin:/usr/local/bin:/usr/bin:/bin",
                "LANG": "C.UTF-8",
            },
            cwd=instance.cwd,
        )
        # SWE-bench can append an empty setup commit to the pinned revision.
        trees = environment.execute(
            ["git", "rev-parse", "HEAD^{tree}", f"{instance.base_commit}^{{tree}}"], shell=False
        )
        tree_ids = trees["stdout"].splitlines()
        if trees["returncode"] != 0 or len(tree_ids) != 2 or tree_ids[0] != tree_ids[1]:
            raise RuntimeError(f"Image checkout does not match {instance.base_commit}.\n{trees['output']}")
        clean = environment.execute(["git", "diff", "--quiet", "HEAD", "--"], shell=False)
        if clean["returncode"] != 0:
            raise RuntimeError(f"The image checkout has tracked changes.\n{clean['output']}")
        python = environment.execute([TESTBED_PYTHON, "--version"], shell=False)
        if python["returncode"] != 0:
            raise RuntimeError(f"Could not start the image's testbed Python.\n{python['output']}")
        yield environment


def run_swebench(args: argparse.Namespace) -> int:
    require_model_settings()
    instance = load(args.instance)
    suffix = "-baseline" if args.compact_threshold_tokens is None else ""
    basename = f"artifacts/{instance.instance_id}{suffix}"
    with local_swebench(instance) as environment:
        generate_patch(
            environment,
            task=instance.problem_statement,
            model=args.model,
            step_limit=args.step_limit,
            skills_path=args.skills_path,
            trajectory=args.trajectory or Path(f"{basename}-trajectory.json"),
            patch_output=args.patch_output or Path(f"{basename}.patch"),
            compact_threshold_tokens=args.compact_threshold_tokens,
        )
    return 0


def check_swebench(args: argparse.Namespace) -> int:
    instance = load(args.instance)
    patch_path = args.patch or Path(f"artifacts/{instance.instance_id}.patch")
    if not patch_path.is_file():
        raise FileNotFoundError(
            f"Patch not found at {patch_path}. Run tests_scripts/run-swebench-agent.sh first."
        )
    patch = patch_path.read_text(encoding="utf-8")
    if not patch.strip():
        raise ValueError(f"Patch at {patch_path} is empty.")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with local_swebench(instance) as environment:
        report = replay_patch(environment, instance, patch, args.timeout)
    print(report.summary())
    return 0 if report.resolved else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)
    run = commands.add_parser("run-swebench-agent", help="Generate a patch locally")
    check = commands.add_parser("check-swebench", help="Grade a patch locally")
    for command in (run, check):
        command.add_argument(
            "instance", nargs="?", choices=available(), default=os.environ.get("INSTANCE", DEFAULT_INSTANCE)
        )

    patch = os.environ.get("SWEBENCH_PATCH")
    run.add_argument("--model", default=os.environ.get("MODEL"))
    run.add_argument("--step-limit", type=int, default=os.environ.get("STEPS", "200"))
    run.add_argument(
        "--skills-path", type=Path, default=os.environ.get("CODE_SKILLS", "tasks/code-skills")
    )
    run.add_argument(
        "--compact-threshold-tokens", type=_compact_threshold,
        default=os.environ.get("COMPACT_THRESHOLD", "6000"),
        help="Token threshold for compaction (default 6000). Use 0 for the full-context baseline.",
    )
    run.add_argument("--trajectory", type=Path, default=os.environ.get("SWEBENCH_TRAJECTORY"))
    run.add_argument("--patch-output", type=Path, default=patch)
    run.set_defaults(action=run_swebench)

    check.add_argument("--patch", type=Path, default=patch)
    check.add_argument("--timeout", type=float, default=1800)
    check.set_defaults(action=check_swebench)

    args = parser.parse_args()
    try:
        return args.action(args)
    except (OSError, KeyError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
