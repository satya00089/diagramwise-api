"""Explicit live smoke test on public reference input, without dataset mutations.

This is not a release acceptance report or human ground truth. It records failures
as returned; it never retries a low score or injects expected scores into prompts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.request_models import AssessmentRequest
from app.services.ai_assessor import AIAssessorService
from scripts.walkthrough_fixtures import build_architecture, make_request


class SmokeAssessor(AIAssessorService):
    """Keep diagnostics locally for this explicitly public fixture only."""
    def __init__(self):
        super().__init__()
        self.smoke_outputs = []
        self.validation_errors = []

    async def _generate_json(self, **kwargs):
        response = await super()._generate_json(**kwargs)
        self.smoke_outputs.append({"task": kwargs.get("task"), "content": response.content,
                                   "trace_id": response.trace_id, "finish_reason": response.finish_reason})
        return response

    def _transform_ai_response(self, ai_result, request=None):
        try:
            return super()._transform_ai_response(ai_result, request)
        except ValueError as error:
            self.validation_errors.append(str(error)[:4000])
            raise


def repository_path(path: Path) -> Path:
    """Resolve a CLI path and reject traversal outside this checkout."""
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError as error:
        raise ValueError("Assessment smoke paths must stay inside the API repository") from error
    return resolved


def build_request(problem: dict, guide: dict, spec: dict | None = None) -> dict:
    """Replay only applied actions, using the same fixture path as evaluation."""
    return make_request(problem, guide, build_architecture(guide), spec)


async def run(args) -> None:
    args.walkthrough = repository_path(args.walkthrough)
    args.output = repository_path(args.output)
    if args.manifest:
        args.manifest = repository_path(args.manifest)
    guide = json.loads(args.walkthrough.read_text(encoding="utf-8"))
    problems = json.loads((ROOT / "tests/fixtures/walkthroughs/problems.json").read_text(encoding="utf-8"))
    problem = next(item for item in problems if item["id"] == guide["problem_id"])
    spec = _load_requirement_spec(args.manifest, guide["problem_id"])
    request = build_request(problem, guide, spec)
    _apply_negative_mutation(request, args.negative)
    service = SmokeAssessor()
    frozen = _frozen_metadata(service, args.walkthrough)
    results = await _run_assessments(service, request, args.repeats)
    _write_smoke_output(args, guide, request, frozen, results)


def _load_requirement_spec(manifest_path: Path | None, problem_id: str) -> dict | None:
    if not manifest_path:
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    spec = next((row["proposedSpec"] for row in manifest["changes"]
                 if row["id"] == problem_id), None)
    if spec is None:
        raise ValueError("Manifest has no requirement spec for this walkthrough")
    return spec


def _apply_negative_mutation(request: dict, negative: str | None) -> None:
    if negative != "no-permission-enforcement":
        return
    for node in request["components"]:
        props = node["properties"]
        if node["id"] == "guided_auth_service":
            props.update({"description": "Identity only. Every caller can read, edit, share and roll back every document; document roles are display-only and are never enforced.",
                          "purpose": "Identity only; document permissions are deliberately not enforced.",
                          "permissionChecks": "Disabled: allow all document actions regardless of ACL",
                          "revocation": "No ACL version check or revoked-session invalidation", "linkSharing": "Anyone may read or edit any shared document"})
        if node["id"] == "guided_collab_server":
            props["authorization"] = "Accept every edit without checking current document permissions"
        if node["id"] == "guided_search":
            props["authorization"] = "Return all document contents without permission filtering or recheck"


def _frozen_metadata(service: SmokeAssessor, walkthrough_path: Path) -> dict:
    return {
        "model": service._model_version(),
        "rubricVersion": service.RUBRIC_VERSION,
        "promptHash": hashlib.sha256((ROOT / "app/utils/prompts.py").read_bytes()).hexdigest(),
        "reviewerHash": hashlib.sha256((ROOT / "app/services/ai_assessor.py").read_bytes()).hexdigest(),
        "walkthroughHash": hashlib.sha256(walkthrough_path.read_bytes()).hexdigest(),
        "temperature": service.settings.llm_temperature,
    }


async def _run_assessments(service: SmokeAssessor, request: dict, repeats: int) -> list[dict]:
    results = []
    for repeat in range(1, repeats + 1):
        service.smoke_outputs = []
        service.validation_errors = []
        result = await service.assess_design(AssessmentRequest.model_validate(request))
        results.append({"repeat": repeat, "result": result.model_dump(mode="json"),
                        "providerOutputs": service.smoke_outputs, "validationErrors": service.validation_errors})
        print(json.dumps({"repeat": repeat, "source": result.source.value,
            "scoreAvailable": result.score_available, "score": result.overall_score if result.score_available else None,
            "verdict": result.verdict.value}), flush=True)
    return results


def _write_smoke_output(args, guide: dict, request: dict, frozen: dict, results: list[dict]) -> None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "live-public-fixture-smoke", "frozen": frozen,
        "walkthroughVersion": guide["version"], "notReleaseAcceptance": True,
        "humanLabelsReviewed": False, "negativeMutation": args.negative,
        "request": request, "runs": results,
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--walkthrough", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--negative", choices=["no-permission-enforcement"])
    parser.add_argument("--manifest", type=Path, help="Explicit local requirements manifest for a versioned guide")
    args = parser.parse_args()
    args.walkthrough = repository_path(args.walkthrough)
    args.output = repository_path(args.output)
    if args.manifest:
        args.manifest = repository_path(args.manifest)
    if args.output.exists():
        parser.error("Output already exists; do not overwrite or cherry-pick a recorded run")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
