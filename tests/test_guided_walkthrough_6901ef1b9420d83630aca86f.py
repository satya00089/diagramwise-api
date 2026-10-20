"""Frozen-brief, catalog, safeguards, and replay checks for auth review draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "6901ef1b9420d83630aca86f"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

FROZEN_BRIEF = {
    "id": "6901ef1b9420d83630aca86f",
    "title": "Design a User Login and Authentication System",
    "description": "Design a secure authentication system with login, registration, and session management.",
    "requirements": [
        "User registration and login",
        "Password hashing and security",
        "Session management",
        "Multi-factor authentication (MFA)",
        "Password reset functionality",
        "OAuth and social login",
        "Rate limiting for login attempts",
        "Handle millions of users",
    ],
    "constraints": [
        "Secure password storage (bcrypt, argon2)",
        "Prevent brute force attacks",
        "Session hijacking prevention",
        "GDPR and privacy compliance",
        "Low latency for authentication",
    ],
    "hints": [
        "JWT or session tokens",
        "Redis for session storage",
        "Rate limiting per IP/user",
        "Email verification for registration",
        "Audit logs for security events",
    ],
}
ANCHORS = {
    *(f"legacy-requirement:{index}" for index in range(1, 9)),
    *(f"legacy-constraint:{index}" for index in range(1, 6)),
}
ACTION_TYPES = {
    "add_component",
    "add_connection",
    "decision_point",
    "update_component",
    "scale_trigger",
}
STEP_TYPES = ACTION_TYPES | {"explanation"}
CONNECTION_TYPES = {
    "http",
    "api-call",
    "database-connection",
    "message-queue",
    "data-flow",
}
EXPECTED_PHASES = [
    ("Establish the request path and abuse boundary", 1, 12),
    ("Place identity and security stores", 13, 18),
    ("Connect identity, recovery, and audit flows", 19, 32),
    ("Harden credentials, recovery, and federation", 33, 43),
    ("Scale from measured behavior and review open policies", 44, 45),
]


def load_guide():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, GuidedWalkthrough.model_validate(raw), problem


def catalog_block(catalog: str, component_type: str, step_id: str) -> str:
    match = re.search(rf'\bid:\s*"{re.escape(component_type)}"', catalog)
    assert match is not None, f"{step_id}: unknown catalog component {component_type}"
    block_end = catalog.find("\n  },", match.start())
    assert block_end > match.start(), f"{step_id}: incomplete component catalog entry"
    return catalog[match.start() : block_end]


def assert_supported_catalog_properties(
    catalog: str, component_type: str, properties: dict, step_id: str
) -> None:
    block = catalog_block(catalog, component_type, step_id)
    supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
    assert set(properties) <= supported, (
        f"{step_id}: unsupported {component_type} properties "
        f"{sorted(set(properties) - supported)}"
    )
    for key, value in properties.items():
        field_start = re.search(rf'\{{\s*key:\s*"{re.escape(key)}"', block)
        assert field_start, f"{step_id}: missing catalog property {component_type}.{key}"
        field_end = block.find("},", field_start.start())
        assert field_end > field_start.start(), f"{step_id}: incomplete property {key}"
        field = block[field_start.start() : field_end]
        field_type = re.search(r'\btype:\s*"([^"]+)"', field)
        assert field_type, f"{step_id}: property {component_type}.{key} has no type"
        if field_type.group(1) in {"text", "textarea"}:
            assert isinstance(value, str), f"{step_id}/{key} must be text"
        elif field_type.group(1) == "boolean":
            assert type(value) is bool, f"{step_id}/{key} must be boolean"
        elif field_type.group(1) == "number":
            assert type(value) in {int, float}, f"{step_id}/{key} must be numeric"
        elif field_type.group(1) == "select":
            options = re.search(r'\boptions:\s*\[([^\]]*)\]', field, re.DOTALL)
            assert options, f"{step_id}/{key}: catalog select options are missing"
            allowed = set(re.findall(r'"([^"]+)"', options.group(1)))
            assert value in allowed, f"{step_id}/{key}: unsupported select option {value!r}"


def reachable(start: str, neighbors: dict[str, set[str]]) -> set[str]:
    reached = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    return reached


def test_frozen_brief_matches_repository_snapshot_and_schema():
    raw, guide, problem = load_guide()

    snapshot_brief = {key: problem[key] for key in FROZEN_BRIEF}
    assert snapshot_brief == FROZEN_BRIEF
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert guide.totalSteps == len(guide.steps) == 45
    assert raw["totalSteps"] == len(raw["steps"])
    assert {step.type for step in guide.steps} == STEP_TYPES
    assert all(step.title.strip() and step.content.strip() for step in guide.steps)


def test_phases_are_ordered_and_every_anchor_has_an_action():
    _, guide, _ = load_guide()

    assert [(phase.name, *phase.stepRange) for phase in guide.phases] == EXPECTED_PHASES
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    next_step = 1
    all_anchors = set()
    action_anchors = set()
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step and start <= end <= guide.totalSteps
        assert all(step.phase == phase.name for step in guide.steps[start - 1 : end])
        next_step = end + 1
    assert next_step == guide.totalSteps + 1

    for step in guide.steps:
        anchors = set(step.requirementIds)
        assert len(anchors) == len(step.requirementIds), f"{step.id}: repeated anchor"
        assert anchors <= ANCHORS, f"{step.id}: unknown anchors {sorted(anchors - ANCHORS)}"
        all_anchors.update(anchors)
        if step.type in ACTION_TYPES:
            action_anchors.update(anchors)
    assert all_anchors == ANCHORS
    assert action_anchors == ANCHORS


def test_catalog_properties_actions_and_replay_form_one_connected_graph():
    raw, guide, _ = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    components = {}
    seen_edges = set()

    for step in guide.steps:
        if step.type == "add_component":
            component = step.component
            assert component is not None
            assert component.nodeId not in components
            assert set(component.position) == {"x", "y"}
            assert all(type(value) in {int, float} for value in component.position.values())
            assert component.properties["componentName"] == component.label
            assert len(component.properties["purpose"]) >= 70
            assert component.highlightReason
            assert component.componentType != "custom-component" or component.nodeId == "auth_external_identity_provider"
            components[component.nodeId] = component
            assert_supported_catalog_properties(
                catalog, component.componentType, component.properties, step.id
            )
        elif step.type == "add_connection":
            connection = step.connection
            assert connection is not None
            assert connection.edgeId not in seen_edges
            assert connection.sourceNodeId in components
            assert connection.targetNodeId in components
            assert connection.connectionType in CONNECTION_TYPES
            assert connection.label and connection.description
            seen_edges.add(connection.edgeId)
        elif step.type == "decision_point":
            assert step.decision is not None
            assert step.decision.chosen and step.decision.chosenReason
            assert len(step.decision.alternatives) >= 2

        if step.componentUpdate is not None:
            update = step.componentUpdate
            assert update.nodeId in components, f"{step.id}: update precedes its component"
            assert update.properties
            assert_supported_catalog_properties(
                catalog, components[update.nodeId].componentType, update.properties, step.id
            )
        if step.type == "scale_trigger":
            assert step.scaleTrigger is not None
            assert step.scaleTrigger.metric and step.scaleTrigger.action and step.scaleTrigger.impact

    assert len(components) == 13
    custom_nodes = [node_id for node_id, component in components.items() if component.componentType == "custom-component"]
    assert custom_nodes == ["auth_external_identity_provider"]
    assert "no catalog concept models an external oauth/oidc identity provider" in (
        components["auth_external_identity_provider"].highlightReason.casefold()
    )

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    nodes = {component["id"]: component for component in architecture["components"]}
    edges = architecture["connections"]
    assert len(nodes) == len(components)
    assert len(edges) == len(seen_edges)
    assert len(replay["appliedStepIds"]) + len(replay["explanationOnlyStepIds"]) == guide.totalSteps
    assert len(replay["appliedStepIds"]) >= 35

    neighbors = {node_id: set() for node_id in nodes}
    edge_pairs = set()
    for edge in edges:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["type"] in CONNECTION_TYPES
        pair = (edge["source"], edge["target"])
        assert pair not in edge_pairs
        edge_pairs.add(pair)
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    assert reachable("auth_web_client", neighbors) == set(nodes)
    assert {
        ("auth_rate_limiter", "auth_service"),
        ("auth_service", "auth_identity_store"),
        ("auth_service", "auth_session_cache"),
        ("auth_external_identity_provider", "auth_service"),
        ("auth_service", "auth_audit_store"),
        ("auth_audit_store", "auth_monitoring"),
    } <= edge_pairs


def test_authentication_safeguards_are_explicit_and_replayed():
    raw, _, _ = load_guide()
    replay = build_architecture(raw)
    nodes = {component["id"]: component for component in replay["architecture"]["components"]}
    authored = json.dumps(raw, ensure_ascii=False).casefold()

    for phrase in (
        "argon2id",
        "bcrypt",
        "unique salt",
        "never store plaintext",
        "reversibly encrypted",
        "email verification",
        "single-use",
        "persist only their digests",
        "webauthn",
        "totp",
        "recovery codes",
        "one-time code hashes",
        "allow-listed redirect",
        "pkce",
        "one-time state",
        "oidc nonce",
        "reject replay",
        "opaque",
        "httponly",
        "samesite",
        "csrf",
        "revoke",
        "per-ip",
        "normalized-account",
        "generic responses",
        "append-only",
        "pseudonymous",
        "retention and deletion",
        "does not claim gdpr compliance",
        "no numeric thresholds",
    ):
        assert phrase in authored, f"Missing authentication safeguard: {phrase}"

    identity_purpose = nodes["auth_identity_store"]["properties"]["purpose"].casefold()
    session_purpose = nodes["auth_session_cache"]["properties"]["purpose"].casefold()
    auth_purpose = nodes["auth_service"]["properties"]["purpose"].casefold()
    audit_purpose = nodes["auth_audit_store"]["properties"]["purpose"].casefold()
    rate_purpose = nodes["auth_rate_limiter"]["properties"]["purpose"].casefold()

    assert "argon2id" in identity_purpose and "bcrypt" in identity_purpose
    assert "never store plaintext" in identity_purpose
    assert "unique salt" in identity_purpose
    assert "opaque session" in auth_purpose
    assert "rotate after authentication" in auth_purpose
    assert "revoke" in auth_purpose
    assert "webauthn/passkeys" in auth_purpose
    assert "pkce verifier" in auth_purpose and "csrf defenses" in auth_purpose
    assert "reject replay" in auth_purpose
    assert nodes["auth_service"]["properties"]["sessions"] == "redis"
    assert nodes["auth_service"]["properties"]["mfa"] is True
    assert nodes["auth_service"]["properties"]["oauth"] is True
    assert "one-time oauth state" in session_purpose
    assert "no link tracking" in nodes["auth_email_service"]["properties"]["purpose"].casefold()
    assert "per-ip" in rate_purpose and "account" in rate_purpose
    assert nodes["auth_rate_limiter"]["properties"]["backend"] == "Redis"
    assert nodes["auth_rate_limiter"]["properties"]["distributed"] is True
    assert "append-only" in audit_purpose and "exclude credentials" in audit_purpose
    assert nodes["auth_audit_store"]["properties"]["auditLog"] is True
    assert nodes["auth_external_identity_provider"]["properties"]["originalComponentId"] == "custom-component"

    numeric_policy_fields = {"requestsPerMinute", "requestsPerSecond", "tokenTTL", "retention"}
    for component in raw["steps"]:
        properties = component.get("component", {}).get("properties", {})
        assert not (numeric_policy_fields & properties.keys())
        update = component.get("componentUpdate", {}).get("properties", {})
        assert not (numeric_policy_fields & update.keys())


def test_frozen_brief_semantics_are_taught_under_their_anchors():
    _, guide, problem = load_guide()
    teaching_checks = [
        ("requirements", 1, ("registration", "login")),
        ("requirements", 2, ("argon2id", "bcrypt", "unique salt", "never store plaintext")),
        ("requirements", 3, ("opaque session", "revoke")),
        ("requirements", 4, ("webauthn/passkeys", "totp", "recovery codes")),
        ("requirements", 5, ("single-use", "reset", "revoke active sessions")),
        ("requirements", 6, ("pkce", "one-time state", "oidc nonce")),
        ("requirements", 7, ("per-ip", "normalized-account", "generic responses")),
        ("requirements", 8, ("millions of users", "load-test")),
        ("constraints", 1, ("argon2id", "bcrypt", "never store plaintext")),
        ("constraints", 2, ("brute-force", "progressive friction", "generic responses")),
        ("constraints", 3, ("httponly", "samesite", "csrf")),
        ("constraints", 4, ("retention and deletion", "does not claim gdpr compliance")),
        ("constraints", 5, ("low authentication latency", "service objectives")),
    ]

    for section, index, phrases in teaching_checks:
        brief_item = problem[section][index - 1]
        assert brief_item == FROZEN_BRIEF[section][index - 1]
        prefix = "legacy-requirement" if section == "requirements" else "legacy-constraint"
        anchor = f"{prefix}:{index}"
        anchored_steps = [step for step in guide.steps if anchor in step.requirementIds]
        assert anchored_steps, f"{brief_item!r}: no walkthrough step cites {anchor}"

        authored = " ".join(step.model_dump_json() for step in anchored_steps).casefold()
        for phrase in phrases:
            assert phrase in authored, (
                f"{brief_item!r} ({anchor}): missing anchored teaching for {phrase!r}"
            )
