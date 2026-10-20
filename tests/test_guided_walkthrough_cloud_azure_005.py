"""Focused structural checks for the customer identity walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_azure_005"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

TITLE = "Build a Secure Identity Management Solution for Customers"
DESCRIPTION = (
    "Design an identity management solution that provides user registration, social "
    "identity integration, multi-factor authentication, and conditional access policies."
)
REQUIREMENTS = [
    "User registration and sign-in",
    "Social identity provider integration",
    "Multi-factor authentication",
    "Custom user attributes",
    "Password reset and recovery",
    "Conditional access policies",
    "Branding and customization",
    "Support millions of users",
]
CONSTRAINTS = [
    "Authentication latency under 500ms",
    "Support 100k+ daily logins",
    "Comply with GDPR and privacy laws",
    "Implement risk-based authentication",
    "Handle account takeover prevention",
]
HINTS = [
    "Azure AD B2C for customer identity",
    "Custom policies for user journeys",
    "MFA for security",
    "Conditional Access for risk assessment",
    "Graph API for user management",
    "Application Insights for monitoring",
]
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
EXPECTED_ACTION_ANCHORS = {
    "identity_05": {"legacy-requirement:1", "legacy-constraint:5"},
    "identity_06": EXPECTED_ANCHORS,
    "identity_07": {"legacy-requirement:1"},
    "identity_09": {
        "legacy-requirement:2",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "identity_10": {
        "legacy-requirement:1",
        "legacy-requirement:2",
        "legacy-constraint:5",
    },
    "identity_12": {
        "legacy-requirement:1",
        "legacy-requirement:3",
        "legacy-constraint:4",
        "legacy-constraint:5",
    },
    "identity_19": {"legacy-constraint:5"},
    "identity_20": {"legacy-constraint:5"},
    "identity_22": {"legacy-constraint:5"},
    "identity_23": {
        "legacy-requirement:4",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "identity_24": {"legacy-requirement:4", "legacy-constraint:5"},
    "identity_25": {
        "legacy-requirement:4",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "identity_26": {"legacy-requirement:4", "legacy-constraint:5"},
    "identity_29": {
        "legacy-constraint:1",
        "legacy-constraint:3",
        "legacy-constraint:4",
        "legacy-constraint:5",
    },
    "identity_30": {
        "legacy-requirement:6",
        "legacy-constraint:1",
        "legacy-constraint:3",
        "legacy-constraint:4",
        "legacy-constraint:5",
    },
    "identity_31": {"legacy-constraint:3", "legacy-constraint:5"},
    "identity_32": {"legacy-requirement:4", "legacy-constraint:3"},
}
EXPECTED_COMPONENT_TYPES = {
    "customer_apps": "custom-component",
    "customer_identity": "auth-service",
    "social_idps": "custom-component",
    "customer_api_gateway": "api-gateway",
    "identity_admin_api": "serverless-function",
    "microsoft_graph": "custom-component",
    "application_insights": "monitoring",
}
EXPECTED_CONNECTION_PAIRS = {
    ("customer_apps", "customer_identity"),
    ("customer_identity", "social_idps"),
    ("customer_apps", "customer_api_gateway"),
    ("customer_identity", "customer_api_gateway"),
    ("customer_api_gateway", "identity_admin_api"),
    ("identity_admin_api", "microsoft_graph"),
    ("customer_identity", "application_insights"),
    ("customer_api_gateway", "application_insights"),
    ("identity_admin_api", "application_insights"),
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


def test_frozen_brief_matches_target_and_walkthrough_is_only_a_review_draft():
    raw, problem, guide = _load()

    assert problem["id"] == PROBLEM_ID
    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert raw["totalSteps"] == len(raw["steps"]) == 42


def test_phase_sequence_and_every_brief_anchor_has_a_design_action():
    raw, _, guide = _load()
    assert [step.stepNumber for step in guide.steps] == list(range(1, 43))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert [
        (phase.name, phase.stepRange[0], phase.stepRange[1]) for phase in guide.phases
    ] == [
        ("Frame the customer identity boundary and targets", 1, 8),
        ("Build the customer sign-in and policy journeys", 9, 18),
        ("Protect application APIs and privileged user management", 19, 30),
        ("Address privacy, failures, scale, and verification", 31, 42),
    ]

    covered_numbers = []
    for phase in guide.phases:
        start, end = phase.stepRange
        expected_start = covered_numbers[-1] + 1 if covered_numbers else 1
        assert start == expected_start
        covered_numbers.extend(range(start, end + 1))
        assert all(
            step.phase == phase.name
            for step in guide.steps
            if start <= step.stepNumber <= end
        )
    assert covered_numbers == list(range(1, guide.totalSteps + 1))

    anchors = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert anchors == EXPECTED_ANCHORS
    action_anchors = {
        anchor
        for step in raw["steps"]
        if step["type"] in {"add_component", "add_connection"} or step.get("componentUpdate")
        for anchor in step.get("requirementIds", [])
    }
    assert action_anchors == EXPECTED_ANCHORS
    action_anchor_map = {
        step["id"]: set(step.get("requirementIds", []))
        for step in raw["steps"]
        if step["type"] in {"add_component", "add_connection"}
        or step.get("componentUpdate")
    }
    assert action_anchor_map == EXPECTED_ACTION_ANCHORS

    for step in raw["steps"]:
        if step["type"] == "add_component":
            assert step["component"]["highlightReason"]
        elif step["type"] == "add_connection":
            assert step["connection"]["label"] and step["connection"]["description"]
        elif step["type"] == "decision_point":
            assert step["decision"]["question"] and step["decision"]["chosenReason"]
            assert len(step["decision"]["alternatives"]) >= 2
        elif step["type"] == "scale_trigger":
            trigger = step["scaleTrigger"]
            assert trigger["metric"] and trigger["action"] and trigger["impact"]


def test_catalog_types_properties_and_ordered_architecture_are_supported():
    raw, _, _ = _load()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step["component"]["nodeId"]: step["component"]
        for step in raw["steps"]
        if step["type"] == "add_component"
    }
    assert {
        node_id: component["componentType"] for node_id, component in additions.items()
    } == EXPECTED_COMPONENT_TYPES

    for component in additions.values():
        assert set(component["position"]) == {"x", "y"}
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 80
        _assert_supported_properties(component["componentType"], component["properties"], catalog)

    for step in raw["steps"]:
        update = step.get("componentUpdate")
        if update:
            component = additions[update["nodeId"]]
            _assert_supported_properties(
                component["componentType"], update["properties"], catalog
            )

    added_nodes = set()
    edge_ids = set()
    action_ids = []
    for step in sorted(raw["steps"], key=lambda item: item["stepNumber"]):
        if step["type"] == "add_component":
            node_id = step["component"]["nodeId"]
            assert node_id not in added_nodes
            added_nodes.add(node_id)
            action_ids.append(step["id"])
        elif step["type"] == "add_connection":
            edge = step["connection"]
            assert edge["sourceNodeId"] in added_nodes
            assert edge["targetNodeId"] in added_nodes
            assert edge["edgeId"] not in edge_ids
            edge_ids.add(edge["edgeId"])
            action_ids.append(step["id"])
        elif step.get("componentUpdate"):
            action_ids.append(step["id"])

    built = build_architecture(raw)
    architecture = built["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert set(nodes) == set(EXPECTED_COMPONENT_TYPES)
    assert len(edges) == len(EXPECTED_CONNECTION_PAIRS)
    assert built["appliedStepIds"] == action_ids
    assert built["provenance"]["problemId"] == PROBLEM_ID
    assert built["provenance"]["walkthroughVersion"] == "1.0.0-review-draft"

    actual_pairs = set()
    neighbors = {node_id: set() for node_id in nodes}
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] and edge["label"] and edge["description"]
        actual_pairs.add((edge["source"], edge["target"]))
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    assert actual_pairs == EXPECTED_CONNECTION_PAIRS

    reached = set()
    pending = deque(["customer_apps"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes.keys()


def test_guidance_covers_security_privacy_and_only_supplied_numeric_targets():
    raw, _, _ = _load()
    content = "\n".join(step["content"] for step in raw["steps"]).casefold()
    for phrase in (
        "azure ad b2c", "microsoft graph", "application insights", "conditional access",
        "social", "mfa", "password recovery", "account-takeover", "gdpr",
        "under 500ms", "100k+ daily logins", "regions", "no availability sla",
    ):
        assert phrase in content, f"Missing problem-specific guidance: {phrase}"

    numeric_targets = set(
        re.findall(r"\b\d+(?:\.\d+)?\s*(?:ms|k\+\s+daily logins)\b", content)
    )
    assert numeric_targets == {"500ms", "100k+ daily logins"}


def test_authentication_authorization_proofing_tenant_and_lifecycle_are_distinct():
    raw, _, _ = _load()
    steps = {step["id"]: step for step in raw["steps"]}

    api_auth = steps["identity_21"]["content"].casefold()
    assert "authentication validates" in api_auth
    assert "authorization then evaluates" in api_auth
    assert "conditional access" in api_auth
    assert "does not replace api authorization" in api_auth
    assert "the brief does not state whether the application is multi-tenant" in api_auth
    assert "never trust a client-supplied tenant identifier alone" in api_auth

    social = steps["identity_11"]["content"].casefold()
    assert "not formal proofing" in social
    assert "not identity proofing" in social
    assert "the frozen brief asks for social sign-in, not identity proofing" in social
    validation = steps["identity_40"]["content"].casefold()
    assert "the brief does not require formal identity proofing" in validation
    assert "if the product is multi-tenant" in validation

    recovery = steps["identity_15"]["content"].casefold()
    for lifecycle_concept in (
        "revokes existing sessions or refresh credentials",
        "access-token and refresh-token lifetime",
        "rotation/revocation",
        "logout semantics",
        "none of those durations or guarantees is supplied by the brief",
    ):
        assert lifecycle_concept in recovery
    graph_credential = steps["identity_26"]["content"].casefold()
    assert "approved server-side credential mechanism" in graph_credential
    assert "rotation, expiry, and revocation" in graph_credential
    assert "do not expose graph credentials" in graph_credential

    evidence = steps["identity_41"]["content"].casefold()
    assert "not proof of production capacity, gdpr compliance, or a provider sla" in evidence
