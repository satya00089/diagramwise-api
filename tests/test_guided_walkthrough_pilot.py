"""Public guide-response and applied-design contracts for the rollout pilot."""

import json
from pathlib import Path

from app.models.walkthrough_models import GuidedWalkthrough
from scripts.walkthrough_fixtures import build_architecture, make_request


ROOT = Path(__file__).resolve().parents[1]
GUIDES = ROOT / "data" / "guided-walkthroughs"
COVERAGE = ROOT / "docs" / "guided-walkthrough-pilot-coverage.json"
PROBLEMS = {
    row["id"]: row
    for row in json.loads((ROOT / "tests/fixtures/walkthroughs/problems.json").read_text(encoding="utf-8"))
}


def load_guide(problem_id: str) -> dict:
    data = json.loads((GUIDES / f"{problem_id}.json").read_text(encoding="utf-8"))
    return GuidedWalkthrough.model_validate(data).model_dump(exclude_none=True)


def test_url_shortener_guide_yields_a_permanent_unique_link_and_async_analytics_design():
    problem_id = "68d7013f6f42e23bb16a222c"
    guide = load_guide(problem_id)
    built = build_architecture(guide)
    request = make_request(PROBLEMS[problem_id], guide, built)
    nodes = {node["id"]: node for node in request["components"]}
    edges = {(edge["source"], edge["target"]) for edge in request["connections"]}

    assert guide["problem_id"] == problem_id
    assert {"guided_url_gateway", "guided_url_service", "guided_url_allocator",
            "guided_url_cache", "guided_url_links", "guided_url_clicks",
            "guided_url_analytics"} <= nodes.keys()
    assert "permanent mappings readable" in nodes["guided_url_links"]["properties"]["purpose"].lower()
    assert "no ttl or automatic expiry" in nodes["guided_url_links"]["properties"]["purpose"].lower()
    assert "conditionally reserves both" in nodes["guided_url_allocator"]["properties"]["purpose"].lower()
    assert "post /links" in nodes["guided_url_service"]["properties"]["purpose"].lower()
    assert "emit clicks asynchronously" in nodes["guided_url_service"]["properties"]["purpose"].lower()
    assert ("guided_url_service", "guided_url_clicks") in edges
    assert ("guided_url_clicks", "guided_url_analytics") in edges
    assert ("guided_url_service", "guided_url_analytics_store") in edges
    assert request["problem"]["requirements"].count("Handle 100M URLs per day") == 1


def test_chat_guide_yields_durable_group_delivery_offline_replay_and_encrypted_media():
    problem_id = "68d7013f6f42e23bb16a222d"
    guide = load_guide(problem_id)
    request = make_request(PROBLEMS[problem_id], guide, build_architecture(guide))
    nodes = {node["id"]: node for node in request["components"]}
    edges = {(edge["source"], edge["target"]) for edge in request["connections"]}

    assert {"guided_chat_sessions", "guided_chat_auth", "guided_chat_write",
            "guided_chat_store", "guided_chat_events", "guided_chat_fanout",
            "guided_chat_presence", "guided_chat_media", "guided_chat_push"} <= nodes.keys()
    assert nodes["guided_chat_clients"]["type"] == "frontend"
    assert nodes["guided_chat_auth"]["type"] == "security"
    assert nodes["guided_chat_sessions"]["type"] == "backend"
    assert "ack after = durable-commit" in nodes["guided_chat_write"]["properties"]["purpose"].lower()
    assert "offline replay = per-user-delivery-cursor" in nodes["guided_chat_store"]["properties"]["purpose"].lower()
    assert "encryption = client-side-envelope" in nodes["guided_chat_media"]["properties"]["purpose"].lower()
    assert "sender-submit to recipient-client receive ack slo = p95 <100ms" in nodes["guided_chat_write"]["properties"]["purpose"].lower()
    assert "2.5b writes/day" in nodes["guided_chat_fanout"]["properties"]["purpose"].lower()
    assert "cost controls:" in nodes["guided_chat_fanout"]["properties"]["purpose"].lower()
    assert "load-test the 50m-dau assumptions" in nodes["guided_chat_monitor"]["properties"]["purpose"].lower()
    assert ("guided_chat_write", "guided_chat_store") in edges
    assert ("guided_chat_events", "guided_chat_fanout") in edges
    assert ("guided_chat_fanout", "guided_chat_push") in edges
    assert ("guided_chat_recipients", "guided_chat_delivery") in edges
    assert ("guided_chat_delivery", "guided_chat_store") in edges
    assert ("guided_chat_store", "guided_chat_delivery") in edges
    assert ("guided_chat_delivery", "guided_chat_clients") in edges
    assert "50M daily active users" in request["problem"]["requirements"]
    assert "backpressure before commit" in nodes["guided_chat_fanout"]["properties"]["purpose"].lower()
    assert "2.5b writes/day" in nodes["guided_chat_fanout"]["properties"]["purpose"].lower()
    assert "sender-notification outbox" in nodes["guided_chat_delivery"]["properties"]["purpose"].lower()
    assert "stable event_id" in nodes["guided_chat_delivery"]["properties"]["purpose"].lower()
    assert len(nodes) == 16
    assert len(edges) == 22


def test_news_feed_guide_yields_hybrid_fanout_ranked_reads_moderation_and_trends():
    problem_id = "68d7013f6f42e23bb16a222e"
    guide = load_guide(problem_id)
    request = make_request(PROBLEMS[problem_id], guide, build_architecture(guide))
    nodes = {node["id"]: node for node in request["components"]}
    edges = {(edge["source"], edge["target"]) for edge in request["connections"]}

    assert {"guided_feed_post", "guided_feed_graph", "guided_feed_posts",
            "guided_feed_moderation", "guided_feed_events", "guided_feed_fanout",
            "guided_feed_cache", "guided_feed_read", "guided_feed_ranker",
            "guided_feed_realtime", "guided_feed_trends", "guided_feed_media"} <= nodes.keys()
    assert nodes["guided_feed_post"]["type"] == "backend"
    assert nodes["guided_feed_clients"]["type"] == "frontend"
    assert nodes["guided_feed_ranker"]["type"] == "backend"
    assert "strategy = push-ordinary-pull-celebrity" in nodes["guided_feed_fanout"]["properties"]["purpose"].lower()
    assert "initial pull threshold = 100000 followers" in nodes["guided_feed_fanout"]["properties"]["purpose"].lower()
    assert "conditional-unique(reader_id,event_id)" in nodes["guided_feed_fanout"]["properties"]["purpose"].lower()
    assert "latency target ms = 200" in nodes["guided_feed_read"]["properties"]["purpose"].lower()
    assert "parallel celebrity merge 40ms max-20-authors" in nodes["guided_feed_read"]["properties"]["purpose"].lower()
    assert "permission lookup timeout = fail-closed omit" in nodes["guided_feed_read"]["properties"]["purpose"].lower()
    assert "trending endpoint = get /trending?window=..." in nodes["guided_feed_read"]["properties"]["purpose"].lower()
    assert "publish gate = moderation-approved" in nodes["guided_feed_posts"]["properties"]["purpose"].lower()
    assert ("guided_feed_events", "guided_feed_fanout") in edges
    assert ("guided_feed_fanout", "guided_feed_cache") in edges
    assert ("guided_feed_events", "guided_feed_realtime") in edges
    assert ("guided_feed_events", "guided_feed_trends") in edges
    assert ("guided_feed_read", "guided_feed_trend_store") in edges
    assert "1B daily active users" in request["problem"]["requirements"]


def test_video_streaming_guide_covers_transcoding_rights_search_and_personalized_playback():
    problem_id = "68d7013f6f42e23bb16a222f"
    guide = load_guide(problem_id)
    request = make_request(PROBLEMS[problem_id], guide, build_architecture(guide))
    nodes = {node["id"]: node for node in request["components"]}
    edges = {(edge["source"], edge["target"]) for edge in request["connections"]}

    assert {
        "guided_video_originals", "guided_video_metadata", "guided_video_encode_queue",
        "guided_video_encoder", "guided_video_renditions", "guided_video_catalog",
        "guided_video_entitlement", "guided_video_cdn", "guided_video_search",
        "guided_video_profiles", "guided_video_recommendations",
    } <= nodes.keys()
    assert nodes["guided_video_web"]["type"] == "frontend"
    assert nodes["guided_video_mobile"]["type"] == "frontend"
    assert nodes["guided_video_encoder"]["type"] == "backend"
    assert nodes["guided_video_recommendations"]["type"] == "backend"
    assert nodes["guided_video_search"]["type"] == "backend"
    assert ("guided_video_encoder", "guided_video_catalog") in edges
    assert ("guided_video_entitlement", "guided_video_cdn") in edges
    assert ("guided_video_events", "guided_video_recommendations") in edges
    assert "Adaptive bitrate streaming" in request["problem"]["requirements"]
    assert "Copyright protection and DRM" in request["problem"]["constraints"]


def test_ride_sharing_guide_covers_fresh_geo_matching_quotes_and_idempotent_payments():
    problem_id = "68d7013f6f42e23bb16a2230"
    guide = load_guide(problem_id)
    request = make_request(PROBLEMS[problem_id], guide, build_architecture(guide))
    nodes = {node["id"]: node for node in request["components"]}
    edges = {(edge["source"], edge["target"]) for edge in request["connections"]}

    assert {
        "guided_ride_rider", "guided_ride_driver", "guided_ride_trip_service",
        "guided_ride_trip_store", "guided_ride_location_events",
        "guided_ride_location_processor", "guided_ride_geo_store",
        "guided_ride_matcher", "guided_ride_route_pricing", "guided_ride_payment",
        "guided_ride_payment_ledger", "guided_ride_notifications",
    } <= nodes.keys()
    assert nodes["guided_ride_rider"]["type"] == "frontend"
    assert nodes["guided_ride_location_processor"]["type"] == "analytics"
    assert nodes["guided_ride_matcher"]["type"] == "backend"
    assert nodes["guided_ride_payment"]["type"] == "backend"
    assert nodes["guided_ride_payment"]["properties"]["tokenization"] is True
    assert ("guided_ride_location_processor", "guided_ride_geo_store") in edges
    assert ("guided_ride_geo_store", "guided_ride_matcher") in edges
    assert ("guided_ride_matcher", "guided_ride_trip_service") in edges
    assert ("guided_ride_location_processor", "guided_ride_route_pricing") in edges
    assert ("guided_ride_route_pricing", "guided_ride_trip_service") in edges
    assert ("guided_ride_payment", "guided_ride_payment_ledger") in edges
    assert len(nodes) == 14
    guide_connections = {
        step["connection"]["edgeId"]: step["connection"]
        for step in guide["steps"]
        if step.get("connection")
    }
    assert "completed-trip ratings" in guide_connections[
        "guided_ride_rider_gateway"
    ]["label"].lower()
    assert "one idempotent rating" in guide_connections[
        "guided_ride_rider_gateway"
    ]["description"].lower()
    assert "ratings" in guide_connections["guided_ride_driver_gateway"]["label"].lower()
    assert "rating commands" in guide_connections["guided_ride_gateway_trip"]["label"].lower()
    assert "one rating per participant" in guide_connections[
        "guided_ride_gateway_trip"
    ]["description"].lower()
    assert "uniquely keyed by trip and rating author" in nodes[
        "guided_ride_trip_store"
    ]["properties"]["purpose"].lower()
    assert len(guide["steps"]) == 43
    assert len(request["components"]) == 14
    assert len(request["connections"]) == 24
    assert len(build_architecture(guide)["appliedStepIds"]) == 40
    reservation = guide_connections["guided_ride_matcher_trip"]["description"].lower()
    assert "atomically condition" in reservation
    assert "unique driver lease" in reservation
    assert "p95 <=5s" in nodes["guided_ride_matcher"]["properties"]["purpose"].lower()
    route_purpose = nodes["guided_ride_route_pricing"]["properties"]["purpose"].lower()
    assert "active trips" in route_purpose
    assert "coalescing requests" in route_purpose
    assert "routeversion" in nodes["guided_ride_trip_service"]["properties"]["purpose"].lower()
    assert "fresh trip-scoped map-matched position" in guide_connections[
        "guided_ride_location_route"
    ]["description"].lower()
    assert "never mutate the accepted quote" in guide_connections[
        "guided_ride_route_trip_guidance"
    ]["description"].lower()
    assert "fail closed" in guide["steps"][12]["content"].lower()
    assert "acceptedquoteid" in guide["steps"][23]["content"].lower()
    assert "116 average ride starts per second" in guide["steps"][38]["content"].lower()
    assert "new routeversion" in guide["steps"][41]["content"].lower()
    assert (
        "guided_ride_payment",
        "guided_ride_trip_service",
    ) in edges
    assert "Handle 10M daily rides" in request["problem"]["requirements"]


def test_every_saved_brief_line_maps_to_an_action_the_learner_can_apply():
    matrix = json.loads(COVERAGE.read_text(encoding="utf-8"))

    for problem_id, mapping in matrix.items():
        guide = load_guide(problem_id)
        built = build_architecture(guide)
        applied = set(built["appliedStepIds"])
        problem = PROBLEMS[problem_id]
        assert [step["stepNumber"] for step in guide["steps"]] == list(
            range(1, guide["totalSteps"] + 1)
        )
        ranges = [phase["stepRange"] for phase in guide["phases"]]
        assert ranges[0][0] == 1
        assert ranges[-1][1] == guide["totalSteps"]
        assert all(left[1] + 1 == right[0] for left, right in zip(ranges, ranges[1:]))
        phase_by_number = {
            number: phase["name"]
            for phase in guide["phases"]
            for number in range(phase["stepRange"][0], phase["stepRange"][1] + 1)
        }
        assert all(phase_by_number[step["stepNumber"]] == step["phase"] for step in guide["steps"])

        node_ids = {node["id"] for node in built["architecture"]["components"]}
        adjacency = {node_id: set() for node_id in node_ids}
        for edge in built["architecture"]["connections"]:
            adjacency[edge["source"]].add(edge["target"])
            adjacency[edge["target"]].add(edge["source"])
        reached = set()
        pending = [next(iter(node_ids))]
        while pending:
            node_id = pending.pop()
            if node_id in reached:
                continue
            reached.add(node_id)
            pending.extend(adjacency[node_id] - reached)
        assert reached == node_ids

        assert set(mapping["requirements"]) == set(problem["requirements"])
        assert set(mapping["constraints"]) == set(problem["constraints"])
        for category in ("requirements", "constraints"):
            for step_ids in mapping[category].values():
                assert step_ids
                assert set(step_ids) <= applied


def test_payment_walkthrough_preserves_catalog_roles_and_covers_every_anchor():
    problem_id = "68d7013f6f42e23bb16a2232"
    guide = load_guide(problem_id)
    built = build_architecture(guide)
    request = make_request(PROBLEMS[problem_id], guide, built)
    components = {row["id"]: row for row in request["components"]}
    edges = {(row["source"], row["target"]) for row in request["connections"]}
    anchors = {
        anchor
        for step in guide["steps"]
        for anchor in step.get("requirementIds", [])
    }

    assert guide["totalSteps"] == 46
    assert len(components) == 15
    assert len(edges) == 19
    assert anchors == {
        *(f"legacy-requirement:{index}" for index in range(1, 9)),
        *(f"legacy-constraint:{index}" for index in range(1, 6)),
    }
    assert components["pay_card_processor"]["properties"]["originalComponentId"] == "payment-service"
    assert components["pay_fraud"]["properties"]["originalComponentId"] == "ml-model"
    assert components["pay_ledger"]["properties"]["originalComponentId"] == "database"
    assert components["pay_events"]["properties"]["originalComponentId"] == "message-broker"
    assert components["pay_compliance_archive"]["properties"]["originalComponentId"] == "object-storage"
    assert components["pay_compliance_archive"]["properties"]["versioning"] is True
    assert components["pay_compliance_archive"]["properties"]["checksumValidation"] is True
    assert components["pay_card_processor"]["properties"]["pciDss"] is True
    assert "only its opaque token returns to the client" in components["pay_card_processor"]["properties"]["purpose"].lower()
    assert "kyc/aml/sanctions" in components["pay_auth"]["properties"]["purpose"].lower()
    assert "normalize card, bank-transfer, and wallet provider results" in components["pay_orchestrator"]["properties"]["purpose"].lower()
    assert components["pay_bank_wallet"]["properties"]["componentType"] == "Payment method adapter"
    assert components["pay_fx"]["properties"]["componentType"] == "Currency conversion service"
    assert ("pay_ledger", "pay_events") in edges
    assert ("pay_events", "pay_reconciliation") in edges
    assert ("pay_events", "pay_analytics") in edges
    assert ("pay_events", "pay_notifications") in edges
    assert ("pay_events", "pay_compliance_archive") in edges
