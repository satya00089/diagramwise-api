"""Early request-body limits for the simulator endpoints."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _RequestBodyTooLarge(Exception):
    pass


class SimulationRequestSizeLimitMiddleware:
    """Bound raw bodies before FastAPI parses JSON into model objects."""

    _limits = {
        ("POST", "/api/v1/simulation/prepare"): 256 * 1024,
        ("POST", "/api/v1/simulation/runs"): 56 * 1024,
    }

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limits.get((scope.get("method", ""), scope.get("path", "")))
        if limit is None:
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        try:
            if int(headers.get(b"content-length", b"0")) > limit:
                await self._send_too_large(send)
                return
        except ValueError:
            pass

        body_length = 0

        async def limited_receive() -> Message:
            nonlocal body_length
            message = await receive()
            if message["type"] == "http.request":
                body_length += len(message.get("body", b""))
                if body_length > limit:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await self._send_too_large(send)

    @staticmethod
    async def _send_too_large(send: Send) -> None:
        body = b'{"detail":"Request body exceeds the simulator limit."}'
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
