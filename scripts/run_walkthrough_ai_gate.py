"""Run a strict, repeatable AI gate against the isolated local E2E API.

The request is assembled from frozen problem briefs and explicit walkthrough
actions, with the same system-generated reasoning context as the frontend. This
is not browser Apply/Save/Reload proof and never writes to AWS.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.requirements_migration import read_json, records
from scripts.walkthrough_fixtures import build_architecture, make_request


def client_reasoning_context(problem: dict, guide: dict, request: dict) -> dict:
    spec = problem.get("requirementSpec")
    entries = []
    if spec:
        entries = [
            row
            for field in ("functional", "nonFunctional")
            for row in spec.get(field, [])
            if row.get("scope") == "core"
        ]
    original = [*problem.get("requirements", []), *problem.get("constraints", [])]

    def target(category: str, pattern: str) -> str:
        regex = re.compile(pattern, re.IGNORECASE)
        matches = (
            [
                row["text"]
                for row in spec.get("nonFunctional", [])
                if row.get("scope") == "core"
                and (row.get("category") == category or regex.search(row["text"]))
            ]
            if spec
            else [value for value in original if regex.search(value)]
        )
        if matches:
            return "Provided by the problem: " + "; ".join(matches)
        return (
            f"No explicit {category} target is specified. Explain your assumption "
            "if it affects this design."
        )

    components = request["components"]
    connected = {
        node_id
        for edge in request["connections"]
        for node_id in (edge["source"], edge["target"])
    }
    disconnected = sum(node["id"] not in connected for node in components)
    roles = list(
        dict.fromkeys(
            step["component"]["componentType"]
            for step in sorted(guide["steps"], key=lambda row: row["stepNumber"])
            if step.get("type") == "add_component"
        )
    )
    requirements = [problem.get("description", "")]
    requirements.extend(
        [row["text"] for row in entries]
        if spec
        else original
    )
    assumptions = spec.get("assumptions", []) if spec else []
    if assumptions:
        requirements.extend(["Reference assumptions (replaceable, not mandatory):", *assumptions])

    return {
        "requirements": "\n".join(value for value in requirements if value),
        "scaleAssumptions": target("scale", r"scale|million|billion|\bDAU\b|concurrent|large documents"),
        "expectedTraffic": target("traffic", r"requests|traffic|per (second|day|month)|\bDAU\b"),
        "readWriteRatio": target("readWriteRatio", r"read.heavy|write.heavy|read.*write|\d+:\d+"),
        "latencyGoals": target("latency", r"latency|\d+\s*ms|response time"),
        "availabilityTarget": target("availability", r"availability|uptime|\bSLA\b"),
        "consistencyRequirements": target(
            "consistency", r"consisten|without conflicts|uniqueness|unique|synchroniz"
        ),
        "technologyChoices": (
            f"Canvas roles: {', '.join(roles)}. Explain the choices and alternatives."
            if roles
            else "No components yet."
        ),
        "tradeoffs": (
            "Explain the trade-offs of your submitted design; reference choices are "
            "not the only correct choices."
        ),
        "unresolvedRisks": (
            f"{disconnected} components are disconnected; review their purpose and failure paths."
            if disconnected
            else "Review failure paths using the actual connections and accepted design decisions."
        ),
    }


def prepare_request(problem: dict, guide: dict) -> dict:
    built = build_architecture(guide)
    request = make_request(problem, guide, built)
    # The fixture helper synthesizes a legacy digest for offline comparisons.
    # The browser sends a revision only when the catalog problem has a typed
    # requirement spec; sending that synthetic digest makes the real API reject
    # the request with 409 because legacy catalog rows have no revision.
    if not problem.get("requirementSpec"):
        request["problem"].pop("requirementRevision", None)
    positions = {
        step["component"]["nodeId"]: step["component"].get("position", {})
        for step in guide["steps"]
        if step.get("type") == "add_component" and step.get("component")
    }
    for component in request["components"]:
        component["position"] = positions.get(component["id"], {})
    request["reasoningContext"] = client_reasoning_context(problem, guide, request)
    return request


def submit(url: str, body: bytes, timeout: float) -> tuple[int, dict]:
    http_request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(http_request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {"detail": raw[:2000]}
        return error.code, detail
    except (TimeoutError, URLError) as error:
        return 0, {"transport_error": str(error)[:2000]}


def required_anchor_ids(problem: dict) -> set[str]:
    """Return the exact required coverage IDs for a typed or legacy brief."""
    spec = problem.get("requirementSpec")
    if spec is not None:
        if not isinstance(spec, dict):
            raise ValueError("requirementSpec must be an object")

        required_ids: set[str] = set()
        for field in ("functional", "nonFunctional"):
            entries = spec.get(field, [])
            if not isinstance(entries, list):
                raise ValueError(f"requirementSpec.{field} must be a list")
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    raise ValueError(f"requirementSpec.{field}[{index}] must be an object")
                scope = entry.get("scope")
                if scope not in {"core", "extension"}:
                    raise ValueError(
                        f"requirementSpec.{field}[{index}] must declare core or extension scope"
                    )
                if scope == "extension":
                    continue
                anchor_id = entry.get("id")
                if not isinstance(anchor_id, str) or not anchor_id.strip():
                    raise ValueError(
                        f"requirementSpec.{field}[{index}] core entry must have a non-empty id"
                    )
                if anchor_id in required_ids:
                    raise ValueError(f"Duplicate core requirement anchor: {anchor_id}")
                required_ids.add(anchor_id)

        if not required_ids:
            raise ValueError("requirementSpec must contain at least one core requirement anchor")
        return required_ids

    requirements = problem.get("requirements", []) or []
    constraints = problem.get("constraints", []) or []
    if not isinstance(requirements, list) or not isinstance(constraints, list):
        raise ValueError("Legacy requirements and constraints must be lists")
    required_ids = {
        *[f"legacy-requirement:{index}" for index in range(1, len(requirements) + 1)],
        *[f"legacy-constraint:{index}" for index in range(1, len(constraints) + 1)],
    }
    if not required_ids:
        raise ValueError("Problem brief contains no gate-eligible requirement anchors")
    return required_ids


def gate_result(status: int, response: dict, required_ids: set[str]) -> dict:
    coverage = {
        row.get("requirement_id"): row.get("status")
        for row in response.get("requirement_coverage", [])
        if isinstance(row, dict)
    }
    unsupported = sorted(
        requirement_id
        for requirement_id in required_ids
        if coverage.get(requirement_id) != "supported"
    )
    checks = {
        "http_200": status == 200,
        "ai_source": response.get("source") == "ai",
        "score_available": response.get("score_available") is True,
        "valid": response.get("is_valid") is True,
        "score_at_least_95": isinstance(response.get("overall_score"), int)
        and response["overall_score"] >= 95,
        "strong_alignment": response.get("verdict") == "strong_alignment",
        "all_required_anchors_supported": not unsupported,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "unsupportedAnchors": unsupported,
        "httpStatus": status,
        "source": response.get("source"),
        "scoreAvailable": response.get("score_available"),
        "valid": response.get("is_valid"),
        "score": response.get("overall_score"),
        "verdict": response.get("verdict"),
        "coverage": coverage,
        "summary": response.get("summary"),
        "findings": response.get("findings", []),
        "transportOrHttpError": response.get("transport_error") or response.get("detail"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", nargs="+", required=True, help="Problem IDs with local guide drafts")
    parser.add_argument("--rounds", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--parallelism", type=int, choices=range(1, 7), default=3)
    parser.add_argument("--base-url", default="http://127.0.0.1:8019")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=110)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; preserve each evidence run and choose a new path")

    problem_rows = records(read_json(ROOT / "tests/fixtures/walkthroughs/problems.json"))
    problems = {str(row["id"]): row for row in problem_rows}
    candidates = {}
    for problem_id in args.ids:
        guide_path = ROOT / "data/guided-walkthroughs" / f"{problem_id}.json"
        if problem_id not in problems or not guide_path.is_file():
            parser.error(f"Missing frozen brief or guide draft for {problem_id}")
        guide = read_json(guide_path)
        if guide.get("problem_id") != problem_id:
            parser.error(f"Guide ID mismatch in {guide_path.name}")
        try:
            required_ids = required_anchor_ids(problems[problem_id])
        except ValueError as error:
            parser.error(f"Invalid assessment anchors for {problem_id}: {error}")
        request = prepare_request(problems[problem_id], guide)
        body = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        candidates[problem_id] = {
            "request": request,
            "body": body,
            "requestSha256": hashlib.sha256(body).hexdigest(),
            "walkthroughSha256": hashlib.sha256(guide_path.read_bytes()).hexdigest(),
            "requiredAnchors": sorted(required_ids),
            "results": [],
        }

    rounds = []
    active = set(candidates)
    with ThreadPoolExecutor(max_workers=min(args.parallelism, len(candidates))) as executor:
        for round_number in range(1, args.rounds + 1):
            futures = {
                executor.submit(
                    submit,
                    args.base_url.rstrip("/") + "/api/v1/assess",
                    candidate["body"],
                    args.timeout_seconds,
                ): problem_id
                for problem_id, candidate in candidates.items()
                if problem_id in active
            }
            if not futures:
                break
            round_results = []
            failed_this_round = set()
            for future in as_completed(futures):
                problem_id = futures[future]
                status, response = future.result()
                result = gate_result(
                    status,
                    response,
                    set(candidates[problem_id]["requiredAnchors"]),
                )
                candidates[problem_id]["results"].append(result)
                round_results.append({"problemId": problem_id, "run": round_number, **result})
                if not result["passed"]:
                    failed_this_round.add(problem_id)
                print(
                    json.dumps(
                        {
                            "problemId": problem_id,
                            "run": round_number,
                            "score": result["score"],
                            "valid": result["valid"],
                            "verdict": result["verdict"],
                            "source": result["source"],
                            "passed": result["passed"],
                            "unsupportedAnchors": result["unsupportedAnchors"],
                        }
                    ),
                    flush=True,
                )
            rounds.append({"round": round_number, "results": round_results})
            # A strict five-for-five candidate cannot recover from an invalid,
            # low-scoring, uncovered, or unavailable run by cherry-picking later
            # successes. Stop it now and reserve provider capacity for candidates
            # that can still pass this exact payload gate.
            active.difference_update(failed_this_round)

    candidates_summary = {}
    for problem_id, candidate in candidates.items():
        candidate_pass = len(candidate["results"]) == args.rounds and all(
            result["passed"] for result in candidate["results"]
        )
        candidates_summary[problem_id] = {
            "passed": candidate_pass,
            "runsCompleted": len(candidate["results"]),
            "requestSha256": candidate["requestSha256"],
            "walkthroughSha256": candidate["walkthroughSha256"],
            "requiredAnchors": candidate["requiredAnchors"],
            "results": candidate["results"],
        }

    document = {
        "kind": "local-loopback-walkthrough-ai-gate",
        "scope": "local-only; no AWS writes; not browser Apply/Save/Reload proof",
        "roundsPerCandidate": args.rounds,
        "parallelism": min(args.parallelism, len(candidates)),
        "baseUrl": args.base_url,
        "candidates": candidates_summary,
        "rounds": rounds,
        "allCandidatesPassed": all(row["passed"] for row in candidates_summary.values()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"allCandidatesPassed": document["allCandidatesPassed"], "output": str(args.output)}))
    return 0 if document["allCandidatesPassed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
