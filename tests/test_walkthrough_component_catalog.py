"""Catalog references in the URL Shortener walkthrough must be resolvable."""

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "data" / "guided-walkthroughs" / "68d7013f6f42e23bb16a222c.json"
GUIDES = ROOT / "data" / "guided-walkthroughs"
COMPONENT_CATALOG = ROOT.parent / "diagrammatic" / "src" / "config" / "components.ts"


class TestWalkthroughComponentCatalog(unittest.TestCase):
    def test_url_shortener_walkthrough_uses_canonical_component_ids(self):
        guide = json.loads(GUIDE.read_text(encoding="utf-8"))
        actual = {
            step["stepNumber"]: step["component"]["componentType"]
            for step in guide["steps"]
            if step.get("type") == "add_component"
        }

        self.assertEqual(
            actual,
            {
                2: "web-app",
                3: "cdn",
                5: "api-gateway",
                7: "loadbalancer",
                9: "backend-server",
                12: "id-generator",
                15: "database",
                18: "cache",
                23: "queue",
                25: "processing-worker",
                27: "database",
                29: "monitoring",
            },
        )

    def test_every_review_guide_uses_catalog_ids_and_editable_properties(self):
        catalog = COMPONENT_CATALOG.read_text(encoding="utf-8")

        for path in GUIDES.glob("*.json"):
            guide = json.loads(path.read_text(encoding="utf-8"))
            components = {
                step["component"]["nodeId"]: step["component"]
                for step in guide["steps"]
                if step.get("type") == "add_component"
            }
            for step in guide["steps"]:
                if step.get("type") == "add_component":
                    component = step["component"]
                    component_type = component["componentType"]
                    properties = component.get("properties", {})
                elif step.get("componentUpdate"):
                    update = step["componentUpdate"]
                    component = components[update["nodeId"]]
                    component_type = component["componentType"]
                    properties = update.get("properties", {})
                else:
                    continue

                match = re.search(
                    rf'\bid:\s*"{re.escape(component_type)}"', catalog
                )
                self.assertIsNotNone(
                    match,
                    f"{path.name}/{step['id']} uses non-catalog ID {component_type}",
                )
                block_end = catalog.find("\n  },", match.start())
                component_block = catalog[match.start() : block_end]
                supported = set(
                    re.findall(r'\bkey:\s*"([^"]+)"', component_block)
                )
                property_keys = set(properties)
                self.assertTrue(
                    property_keys <= supported,
                    f"{path.name}/{step['id']} has unsupported properties "
                    f"{sorted(property_keys - supported)}",
                )
                if step.get("type") == "add_component":
                    self.assertTrue(
                        {"componentName", "purpose"} <= property_keys,
                        f"{path.name}/{step['id']} lacks editable catalog context",
                    )
