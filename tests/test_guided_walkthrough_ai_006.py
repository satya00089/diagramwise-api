"""Frozen live-brief, catalog, and connected-graph checks for ai_006."""

from collections import deque
import json
from pathlib import Path
import re

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_ID = "ai_006"
GUIDE_PATH = ROOT / "data" / "guided-walkthroughs" / f"{PROBLEM_ID}.json"
PROBLEMS_PATH = ROOT / "tests" / "fixtures" / "walkthroughs" / "problems.json"
CATALOG_PATH = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"

# Captured from the strongly consistent live DynamoDB item. Keep the published
# brief immutable; the walkthrough records design actions, not a replacement brief.
FROZEN_BRIEF = {
    "id": "ai_006",
    "title": "Design a Generative AI Image and Video Platform",
    "slug": "design-a-generative-ai-image-and-video-platform",
    "description": (
        "Design a platform for generating images and videos from text prompts using diffusion models, "
        "with support for fine-tuning, style transfer, inpainting, and content safety filtering."
    ),
    "difficulty": "Very Hard",
    "category": "AI - Generative Media",
    "domain": "aiml",
    "estimated_time": "90+ minutes",
    "requirements": [
        "Generate images from text prompts",
        "Support image-to-image transformation",
        "Implement inpainting and outpainting",
        "Generate short video clips from prompts",
        "Allow model fine-tuning with custom datasets",
        "Apply content safety filters on outputs",
        "Manage GPU queues for generation jobs",
        "Provide an API and web interface",
    ],
    "constraints": [
        "Image generation under 10 seconds",
        "Video generation under 60 seconds for 5s clips",
        "Support 10k+ concurrent generation requests",
        "GPU memory efficient for batch processing",
        "Filter 99.9% of unsafe generated content",
    ],
    "hints": [
        "Use Stable Diffusion or similar diffusion models",
        "Implement LoRA for efficient fine-tuning",
        "Use task queues (Celery, Bull) for async generation",
        "Deploy on GPU clusters with auto-scaling",
        "Implement NSFW classifiers on generated output",
        "Use CDN for caching and serving generated media",
    ],
    "tags": ["ai", "generative-ai", "diffusion-models", "image-generation", "gpu", "creative-ai"],
    "companies": ["Stability AI", "Midjourney", "Adobe", "OpenAI"],
}

ACTION_TYPES = {"add_component", "add_connection"}
CONNECTION_TYPES = {"api-call", "data-flow", "database-connection", "event-stream", "message-queue"}
EXPECTED_COMPONENT_TYPES = {
    "ai006_web": "web-app",
    "ai006_api": "api-gateway",
    "ai006_orchestrator": "backend-server",
    "ai006_job_db": "database",
    "ai006_media_storage": "object-storage",
    "ai006_job_queue": "queue",
    "ai006_generation_worker": "processing-worker",
    "ai006_training_worker": "processing-worker",
    "ai006_gpu_cluster": "gpu-cluster",
    "ai006_diffusion_serving": "model-serving",
    "ai006_safety_serving": "model-serving",
    "ai006_cdn": "cdn",
    "ai006_monitoring": "monitoring",
}


def load_guide() -> tuple[dict, GuidedWalkthrough]:
    raw = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    return raw, GuidedWalkthrough.model_validate(raw)


def catalog_block(catalog: str, component_type: str) -> str:
    match = re.search(rf'(?m)^\s*id:\s*"{re.escape(component_type)}"\s*,', catalog)
    assert match, f"Unknown component catalog ID {component_type!r}"
    end = re.search(r"(?m)^  \},\s*$", catalog[match.end() :])
    assert end, f"Could not delimit catalog entry {component_type!r}"
    return catalog[match.start() : match.end() + end.start()]


def expected_anchors() -> set[str]:
    return {
        *(f"legacy-requirement:{index}" for index in range(1, len(FROZEN_BRIEF["requirements"]) + 1)),
        *(f"legacy-constraint:{index}" for index in range(1, len(FROZEN_BRIEF["constraints"]) + 1)),
    }


def test_frozen_live_brief_matches_catalog_snapshot_and_candidate_version():
    raw, guide = load_guide()
    snapshot = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    problem = next(row for row in snapshot if row["id"] == PROBLEM_ID)

    assert guide.problem_id == FROZEN_BRIEF["id"]
    assert guide.version == "1.0"
    for field, expected in FROZEN_BRIEF.items():
        assert problem[field] == expected, f"Frozen problem field changed: {field}"
    assert "has_guided_walkthrough" not in raw
    visible_copy = " ".join(
        [step.title + " " + step.content for step in guide.steps]
        + [step.component.label + " " + (step.component.description or "") for step in guide.steps if step.component]
    ).casefold()
    assert not any(term in visible_copy for term in ("unpublished", "local draft", "coming soon"))


def test_every_live_requirement_and_constraint_is_anchored_to_graph_actions():
    raw, guide = load_guide()
    anchors = expected_anchors()
    actions = [step for step in guide.steps if step.type in ACTION_TYPES]
    action_anchors = {anchor for step in actions for anchor in step.requirementIds}
    assert action_anchors == anchors

    action_copy_by_anchor = {
        anchor: " ".join(
            step.content
            + (step.component.description + " " + step.component.highlightReason + " " + str(step.component.properties)
               if step.component else "")
            + (step.connection.label + " " + step.connection.description if step.connection else "")
            for step in actions
            if anchor in step.requirementIds
        ).casefold()
        for anchor in anchors
    }
    requirement_signals = [
        "text-to-image",
        "image-to-image",
        "inpainting",
        "video",
        "fine-tuning",
        "safety",
        "gpu",
        "api",
    ]
    constraint_signals = [
        "under 10 seconds",
        "under 60 seconds",
        "10k+ concurrent",
        "memory",
        "99.9%",
    ]
    for index, signal in enumerate(requirement_signals, start=1):
        assert signal in action_copy_by_anchor[f"legacy-requirement:{index}"]
    for index, signal in enumerate(constraint_signals, start=1):
        assert signal in action_copy_by_anchor[f"legacy-constraint:{index}"]


def test_catalog_properties_replay_and_graph_connectivity():
    raw, guide = load_guide()
    catalog = CATALOG_PATH.read_text(encoding="utf-8")
    additions = {
        step.component.nodeId: step.component
        for step in guide.steps
        if step.type == "add_component" and step.component is not None
    }
    assert {node_id: component.componentType for node_id, component in additions.items()} == EXPECTED_COMPONENT_TYPES

    for node_id, component in additions.items():
        block = catalog_block(catalog, component.componentType)
        supported = set(re.findall(r'\bkey:\s*"([^"]+)"', block))
        assert component.properties
        assert set(component.properties) <= supported, (
            f"{node_id} has unsupported {component.componentType} properties: "
            f"{sorted(set(component.properties) - supported)}"
        )

    replay = build_architecture(raw)
    architecture = replay["architecture"]
    components = {component["id"] for component in architecture["components"]}
    edges = architecture["connections"]
    assert components == set(EXPECTED_COMPONENT_TYPES)
    assert len(edges) == 26
    assert len({edge["id"] for edge in edges}) == len(edges)
    neighbors = {component_id: set() for component_id in components}
    for edge in edges:
        assert edge["type"] in CONNECTION_TYPES
        assert edge["source"] in components and edge["target"] in components
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])

    reached: set[str] = set()
    pending = deque(["ai006_web"])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(neighbors[current] - reached)
    assert reached == components
    assert len(replay["appliedStepIds"]) > len(replay["explanationOnlyStepIds"])


def test_steps_and_phase_ranges_are_complete_and_ordered():
    _, guide = load_guide()
    assert guide.totalSteps == len(guide.steps) == 48
    assert [step.stepNumber for step in guide.steps] == list(range(1, guide.totalSteps + 1))
    assert len({step.id for step in guide.steps}) == guide.totalSteps
    assert all(step.type in ACTION_TYPES | {"explanation", "decision_point", "scale_trigger", "conclusion"}
               for step in guide.steps)

    next_step = 1
    for phase in guide.phases:
        start, end = phase.stepRange
        assert start == next_step <= end
        assert all(guide.steps[index - 1].phase == phase.name for index in range(start, end + 1))
        next_step = end + 1
    assert next_step == guide.totalSteps + 1
