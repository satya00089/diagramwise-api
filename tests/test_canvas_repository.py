from app.services.canvas_repository import CanvasRepository


def test_canvas_summary_query_projects_counts_without_graph_payloads():
    class FakeTable:
        def __init__(self):
            self.query_args = None

        def query(self, **kwargs):
            self.query_args = kwargs
            return {
                "Items": [
                    {
                        "userId": "owner-1",
                        "id": "design-1#canvas#canvas-1",
                        "canvasId": "canvas-1",
                        "name": "Main",
                        "kind": "other",
                        "order": 0,
                        "version": 3,
                        "updatedAt": "2026-10-15T00:00:00Z",
                        "nodeCount": 2,
                        "edgeCount": 1,
                    }
                ]
            }

    table = FakeTable()
    repository = CanvasRepository(table, "owner-1", "Design title")

    summaries = repository.list_canvas_summaries("design-1")

    assert summaries == [
        {
            "id": "canvas-1",
            "title": "Design title",
            "name": "Main",
            "kind": "other",
            "order": 0,
            "nodeCount": 2,
            "edgeCount": 1,
            "version": 3,
            "updatedAt": "2026-10-15T00:00:00Z",
        }
    ]
    projected_fields = set(table.query_args["ExpressionAttributeNames"].values())
    assert "nodes" not in projected_fields
    assert "edges" not in projected_fields
