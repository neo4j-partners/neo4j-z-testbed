"""Output, settings, and error handling shared by the laptop test scripts."""

import getpass
import os
import textwrap
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

from dotenv import load_dotenv
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable

ENV_FILE = Path(__file__).resolve().with_name(".env")
WIDTH = 72


class Check(NamedTuple):
    name: str
    passed: bool
    detail: str


def section(step: int | None, title: str, what: str, *, total: int) -> None:
    label = f"[{step}/{total}] {title}" if step else title
    print()
    print("=" * WIDTH)
    print(label)
    print("=" * WIDTH)
    print(textwrap.fill(what, WIDTH))
    print()


def kv(label: str, value: object) -> None:
    print(f"  {label:<24} {value}")


def ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms"


def show_checks(checks: Iterable[Check]) -> None:
    for check in checks:
        print(
            f"  {'PASS' if check.passed else 'FAIL'}  {check.name:<20} {check.detail}"
        )


def required_setting(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Set {name} in {ENV_FILE}. See .env.example.")
    return value


def neo4j_password() -> str:
    return os.environ.get("NEO4J_PW") or getpass.getpass("  Password for neo4j: ")


def run_guarded(action: Callable[[], bool]) -> int:
    """Load the settings, run a test, and turn its result into an exit code."""
    load_dotenv(ENV_FILE)
    try:
        return 0 if action() else 1
    except AuthError as err:
        print(f"\nLogin failed: {err.message}")
    except ServiceUnavailable as err:
        print(f"\nCannot reach Neo4j: {err}")
    except Neo4jError as err:
        print(f"\nNeo4j error {err.code}: {err.message}")
    except RuntimeError as err:
        print(f"\n{err}")
    return 1
