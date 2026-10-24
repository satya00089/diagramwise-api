import unittest

from pydantic import ValidationError

from app.models.event_simulation_models import EventSimulationRunCreate


def _config(**extra):
    return {
        "capacity": 4,
        "serviceMs": 10,
        "serviceCv": 0,
        "queueLimit": 10,
        "hitRate": 0,
        "errorRate": 0,
        "timeoutMs": 100,
        "retries": 0,
        "rps": 0,
        **extra,
    }


def _payload():
    return {
        "snapshot": {
            "contractVersion": "2",
            "engineVersion": "event-v1",
            "profileVersion": "profiles-v1",
            "scope": {"designId": "design-1", "canvasId": "canvas-1", "exerciseId": None},
            "graphFingerprint": "abc123",
            "topology": {
                "nodes": [
                    {"id": "client", "kind": "client", "label": "Client", "x": 0, "y": 0, "config": _config(rps=100)},
                    {"id": "api", "kind": "service", "label": "API", "x": 100, "y": 0, "config": _config()},
                ],
                "edges": [{"id": "client-api", "from": "client", "to": "api", "weight": 1}],
            },
            "workload": {"rps": 100, "pattern": "steady", "seed": 1},
            "commands": [{"atMs": 100, "command": {"type": "replicas", "nodeId": "api", "instances": 2}}],
            "result": {"timeMs": 1000, "offeredRps": 100, "goodputRps": 99, "errorRate": 0.01, "p50": 10, "p95": 20, "p99": 30, "totalRequests": 100, "totalFailed": 1, "status": "complete"},
        }
    }


class EventSimulationModelTests(unittest.TestCase):
    def test_rejects_settings_from_another_component_model(self):
        for kind, setting in [("client", "lockMs"), ("service", "coldStartMs"), ("db", "partitions")]:
            with self.subTest(kind=kind, setting=setting):
                payload = _payload()
                node = payload["snapshot"]["topology"]["nodes"][1]
                node["kind"] = kind
                node["config"][setting] = 1
                with self.assertRaises(ValidationError):
                    EventSimulationRunCreate.model_validate(payload)

    def test_accepts_supported_component_settings(self):
        for kind, setting in [("db", "lockMs"), ("lambda", "coldStartMs"), ("streambroker", "partitions")]:
            with self.subTest(kind=kind, setting=setting):
                payload = _payload()
                node = payload["snapshot"]["topology"]["nodes"][1]
                node["kind"] = kind
                node["config"][setting] = 1
                EventSimulationRunCreate.model_validate(payload)

    def test_accepts_a_bounded_versioned_replay(self):
        parsed = EventSimulationRunCreate.model_validate(_payload())
        assert parsed.snapshot.topology.nodes[0].id == "client"
        assert parsed.snapshot.commands[0].command.type == "replicas"

    def test_rejects_an_unknown_model_setting(self):
        payload = _payload()
        payload["snapshot"]["topology"]["nodes"][1]["config"]["javascript"] = 1
        with self.assertRaises(ValidationError):
            EventSimulationRunCreate.model_validate(payload)

    def test_rejects_a_command_for_a_missing_component(self):
        payload = _payload()
        payload["snapshot"]["commands"][0]["command"]["nodeId"] = "missing"
        with self.assertRaises(ValidationError):
            EventSimulationRunCreate.model_validate(payload)

    def test_rejects_a_result_with_impossible_counts(self):
        payload = _payload()
        payload["snapshot"]["result"]["totalFailed"] = 101
        with self.assertRaises(ValidationError):
            EventSimulationRunCreate.model_validate(payload)

    def test_rejects_a_zero_weight_connection(self):
        payload = _payload()
        payload["snapshot"]["topology"]["edges"][0]["weight"] = 0
        with self.assertRaises(ValidationError):
            EventSimulationRunCreate.model_validate(payload)

    def test_rejects_fractional_component_capacity(self):
        payload = _payload()
        payload["snapshot"]["topology"]["nodes"][1]["config"]["capacity"] = 2.5
        with self.assertRaises(ValidationError):
            EventSimulationRunCreate.model_validate(payload)
