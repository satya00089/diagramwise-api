"""Focused ASGI tests for simulator request-size limits."""

import asyncio
import unittest
from typing import Any

from app.middleware.request_size_limit import SimulationRequestSizeLimitMiddleware


class SimulationRequestSizeLimitTests(unittest.TestCase):
    def run_asgi(self, body_chunks: list[bytes], content_length: bytes | None = None) -> tuple[list[dict[str, Any]], bool]:
        downstream_called = False
        sent: list[dict[str, Any]] = []

        async def downstream(scope, receive, send):
            nonlocal downstream_called
            downstream_called = True
            while (await receive()).get("more_body", False):
                pass
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        headers = [] if content_length is None else [(b"content-length", content_length)]
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/simulation/prepare",
            "headers": headers,
        }
        chunk_index = 0

        async def receive():
            nonlocal chunk_index
            if chunk_index >= len(body_chunks):
                return {"type": "http.request", "body": b"", "more_body": False}
            chunk = body_chunks[chunk_index]
            chunk_index += 1
            return {
                "type": "http.request",
                "body": chunk,
                "more_body": chunk_index < len(body_chunks),
            }

        async def send(message):
            sent.append(message)

        asyncio.run(SimulationRequestSizeLimitMiddleware(downstream)(scope, receive, send))
        return sent, downstream_called

    def test_content_length_over_limit_is_rejected_before_body_read(self):
        sent, downstream_called = self.run_asgi([], b"262145")

        self.assertEqual(sent[0]["status"], 413)
        self.assertFalse(downstream_called)

    def test_chunked_body_over_limit_is_rejected(self):
        sent, downstream_called = self.run_asgi([b"x" * (128 * 1024), b"y" * (129 * 1024)])

        self.assertEqual(sent[0]["status"], 413)
        self.assertTrue(downstream_called)

    def test_body_under_limit_reaches_endpoint(self):
        sent, downstream_called = self.run_asgi([b"valid"])

        self.assertEqual(sent[0]["status"], 200)
        self.assertTrue(downstream_called)


if __name__ == "__main__":
    unittest.main()
