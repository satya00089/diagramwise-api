"""Validation for the bounded saved-run API contract."""

import copy
import unittest

from pydantic import ValidationError

from app.models.simulation_models import SimulationRunCreate


def valid_run_payload():
    problem_id = "url-shortener-like-bit-ly"
    return {
        "problemId": problem_id,
        "requirementRevision": "rev-1",
        "snapshot": {
            "input": {
                "scenarioId": "url-shortener-capacity",
                "scenarioVersion": "1",
                "modelVersion": "capacity-v1",
                "requestRate": 1000,
                "redirectSharePercent": 95,
                "cacheHitPercent": 90,
                "profileCapacities": {
                    "ingress": 5000,
                    "compute": 1500,
                    "cache": 10000,
                    "database": 600,
                },
                "provenance": {
                    "requestRate": "educational-default",
                    "redirectSharePercent": "user",
                    "cacheHitPercent": "user",
                    "profileCapacities": {
                        "ingress": "educational-default",
                        "compute": "educational-default",
                        "cache": "user",
                        "database": "educational-default",
                    },
                },
            },
            "result": {
                "modelVersion": "capacity-v1",
                "requestRate": 1000,
                "redirectsPerSecond": 950,
                "linkCreationsPerSecond": 50,
                "cacheHitsPerSecond": 855,
                "cacheMissesPerSecond": 95,
                "databaseRedirectReadsPerSecond": 95,
                "databaseLinkWritesPerSecond": 50,
                "estimatedCapacityAtMixRequestsPerSecond": 1500,
                "limitingNodeId": "compute",
                "bottleneckNodeId": None,
                "bottleneckDemandPerSecond": 1000,
                "bottleneckCapacityPerSecond": 1500,
                "nodeMetrics": [
                    {
                        "nodeId": "compute",
                        "label": "Redirect API",
                        "role": "compute",
                        "redirectDemandPerSecond": 950,
                        "createLinkDemandPerSecond": 50,
                        "demandPerSecond": 1000,
                        "capacityPerSecond": 1500,
                        "utilization": 2 / 3,
                        "unit": "requests/s",
                    },
                    {
                        "nodeId": "cache",
                        "label": "Cache",
                        "role": "cache",
                        "redirectDemandPerSecond": 950,
                        "createLinkDemandPerSecond": 0,
                        "demandPerSecond": 950,
                        "capacityPerSecond": 10000,
                        "utilization": 0.095,
                        "unit": "ops/s",
                    },
                    {
                        "nodeId": "database",
                        "label": "Links database",
                        "role": "database",
                        "redirectDemandPerSecond": 95,
                        "createLinkDemandPerSecond": 50,
                        "demandPerSecond": 145,
                        "capacityPerSecond": 600,
                        "utilization": 145 / 600,
                        "unit": "ops/s",
                    }
                ],
            },
            "graphFingerprint": "a" * 32,
            "preparationFingerprint": "b" * 32,
            "preparedRoutes": [
                {
                    "operation": "redirect",
                    "nodeIds": ["client", "compute", "cache", "database"],
                    "edgeIds": ["e1", "e2", "e3"],
                    "nodeLabels": ["Client", "Redirect API", "Cache", "Links database"],
                    "explanation": "The redirect can read through cache and database.",
                },
                {
                    "operation": "create-link",
                    "nodeIds": ["client", "compute", "database"],
                    "edgeIds": ["e4", "e5"],
                    "nodeLabels": ["Client", "Redirect API", "Links database"],
                    "explanation": "Link creation writes to the database.",
                },
            ],
            "componentRoles": [
                {"nodeId": "client", "label": "Client", "role": "client"},
                {"nodeId": "compute", "label": "Redirect API", "role": "compute"},
                {"nodeId": "cache", "label": "Cache", "role": "cache"},
                {"nodeId": "database", "label": "Links database", "role": "database"},
            ],
            "exerciseId": problem_id,
            "requirementRevision": "rev-1",
        },
    }


class SimulationSavedRunModelTests(unittest.TestCase):
    def test_accepts_versioned_bounded_snapshot(self):
        request = SimulationRunCreate.model_validate(valid_run_payload())

        self.assertEqual(request.snapshot.result.model_version, "capacity-v1")
        self.assertEqual(len(request.snapshot.prepared_routes), 2)

    def test_rejects_snapshot_for_another_exercise_revision(self):
        payload = valid_run_payload()
        payload["snapshot"]["exerciseId"] = "another-exercise"

        with self.assertRaises(ValidationError):
            SimulationRunCreate.model_validate(payload)

    def test_rejects_unmodeled_provenance(self):
        payload = copy.deepcopy(valid_run_payload())
        payload["snapshot"]["input"]["provenance"]["requestRate"] = "measured"

        with self.assertRaises(ValidationError):
            SimulationRunCreate.model_validate(payload)

    def test_rejects_malformed_route_edges(self):
        payload = copy.deepcopy(valid_run_payload())
        payload["snapshot"]["preparedRoutes"][0]["edgeIds"] = ["e1"]

        with self.assertRaises(ValidationError):
            SimulationRunCreate.model_validate(payload)

    def test_rejects_route_with_an_interior_client(self):
        payload = copy.deepcopy(valid_run_payload())
        payload["snapshot"]["componentRoles"].append(
            {"nodeId": "interior-client", "label": "Another client", "role": "client"}
        )
        route = payload["snapshot"]["preparedRoutes"][0]
        route["nodeIds"] = ["client", "compute", "interior-client", "cache", "database"]
        route["edgeIds"] = ["e1", "e2", "e3", "e4"]
        route["nodeLabels"] = ["Client", "Redirect API", "Another client", "Cache", "Links database"]

        with self.assertRaises(ValidationError):
            SimulationRunCreate.model_validate(payload)

    def test_rejects_capacity_outside_simulator_supported_range(self):
        payload = copy.deepcopy(valid_run_payload())
        payload["snapshot"]["input"]["profileCapacities"]["database"] = 3001

        with self.assertRaises(ValidationError):
            SimulationRunCreate.model_validate(payload)

    def test_rejects_result_that_does_not_match_node_metrics(self):
        payload = copy.deepcopy(valid_run_payload())
        payload["snapshot"]["result"]["databaseRedirectReadsPerSecond"] = 96

        with self.assertRaises(ValidationError):
            SimulationRunCreate.model_validate(payload)

    def test_rejects_oversized_estimated_capacity(self):
        payload = copy.deepcopy(valid_run_payload())
        payload["snapshot"]["result"]["estimatedCapacityAtMixRequestsPerSecond"] = 20_001

        with self.assertRaises(ValidationError):
            SimulationRunCreate.model_validate(payload)

    def test_rejects_snapshot_larger_than_storage_limit(self):
        payload = copy.deepcopy(valid_run_payload())
        payload["snapshot"]["componentRoles"] = [
            {"nodeId": f"role-{index}", "label": "r" * 240, "role": "database"}
            for index in range(100)
        ]
        metric = payload["snapshot"]["result"]["nodeMetrics"][0]
        payload["snapshot"]["result"]["nodeMetrics"] = [
            {**metric, "nodeId": f"node-{index}-" + ("x" * 150), "label": "m" * 240}
            for index in range(100)
        ]

        with self.assertRaises(ValidationError):
            SimulationRunCreate.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
