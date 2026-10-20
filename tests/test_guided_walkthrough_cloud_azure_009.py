"""Focused structural checks for the Azure consortium blockchain walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_azure_009"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

TITLE = "Design a Blockchain Network Solution"
DESCRIPTION = (
    "Design a blockchain network that deploys smart contracts, integrates with external "
    "systems, ensures data integrity, and provides consortium governance."
)
REQUIREMENTS = [
    "Deploy blockchain network",
    "Implement smart contracts",
    "Manage consortium members",
    "Store off-chain data",
    "Integrate with existing systems",
    "Monitor blockchain transactions",
    "Ensure data immutability",
    "Handle consensus mechanisms",
]
CONSTRAINTS = [
    "Transaction finality under 10 seconds",
    "Support 1000+ transactions per second",
    "Ensure Byzantine fault tolerance",
    "Maintain privacy for sensitive data",
    "Scale consortium to 100+ members",
]
HINTS = [
    "Azure Blockchain Service for network",
    "Ethereum or Hyperledger Fabric",
    "Cosmos DB for off-chain storage",
    "Logic Apps for integration",
    "Azure Monitor for observability",
    "Key Vault for cryptographic keys",
]
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
EXPECTED_ACTION_ANCHORS = {
    "blockchain_04": {"legacy-constraint:5"},
    "blockchain_05": {"legacy-requirement:3", "legacy-constraint:4"},
    "blockchain_06": {"legacy-requirement:3", "legacy-constraint:4"},
    "blockchain_07": {
        "legacy-requirement:4",
        "legacy-requirement:5",
        "legacy-constraint:1",
    },
    "blockchain_08": {
        "legacy-requirement:3",
        "legacy-requirement:6",
        "legacy-constraint:4",
    },
    "blockchain_09": {
        "legacy-requirement:1",
        "legacy-requirement:7",
        "legacy-requirement:8",
        "legacy-constraint:1",
        "legacy-constraint:2",
        "legacy-constraint:3",
        "legacy-constraint:5",
    },
    "blockchain_10": {
        "legacy-requirement:8",
        "legacy-constraint:1",
        "legacy-constraint:2",
    },
    "blockchain_11": {
        "legacy-requirement:2",
        "legacy-requirement:5",
        "legacy-requirement:7",
    },
    "blockchain_12": {
        "legacy-requirement:2",
        "legacy-requirement:7",
        "legacy-requirement:8",
        "legacy-constraint:1",
    },
    "blockchain_13": {
        "legacy-requirement:3",
        "legacy-requirement:8",
        "legacy-constraint:5",
    },
    "blockchain_14": {"legacy-requirement:3"},
    "blockchain_15": {"legacy-requirement:3", "legacy-requirement:8"},
    "blockchain_17": {
        "legacy-requirement:2",
        "legacy-requirement:3",
        "legacy-constraint:4",
    },
    "blockchain_18": {
        "legacy-requirement:2",
        "legacy-requirement:3",
        "legacy-constraint:4",
    },
    "blockchain_21": {"legacy-requirement:4", "legacy-constraint:4"},
    "blockchain_22": {"legacy-requirement:4", "legacy-constraint:4"},
    "blockchain_25": {"legacy-requirement:5"},
    "blockchain_26": {"legacy-requirement:5"},
    "blockchain_27": {"legacy-requirement:5"},
    "blockchain_28": {"legacy-requirement:5"},
    "blockchain_29": {
        "legacy-requirement:5",
        "legacy-requirement:8",
        "legacy-constraint:1",
    },
    "blockchain_31": {
        "legacy-requirement:6",
        "legacy-requirement:8",
        "legacy-constraint:1",
        "legacy-constraint:2",
        "legacy-constraint:3",
        "legacy-constraint:4",
    },
    "blockchain_32": {
        "legacy-requirement:6",
        "legacy-constraint:1",
        "legacy-constraint:4",
    },
    "blockchain_33": {
        "legacy-requirement:6",
        "legacy-requirement:8",
        "legacy-constraint:1",
        "legacy-constraint:3",
    },
    "blockchain_34": {
        "legacy-requirement:5",
        "legacy-requirement:6",
        "legacy-constraint:4",
    },
    "blockchain_35": {
        "legacy-requirement:3",
        "legacy-requirement:8",
        "legacy-constraint:5",
    },
    "blockchain_36": {
        "legacy-requirement:2",
        "legacy-requirement:6",
        "legacy-requirement:8",
        "legacy-constraint:1",
        "legacy-constraint:2",
    },
}
ACTION_STEP_TYPES = {"add_component", "add_connection", "scale_trigger"}
EXPECTED_COMPONENT_TYPES = {
    "consortium_clients": "custom-component",
    "member_api_gateway": "api-gateway",
    "transaction_service": "custom-component",
    "consortium_network": "custom-component",
    "smart_contracts": "custom-component",
    "consortium_governance": "custom-component",
    "key_vault": "secrets-manager",
    "offchain_store": "database",
    "integration_workflows": "custom-component",
    "existing_systems": "custom-component",
    "azure_monitor": "monitoring",
}
EXPECTED_CONNECTION_PAIRS = {
    ("consortium_clients", "member_api_gateway"),
    ("member_api_gateway", "transaction_service"),
    ("transaction_service", "consortium_network"),
    ("consortium_network", "smart_contracts"),
    ("transaction_service", "consortium_governance"),
    ("consortium_governance", "consortium_network"),
    ("transaction_service", "key_vault"),
    ("transaction_service", "offchain_store"),
    ("existing_systems", "integration_workflows"),
    ("integration_workflows", "transaction_service"),
    ("consortium_network", "integration_workflows"),
    ("transaction_service", "azure_monitor"),
    ("consortium_network", "azure_monitor"),
    ("integration_workflows", "azure_monitor"),
}


def _load() -> tuple[dict, dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, problem, GuidedWalkthrough.model_validate(raw)


def _iter_text(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _iter_text(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_text(nested)


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
            assert options, f"Missing catalog options for {component_type}.{key}"
            assert value in set(re.findall(r'"([^"]+)"', options[1]))


def test_frozen_brief_matches_target_and_walkthrough_is_only_a_review_draft():
    raw, problem, guide = _load()

    assert problem["id"] == PROBLEM_ID
    assert problem["slug"] == "design-a-blockchain-network-solution"
    assert problem["title"] == TITLE
    assert problem["description"] == DESCRIPTION
    assert problem["requirements"] == REQUIREMENTS
    assert problem["constraints"] == CONSTRAINTS
    assert problem["hints"] == HINTS
    assert problem["companies"] == ["Microsoft", "ConsenSys", "IBM"]
    assert problem["has_guided_walkthrough"] is False
    assert guide.problem_id == PROBLEM_ID
    assert guide.version == "1.0.0-review-draft"
    assert guide.requirementRevision is None
    assert raw["totalSteps"] == len(raw["steps"]) == 40


def test_phase_sequence_and_every_brief_anchor_has_a_design_action():
    raw, _, guide = _load()
    assert [step.stepNumber for step in guide.steps] == list(range(1, 41))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert [
        (phase.name, phase.stepRange[0], phase.stepRange[1]) for phase in guide.phases
    ] == [
        ("Frame consortium, transaction, and finality targets", 1, 10),
        ("Model the ledger, contracts, membership, and key boundary", 11, 20),
        ("Separate private off-chain data from integrations", 21, 30),
        ("Observe, scale, and validate the design", 31, 40),
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
        step["id"]: set(step.get("requirementIds", []))
        for step in raw["steps"]
        if step["type"] in ACTION_STEP_TYPES
    }
    assert action_anchors == EXPECTED_ACTION_ANCHORS
    assert set().union(*action_anchors.values()) == EXPECTED_ANCHORS

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


def test_catalog_types_properties_and_ordered_connected_architecture_are_supported():
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

    assert additions["key_vault"]["properties"]["provider"] == "Azure Key Vault"
    assert additions["offchain_store"]["properties"]["type"] == "NoSQL"
    assert additions["integration_workflows"]["properties"]["technology"] == "Azure Logic Apps"
    assert additions["azure_monitor"]["properties"]["stack"] == "Azure Monitor"

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
    pending = deque(["consortium_clients"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes.keys()


def test_guide_preserves_open_chain_privacy_governance_and_workload_decisions():
    raw, _, _ = _load()
    content = "\n".join(step["content"] for step in raw["steps"]).casefold()
    for phrase in (
        "ethereum or hyperledger fabric",
        "consensus algorithm",
        "byzantine fault tolerance",
        "privacy scheme",
        "voting thresholds",
        "1000+ transactions per second",
        "under 10 seconds",
        "100+ members",
        "azure cosmos db",
        "azure logic apps",
        "azure monitor",
        "azure key vault",
    ):
        assert phrase in content, f"Missing problem-specific guidance: {phrase}"

    assert "majority voting" in content
    assert "quorum" in content
    assert "do not assume" in content
    numeric_targets = set(
        re.findall(r"\b\d+\+?\s*(?:transactions per second|seconds|members)\b", content)
    )
    assert numeric_targets == {
        "10 seconds",
        "1000+ transactions per second",
        "100+ members",
    }


def test_vendor_candidates_and_blockchain_properties_are_not_promised_as_guarantees():
    raw, _, _ = _load()
    steps = {step["id"]: step for step in raw["steps"]}
    text = "\n".join(_iter_text(raw)).casefold()

    assert "not named in the brief's hints" in steps["blockchain_05"]["content"].casefold()
    assert (
        "not as a claim about present availability or suitability"
        in steps["blockchain_09"]["content"].casefold()
    )
    assert (
        "where supported by the selected chain"
        in steps["blockchain_17"]["component"]["properties"]["purpose"].casefold()
    )
    assert "validate partitioning and service fit" in steps["blockchain_21"]["content"].casefold()
    assert "do not assume a delivery guarantee" in text
    assert "not a guarantee of chain-specific telemetry coverage" in steps["blockchain_31"]["content"].casefold()
    assert "immutability depends on the selected chain" in steps["blockchain_20"]["content"].casefold()
    security_step_text = "\n".join(_iter_text(steps["blockchain_37"])).casefold()
    assert "do not infer bft from a product name" in security_step_text
    assert "require platform-specific fault tests" in security_step_text

    numeric_claim_pattern = re.compile(
        r"\b\d[\d,]*(?:\.\d+)?\+?\s*(?:"
        r"transactions?\s*(?:per second|/s|/sec)|requests?\s*(?:per second|/s|/sec)|"
        r"operations?\s+per second|tps|rps|ops/s|seconds?|milliseconds?|ms|%|"
        r"members?|validators?|nodes?|faults?)\b",
        re.IGNORECASE,
    )
    numeric_claims = {
        re.sub(r"\s+", " ", match.group(0).casefold()).strip()
        for match in numeric_claim_pattern.finditer(text)
    }
    assert numeric_claims == {
        "10 seconds",
        "1000+ transactions per second",
        "100+ members",
        "100 validators",
    }
    assert re.search(r"\bdoes not imply 100 validators\b", text)
    assert not re.search(r"\bp(?:50|90|95|99)\b", text)
