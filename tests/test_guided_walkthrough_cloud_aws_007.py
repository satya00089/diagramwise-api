"""Frozen-brief, component-catalog, and graph checks for the AWS CDN draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_aws_007"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "cloud_aws_007",
    "title": "Design a Global Content Delivery Network",
    "slug": "design-a-global-content-delivery-network",
    "description": "Design a global CDN architecture that serves static and dynamic content with low latency, customizes content based on location, and protects against DDoS attacks.",
    "difficulty": "Medium",
    "category": "AWS - CDN",
    "domain": "infra",
    "estimated_time": "30-45 minutes",
    "requirements": [
        "Serve static and dynamic content globally",
        "Minimize latency for users worldwide",
        "Cache content at edge locations",
        "Customize content based on location",
        "Handle HTTPS requests",
        "Protect against DDoS attacks",
        "Invalidate cached content",
        "Monitor cache performance",
    ],
    "constraints": [
        "Cache hit ratio above 80%",
        "Latency under 100ms globally",
        "Support 10M+ requests per day",
        "Handle traffic spikes gracefully",
        "Minimize origin server load",
    ],
    "hints": [
        "CloudFront for CDN",
        "S3 as origin for static content",
        "Lambda@Edge for edge computing",
        "Route 53 for DNS routing",
        "AWS Shield for DDoS protection",
        "CloudWatch for monitoring",
    ],
    "tags": ["aws", "cloudfront", "cdn", "s3", "lambda-edge", "route53"],
    "companies": ["Amazon", "Netflix", "Disney+"],
    "has_guided_walkthrough": False,
}

STEP_TYPES = {
    "explanation",
    "add_component",
    "add_connection",
    "decision_point",
    "scale_trigger",
    "update_component",
}
CONNECTION_TYPES = {"api-call", "data-flow", "event-stream", "http"}
EXPECTED_COMPONENT_TYPES = {
    "aws007_viewers": "web-app",
    "aws007_route53": "authoritative-nameserver",
    "aws007_cloudfront": "cdn",
    "aws007_s3_origin": "object-storage",
    "aws007_dynamic_origin": "backend-server",
    "aws007_lambda_edge": "serverless-function",
    "aws007_acm": "custom-component",
    "aws007_shield": "custom-component",
    "aws007_cloudwatch": "monitoring",
}
CUSTOM_COMPONENT_GAPS = {"aws007_acm", "aws007_shield"}


def load_guide() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^    id:\s*"{re.escape(component_type)}"\s*,', catalog)
    assert match is not None, f"Unknown catalog component ID {component_type!r}"
    following = re.search(r"(?m)^  \},\s*$", catalog[match.end() :])
    assert following is not None, f"Could not delimit catalog component {component_type!r}"
    return catalog[match.start() : match.end() + following.start()]


def expected_anchors() -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }


def test_live_brief_is_preserved_and_draft_stays_unpublished():
    raw, guide = load_guide()
    assert raw["problem_id"] == guide.problem_id == FROZEN_BRIEF["id"]
    assert raw["version"] == "1.0-local-draft"
    assert guide.requirementRevision is None

    opening = guide.steps[0].content
    for field in ("title", "slug", "description", "difficulty", "category", "domain", "estimated_time"):
        assert FROZEN_BRIEF[field] in opening
    for field in ("requirements", "constraints", "hints", "tags", "companies"):
        assert all(value in opening for value in FROZEN_BRIEF[field]), field
    assert "has_guided_walkthrough=false" in opening
    assert "unpublished local draft" in opening
    assert FROZEN_BRIEF["has_guided_walkthrough"] is False


def test_ordered_steps_cover_every_brief_anchor_with_graph_actions():
    _, guide = load_guide()
    assert guide.totalSteps == len(guide.steps) == 35
    assert [step.stepNumber for step in guide.steps] == list(range(1, 36))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in STEP_TYPES for step in guide.steps)

    all_anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    actionable_anchors = {
        anchor
        for step in guide.steps
        if step.type in {"add_component", "add_connection", "update_component"}
        for anchor in step.requirementIds
    }
    assert all_anchors == actionable_anchors == expected_anchors()

    for step in guide.steps:
        if step.type == "add_component":
            assert step.component is not None
        elif step.type == "add_connection":
            assert step.connection is not None
        elif step.type == "update_component":
            assert step.componentUpdate is not None
        elif step.type == "decision_point":
            assert step.decision is not None and step.decision.question and step.decision.chosen
        elif step.type == "scale_trigger":
            assert step.scaleTrigger is not None
            assert all(getattr(step.scaleTrigger, key) for key in ("metric", "action", "impact"))

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1


def test_components_use_supported_catalog_properties_and_limit_custom_gaps():
    raw, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step.get("type") == "add_component"
    }
    assert {node_id: row["componentType"] for node_id, row in additions.items()} == EXPECTED_COMPONENT_TYPES
    assert {node_id for node_id, row in additions.items() if row["componentType"] == "custom-component"} == CUSTOM_COMPONENT_GAPS

    for step in raw["steps"]:
        if step.get("type") == "add_component":
            component = step["component"]
            component_type = component["componentType"]
            properties = component.get("properties", {})
            assert {"componentName", "purpose"} <= set(properties)
        elif step.get("componentUpdate"):
            update = step["componentUpdate"]
            component = additions[update["nodeId"]]
            component_type = component["componentType"]
            properties = update.get("properties", {})
        else:
            continue

        block = catalog_block(catalog, component_type)
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert properties
        assert set(properties) <= supported, (
            f"{step['id']} uses unsupported {component_type} properties: "
            f"{sorted(set(properties) - supported)}"
        )

    for node_id in CUSTOM_COMPONENT_GAPS:
        assert additions[node_id]["properties"]["technology"]
        assert "no " in additions[node_id]["properties"]["notes"].casefold()


def test_replay_builds_one_connected_delivery_graph_with_valid_connections():
    raw, _ = load_guide()
    replay = build_architecture(raw)
    architecture = replay["architecture"]
    components = {component["id"] for component in architecture["components"]}
    connections = architecture["connections"]
    assert components == set(EXPECTED_COMPONENT_TYPES)
    assert len(connections) == 10
    assert len(replay["appliedStepIds"]) > len(replay["explanationOnlyStepIds"])

    neighbors = {component_id: set() for component_id in components}
    edge_ids = set()
    for connection in connections:
        assert connection["type"] in CONNECTION_TYPES
        assert connection["source"] in components and connection["target"] in components
        assert connection["id"] not in edge_ids
        edge_ids.add(connection["id"])
        neighbors[connection["source"]].add(connection["target"])
        neighbors[connection["target"]].add(connection["source"])

    reached: set[str] = set()
    pending = deque([next(iter(components))])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == components


def test_walkthrough_reuses_catalog_roles_and_does_not_invent_sizing_values():
    raw, _ = load_guide()
    narrative = " ".join(step.get("content", "") for step in raw["steps"])
    measurements = re.findall(
        r"\b\d+(?:\.\d+)?\s*(?:%|ms\b|seconds?\b|minutes?\b|hours?\b|"
        r"requests per second\b|rps\b|GB\b|TB\b|users\b|instances\b)",
        narrative,
        flags=re.IGNORECASE,
    )
    assert set(measurements) == {"45 minutes", "80%", "100ms"}

    text = json.dumps(raw, ensure_ascii=False).casefold()
    for supplied_target in (
        "cache hit ratio above 80%",
        "latency under 100ms globally",
        "10m+ requests per day",
        "handle traffic spikes gracefully",
        "minimize origin server load",
    ):
        assert supplied_target in text
    assert "peak rate" in text
    assert "10m+ requests per day as the supplied daily target" in text
