#!/usr/bin/env python3
"""Verify local tooling required for MealSight development."""

from __future__ import annotations

import logging
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5


class Status(Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str
    hint: str | None = None


def run_command(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Command timed out: %s", " ".join(args))
        return None
    output = (result.stdout or "") + (result.stderr or "")
    return output.strip() if result.returncode == 0 or output.strip() else None


def extract_version(text: str) -> str | None:
    match = re.search(r"(\d+\.\d+(\.\d+)?)", text)
    return match.group(1) if match else None


def install_hint(tool: str) -> str:
    system = platform.system()
    hints = {
        "Darwin": {
            "python": "brew install python@3.11",
            "node": "brew install node@20",
            "npm": "npm ships with Node.js — reinstall Node via brew install node@20",
            "git": "brew install git",
            "docker": "brew install --cask docker (then launch Docker Desktop)",
            "ffmpeg": "brew install ffmpeg",
            "uv": "brew install uv  (or: curl -LsSf https://astral.sh/uv/install.sh | sh)",
        },
        "Linux": {
            "python": "sudo apt install python3.11 (or use pyenv/uv python install 3.11)",
            "node": "Install via nvm: nvm install 20",
            "npm": "npm ships with Node.js — reinstall Node 20 via nvm",
            "git": "sudo apt install git",
            "docker": "curl -fsSL https://get.docker.com | sh, then start the docker daemon",
            "ffmpeg": "sudo apt install ffmpeg",
            "uv": "curl -LsSf https://astral.sh/uv/install.sh | sh",
        },
        "Windows": {
            "python": "winget install Python.Python.3.11",
            "node": "winget install OpenJS.NodeJS.LTS",
            "npm": "npm ships with Node.js — reinstall Node 20",
            "git": "winget install Git.Git",
            "docker": "winget install Docker.DockerDesktop (then launch Docker Desktop)",
            "ffmpeg": "winget install Gyan.FFmpeg",
            "uv": "winget install astral-sh.uv",
        },
    }
    platform_hints = hints.get(system, hints["Linux"])
    return platform_hints.get(tool, f"Install {tool} for your platform")


def check_python() -> CheckResult:
    major, minor, micro = sys.version_info[:3]
    version_str = f"{major}.{minor}.{micro}"
    if (major, minor) == (3, 11):
        return CheckResult("Python 3.11.x", Status.OK, version_str)
    if (major, minor) in {(3, 12), (3, 13)}:
        return CheckResult(
            "Python 3.11.x",
            Status.WARN,
            f"found {version_str}, expected 3.11.x",
            "3.12/3.13 have known wheel gaps for this stack — prefer 3.11 via "
            "`uv python install 3.11` or " + install_hint("python"),
        )
    return CheckResult(
        "Python 3.11.x",
        Status.WARN,
        f"found {version_str}, expected 3.11.x",
        install_hint("python"),
    )


def check_node() -> CheckResult:
    output = run_command(["node", "--version"])
    if output is None:
        return CheckResult("Node.js 20+", Status.FAIL, "not found", install_hint("node"))
    version = extract_version(output)
    if version is None:
        return CheckResult("Node.js 20+", Status.FAIL, f"unparseable output: {output}", install_hint("node"))
    major = int(version.split(".")[0])
    if major >= 20:
        return CheckResult("Node.js 20+", Status.OK, version)
    return CheckResult("Node.js 20+", Status.FAIL, f"found {version}, need 20+", install_hint("node"))


def check_npm() -> CheckResult:
    output = run_command(["npm", "--version"])
    if output is None:
        return CheckResult("npm", Status.FAIL, "not found", install_hint("npm"))
    return CheckResult("npm", Status.OK, output)


def check_git() -> CheckResult:
    output = run_command(["git", "--version"])
    if output is None:
        return CheckResult("git", Status.FAIL, "not found", install_hint("git"))
    version = extract_version(output) or output
    return CheckResult("git", Status.OK, version)


def check_docker() -> CheckResult:
    binary_output = run_command(["docker", "--version"])
    if binary_output is None:
        return CheckResult("docker", Status.FAIL, "binary not found", install_hint("docker"))
    version = extract_version(binary_output) or binary_output
    daemon_output = run_command(["docker", "info"])
    if daemon_output is None:
        return CheckResult(
            "docker",
            Status.FAIL,
            f"binary {version} found, but daemon unreachable",
            "Start Docker Desktop (or the docker daemon) and re-run this check",
        )
    return CheckResult("docker", Status.OK, f"{version} (daemon reachable)")


def check_ffmpeg() -> CheckResult:
    output = run_command(["ffmpeg", "-version"])
    if output is None:
        return CheckResult("ffmpeg", Status.FAIL, "not found", install_hint("ffmpeg"))
    version = extract_version(output.splitlines()[0]) or output.splitlines()[0]
    return CheckResult("ffmpeg", Status.OK, version)


def check_uv() -> CheckResult:
    output = run_command(["uv", "--version"])
    if output is None:
        return CheckResult("uv", Status.FAIL, "not found", install_hint("uv"))
    version = extract_version(output) or output
    return CheckResult("uv", Status.OK, version)


def print_table(results: list[CheckResult]) -> None:
    name_width = max(len(r.name) for r in results) + 2
    status_width = 8
    print()
    print(f"{'TOOL':<{name_width}}{'STATUS':<{status_width}}DETAIL")
    print("-" * (name_width + status_width + 40))
    for r in results:
        print(f"{r.name:<{name_width}}{r.status.value:<{status_width}}{r.detail}")
        if r.hint and r.status is not Status.OK:
            print(f"{'':<{name_width}}{'':<{status_width}}-> {r.hint}")
    print()


def main() -> int:
    logger.info("Running MealSight environment checks on %s", platform.platform())
    checks = [
        check_python(),
        check_node(),
        check_npm(),
        check_git(),
        check_docker(),
        check_ffmpeg(),
        check_uv(),
    ]
    print_table(checks)

    failures = [c for c in checks if c.status is Status.FAIL]
    warnings = [c for c in checks if c.status is Status.WARN]

    if failures:
        print(f"RESULT: FAIL ({len(failures)} critical issue(s), {len(warnings)} warning(s))")
        return 1
    if warnings:
        print(f"RESULT: PASS with {len(warnings)} warning(s)")
        return 0
    print("RESULT: PASS — all tools OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
