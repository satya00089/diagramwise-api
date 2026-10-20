"""Focused structural and brief-alignment checks for the Azure REST API draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_azure_002"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

TITLE = "Build a Serverless REST API"
DESCRIPTION = (
    "Design a serverless REST API that handles HTTP requests with CRUD operations, "
    "authentication, rate limiting, caching, and performance monitoring."
)
REQUIREMENTS = [
    "Handle HTTP requests via REST API",
    "Implement CRUD operations",
    "Authenticate and authorize requests",
    "Rate limit API consumers",
    "Cache frequent responses",
    "Monitor API performance",
    "Handle errors gracefully",
    "Scale based on demand",
]
CONSTRAINTS = [
    "API response time under 200ms",
    "Support 10k requests per second",
    "Cost-effective for variable load",
    "Implement JWT authentication",
    "Maintain 99.9% availability",
]
HINTS = [
    "Azure Functions for serverless compute",
    "API Management for gateway",
    "Cosmos DB for data storage",
    "Application Insights for monitoring",
    "Azure AD for authentication",
    "Redis Cache for caching",
]
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
ACTION_TYPES = {"add_component", "add_connection", "decision_point", "scale_trigger"}
def _anchors(requirements=(), constraints=()) -> set[str]:
    return {
        *(f"legacy-requirement:{number}" for number in requirements),
        *(f"legacy-constraint:{number}" for number in constraints),
    }


EXPECTED_STEP_ANCHORS = {
    "api_01": set(EXPECTED_ANCHORS),
    "api_02": _anchors((1, 6), (1,)),
    "api_03": _anchors((1, 3, 4), (2, 4)),
    "api_04": _anchors((3,), (4,)),
    "api_05": _anchors((3,), (4,)),
    "api_06": _anchors((1, 3, 4), (4,)),
    "api_07": _anchors((2, 3, 8)),
    "api_08": _anchors((1, 2, 3, 4), (4,)),
    "api_09": _anchors((2,)),
    "api_10": _anchors((2, 3)),
    "api_11": _anchors((2, 7)),
    "api_12": _anchors((2, 3), (2,)),
    "api_13": _anchors((2, 7)),
    "api_14": _anchors((3, 5), (1,)),
    "api_15": _anchors((2, 5), (1,)),
    "api_16": _anchors((3, 5)),
    "api_17": _anchors((3, 5)),
    "api_18": _anchors((4, 7)),
    "api_19": _anchors((3, 5), (4,)),
    "api_20": _anchors((6,)),
    "api_21": _anchors((4, 6), (1,)),
    "api_22": _anchors((6,), (1,)),
    "api_23": _anchors((6,), (1, 2, 5)),
    "api_24": _anchors((5, 6), (1, 3, 5)),
    "api_25": _anchors((6,), (1, 5)),
    "api_26": _anchors((5, 7), (5,)),
    "api_27": _anchors((3, 6, 7), (4,)),
    "api_28": _anchors((6, 8), (1, 2)),
    "api_29": _anchors((8,), (1, 2, 3)),
    "api_30": _anchors((2, 8), (1, 2, 3)),
    "api_31": _anchors((2, 8), (2,)),
    "api_32": _anchors((1, 4, 8), (1, 2)),
    "api_33": _anchors((5,), (1, 3)),
    "api_34": _anchors((7,), (3, 5)),
    "api_35": _anchors((2, 7), (1, 5)),
    "api_36": _anchors((3,), (4,)),
    "api_37": _anchors((1, 4, 7)),
    "api_38": _anchors((6, 7), (5,)),
    "api_39": _anchors((1, 2, 3, 4, 5, 6, 8), (1, 2, 4, 5)),
    "api_40": _anchors((8,), (2, 3)),
    "api_41": set(EXPECTED_ANCHORS),
    "api_42": set(EXPECTED_ANCHORS),
}


def _load() -> tuple[dict, dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, problem, GuidedWalkthrough.model_validate(raw)


def _catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^    id:\s*"{re.escape(component_type)}"', catalog)
    assert match, f"Unknown component catalog ID: {component_type}"
    end = catalog.find("\n  },", match.start())
    assert end > match.start(), f"Could not bound catalog component: {component_type}"
    return catalog[match.start() : end]


def _assert_supported_properties(component_type: str, properties: dict, catalog: str) -> None:
    block = _catalog_block(catalog, component_type)
    keys = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= keys, (
        f"Unsupported {component_type} properties: {set(properties) - keys}"
    )

    for key, value in properties.items():
        marker = re.search(rf'\bkey:\s*"{re.escape(key)}"', block)
        assert marker, f"Missing catalog definition for {component_type}.{key}"
        remainder = block[marker.start() :]
        next_property = re.search(r"\n\s*\{\s*key:", remainder[1:])
        property_block = remainder[: next_property.start() + 1] if next_property else remainder
        field_type = re.search(r'\btype:\s*"([^"]+)"', property_block)
        assert field_type, f"Missing field type for {component_type}.{key}"
        if field_type[1] == "boolean":
            assert type(value) is bool
        elif field_type[1] == "number":
            assert type(value) in (int, float)
        elif field_type[1] == "select":
            options = re.search(r"\boptions:\s*\[([^\]]*)\]", property_block, re.DOTALL)
            assert options, f"Missing select options for {component_type}.{key}"
            assert value in set(re.findall(r'"([^"]+)"', options[1]))


def test_schema_matches_the_supplied_brief_and_maps_every_anchor_to_an_action():
    _, problem, guide = _load()

    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 42
    assert [step.stepNumber for step in guide.steps] == list(range(1, 43))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    expected_phases = [
        ("Define the API contract and latency boundary", 1, 8),
        ("Secure ingress and implement synchronous CRUD", 9, 17),
        ("Cache safely and make failures observable", 18, 27),
        ("Scale, protect availability, and prove the targets", 28, 42),
    ]
    assert [
        (phase.name, phase.stepRange[0], phase.stepRange[1]) for phase in guide.phases
    ] == expected_phases
    phase_by_step = {
        number: phase.name
        for phase in guide.phases
        for number in range(phase.stepRange[0], phase.stepRange[1] + 1)
    }
    assert list(phase_by_step) == list(range(1, 43))
    assert all(phase_by_step[step.stepNumber] == step.phase for step in guide.steps)
    assert {step.type for step in guide.steps} == {
        "explanation", "add_component", "add_connection", "decision_point", "scale_trigger"
    }

    by_id = {step.id: step for step in guide.steps}
    all_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert all_anchors == EXPECTED_ANCHORS
    assert EXPECTED_STEP_ANCHORS.keys() == by_id.keys()
    for step_id, expected_anchors in EXPECTED_STEP_ANCHORS.items():
        assert set(by_id[step_id].requirementIds) == expected_anchors, (
            f"{step_id} has an unrelated or missing requirement anchor"
        )
    for anchor in EXPECTED_ANCHORS:
        assert any(
            step.type in ACTION_TYPES and anchor in step.requirementIds
            for step in guide.steps
        ), f"{anchor} has no concrete design action"

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component and step.component.label
        elif step.type == "add_connection":
            assert step.connection and step.connection.label and step.connection.description
        elif step.type == "decision_point":
            assert step.decision and step.decision.question and step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2
        elif step.type == "scale_trigger":
            assert step.scaleTrigger
            assert all((step.scaleTrigger.metric, step.scaleTrigger.action, step.scaleTrigger.impact))


def test_catalog_types_properties_and_select_options_are_supported():
    raw, _, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    expected_types = {
        "apim": "api-gateway",
        "entra": "auth-service",
        "functions": "serverless-function",
        "cosmos": "database",
        "redis": "cache",
        "insights": "monitoring",
    }
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }
    assert {node_id: component["componentType"] for node_id, component in additions.items()} == expected_types
    assert all(component_type != "custom-component" for component_type in expected_types.values())

    for step in raw["steps"]:
        if step["type"] == "add_component":
            component = step["component"]
            assert set(component["position"]) == {"x", "y"}
            assert component["properties"]["componentName"] == component["label"]
            assert len(component["properties"]["purpose"]) >= 80
            assert component["highlightReason"]
            _assert_supported_properties(component["componentType"], component["properties"], catalog)
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component = additions[update["nodeId"]]
            _assert_supported_properties(component["componentType"], update["properties"], catalog)

    apim_policy = next(
        step["componentUpdate"]["properties"]
        for step in raw["steps"]
        if step.get("componentUpdate", {}).get("nodeId") == "apim"
    )
    cosmos_policy = next(
        step["componentUpdate"]["properties"]
        for step in raw["steps"]
        if step.get("componentUpdate", {}).get("nodeId") == "cosmos"
    )
    redis_policy = next(
        step["componentUpdate"]["properties"]
        for step in raw["steps"]
        if step.get("componentUpdate", {}).get("nodeId") == "redis"
    )
    assert apim_policy["authentication"] == "JWT"
    assert cosmos_policy["type"] == "NoSQL"
    assert redis_policy["engine"] == "redis"


def test_ordered_replay_produces_one_connected_api_architecture():
    raw, _, _ = _load()
    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert nodes.keys() == {"apim", "entra", "functions", "cosmos", "redis", "insights"}
    assert len(edges) == 10
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0.0-review-draft"

    neighbors = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    edge_pairs = set()
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["label"] and edge["description"]
        edge_pairs.add((edge["source"], edge["target"]))
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached = set()
    pending = deque(["apim"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes.keys()
    assert {
        ("entra", "apim"),
        ("apim", "functions"),
        ("functions", "cosmos"),
        ("functions", "redis"),
        ("redis", "functions"),
        ("apim", "insights"),
        ("functions", "insights"),
        ("cosmos", "insights"),
        ("redis", "insights"),
    } <= edge_pairs


def test_guidance_covers_azure_failure_security_scale_and_unproven_targets():
    raw, _, _ = _load()
    content = "\n".join(step["content"] for step in raw["steps"]).casefold()
    for phrase in (
        "azure functions", "api management", "cosmos db", "application insights",
        "azure ad", "redis cache", "200ms", "10k requests per second", "99.9%",
        "percentile", "cold start", "etag", "partition key", "hot partition",
        "cache-aside", "invalidate", "consumer-specific", "retry-after", "idempotency",
        "managed identity", "least-privilege", "401", "403", "429", "5xx",
        "regional", "failover", "load-test", "variable load", "not measured guarantees",
        "cross-tenant authorization attempts",
    ):
        assert phrase in content, f"Missing domain-specific guidance: {phrase}"


def test_numeric_slo_claims_are_limited_to_the_frozen_brief_targets():
    raw, problem, _ = _load()
    serialized = json.dumps(raw, ensure_ascii=False)
    numeric_targets = {
        claim.casefold()
        for claim in re.findall(
            r"\b\d+(?:\.\d+)?(?:k|m|b)?\s*(?:ms|%|[- ]?rps|requests per second)(?=$|[^A-Za-z0-9])",
            serialized,
            re.IGNORECASE,
        )
    }
    assert numeric_targets <= {
        "200ms",
        "99.9%",
        "10k-rps",
        "10k requests per second",
    }
    assert {"200ms", "99.9%"} <= numeric_targets
    assert any("10k" in constraint.casefold() for constraint in problem["constraints"])

