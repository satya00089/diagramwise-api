"""Replay an explicitly public E2E fixture; never touches AWS or Langfuse.

Keep every bounded attempt and validation error, not only successful reviews.
This is diagnostic evidence, not a benchmark or a release acceptance label.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.models.request_models import AssessmentRequest
from app.services.ai_assessor import AIAssessorService
from app.utils.config import get_settings


async def no_reference_lookup(_):
    await asyncio.sleep(0)
    return []


def repository_path(path: Path) -> Path:
    """Resolve a CLI path and reject traversal outside this checkout."""
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError as error:
        raise ValueError("Diagnostic paths must stay inside the API repository") from error
    return resolved


# Prevent even constructing the DynamoDB singleton on the fallback path.
reference = ModuleType("app.services.walkthrough_reference")
reference.get_fallback_reference_checks = no_reference_lookup
sys.modules[reference.__name__] = reference


class DiagnosticAssessor(AIAssessorService):
    def __init__(self):
        super().__init__(settings=get_settings().model_copy(update={"langfuse_enabled": False}))
        self.outputs = []
        self.errors = []

    async def _generate_json(self, **kwargs):
        response = await super()._generate_json(**kwargs)
        self.outputs.append({"task": kwargs["task"], "content": response.content,
                             "finish_reason": response.finish_reason})
        return response

    def _transform_ai_response(self, ai_result, request=None):
        try:
            return super()._transform_ai_response(ai_result, request)
        except ValueError as error:
            self.errors.append(str(error))
            raise


async def run(args):
    recorded = json.loads(args.session.read_text(encoding="utf-8"))
    raw = next(item for item in recorded["assessmentInputs"]
               if item.get("problem", {}).get("id") == args.problem_id)
    assessor = DiagnosticAssessor()
    result = await assessor.assess_design(AssessmentRequest.model_validate(raw))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"kind": "public-fixture-diagnostic", "awsWrites": 0,
        "langfuseWrites": 0, "request": raw, "model": assessor._model_version(),
        "promptHash": hashlib.sha256((ROOT / "app/utils/prompts.py").read_bytes()).hexdigest(),
        "result": result.model_dump(mode="json"), "providerOutputs": assessor.outputs,
        "validationErrors": assessor.errors}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scoreAvailable": result.score_available, "score": result.overall_score,
                      "verdict": result.verdict.value, "validationErrors": assessor.errors}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--problem-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.session = repository_path(args.session)
    args.output = repository_path(args.output)
    if args.output.exists():
        parser.error("Output exists; preserve every recorded run")
    asyncio.run(run(args))
