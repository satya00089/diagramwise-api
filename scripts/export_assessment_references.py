"""Export public problem/guide inputs using AWS CLI, without remote mutations.

These snapshots support offline migrations and reproducible assessment fixtures.
No user attempts, credentials, or private diagrams are exported.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from decimal import Decimal
from pathlib import Path
import subprocess

from boto3.dynamodb.types import TypeDeserializer

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TABLES = {"diagrammatic_problems", "diagrammatic_guided_walkthroughs"}
PROBLEM_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def repository_path(path: Path) -> Path:
    """Resolve a CLI output path and reject traversal outside this checkout."""
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError as error:
        raise ValueError("Export paths must stay inside the API repository") from error
    return resolved


def repository_output_file(directory: Path, name: str) -> Path:
    """Reject child symlinks that redirect generated exports outside the folder."""
    target = directory / name
    if target.is_symlink():
        raise ValueError("Export output files must not be symlinks")
    resolved = target.resolve()
    if resolved.parent != directory:
        raise ValueError("Export output files must stay inside the output directory")
    return resolved


def scan(table: str, region: str) -> list[dict]:
    if table not in ALLOWED_TABLES:
        raise ValueError("Unsupported public assessment table")
    if not re.fullmatch(r"[a-z0-9-]{1,32}", region):
        raise ValueError("Invalid AWS region")
    env = {**os.environ, "AWS_PAGER": "", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    result = subprocess.run(
        ["aws", "dynamodb", "scan", "--table-name", table, "--region", region,
         "--output", "json"],
        check=True, capture_output=True, env=env, shell=False,
    )
    deserialize = TypeDeserializer().deserialize
    return [{key: deserialize(value) for key, value in item.items()}
            for item in json.loads(result.stdout.decode("utf-8"))["Items"]]


def encode_number(value: object) -> object:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Unsupported snapshot value: {type(value).__name__}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--region", default="ap-south-1")
    args = parser.parse_args()
    args.output = repository_path(args.output)
    problems = scan("diagrammatic_problems", args.region)
    walkthroughs = scan("diagrammatic_guided_walkthroughs", args.region)
    args.output.mkdir(parents=True, exist_ok=True)
    repository_output_file(args.output, "problems.json").write_text(
        json.dumps(sorted(problems, key=lambda p: p["id"]), indent=2,
                   ensure_ascii=False, default=encode_number) + "\n", encoding="utf-8",
    )
    for guide in walkthroughs:
        problem_id = str(guide.get("problem_id") or "")
        if not PROBLEM_ID_PATTERN.fullmatch(problem_id) or problem_id in {".", ".."}:
            raise ValueError("Walkthrough contains an invalid problem_id")
        repository_output_file(args.output, f"{problem_id}.json").write_text(
            json.dumps(guide, indent=2, ensure_ascii=False, default=encode_number) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({"problems": len(problems), "walkthroughs": len(walkthroughs),
                      "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
