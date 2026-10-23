"""Loopback-only E2E harness: real product routers/service, isolated storage/auth.

Only the configured AI provider may be called. No AWS resource is constructed.
This harness is not imported by the deployed application. Draft catalog specs
are test fixtures, not human approval or publication. Require explicit opt-in:
E2E_LIVE_PROVIDER=1 python -m uvicorn scripts.e2e_assessment_app:app --host 127.0.0.1 --port 8010
"""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import cast
from unittest.mock import patch
import json
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mypy_boto3_dynamodb.service_resource import Table

if os.environ.get("E2E_LIVE_PROVIDER") != "1":
    raise RuntimeError("Explicit E2E_LIVE_PROVIDER=1 required; this is a local test harness")

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = Path(os.environ.get("E2E_RUN_DIR", str(ROOT / "data/e2e-20261010-01"))).resolve()
if not RUN_DIR.is_relative_to(ROOT / "data") or RUN_DIR == ROOT / "data":
    raise RuntimeError("E2E output must be a new child directory of this checkout's data directory")
RUN_DIR.mkdir(parents=True, exist_ok=False)


class ForbiddenTable:
    def __getattr__(self, name):
        raise AssertionError(f"Real AWS operation forbidden in E2E harness: {name}")


class GuardResource:
    def Table(self, _):
        return ForbiddenTable()


# Existing service modules construct a singleton on import. Block construction
# before importing them, not after a real AWS resource might have been created.
with patch("boto3.resource", return_value=GuardResource()):
    from app.services import dynamodb_service as database_module
    from app.routers import assessment, attempts, interview, problems, walkthroughs
    from app.routers.auth import get_current_user

from app.services.ai_assessor import AIAssessorService
from app.services.dynamodb_service import DynamoDBService, convert_decimal_to_float
from app.services.llm_port import LLMRequest, LLMResponse
from app.utils.config import get_settings

problem_rows = json.loads((ROOT / "tests/fixtures/walkthroughs/problems.json").read_text(encoding="utf-8"))
problem_data = {row["id"]: row for row in problem_rows}
draft = json.loads((ROOT / "docs/requirements-catalog-draft.json").read_text(encoding="utf-8"))
for change in draft["changes"]:
    problem_data[change["id"]]["requirementSpec"] = change["proposedSpec"]
guide_data = {path.stem: json.loads(path.read_text(encoding="utf-8"))
              for path in (ROOT / "data/assessment-reference-candidates/walkthroughs").glob("*.json")}

lock = RLock()
events = []
assessment_inputs = []
assessment_outputs = []
mode = {"outage": False}


class MemoryAttempts:
    """Minimal DynamoDB adapter; the actual attempt service owns all semantics."""
    def __init__(self):
        self.items = {}

    def get_item(self, **kwargs):
        key = (kwargs["Key"]["userId"], kwargs["Key"]["problemId"])
        with lock:
            item = self.items.get(key)
            return {"Item": deepcopy(item)} if item else {}

    def update_item(self, **kwargs):
        key = (kwargs["Key"]["userId"], kwargs["Key"]["problemId"])
        with lock:
            item = self.items.setdefault(key, deepcopy(kwargs["Key"]))
            names = kwargs.get("ExpressionAttributeNames", {})
            values = kwargs["ExpressionAttributeValues"]
            for alias, attribute in names.items():
                value_alias = alias.replace("#", ":", 1)
                if not alias.startswith("#a") or value_alias not in values:
                    raise AssertionError("Unexpected E2E storage expression")
                keep_existing = f"{alias} = if_not_exists({alias}, {value_alias})" in kwargs["UpdateExpression"]
                if not (keep_existing and attribute in item):
                    item[attribute] = deepcopy(values[value_alias])
            return {"Attributes": deepcopy(item)}

    def query(self, **_):
        with lock:
            return {"Items": deepcopy(list(self.items.values()))}


class MemoryProblems:
    def get_item(self, **kwargs):
        row = problem_data.get(kwargs["Key"]["id"])
        return {"Item": deepcopy(row)} if row else {}


storage = MemoryAttempts()
service = DynamoDBService.__new__(DynamoDBService)
service.attempts_table = cast(Table, storage)
service.problems_table = cast(Table, MemoryProblems())
service.get_problem_by_id = lambda problem_id: deepcopy(problem_data.get(problem_id))
service.get_problem_by_slug = lambda slug: next((deepcopy(row) for row in problem_data.values() if row.get("slug") == slug), None)
service.get_walkthrough_by_problem_id = lambda problem_id: deepcopy(guide_data.get(problem_id))
setattr(database_module, "dynamodb_service", service)
for module in (attempts, problems, walkthroughs):
    setattr(module, "dynamodb_service", service)

settings = get_settings().model_copy(update={"langfuse_enabled": False})


class OutageLLM:
    async def generate(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("Simulated provider outage: local E2E fault injection")


def assessor_service():
    return AIAssessorService(settings=settings, llm=OutageLLM() if mode["outage"] else None)


interview.AIAssessorService = assessor_service
app = FastAPI(title="Local assessment E2E (isolated storage/auth)")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5181"],
                   allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
app.dependency_overrides[get_current_user] = lambda: {"user_id": "e2e-learner", "email": "e2e@example.invalid"}
app.dependency_overrides[assessment.get_problem_lookup] = lambda: service.get_problem_by_id
app.dependency_overrides[assessment.get_assessor_service] = assessor_service


def snapshot():
    return {"scope": "local-only", "awsWrites": 0, "authentication": "isolated synthetic user",
            "storage": "in-memory adapter; real attempt service", "humanLabelsApproved": False,
            "provider": settings.llm_provider, "outage": mode["outage"], "events": events,
            "assessmentInputs": assessment_inputs, "assessmentOutputs": assessment_outputs,
            "attempts": convert_decimal_to_float(list(storage.items.values()))}


@app.middleware("http")
async def record_public_test_requests(request: Request, call_next):
    started = datetime.now(timezone.utc)
    if request.url.path == "/api/v1/assess" and request.method == "POST":
        assessment_inputs.append(await request.json())
    response = await call_next(request)
    # CORS preflight returns plain "OK", not an assessment JSON object.
    # Observe only actual assessment responses, leaving OPTIONS untouched.
    if request.url.path == "/api/v1/assess" and request.method == "POST":
        body = b"".join([chunk async for chunk in response.body_iterator])
        assessment_outputs.append(json.loads(body))
        response = JSONResponse(json.loads(body), status_code=response.status_code,
                                headers=dict(response.headers))
    events.append({"method": request.method, "path": request.url.path, "status": response.status_code,
                   "durationMs": int((datetime.now(timezone.utc) - started).total_seconds() * 1000)})
    # Runtime-generated evidence from this public test session, never credentials.
    with lock:
        pending = RUN_DIR / "session.json.tmp"
        pending.write_text(json.dumps(snapshot(), indent=2, default=str) + "\n", encoding="utf-8")
        pending.replace(RUN_DIR / "session.json")
    return response


@app.get("/__e2e/state")
def test_state():
    return snapshot()


@app.post("/__e2e/mode")
def test_mode(value: dict):
    if set(value) != {"outage"} or not isinstance(value["outage"], bool):
        raise HTTPException(400, "Only the explicit boolean outage flag is accepted")
    mode.update(value)
    return mode


@app.get("/api/v1/auth/me")
def local_user():
    return {"id": "e2e-learner", "email": "e2e@example.invalid", "name": "E2E Learner",
            "createdAt": "2026-10-10T00:00:00Z", "updatedAt": "2026-10-10T00:00:00Z"}


@app.get("/api/v1/auth/me/preferences")
def local_preferences():
    return {}


@app.patch("/api/v1/auth/me/preferences")
def accept_local_preferences(value: dict):
    return value


@app.get("/api/components")
def local_palette():
    return {"items": [], "count": 0, "lastEvaluatedKey": None}


@app.get("/api/components/{component_id}")
def local_component(component_id: str):
    return {"id": component_id, "provider": "General", "label": component_id,
            "nodeType": "custom", "group": "GENERAL", "properties": [], "description": "Local test palette metadata"}


@app.post("/api/v1/analytics/batch")
def local_analytics():
    return {"success": True}


@app.get("/health")
def health():
    return {"status": "ready", "scope": "loopback-only", "guides": len(guide_data), "awsWrites": 0}


for module in (problems, walkthroughs, assessment, interview, attempts):
    app.include_router(module.router, prefix="/api/v1")
