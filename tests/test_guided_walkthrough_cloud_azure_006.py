"""Focused frozen-brief and structural checks for the Azure HPC walkthrough draft."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "cloud_azure_006"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

# These values were fetched from the strongly consistent DynamoDB item in ap-south-1.
TITLE = "Design a High-Performance Computing Cluster"
DESCRIPTION = (
    "Design an HPC cluster that deploys large-scale compute nodes, runs parallel "
    "scientific workloads, optimizes job scheduling, and provides low-latency networking."
)
REQUIREMENTS = [
    "Deploy large-scale compute clusters",
    "Run parallel workloads efficiently",
    "Manage job scheduling and queuing",
    "Optimize network for MPI workloads",
    "Cache shared file systems",
    "Auto-scale based on job queue",
    "Monitor resource utilization",
    "Support scientific simulations",
]
CONSTRAINTS = [
    "Network latency under 2 microseconds",
    "Support 10,000+ cores",
    "Minimize job wait time",
    "Cost-effective compute resources",
    "High throughput for I/O operations",
]
HINTS = [
    "Azure CycleCloud for cluster management",
    "Azure Batch for job scheduling",
    "HPC Cache for file system caching",
    "InfiniBand for low-latency networking",
    "H-series VMs for HPC workloads",
    "Azure NetApp Files for shared storage",
]
EXPECTED_ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}
GRAPH_ACTION_TYPES = {"add_component", "add_connection"}
EXPECTED_COMPONENT_TYPES = {
    "workload_submitters": "custom-component",
    "batch_scheduler": "queue",
    "hpc_compute_pool": "custom-component",
    "infiniband_fabric": "custom-component",
    "shared_filesystem": "file-storage",
    "hpc_cache": "custom-component",
    "resource_monitoring": "monitoring",
}
EXPECTED_CONNECTION_PAIRS = {
    ("workload_submitters", "batch_scheduler"),
    ("batch_scheduler", "hpc_compute_pool"),
    ("hpc_compute_pool", "infiniband_fabric"),
    ("hpc_compute_pool", "hpc_cache"),
    ("shared_filesystem", "hpc_cache"),
    ("batch_scheduler", "resource_monitoring"),
    ("hpc_compute_pool", "resource_monitoring"),
    ("infiniband_fabric", "resource_monitoring"),
    ("hpc_cache", "resource_monitoring"),
    ("shared_filesystem", "resource_monitoring"),
}


def _load() -> tuple[dict, dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    problems = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in problems if row["id"] == PROBLEM_ID)
    return raw, problem, GuidedWalkthrough.model_validate(raw)


def _brief_prefix() -> str:
    lines = [
        "Problem brief copied verbatim from the current DynamoDB row:",
        f"Title: {TITLE}",
        f"Description: {DESCRIPTION}",
        "Requirements:",
        *(f"- {item}" for item in REQUIREMENTS),
        "Constraints:",
        *(f"- {item}" for item in CONSTRAINTS),
        "Hints:",
        *(f"- {item}" for item in HINTS),
        "",
    ]
    return "\n".join(lines)


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


def _step_text(step: dict) -> list[str]:
    texts = [step["title"], step["content"]]
    component = step.get("component")
    if component:
        texts.extend(
            [
                component["label"],
                component["description"],
                component["highlightReason"],
                *(str(value) for value in component.get("properties", {}).values()),
            ]
        )
    connection = step.get("connection")
    if connection:
        texts.extend([connection["label"], connection["description"]])
    decision = step.get("decision")
    if decision:
        texts.extend([decision["question"], decision["chosen"], decision["chosenReason"]])
        texts.extend(
            text
            for alternative in decision.get("alternatives", [])
            for text in (alternative["option"], alternative["tradeoff"])
        )
    trigger = step.get("scaleTrigger")
    if trigger:
        texts.extend([trigger["metric"], trigger["action"], trigger["impact"]])
    return texts


def test_frozen_brief_matches_live_row_and_walkthrough_is_unpublished():
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
    assert raw["steps"][0]["content"].startswith(_brief_prefix())


def test_phases_cover_every_step_and_all_brief_anchors_are_actionable():
    raw, _, guide = _load()

    assert guide.totalSteps == len(guide.steps) == 38
    assert [step.stepNumber for step in guide.steps] == list(range(1, 39))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert [
        (phase.name, phase.stepRange[0], phase.stepRange[1]) for phase in guide.phases
    ] == [
        ("Frame the workload and choose a scheduling model", 1, 7),
        ("Submit and describe scientific jobs", 8, 12),
        ("Allocate parallel compute over the MPI fabric", 13, 19),
        ("Route shared file access through an HPC cache", 20, 26),
        ("Measure queueing, capacity, I/O, and cost", 27, 38),
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
        if step["type"] in GRAPH_ACTION_TYPES or step.get("scaleTrigger")
        for anchor in step.get("requirementIds", [])
    }
    assert action_anchors == EXPECTED_ANCHORS

    for step in raw["steps"][1:]:
        assert not any(re.search(r"\d", text) for text in _step_text(step)), (
            f"{step['id']} introduces a numeric value beyond the verbatim brief"
        )


def test_components_use_catalog_types_and_supported_editable_properties():
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

    custom_labels = {
        component["label"]
        for component in additions.values()
        if component["componentType"] == "custom-component"
    }
    assert custom_labels == {
        "Scientific Workload Submitters",
        "H-series VM Compute Pool",
        "InfiniBand MPI Fabric",
        "Azure HPC Cache",
    }

    for component in additions.values():
        assert set(component["position"]) == {"x", "y"}
        assert component["properties"]["componentName"] == component["label"]
        assert len(component["properties"]["purpose"]) >= 40
        _assert_supported_properties(component["componentType"], component["properties"], catalog)


def test_ordered_replay_builds_the_expected_connected_architecture():
    raw, _, _ = _load()
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
    pending = deque(["workload_submitters"])
    while pending:
        current = pending.popleft()
        if current not in reached:
            reached.add(current)
            pending.extend(neighbors[current] - reached)
    assert reached == nodes.keys()


def test_guidance_covers_hpc_hints_without_claiming_unverified_targets():
    raw, _, _ = _load()
    text = "\n".join(
        value
        for step in raw["steps"]
        for value in _step_text(step)
    ).casefold()

    for phrase in (
        "azure cyclecloud",
        "azure batch",
        "hpc cache",
        "infiniband",
        "h-series vms",
        "azure netapp files",
        "10,000+ cores",
        "2 microseconds",
        "job wait",
        "cost-effective",
        "high throughput",
    ):
        assert phrase in text, f"Missing problem-specific guidance: {phrase}"
