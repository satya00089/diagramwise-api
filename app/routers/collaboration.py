"""WebSocket router for real-time collaboration on diagrams."""

import json
import asyncio
import logging
import time
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from app.services.dynamodb_service import dynamodb_service
from app.services.validation import validate_diagram_access
from app.services.auth_sessions import auth_session_service
from app.services.browser_auth import AUTH_SESSION_COOKIE, require_allowed_origin
from app.utils.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Store active connections: diagram_id -> list of (websocket, user_id)
active_connections: Dict[str, List[Tuple[WebSocket, str]]] = {}

# Debounced save tracking: diagram_id -> (last_update_time, pending_data, save_task)
debounced_saves: Dict[str, Tuple[float, Dict[str, Any], Any]] = {}


class RateLimiter:
    """Simple rate limiter using sliding window with burst allowance."""

    def __init__(self, max_per_second: float, burst_allowance: int = 10):
        self.max_per_second = max_per_second
        self.burst_allowance = burst_allowance
        self.timestamps: List[float] = []

    def is_allowed(self) -> bool:
        """Check if request is allowed under rate limit."""
        now = time.time()

        # Remove old timestamps outside the 1-second window
        self.timestamps = [t for t in self.timestamps if now - t < 1]

        # Allow bursts up to burst_allowance, but enforce average rate
        if len(self.timestamps) >= self.max_per_second + self.burst_allowance:
            return False

        self.timestamps.append(now)
        return True


# Rate limiters per user: user_id -> message_type -> RateLimiter
user_rate_limiters: Dict[str, Dict[str, RateLimiter]] = {}


def get_rate_limiter(user_id: str, message_type: str) -> RateLimiter:
    """Get or create rate limiter for user and message type."""
    if user_id not in user_rate_limiters:
        user_rate_limiters[user_id] = {}

    if message_type not in user_rate_limiters[user_id]:
        # Set rate limits based on message type
        if message_type == "cursor_move":
            # Allow high frequency cursor updates for smooth tracking
            # Average: 120/s, Burst: up to 50 messages
            user_rate_limiters[user_id][message_type] = RateLimiter(120, 50)
        elif message_type == "diagram_update":
            # More restrictive for diagram updates to prevent spam
            user_rate_limiters[user_id][message_type] = RateLimiter(10, 5)
        elif message_type == "ping":
            # Very restrictive for ping to prevent abuse
            user_rate_limiters[user_id][message_type] = RateLimiter(1, 0)
        else:
            # Default rate limit
            user_rate_limiters[user_id][message_type] = RateLimiter(10, 2)

    return user_rate_limiters[user_id][message_type]


def _validate_cursor_message(data: Dict[str, Any]) -> tuple[bool, str]:
    if "position" not in data:
        return False, "Missing 'position' field"
    position = data["position"]
    if not isinstance(position, dict) or not {"x", "y"}.issubset(position):
        return False, "Invalid 'position' format, must contain 'x' and 'y' coordinates"
    if not all(isinstance(position[key], (int, float)) for key in ("x", "y")):
        return False, "Position coordinates must be numbers"
    return True, ""


def _validate_timestamp(data: Dict[str, Any]) -> tuple[bool, str]:
    if "timestamp" not in data:
        return True, ""
    timestamp = data["timestamp"]
    if not isinstance(timestamp, str):
        return False, "Invalid timestamp format"
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False, "Invalid timestamp format"
    return True, ""


def validate_message(message_type: str, data: Dict[str, Any]) -> tuple[bool, str]:
    """Validate message format and required fields."""
    if message_type == "cursor_move":
        valid, error = _validate_cursor_message(data)
        if not valid:
            return False, error
    elif message_type == "diagram_update" and "data" not in data:
        return False, "Missing 'data' field"
    return _validate_timestamp(data)


def debounced_save_diagram(
    diagram_id: str, user_id: str, update_data: Dict[str, Any]
):
    """Save diagram updates with debouncing (5-second delay)."""
    current_time = time.time()

    # Cancel any existing save task for this diagram
    if diagram_id in debounced_saves:
        _, _, existing_task = debounced_saves[diagram_id]
        if not existing_task.done():
            existing_task.cancel()

    # Schedule new save task
    async def save_after_delay():
        await asyncio.sleep(5)  # 5 second debounce
        try:
            # Extract update data
            nodes = update_data.get("nodes")
            edges = update_data.get("edges")
            title = update_data.get("title")
            description = update_data.get("description")

            # Resolve the owner directly through the collaborator membership.
            diagram, _ = dynamodb_service.get_diagram_for_user(user_id, diagram_id)

            if diagram:
                # Update the diagram
                dynamodb_service.update_diagram(
                    user_id=diagram.userId,  # Use owner ID
                    diagram_id=diagram_id,
                    title=title,
                    description=description,
                    nodes=nodes,
                    edges=edges,
                )
                logger.info("Debounced save completed for diagram %s", diagram_id)
            else:
                logger.warning("Diagram not found during debounced save")

        except Exception:
            logger.exception("Failed debounced save for diagram %s", diagram_id)
        finally:
            # Clean up tracking
            if diagram_id in debounced_saves:
                del debounced_saves[diagram_id]

    # Create and track the save task
    save_task = asyncio.create_task(save_after_delay())
    debounced_saves[diagram_id] = (current_time, update_data, save_task)


async def notify_collaborators(
    diagram_id: str, message: Dict[str, Any], exclude_user_id: Optional[str] = None
):
    """Notify all collaborators of a diagram about changes."""
    if diagram_id not in active_connections:
        return

    disconnected: List[Tuple[WebSocket, str]] = []
    for websocket, user_id in active_connections[diagram_id]:
        if exclude_user_id and user_id == exclude_user_id:
            continue

        try:
            await websocket.send_json(message)
        except Exception:
            # Connection is dead, mark for removal
            disconnected.append((websocket, user_id))

    # Remove disconnected clients
    for websocket, user_id in disconnected:
        if websocket in [w for w, _ in active_connections[diagram_id]]:
            active_connections[diagram_id].remove((websocket, user_id))


async def _reject_collaboration(
    websocket: WebSocket, message: str, code: str, close_code: int = 1008
) -> None:
    await websocket.send_json({"type": "error", "message": message, "code": code})
    await websocket.close(code=close_code)


async def _authenticate_collaborator(
    websocket: WebSocket, diagram_id: str, token: Optional[str]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    if not token:
        await _reject_collaboration(websocket, "Authentication required", "INVALID_TOKEN")
        return None

    try:
        payload = auth_session_service.validate(token)
        user_id = payload.get("user_id")
        if not user_id:
            raise ValueError("Invalid token payload")
    except HTTPException as exc:
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            await _reject_collaboration(
                websocket, "Authentication is temporarily unavailable", "AUTH_UNAVAILABLE", 1013
            )
            return None
        await _reject_collaboration(websocket, "Invalid or expired token", "INVALID_TOKEN")
        return None
    except (ValueError, TypeError):
        await _reject_collaboration(websocket, "Invalid or expired token", "INVALID_TOKEN")
        return None

    has_access, error_msg = validate_diagram_access(user_id, diagram_id, "read")
    if not has_access:
        await _reject_collaboration(websocket, error_msg, "PERMISSION_DENIED")
        return None

    user = dynamodb_service.get_user_by_id(user_id)
    if not user:
        await _reject_collaboration(websocket, "User not found", "INVALID_TOKEN")
        return None
    return user_id, _user_summary(user)


def _user_summary(user: Any) -> Dict[str, Any]:
    return {
        "id": user.id,
        "name": user.name or "Anonymous",
        "email": user.email,
        "pictureUrl": user.picture or None,
        "avatarKey": user.avatarKey,
    }


def _get_active_collaborators(diagram_id: str, user_id: str) -> List[Dict[str, Any]]:
    collaborator_ids = [
        collaborator_id
        for _, collaborator_id in active_connections.get(diagram_id, [])
        if collaborator_id != user_id
    ]
    profiles = dynamodb_service.get_user_profiles_by_ids(collaborator_ids)
    collaborators: List[Dict[str, Any]] = []
    for collaborator_id in collaborator_ids:
        profile = profiles.get(collaborator_id)
        if profile:
            collaborators.append(profile)
    return collaborators


def _get_diagram_data(user_id: str, diagram_id: str) -> Optional[Dict[str, Any]]:
    try:
        diagram, access_permission = dynamodb_service.get_diagram_for_user(
            user_id, diagram_id
        )
        if not diagram:
            return None

        is_owner = diagram.userId == user_id
        if is_owner:
            permission = "owner"
        elif access_permission:
            permission = access_permission.value
        else:
            permission = None
        owner_info = None
        if diagram.userId:
            owner = dynamodb_service.get_user_by_id(diagram.userId)
            if owner:
                owner_info = _user_summary(owner)
        return {
            "id": diagram.id,
            "title": diagram.title or "Untitled Diagram",
            "description": diagram.description,
            "nodes": diagram.nodes or [],
            "edges": diagram.edges or [],
            "isOwner": is_owner,
            "permission": permission,
            "owner": owner_info,
            "createdAt": diagram.createdAt,
            "updatedAt": diagram.updatedAt,
        }
    except Exception:
        logger.exception("Failed to load collaboration diagram data")
        return None


def _welcome_message(
    user_info: Dict[str, Any],
    collaborators: List[Dict[str, Any]],
    diagram_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    message: Dict[str, Any] = {
        "type": "welcome",
        "user": user_info,
        "collaborators": collaborators,
        "rateLimits": {
            "cursorMove": {"average": 120, "burst": 50},
            "diagramUpdate": {"average": 10, "burst": 5},
            "ping": {"average": 1, "burst": 0},
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if diagram_data:
        message["diagram"] = diagram_data
    return message


async def _process_diagram_update(
    websocket: WebSocket,
    diagram_id: str,
    user_id: str,
    user_info: Dict[str, Any],
    data: Dict[str, Any],
) -> None:
    has_access, error_msg = validate_diagram_access(user_id, diagram_id, "update")
    if not has_access:
        await websocket.send_json(
            {"type": "error", "message": error_msg, "code": "PERMISSION_DENIED"}
        )
        return

    update_data = {
        "type": "diagram_update",
        "user": user_info,
        "data": data.get("data", {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        debounced_save_diagram(diagram_id, user_id, data.get("data", {}))
        await notify_collaborators(diagram_id, update_data)
    except Exception:
        await websocket.send_json(
            {
                "type": "error",
                "message": "Failed to process update",
                "code": "INTERNAL_ERROR",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


async def _process_collaboration_message(
    websocket: WebSocket,
    diagram_id: str,
    user_id: str,
    user_info: Dict[str, Any],
    data: Dict[str, Any],
) -> None:
    message_type = data.get("type")
    if not isinstance(message_type, str):
        await websocket.send_json(
            {
                "type": "error",
                "message": "Message type must be a string",
                "code": "INVALID_MESSAGE_FORMAT",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        return

    is_valid, validation_error = validate_message(message_type, data)
    if not is_valid:
        await websocket.send_json(
            {
                "type": "error",
                "message": validation_error,
                "code": "INVALID_MESSAGE_FORMAT",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        return

    if not get_rate_limiter(user_id, message_type).is_allowed():
        if message_type != "cursor_move":
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Rate limit exceeded for {message_type}",
                    "code": "RATE_LIMIT_EXCEEDED",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        return

    if message_type == "diagram_update":
        await _process_diagram_update(websocket, diagram_id, user_id, user_info, data)
    elif message_type == "cursor_move":
        await notify_collaborators(
            diagram_id,
            {
                "type": "cursor_move",
                "user": user_info,
                "position": data.get("position", {}),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            exclude_user_id=user_id,
        )
    elif message_type == "ping":
        await websocket.send_json(
            {"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}
        )
    else:
        await websocket.send_json(
            {
                "type": "error",
                "message": f"Unknown message type: {message_type}",
                "code": "UNKNOWN_MESSAGE_TYPE",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


async def _receive_message_or_timeout(websocket: WebSocket) -> Any:
    try:
        return await asyncio.wait_for(websocket.receive_json(), timeout=5)
    except asyncio.TimeoutError:
        return None


def _validate_collaboration_session(token: str, last_check: float) -> float:
    if time.monotonic() - last_check < 5:
        return last_check
    auth_session_service.validate(token)
    return time.monotonic()


async def _send_invalid_message_error(websocket: WebSocket) -> None:
    await websocket.send_json(
        {
            "type": "error",
            "message": "Invalid JSON received",
            "code": "INVALID_MESSAGE_FORMAT",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


async def _receive_and_process_collaboration_message(
    websocket: WebSocket,
    diagram_id: str,
    user_id: str,
    user_info: Dict[str, Any],
    token: str,
    last_session_check: float,
) -> float:
    data = await _receive_message_or_timeout(websocket)
    last_session_check = _validate_collaboration_session(token, last_session_check)
    if data is not None:
        await _process_collaboration_message(websocket, diagram_id, user_id, user_info, data)
    return last_session_check


async def _receive_collaboration_messages(
    websocket: WebSocket,
    diagram_id: str,
    user_id: str,
    user_info: Dict[str, Any],
    token: str,
) -> None:
    last_session_check = time.monotonic()
    while True:
        try:
            last_session_check = await _receive_and_process_collaboration_message(
                websocket, diagram_id, user_id, user_info, token, last_session_check
            )
        except HTTPException as exc:
            code = "AUTH_UNAVAILABLE" if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE else "INVALID_TOKEN"
            message = "Authentication is temporarily unavailable" if code == "AUTH_UNAVAILABLE" else "Session is invalid or revoked"
            await _reject_collaboration(websocket, message, code, 1013 if code == "AUTH_UNAVAILABLE" else 1008)
            return
        except json.JSONDecodeError:
            await _send_invalid_message_error(websocket)


async def _remove_collaborator(
    diagram_id: str, user_id: Optional[str], user_info: Dict[str, Any]
) -> None:
    if not user_id or diagram_id not in active_connections:
        return
    active_connections[diagram_id] = [
        (websocket, uid)
        for websocket, uid in active_connections[diagram_id]
        if uid != user_id
    ]
    if not active_connections[diagram_id]:
        del active_connections[diagram_id]
    await notify_collaborators(
        diagram_id,
        {
            "type": "user_left",
            "user": user_info,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@router.websocket("/diagrams/{diagram_id}/collaborate")
async def collaborate_on_diagram(
    websocket: WebSocket,
    diagram_id: str,
    token: Optional[str] = None,
):
    """WebSocket endpoint for real-time collaboration on diagrams."""
    try:
        require_allowed_origin(websocket.headers.get("origin"), get_settings())
    except HTTPException:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    user_id: Optional[str] = None
    user_info: Dict[str, Any] = {}
    try:
        # Prefer the HttpOnly cookie; keep query-token support temporarily for
        # already-open older clients during the frontend rollout.
        session_token = websocket.cookies.get(AUTH_SESSION_COOKIE) or token
        authenticated = await _authenticate_collaborator(
            websocket, diagram_id, session_token
        )
        if not authenticated:
            return
        user_id, user_info = authenticated
        active_connections.setdefault(diagram_id, []).append((websocket, user_id))
        collaborators = _get_active_collaborators(diagram_id, user_id)
        diagram_data = _get_diagram_data(user_id, diagram_id)
        await notify_collaborators(
            diagram_id,
            {
                "type": "user_joined",
                "user": user_info,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            exclude_user_id=user_id,
        )
        await websocket.send_json(
            _welcome_message(user_info, collaborators, diagram_data)
        )
        await _receive_collaboration_messages(
            websocket, diagram_id, user_id, user_info, session_token or ""
        )
    except WebSocketDisconnect:
        pass
    finally:
        await _remove_collaborator(diagram_id, user_id, user_info)
