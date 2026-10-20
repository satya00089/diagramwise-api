"""Contract and catalog checks for the Azure real-time analytics walkthrough."""

import json
from collections import deque
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / "cloud_azure_008.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"
REQUIRED_ANCHORS = {
    *(f"legacy-requirement:{number}" for number in range(1, 9)),
    *(f"legacy-constraint:{number}" for number in range(1, 6)),
}


def _catalog_entry(catalog: str, component_id: str) -> str:
    entry = re.search(
        rf'(?ms)^ {{4}}id: "{re.escape(component_id)}",.*?^ {{2}}\}},?',
        catalog,
    )
    assert entry, f"Unknown component catalog ID: {component_id}"
    return entry.group(0)


def test_walkthrough_schema_steps_and_requirement_coverage():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    guide = GuidedWalkthrough.model_validate(raw)

    assert guide.problem_id == "cloud_azure_008"
    assert guide.totalSteps == len(guide.steps)
    assert [step.stepNumber for step in guide.steps] == list(
        range(1, guide.totalSteps + 1)
    )
    assert len({step.id for step in guide.steps}) == guide.totalSteps

    phase_numbers = [number for phase in guide.phases for number in range(*(
        phase.stepRange[0], phase.stepRange[1] + 1
    ))]
    assert phase_numbers == list(range(1, guide.totalSteps + 1))
    phase_by_number = {
        number: phase.name
        for phase in guide.phases
        for number in range(phase.stepRange[0], phase.stepRange[1] + 1)
    }
    assert all(phase_by_number[step.stepNumber] == step.phase for step in guide.steps)

    covered = {anchor for step in guide.steps for anchor in step.requirementIds}
    assert REQUIRED_ANCHORS <= covered


def test_actions_replay_as_a_connected_catalog_backed_graph():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    allowed_actions = {
        "add_component",
        "add_connection",
        "decision_point",
        "scale_trigger",
        "explanation",
        "conclusion",
    }
    nodes = set()
    edges = set()

    for step in raw["steps"]:
        assert step["type"] in allowed_actions
        component = step.get("component")
        if component:
            assert component["nodeId"] not in nodes
            nodes.add(component["nodeId"])
            entry = _catalog_entry(catalog, component["componentType"])
            supported = set(re.findall(r'\bkey:\s*"([^"]+)"', entry))
            properties = component.get("properties", {})
            assert {"componentName", "purpose"} <= properties.keys()
            assert set(properties) <= supported

            if component["componentType"] == "object-storage":
                assert properties["provider"] == "Azure Blob"
                assert '"Azure Blob"' in entry
            if component["componentType"] == "database" and component["label"] == "Azure Cosmos DB":
                assert properties["type"] == "NoSQL"
                assert '"NoSQL"' in entry
            if component["componentType"] == "serverless-function":
                assert properties["runtime"] == ".NET"
                assert '".NET"' in entry

        connection = step.get("connection")
        if connection:
            assert connection["sourceNodeId"] in nodes
            assert connection["targetNodeId"] in nodes
            assert connection["edgeId"] not in edges
            edges.add(connection["edgeId"])

    built = build_architecture(raw)
    architecture = built["architecture"]
    assert len(architecture["components"]) == len(nodes)
    assert len(architecture["connections"]) == len(edges)

    adjacency = {node_id: set() for node_id in nodes}
    directed = {node_id: set() for node_id in nodes}
    for edge in architecture["connections"]:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
        directed[edge["source"]].add(edge["target"])

    reached = set()
    pending = deque([next(iter(nodes))])
    while pending:
        node_id = pending.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(adjacency[node_id] - reached)
    assert reached == nodes

    def can_reach(source: str, target: str) -> bool:
        seen = set()
        pending_nodes = [source]
        while pending_nodes:
            current = pending_nodes.pop()
            if current == target:
                return True
            if current not in seen:
                seen.add(current)
                pending_nodes.extend(directed[current] - seen)
        return False

    assert can_reach("app_event_sources", "analytics_event_hubs")
    assert can_reach("device_event_sources", "analytics_event_hubs")
    assert can_reach("operational_cdc", "analytics_event_hubs")
    assert can_reach("analytics_event_hubs", "analytics_stream_job")
    assert can_reach("analytics_event_hubs", "analytics_raw_archive")
    assert can_reach("analytics_raw_archive", "analytics_stream_job")
    assert can_reach("analytics_stream_job", "analytics_cosmos")
    assert can_reach("analytics_stream_job", "analytics_action_publisher")
    assert can_reach("analytics_action_publisher", "analytics_event_grid")
    assert can_reach("analytics_event_grid", "analytics_action_handler")
    assert can_reach("analytics_action_handler", "analytics_cosmos")


def test_guide_explains_lateness_exactly_once_and_operational_limits():
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    content = "\n".join(step["content"] for step in raw["steps"]).lower()

    assert "timestamp by" in content
    assert "watermark" in content
    assert "late-arrival" in content or "late arrival" in content
    assert "exactly-once processing" in content
    assert "upsert" in content
    assert "idempot" in content
    assert "1,000,000" in content or "1m events" in content
    assert "under 5 seconds" in content
    assert "auto-inflate" in content
    assert "scale down" in content or "scale-down" in content
