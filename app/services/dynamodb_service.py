"""DynamoDB service for managing users and diagrams."""

from datetime import datetime, timezone
from dataclasses import dataclass
from decimal import Decimal
import time
from typing import Any, Dict, List, Optional, Tuple, cast
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from mypy_boto3_dynamodb.service_resource import Table
from mypy_boto3_dynamodb.type_defs import TransactWriteItemTypeDef
from pydantic import BaseModel

from app.utils.config import get_settings
from app.models.auth_models import User
from app.models.diagram_models import Diagram, Collaborator, Permission, PublicDiagramResponse
from app.models.attempt_models import AttemptCreate, AttemptResponse, PublicSolutionResponse, LeaderboardEntry
from app.models.feedback_models import FeedbackCreate, FeedbackResponse
from app.models.problem_models import RequirementSpec

settings = get_settings()

DDB_ZERO_VALUE = ":zero"
DDB_NODES_NAME = "#nodes"
DDB_EDGES_NAME = "#edges"
# Canvas items share the diagrams table; this marks them so diagram lists skip them.
CANVAS_RECORD_TYPE = "canvas"
DDB_UPDATED_VALUE = ":updated"


@dataclass
class PreparedAttemptState:
    assessment_count: int
    preserved_assessment: Optional[Dict[str, Any]]
    preserved_reasoning_context: Optional[Dict[str, Any]]
    preserved_interview_session: Optional[Dict[str, Any]]
    existing_data: Dict[str, Any]
    assessment_history: List[Dict[str, Any]]
    addressed_finding_ids: List[str]
    preserved_check: Optional[Dict[str, Any]]


@dataclass
class AttemptSaveState:
    user_id: str
    request: AttemptCreate
    existing_attempt: Optional[AttemptResponse]
    prepared: PreparedAttemptState
    updated_at: str
    problem_requirement_spec: Optional[Dict[str, Any]]


class SimulationRunLimitReached(RuntimeError):
    """The account already has the maximum number of active saved runs."""

def _is_canvas_record(item: Dict[str, Any]) -> bool:
    return item.get("recordType") == CANVAS_RECORD_TYPE

DIAGRAM_SUMMARY_ATTRIBUTES = (
    "userId",
    "id",
    "title",
    "description",
    "createdAt",
    "updatedAt",
    "isPublic",
    "publishedAt",
    "viewCount",
    "nodeCount",
    "edgeCount",
    "collaborators",
    "recordType",
    "familyId",
    "sourceDiagramId",
    "publicSnapshotId",
)
DIAGRAM_SUMMARY_PROJECTION = ", ".join(
    f"#{index}" for index, _ in enumerate(DIAGRAM_SUMMARY_ATTRIBUTES)
)
DIAGRAM_SUMMARY_NAMES = {
    f"#{index}": attribute
    for index, attribute in enumerate(DIAGRAM_SUMMARY_ATTRIBUTES)
}


def convert_floats_to_decimal(obj: Any) -> Any:
    """
    Recursively convert all float values to Decimal for DynamoDB compatibility.
    DynamoDB doesn't support Python float type - requires Decimal instead.
    """
    if isinstance(obj, BaseModel):
        return convert_floats_to_decimal(obj.model_dump(mode="python"))
    if isinstance(obj, list):
        return [convert_floats_to_decimal(item) for item in obj]  # type: ignore[misc]
    elif isinstance(obj, dict):
        return {key: convert_floats_to_decimal(value) for key, value in obj.items()}  # type: ignore[misc]
    elif isinstance(obj, float):
        return Decimal(str(obj))
    else:
        return obj


def convert_decimal_to_float(obj: Any) -> Any:
    """
    Recursively convert all Decimal values back to float for JSON serialization.
    This is needed when retrieving data from DynamoDB.
    """
    if isinstance(obj, list):
        return [convert_decimal_to_float(item) for item in obj]  # type: ignore[misc]
    elif isinstance(obj, dict):
        return {key: convert_decimal_to_float(value) for key, value in obj.items()}  # type: ignore[misc]
    elif isinstance(obj, Decimal):
        return float(obj)
    else:
        return obj


class DynamoDBService:
    """Service for DynamoDB operations."""

    def __init__(self):
        """Initialize DynamoDB service."""
        dynamodb = boto3.resource(  # type: ignore[misc]
            "dynamodb",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        self.users_table: Table = dynamodb.Table(settings.dynamodb_users_table)
        self.diagrams_table: Table = dynamodb.Table(settings.dynamodb_diagrams_table)
        self.diagram_shares_table: Table = dynamodb.Table(
            settings.dynamodb_diagram_shares_table
        )
        self.problems_table: Table = dynamodb.Table(settings.dynamodb_problems_table)
        self.attempts_table: Table = dynamodb.Table(settings.dynamodb_attempts_table)
        self.simulation_runs_table: Table = dynamodb.Table(
            settings.dynamodb_simulation_runs_table
        )
        self.feedback_table: Table = dynamodb.Table(settings.dynamodb_feedback_table)
        self.walkthroughs_table: Table = dynamodb.Table(settings.dynamodb_walkthroughs_table)
        self.auth_sessions_table: Table = dynamodb.Table(settings.dynamodb_auth_sessions_table)

    @staticmethod
    def _serialize_item(item: Dict[str, Any]) -> Dict[str, Any]:
        serializer = TypeSerializer()
        return {name: serializer.serialize(value) for name, value in item.items()}

    @staticmethod
    def _deserialize_item(item: Dict[str, Any]) -> Dict[str, Any]:
        deserializer = TypeDeserializer()
        return {name: deserializer.deserialize(value) for name, value in item.items()}

    def _batch_get_items(
        self,
        table: Table,
        keys: List[Dict[str, Any]],
        projection_expression: Optional[str] = None,
        expression_attribute_names: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Batch-get items in groups of 100 and retry DynamoDB's unprocessed keys."""
        if not keys:
            return []

        table_name = table.name
        client = table.meta.client
        items: List[Dict[str, Any]] = []
        for offset in range(0, len(keys), 100):
            request: Dict[str, Any] = {
                "Keys": [self._serialize_item(key) for key in keys[offset : offset + 100]]
            }
            if projection_expression:
                request["ProjectionExpression"] = projection_expression
            if expression_attribute_names:
                request["ExpressionAttributeNames"] = expression_attribute_names

            pending: Dict[str, Any] = {table_name: request}
            attempts = 0
            while pending:
                response = client.batch_get_item(RequestItems=pending)
                items.extend(
                    self._deserialize_item(item)
                    for item in response.get("Responses", {}).get(table_name, [])
                )
                pending = response.get("UnprocessedKeys", {})
                if pending:
                    attempts += 1
                    if attempts >= 5:
                        raise RuntimeError("DynamoDB left diagram keys unprocessed")
                    time.sleep(0.05 * (2 ** (attempts - 1)))
        return items

    # User operations
    def _resolve_existing_user(
        self, user: User, google_id: Optional[str], picture: Optional[str]
    ) -> User:
        if google_id and not user.googleId:
            updated_user = self.update_user_google_id(user.id, google_id, picture)
            if updated_user:
                return updated_user
        return user

    @staticmethod
    def _build_user_item(
        email: str,
        password_hash: Optional[str],
        name: Optional[str],
        picture: Optional[str],
        google_id: Optional[str],
        email_verified: bool,
    ) -> Dict[str, Any]:
        user_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        item: Dict[str, Any] = {
            "id": user_id,
            "email": email,
            "name": name,
            "createdAt": now,
            "updatedAt": now,
            "emailVerified": email_verified,
        }
        optional_values = {
            "passwordHash": password_hash,
            "picture": picture,
            "googleId": google_id,
        }
        item.update(
            {key: value for key, value in optional_values.items() if value}
        )
        return item

    def _save_new_user(self, item: Dict[str, Any], email: str) -> User:
        try:
            self.users_table.put_item(
                Item=item, ConditionExpression="attribute_not_exists(id)"
            )
        except ClientError as error:
            error_code = error.response.get("Error", {}).get("Code")  # type: ignore[union-attr]
            if error_code == "ConditionalCheckFailedException":
                existing_user = self.get_user_by_email(email)
                if existing_user:
                    return existing_user
            raise
        return User(**item)

    def create_user(
        self,
        email: str,
        password_hash: Optional[str] = None,
        name: Optional[str] = None,
        picture: Optional[str] = None,
        google_id: Optional[str] = None,
        email_verified: bool = False,
    ) -> User:
        """Create a new user in DynamoDB."""
        existing_user = self.get_user_by_email(email)
        if existing_user:
            return self._resolve_existing_user(existing_user, google_id, picture)
        item = self._build_user_item(
            email, password_hash, name, picture, google_id, email_verified
        )
        return self._save_new_user(item, email)

    def save_email_verification_token(
        self, user_id: str, token_hash: str, expires_at: str, sent_at: str
    ) -> Optional[User]:
        """Store the newest verification token, invalidating all previous links."""
        try:
            response = self.users_table.update_item(
                Key={"id": user_id},
                UpdateExpression=(
                    "SET verificationTokenHash = :token, verificationExpiresAt = :expires, "
                    "verificationSentAt = :sent, verificationVersion = "
                    f"if_not_exists(verificationVersion, :zero) + :one, "
                    f"updatedAt = {DDB_UPDATED_VALUE}"
                ),
                ExpressionAttributeValues={
                    ":token": token_hash,
                    ":expires": expires_at,
                    ":sent": sent_at,
                    DDB_ZERO_VALUE: 0,
                    ":one": 1,
                    DDB_UPDATED_VALUE: sent_at,
                },
                ReturnValues="ALL_NEW",
            )
            item = response.get("Attributes")
            return User.model_validate(cast(Dict[str, Any], item)) if item else None
        except ClientError as e:
            print(f"Error saving email verification token: {e}")
            return None

    def mark_email_verified(
        self, user_id: str, expected_token_hash: Optional[str] = None
    ) -> Optional[User]:
        """Mark a user verified and remove the one-time token material."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            update_kwargs: Dict[str, Any] = {
                "Key": {"id": user_id},
                "UpdateExpression": (
                    f"SET emailVerified = :verified, updatedAt = {DDB_UPDATED_VALUE} "
                    "REMOVE verificationTokenHash, verificationExpiresAt, verificationSentAt"
                ),
                "ExpressionAttributeValues": {":verified": True, DDB_UPDATED_VALUE: now},
                "ReturnValues": "ALL_NEW",
            }
            # The conditional write makes the link single-use even if two
            # requests race with the same token.
            if expected_token_hash:
                update_kwargs["ConditionExpression"] = "verificationTokenHash = :expected"
                update_kwargs["ExpressionAttributeValues"][":expected"] = expected_token_hash
            response = self.users_table.update_item(**update_kwargs)
            item = response.get("Attributes")
            return User.model_validate(cast(Dict[str, Any], item)) if item else None
        except ClientError as e:
            print(f"Error marking email verified: {e}")
            return None

    def restore_email_verification_state(
        self, user: User, expected_token_hash: str
    ) -> None:
        """Undo a replacement token when delivery was not accepted by Resend."""
        try:
            values: Dict[str, Any] = {
                ":expected": expected_token_hash,
                DDB_UPDATED_VALUE: user.updatedAt,
                ":version": user.verificationVersion,
            }
            if user.verificationTokenHash and user.verificationExpiresAt and user.verificationSentAt:
                update_expression = (
                    "SET verificationTokenHash = :token, verificationExpiresAt = :expires, "
                    f"verificationSentAt = :sent, verificationVersion = :version, "
                    f"updatedAt = {DDB_UPDATED_VALUE}"
                )
                values.update({
                    ":token": user.verificationTokenHash,
                    ":expires": user.verificationExpiresAt,
                    ":sent": user.verificationSentAt,
                })
            else:
                update_expression = (
                    f"SET verificationVersion = :version, updatedAt = {DDB_UPDATED_VALUE} "
                    "REMOVE verificationTokenHash, verificationExpiresAt, verificationSentAt"
                )
            self.users_table.update_item(
                Key={"id": user.id},
                UpdateExpression=update_expression,
                ConditionExpression="verificationTokenHash = :expected",
                ExpressionAttributeValues=values,
            )
        except ClientError as e:
            # A concurrent resend may have already replaced this state; do not
            # overwrite it with stale data.
            print(f"Error restoring email verification state: {e}")

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email using GSI."""
        try:
            response = self.users_table.query(
                IndexName="email-index", KeyConditionExpression=Key("email").eq(email)
            )
            items = response.get("Items", [])
            if items:
                user_data: Dict[str, Any] = items[0]
                return User(**user_data)
            return None
        except ClientError:
            return None

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        try:
            response = self.users_table.get_item(Key={"id": user_id})
            item = response.get("Item")
            if item:
                user_data: Dict[str, Any] = item
                return User(**user_data)
            return None
        except ClientError:
            return None

    def get_user_profiles_by_ids(
        self, user_ids: List[str]
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """Batch-load the small user profile projection used by diagram lists."""
        ids = list(dict.fromkeys(user_ids))
        if not ids:
            return {}
        try:
            users = self._batch_get_items(
                self.users_table,
                [{"id": user_id} for user_id in ids],
                "#id, #name, #email, #picture, #avatar_key",
                {
                    "#id": "id",
                    "#name": "name",
                    "#email": "email",
                    "#picture": "picture",
                    "#avatar_key": "avatarKey",
                },
            )
            by_id = {
                str(user["id"]): {
                    "id": user["id"],
                    "name": user.get("name") or "Anonymous",
                    "email": user.get("email"),
                    "pictureUrl": user.get("picture") or None,
                    "avatarKey": user.get("avatarKey"),
                }
                for user in users
                if user.get("id")
            }
            return {user_id: by_id.get(user_id) for user_id in ids}
        except (ClientError, RuntimeError):
            return cast(
                Dict[str, Optional[Dict[str, Any]]], dict.fromkeys(ids, None)
            )

    def update_user_profile(
        self, user_id: str, first_name: str, last_name: str
    ) -> Optional[User]:
        """Update a user's editable name fields without changing preferences."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            display_name = " ".join(part for part in (first_name, last_name) if part)
            response = self.users_table.update_item(
                Key={"id": user_id},
                UpdateExpression=(
                    f"SET firstName = :first_name, lastName = :last_name, "
                    f"#name = :display_name, updatedAt = {DDB_UPDATED_VALUE}"
                ),
                ExpressionAttributeNames={"#name": "name"},
                ExpressionAttributeValues={
                    ":first_name": first_name,
                    ":last_name": last_name,
                    ":display_name": display_name,
                    DDB_UPDATED_VALUE: now,
                },
                ReturnValues="ALL_NEW",
            )
            item = response.get("Attributes")
            if item:
                return User.model_validate(cast(Dict[str, Any], item))
            return None
        except ClientError as e:
            print(f"Error updating user profile: {e}")
            return None

    def update_user_avatar(self, user_id: str, avatar_key: Optional[str]) -> Optional[User]:
        """Save or clear a user's curated avatar key."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            response = self.users_table.update_item(
                Key={"id": user_id},
                UpdateExpression=(
                    f"SET avatarKey = :avatar_key, updatedAt = {DDB_UPDATED_VALUE}"
                ),
                ExpressionAttributeValues={
                    ":avatar_key": avatar_key,
                    DDB_UPDATED_VALUE: now,
                },
                ReturnValues="ALL_NEW",
            )
            item = response.get("Attributes")
            if item:
                return User.model_validate(cast(Dict[str, Any], item))
            return None
        except ClientError as e:
            print(f"Error updating user avatar: {e}")
            return None

    def get_user_preferences(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Return the preferences blob for a user, if present."""
        try:
            response = self.users_table.get_item(Key={"id": user_id})
            item = response.get("Item")
            if item:
                # preferences may be stored as a map
                prefs = item.get("preferences")
                return convert_decimal_to_float(prefs) if prefs is not None else None
            return None
        except ClientError:
            return None

    def update_user_preferences(self, user_id: str, preferences: Dict[str, Any]) -> Optional[User]:
        """Upsert user preferences atomically and return updated user."""
        try:
            now = datetime.now(timezone.utc).isoformat()

            prefs_safe = convert_floats_to_decimal(preferences)

            response = self.users_table.update_item(
                Key={"id": user_id},
                UpdateExpression=(
                    f"SET preferences = :prefs, updatedAt = {DDB_UPDATED_VALUE}"
                ),
                ExpressionAttributeValues={
                    ":prefs": prefs_safe,
                    DDB_UPDATED_VALUE: now,
                },
                ReturnValues="ALL_NEW",
            )
            item = response.get("Attributes")
            if item:
                return User.model_validate(cast(Dict[str, Any], item))
            return None
        except ClientError as e:
            print(f"Error updating user preferences: {e}")
            return None

    def update_user_roles(self, user_id: str, roles: List[str]) -> Optional[User]:
        """Replace the persisted application roles for one user."""
        try:
            response = self.users_table.update_item(
                Key={"id": user_id},
                UpdateExpression=(
                    f"SET #roles = :roles, updatedAt = {DDB_UPDATED_VALUE}"
                ),
                ExpressionAttributeNames={"#roles": "roles"},
                ExpressionAttributeValues={
                    ":roles": roles,
                    DDB_UPDATED_VALUE: datetime.now(timezone.utc).isoformat(),
                },
                ReturnValues="ALL_NEW",
            )
            item = response.get("Attributes")
            return User.model_validate(cast(Dict[str, Any], item)) if item else None
        except ClientError as e:
            print(f"Error updating user roles: {e}")
            return None

    def list_users_with_role(self, role: str) -> List[User]:
        """Return users carrying a role, handling DynamoDB scan pagination."""
        users: List[User] = []
        scan_kwargs: Dict[str, Any] = {
            "FilterExpression": Attr("roles").contains(role),
        }
        while True:
            response = self.users_table.scan(**scan_kwargs)
            users.extend(User.model_validate(item) for item in response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key
        return users

    def get_user_by_google_id(self, google_id: str) -> Optional[User]:
        """Get user by Google ID using GSI."""
        try:
            response = self.users_table.query(
                IndexName="googleId-index",
                KeyConditionExpression=Key("googleId").eq(google_id),
            )
            items = response.get("Items", [])
            if items:
                user_data: Dict[str, Any] = items[0]
                return User(**user_data)
            return None
        except ClientError:
            return None

    # Product feedback operations
    def create_feedback(
        self, feedback: FeedbackCreate, user_id: Optional[str] = None
    ) -> FeedbackResponse:
        """Persist a single user feedback item without storing canvas content."""
        feedback_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        item: Dict[str, Any] = {
            "id": feedback_id,
            "createdAt": now,
            "updatedAt": now,
            "status": "new",
            "source": feedback.source.value,
            "category": feedback.category.value,
            "message": feedback.message,
            "reasons": [reason.value for reason in feedback.reasons],
            "context": feedback.context.model_dump(exclude_none=True),
        }
        if feedback.rating is not None:
            item["rating"] = feedback.rating
        if feedback.helpful is not None:
            item["helpful"] = feedback.helpful
        if feedback.contactEmail:
            item["contactEmail"] = str(feedback.contactEmail)
        if feedback.route:
            item["route"] = feedback.route
        if feedback.appVersion:
            item["appVersion"] = feedback.appVersion
        if user_id:
            item["userId"] = user_id

        self.feedback_table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(id)",
        )
        return FeedbackResponse(id=feedback_id, createdAt=now)

    def list_feedback(self, limit: int = 250) -> List[Dict[str, Any]]:
        """Read recent feedback for the protected admin surface."""
        items: List[Dict[str, Any]] = []
        scan_kwargs: Dict[str, Any] = {}
        while len(items) < limit:
            response = self.feedback_table.scan(**scan_kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key
        return sorted(items[:limit], key=lambda item: item.get("createdAt", ""), reverse=True)

    @staticmethod
    def summarize_feedback(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        ratings = [int(item["rating"]) for item in items if item.get("rating") is not None]
        helpful_values = [item["helpful"] for item in items if item.get("helpful") is not None]
        categories: Dict[str, int] = {}
        for item in items:
            category = str(item.get("category", "other"))
            categories[category] = categories.get(category, 0) + 1
        return {
            "total": len(items),
            "new": sum(1 for item in items if item.get("status", "new") == "new"),
            "averageRating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "helpfulRate": round(sum(1 for value in helpful_values if value) / len(helpful_values), 3)
            if helpful_values
            else None,
            "categories": categories,
        }

    def update_feedback_status(self, feedback_id: str, feedback_status: str) -> Optional[Dict[str, Any]]:
        """Update only the admin triage state of a feedback item."""
        try:
            response = self.feedback_table.update_item(
                Key={"id": feedback_id},
                UpdateExpression=(
                    f"SET #status = :status, updatedAt = {DDB_UPDATED_VALUE}"
                ),
                ConditionExpression="attribute_exists(id)",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":status": feedback_status,
                    DDB_UPDATED_VALUE: datetime.now(timezone.utc).isoformat(),
                },
                ReturnValues="ALL_NEW",
            )
            return response.get("Attributes")
        except ClientError as e:
            print(f"Error updating feedback status: {e}")
            return None

    def update_user_google_id(
        self, user_id: str, google_id: str, picture: Optional[str] = None
    ) -> Optional[User]:
        """Update user's Google ID and picture (for linking Google account to existing user)."""
        try:
            now = datetime.now(timezone.utc).isoformat()

            update_expression = (
                f"SET googleId = :google_id, updatedAt = {DDB_UPDATED_VALUE}"
            )
            expression_values: Dict[str, Any] = {
                ":google_id": google_id,
                DDB_UPDATED_VALUE: now,
            }

            # Add picture to update if provided
            if picture:
                update_expression += ", picture = :picture"
                expression_values[":picture"] = picture

            response = self.users_table.update_item(
                Key={"id": user_id},
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values,
                ReturnValues="ALL_NEW",
            )
            item = response.get("Attributes")
            if item:
                user_data: Dict[str, Any] = item
                return User(**user_data)
            return None
        except ClientError as e:
            print(f"Error updating user Google ID: {e}")
            return None

    # Diagram operations
    def create_diagram(
        self,
        user_id: str,
        title: str,
        description: Optional[str],
        nodes: List[Any],
        edges: List[Any],
        reasoning_context: Optional[Dict[str, Any]] = None,
        source_diagram_id: Optional[str] = None,
        family_id: Optional[str] = None,
        diagram_id: Optional[str] = None,
        canonical_document: Optional[Dict[str, Any]] = None,
    ) -> Diagram:
        """Create a new diagram in DynamoDB."""
        diagram_id = diagram_id or str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Convert floats to Decimal for DynamoDB
        nodes_decimal = convert_floats_to_decimal(nodes)
        edges_decimal = convert_floats_to_decimal(edges)

        item: Dict[str, Any] = {
            "id": diagram_id,
            "userId": user_id,
            "title": title,
            "description": description,
            "nodes": nodes_decimal,
            "edges": edges_decimal,
            "canonicalDocument": convert_floats_to_decimal(canonical_document)
            if canonical_document is not None
            else None,
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
            "reasoningContext": convert_floats_to_decimal(reasoning_context)
            if reasoning_context is not None
            else None,
            "createdAt": now,
            "updatedAt": now,
            "recordType": "remix" if source_diagram_id else "canonical",
            "familyId": family_id or diagram_id,
        }
        if source_diagram_id:
            item["sourceDiagramId"] = source_diagram_id

        self.diagrams_table.put_item(Item=item)

        # Return with original float values for response
        return Diagram.model_validate(
            {
                "id": diagram_id,
                "userId": user_id,
                "title": title,
                "description": description,
                "nodes": nodes,
                "edges": edges,
                "canonicalDocument": canonical_document,
                "nodeCount": len(nodes),
                "edgeCount": len(edges),
                "reasoningContext": reasoning_context,
                "createdAt": now,
                "updatedAt": now,
                "recordType": "remix" if source_diagram_id else "canonical",
                "familyId": family_id or diagram_id,
                "sourceDiagramId": source_diagram_id,
            }
        )

    def get_diagrams_by_user(self, user_id: str) -> List[Diagram]:
        """Get all diagrams for a user."""
        try:
            items: List[Dict[str, Any]] = []
            # Handle pagination to get all diagrams
            response = self.diagrams_table.query(
                KeyConditionExpression=Key("userId").eq(user_id)
            )
            response_items = response.get("Items", [])
            items.extend(response_items)

            # Continue fetching if there are more pages
            while "LastEvaluatedKey" in response:
                response = self.diagrams_table.query(
                    KeyConditionExpression=Key("userId").eq(user_id),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                response_items = response.get("Items", [])
                items.extend(response_items)

            # Convert Decimal back to float for JSON serialization
            items = [item for item in items if not _is_canvas_record(item)]
            items_float = [convert_decimal_to_float(item) for item in items]
            return [Diagram(**item) for item in items_float]
        except ClientError as e:
            print(f"Error querying diagrams: {e}")
            return []

    def get_diagram_summaries_by_user(self, user_id: str) -> List[Diagram]:
        """Get owned diagram metadata without loading canvas arrays."""
        try:
            items: List[Dict[str, Any]] = []
            query_kwargs = {
                "KeyConditionExpression": Key("userId").eq(user_id),
                "ProjectionExpression": DIAGRAM_SUMMARY_PROJECTION,
                "ExpressionAttributeNames": DIAGRAM_SUMMARY_NAMES,
            }
            response = self.diagrams_table.query(**query_kwargs)
            items.extend(response.get("Items", []))

            last_evaluated_key = response.get("LastEvaluatedKey")
            while last_evaluated_key:
                response = self.diagrams_table.query(
                    **query_kwargs,
                    ExclusiveStartKey=last_evaluated_key,
                )
                items.extend(response.get("Items", []))
                last_evaluated_key = response.get("LastEvaluatedKey")

            items = [item for item in items if not _is_canvas_record(item)]
            items_float = [convert_decimal_to_float(item) for item in items]
            return [Diagram(**item) for item in items_float]
        except ClientError as e:
            print(f"Error querying diagram summaries: {e}")
            return []

    def get_diagram_summary_page_by_user(
        self,
        user_id: str,
        limit: int,
        exclusive_start_key: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[Diagram], Optional[Dict[str, Any]]]:
        """Get one projected page of owned diagram metadata."""
        try:
            query_kwargs: Dict[str, Any] = {
                "KeyConditionExpression": Key("userId").eq(user_id),
                "ProjectionExpression": DIAGRAM_SUMMARY_PROJECTION,
                "ExpressionAttributeNames": DIAGRAM_SUMMARY_NAMES,
                "Limit": limit,
                "FilterExpression": (
                    (
                        Attr("recordType").not_exists()
                        | Attr("recordType").ne("public_snapshot")
                    )
                    & (
                        Attr("recordType").not_exists()
                        | Attr("recordType").ne(CANVAS_RECORD_TYPE)
                    )
                ),
            }
            if exclusive_start_key:
                query_kwargs["ExclusiveStartKey"] = exclusive_start_key

            response = self.diagrams_table.query(**query_kwargs)
            items = [
                Diagram(**convert_decimal_to_float(item))
                for item in response.get("Items", [])
            ]
            return items, response.get("LastEvaluatedKey")
        except ClientError as e:
            print(f"Error querying diagram summary page: {e}")
            return [], None

    def get_diagram(
        self, user_id: str, diagram_id: str, consistent_read: bool = False
    ) -> Optional[Diagram]:
        """Get a specific diagram."""
        try:
            response = self.diagrams_table.get_item(
                Key={"userId": user_id, "id": diagram_id},
                ConsistentRead=consistent_read,
            )
            item = response.get("Item")
            if item:
                # Convert Decimal back to float for JSON serialization
                item_float: Dict[str, Any] = convert_decimal_to_float(item)
                return Diagram(**item_float)
            return None
        except ClientError:
            return None

    def update_diagram(
        self,
        user_id: str,
        diagram_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        nodes: Optional[List[Any]] = None,
        edges: Optional[List[Any]] = None,
        reasoning_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Diagram]:
        """Update a diagram."""
        try:
            now = datetime.now(timezone.utc).isoformat()

            update_expression = f"SET updatedAt = {DDB_UPDATED_VALUE}"
            expression_values: Dict[str, Any] = {DDB_UPDATED_VALUE: now}
            expression_names: Dict[str, str] = {}

            if title is not None:
                update_expression += ", title = :title"
                expression_values[":title"] = title

            if description is not None:
                update_expression += ", description = :description"
                expression_values[":description"] = description

            if nodes is not None:
                update_expression += f", {DDB_NODES_NAME} = :nodes"
                # Convert floats to Decimal for DynamoDB
                expression_values[":nodes"] = convert_floats_to_decimal(nodes)
                expression_names[DDB_NODES_NAME] = "nodes"
                update_expression += ", nodeCount = :node_count"
                expression_values[":node_count"] = len(nodes)

            if edges is not None:
                update_expression += f", {DDB_EDGES_NAME} = :edges"
                # Convert floats to Decimal for DynamoDB
                expression_values[":edges"] = convert_floats_to_decimal(edges)
                expression_names[DDB_EDGES_NAME] = "edges"
                update_expression += ", edgeCount = :edge_count"
                expression_values[":edge_count"] = len(edges)

            if reasoning_context is not None:
                update_expression += ", reasoningContext = :reasoning_context"
                expression_values[":reasoning_context"] = convert_floats_to_decimal(
                    reasoning_context
                )

            update_kwargs: Dict[str, Any] = {
                "Key": {"userId": user_id, "id": diagram_id},
                "UpdateExpression": update_expression,
                "ExpressionAttributeValues": expression_values,
                "ReturnValues": "ALL_NEW",
            }

            if expression_names:
                update_kwargs["ExpressionAttributeNames"] = expression_names

            response = self.diagrams_table.update_item(**update_kwargs)

            item = response.get("Attributes")
            if item:
                # Convert Decimal back to float for JSON serialization
                item_float: Dict[str, Any] = convert_decimal_to_float(item)
                return Diagram(**item_float)
            return None
        except ClientError:
            return None

    def clear_diagram_graph(
        self, user_id: str, diagram_id: str, node_count: int, edge_count: int
    ) -> bool:
        """Keep legacy counts current while removing the now-canonical canvas graph."""
        try:
            self.diagrams_table.update_item(
                Key={"userId": user_id, "id": diagram_id},
                UpdateExpression=(
                    "SET nodeCount = :node_count, edgeCount = :edge_count, "
                    f"updatedAt = {DDB_UPDATED_VALUE} REMOVE {DDB_NODES_NAME}, {DDB_EDGES_NAME}"
                ),
                ExpressionAttributeNames={DDB_NODES_NAME: "nodes", DDB_EDGES_NAME: "edges"},
                ExpressionAttributeValues={
                    ":node_count": node_count,
                    ":edge_count": edge_count,
                    DDB_UPDATED_VALUE: datetime.now(timezone.utc).isoformat(),
                },
                ConditionExpression=Attr("id").exists(),
            )
            return True
        except ClientError:
            return False

    def delete_diagram(self, user_id: str, diagram_id: str) -> bool:
        """Delete a diagram."""
        try:
            diagram = self.get_diagram(user_id, diagram_id, consistent_read=True)
            if not diagram:
                return False

            transaction: List[TransactWriteItemTypeDef] = [
                {
                    "Delete": {
                        "TableName": self.diagrams_table.name,
                        "Key": self._serialize_item({"userId": user_id, "id": diagram_id}),
                        "ConditionExpression": f"#updated = {DDB_UPDATED_VALUE}",
                        "ExpressionAttributeNames": {"#updated": "updatedAt"},
                        "ExpressionAttributeValues": self._serialize_item(
                            {DDB_UPDATED_VALUE: diagram.updatedAt}
                        ),
                    }
                }
            ]
            if diagram.publicSnapshotId and diagram.publicSnapshotId != diagram_id:
                transaction.append(
                    {
                        "Delete": {
                            "TableName": self.diagrams_table.name,
                            "Key": self._serialize_item(
                                {"userId": user_id, "id": diagram.publicSnapshotId}
                            ),
                        }
                    }
                )
            self.diagrams_table.meta.client.transact_write_items(
                TransactItems=transaction
            )

            # Remove memberships after the parent is gone. Reads are denied as
            # soon as the parent delete commits, and the batch writer avoids the
            # 100-action transaction limit for legacy diagrams with many shares.
            seen_collaborators: set[str] = set()
            with self.diagram_shares_table.batch_writer() as batch:
                for collaborator in diagram.collaborators or []:
                    if collaborator.userId in seen_collaborators:
                        continue
                    seen_collaborators.add(collaborator.userId)
                    batch.delete_item(
                        Key={
                            "collaboratorUserId": collaborator.userId,
                            "diagramId": diagram_id,
                        }
                    )

            self._delete_canvas_records(user_id, diagram_id)
            return True
        except ClientError:
            return False

    def _delete_canvas_records(self, owner_id: str, diagram_id: str) -> None:
        """Remove child canvas records stored in the owner's diagrams-table partition."""
        query: Dict[str, Any] = {
            "KeyConditionExpression": Key("userId").eq(owner_id)
            & Key("id").begins_with(f"{diagram_id}#canvas#"),
            "ProjectionExpression": "#u, #i",
            "ExpressionAttributeNames": {"#u": "userId", "#i": "id"},
        }
        while True:
            response = self.diagrams_table.query(**query)
            with self.diagrams_table.batch_writer() as batch:
                for item in response.get("Items", []):
                    batch.delete_item(Key={"userId": item["userId"], "id": item["id"]})
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            query["ExclusiveStartKey"] = last_key

    # Sharing operations
    def _get_diagram_share(
        self, diagram_id: str, collaborator_user_id: str
    ) -> Optional[Dict[str, Any]]:
        try:
            response = self.diagram_shares_table.get_item(
                Key={
                    "collaboratorUserId": collaborator_user_id,
                    "diagramId": diagram_id,
                },
                ConsistentRead=True,
            )
            return response.get("Item")
        except ClientError:
            return None

    @staticmethod
    def _diagram_share_item(
        diagram_id: str, owner_id: str, collaborator: Collaborator
    ) -> Dict[str, Any]:
        return {
            "collaboratorUserId": collaborator.userId,
            "diagramId": diagram_id,
            "ownerId": owner_id,
            "permission": collaborator.permission.value,
            "email": collaborator.email,
            "name": collaborator.name,
            "picture": collaborator.picture,
            "addedAt": collaborator.addedAt,
        }

    @staticmethod
    def _collaborators_after_change(
        diagram: Diagram,
        collaborator_user_id: str,
        collaborator: Optional[Collaborator],
    ) -> Tuple[List[Collaborator], Optional[Collaborator]]:
        collaborators = list(diagram.collaborators or [])
        existing = next(
            (item for item in collaborators if item.userId == collaborator_user_id),
            None,
        )
        if collaborator is None:
            collaborators = [
                item for item in collaborators
                if item.userId != collaborator_user_id
            ]
        elif existing:
            collaborators = [
                collaborator if item.userId == collaborator_user_id else item
                for item in collaborators
            ]
        else:
            collaborators.append(collaborator)
        return collaborators, existing

    def _collaborator_update_request(
        self,
        diagram: Diagram,
        diagram_id: str,
        owner_id: str,
        collaborators: List[Collaborator],
    ) -> Dict[str, Any]:
        names = {
            "#id": "id",
            "#updated": "updatedAt",
            "#collaborators": "collaborators",
        }
        values: Dict[str, Any] = {
            ":collaborators": convert_floats_to_decimal(
                [item.model_dump(mode="json") for item in collaborators]
            ),
            DDB_UPDATED_VALUE: datetime.now(timezone.utc).isoformat(),
        }
        condition = "attribute_exists(#id)"
        if diagram.updatedAt:
            condition += " AND #updated = :old_updated"
            values[":old_updated"] = diagram.updatedAt
        else:
            condition += " AND attribute_not_exists(#updated)"
        return {
            "TableName": self.diagrams_table.name,
            "Key": self._serialize_item({"userId": owner_id, "id": diagram_id}),
            "UpdateExpression": (
                f"SET #collaborators = :collaborators, #updated = {DDB_UPDATED_VALUE}"
            ),
            "ConditionExpression": condition,
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": self._serialize_item(values),
        }

    def _collaborator_membership_operation(
        self,
        diagram_id: str,
        owner_id: str,
        collaborator_user_id: str,
        collaborator: Optional[Collaborator],
        existing: Optional[Collaborator],
    ) -> Dict[str, Any]:
        share = collaborator or existing
        if share is not None:
            return {
                "Put": {
                    "TableName": self.diagram_shares_table.name,
                    "Item": self._serialize_item(
                        self._diagram_share_item(diagram_id, owner_id, share)
                    ),
                }
            }
        return {
            "Delete": {
                "TableName": self.diagram_shares_table.name,
                "Key": self._serialize_item(
                    {
                        "collaboratorUserId": collaborator_user_id,
                        "diagramId": diagram_id,
                    }
                ),
            }
        }

    def _persist_collaborator_change(
        self,
        diagram_id: str,
        owner_id: str,
        collaborator_user_id: str,
        collaborator: Optional[Collaborator],
    ) -> bool:
        """Atomically update the legacy diagram snapshot and indexed membership."""
        try:
            for _ in range(3):
                diagram = self.get_diagram(owner_id, diagram_id, consistent_read=True)
                if not diagram:
                    return False
                collaborators, existing = self._collaborators_after_change(
                    diagram, collaborator_user_id, collaborator
                )
                update_request = self._collaborator_update_request(
                    diagram, diagram_id, owner_id, collaborators
                )
                membership_operation = self._collaborator_membership_operation(
                    diagram_id,
                    owner_id,
                    collaborator_user_id,
                    collaborator,
                    existing,
                )
                transaction = [
                    {"Update": update_request},
                    membership_operation,
                ]

                try:
                    self.diagrams_table.meta.client.transact_write_items(
                        TransactItems=transaction
                    )
                    return True
                except ClientError as error:
                    if error.response.get("Error", {}).get("Code") != "TransactionCanceledException":
                        raise
            return False
        except ClientError:
            return False

    def share_diagram(
        self, diagram_id: str, owner_id: str, collaborator: Collaborator
    ) -> bool:
        """Share a diagram and atomically maintain its indexed membership row."""
        return self._persist_collaborator_change(
            diagram_id, owner_id, collaborator.userId, collaborator
        )

    def remove_collaborator(
        self, diagram_id: str, owner_id: str, collaborator_user_id: str
    ) -> bool:
        """Remove a collaborator and their indexed membership atomically."""
        return self._persist_collaborator_change(
            diagram_id, owner_id, collaborator_user_id, None
        )

    def update_collaborator_permission(
        self,
        diagram_id: str,
        owner_id: str,
        collaborator_user_id: str,
        permission: Permission,
    ) -> bool:
        """Update permission in the diagram snapshot and membership item."""
        try:
            diagram = self.get_diagram(owner_id, diagram_id, consistent_read=True)
            if not diagram:
                return False
            collaborator = next(
                (item for item in diagram.collaborators if item.userId == collaborator_user_id),
                None,
            )
            if collaborator is None:
                return False
            updated = collaborator.model_copy(update={"permission": permission})
            return self._persist_collaborator_change(
                diagram_id, owner_id, collaborator_user_id, updated
            )
        except ClientError:
            return False

    def get_diagram_collaborators(
        self, diagram_id: str, owner_id: str
    ) -> List[Collaborator]:
        """Return collaborators from the strongly consistent diagram snapshot."""
        try:
            diagram = self.get_diagram(owner_id, diagram_id, consistent_read=True)
            return diagram.collaborators if diagram else []
        except ClientError:
            return []

    def check_collaborator_permission(
        self, diagram_id: str, user_id: str
    ) -> Optional[Permission]:
        """Check shared access with a strongly consistent membership read."""
        share = self._get_diagram_share(diagram_id, user_id)
        if not share:
            return None
        try:
            return Permission(share["permission"])
        except (KeyError, ValueError):
            return None

    def get_diagram_for_user(
        self, user_id: str, diagram_id: str
    ) -> tuple[Optional[Diagram], Optional[Permission]]:
        """Resolve an owned or shared diagram without scanning or loading a shared list."""
        try:
            diagram = self.get_diagram(user_id, diagram_id, consistent_read=True)
            if diagram:
                return diagram, Permission.EDIT

            share = self._get_diagram_share(diagram_id, user_id)
            if not share:
                return None, None
            owner_id = str(share.get("ownerId", ""))
            if not owner_id:
                return None, None
            diagram = self.get_diagram(owner_id, diagram_id)
            if not diagram:
                return None, None
            return diagram, Permission(str(share["permission"]))
        except (ClientError, KeyError, ValueError):
            return None, None

    def _shared_memberships(self, user_id: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        query: Dict[str, Any] = {
            "KeyConditionExpression": Key("collaboratorUserId").eq(user_id),
        }
        response = self.diagram_shares_table.query(**query)
        items.extend(response.get("Items", []))
        last_evaluated_key = response.get("LastEvaluatedKey")
        while last_evaluated_key:
            response = self.diagram_shares_table.query(
                **query, ExclusiveStartKey=last_evaluated_key
            )
            items.extend(response.get("Items", []))
            last_evaluated_key = response.get("LastEvaluatedKey")
        return items

    def _load_shared_diagrams(
        self,
        memberships: List[Dict[str, Any]],
        summary_only: bool = False,
    ) -> List[Diagram]:
        keys = [
            {"userId": item["ownerId"], "id": item["diagramId"]}
            for item in memberships
            if item.get("ownerId") and item.get("diagramId")
        ]
        items = self._batch_get_items(
            self.diagrams_table,
            keys,
            DIAGRAM_SUMMARY_PROJECTION if summary_only else None,
            DIAGRAM_SUMMARY_NAMES if summary_only else None,
        )
        by_key = {(str(item.get("userId")), str(item.get("id"))): item for item in items}
        diagrams: List[Diagram] = []
        for membership in memberships:
            item = by_key.get((str(membership.get("ownerId")), str(membership.get("diagramId"))))
            if not item:
                continue
            diagram = Diagram(**convert_decimal_to_float(item))
            if summary_only:
                diagram.collaborators = [
                    Collaborator(
                        userId=str(membership["collaboratorUserId"]),
                        email=membership.get("email", ""),
                        name=membership.get("name", ""),
                        picture=membership.get("picture"),
                        permission=Permission(str(membership["permission"])),
                        addedAt=membership.get("addedAt", ""),
                    )
                ]
            diagrams.append(diagram)
        return diagrams

    def get_shared_diagrams_for_user(self, user_id: str) -> List[Diagram]:
        """Load full shared diagrams using membership queries and batched item reads."""
        try:
            return self._load_shared_diagrams(self._shared_memberships(user_id))
        except (ClientError, RuntimeError):
            return []

    # Problem operations
    def get_all_problems(self) -> List[Dict[str, Any]]:
        """Get all problems from DynamoDB."""
        try:
            items: List[Dict[str, Any]] = []
            response = self.problems_table.scan()
            items.extend(response.get("Items", []))

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.problems_table.scan(
                    ExclusiveStartKey=response["LastEvaluatedKey"]
                )
                items.extend(response.get("Items", []))

            return items
        except ClientError:
            return []

    def get_shared_diagram_summaries_for_user(self, user_id: str) -> List[Diagram]:
        """Get shared diagram metadata without loading canvas arrays."""
        try:
            return self._load_shared_diagrams(
                self._shared_memberships(user_id), summary_only=True
            )
        except (ClientError, RuntimeError):
            return []

    def get_shared_diagram_summary_page_for_user(
        self,
        user_id: str,
        limit: int,
        exclusive_start_key: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[Diagram], Optional[Dict[str, Any]]]:
        """Query one indexed page of shared membership and batch-load summaries."""
        try:
            query: Dict[str, Any] = {
                "KeyConditionExpression": Key("collaboratorUserId").eq(user_id),
                "Limit": limit,
            }
            if exclusive_start_key:
                query["ExclusiveStartKey"] = exclusive_start_key
            response = self.diagram_shares_table.query(**query)
            memberships = response.get("Items", [])
            diagrams = self._load_shared_diagrams(memberships, summary_only=True)
            return diagrams, response.get("LastEvaluatedKey")
        except (ClientError, RuntimeError) as e:
            print(f"Error querying shared diagram summary page: {e}")
            return [], None

    def check_problems_table(self) -> None:
        """Perform one inexpensive data-plane read and let DynamoDB errors surface."""
        self.problems_table.get_item(
            Key={"id": "__health_probe__"},
            ProjectionExpression="#id",
            ExpressionAttributeNames={"#id": "id"},
        )

    def get_problems_page(
        self,
        limit: int,
        exclusive_start_key: Optional[Dict[str, Any]] = None,
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
    ) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Get one page of problem summaries and DynamoDB's continuation key."""
        try:
            scan_params: Dict[str, Any] = {"Limit": limit}
            if exclusive_start_key:
                scan_params["ExclusiveStartKey"] = exclusive_start_key

            filters = []
            if category:
                filters.append(Attr("category").eq(category))
            if difficulty:
                filters.append(Attr("difficulty").eq(difficulty))
            if filters:
                filter_expression = filters[0]
                for current_filter in filters[1:]:
                    filter_expression = filter_expression & current_filter
                scan_params["FilterExpression"] = filter_expression

            response = self.problems_table.scan(**scan_params)
            return response.get("Items", []), response.get("LastEvaluatedKey")
        except ClientError:
            return [], None

    def count_problems(
        self,
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
    ) -> Optional[int]:
        """Count all matching problems without loading their attributes."""
        try:
            scan_params: Dict[str, Any] = {"Select": "COUNT"}
            filters = []
            if category:
                filters.append(Attr("category").eq(category))
            if difficulty:
                filters.append(Attr("difficulty").eq(difficulty))
            if filters:
                filter_expression = filters[0]
                for current_filter in filters[1:]:
                    filter_expression = filter_expression & current_filter
                scan_params["FilterExpression"] = filter_expression

            total = 0
            while True:
                response = self.problems_table.scan(**scan_params)
                total += int(response.get("Count") or 0)
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    return total
                scan_params["ExclusiveStartKey"] = last_key
        except ClientError:
            return None

    def get_problem_by_id(self, problem_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific problem by ID."""
        try:
            response = self.problems_table.get_item(Key={"id": problem_id})
            return response.get("Item")
        except ClientError:
            return None

    def get_problem_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Get a problem by its public slug."""
        response = self.problems_table.query(
            IndexName="slug-index",
            KeyConditionExpression=Key("slug").eq(slug),
            Limit=2,
        )
        items = response.get("Items", [])
        if len(items) > 1:
            raise RuntimeError(f"Multiple problems use the slug '{slug}'")
        return items[0] if items else None

    def get_problems_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get problems by category using GSI."""
        try:
            items: List[Dict[str, Any]] = []
            response = self.problems_table.query(
                IndexName="category-index",
                KeyConditionExpression=Key("category").eq(category),
            )
            items.extend(response.get("Items", []))

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.problems_table.query(
                    IndexName="category-index",
                    KeyConditionExpression=Key("category").eq(category),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            return items
        except ClientError:
            return []

    def get_problems_by_difficulty(self, difficulty: str) -> List[Dict[str, Any]]:
        """Get problems by difficulty using GSI."""
        try:
            items: List[Dict[str, Any]] = []
            response = self.problems_table.query(
                IndexName="difficulty-index",
                KeyConditionExpression=Key("difficulty").eq(difficulty),
            )
            items.extend(response.get("Items", []))

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.problems_table.query(
                    IndexName="difficulty-index",
                    KeyConditionExpression=Key("difficulty").eq(difficulty),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            return items
        except ClientError:
            return []

    # Problem attempt operations
    @staticmethod
    def _normalize_attempt_assessment(
        assessment: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Retain review content while making score/provenance semantics explicit."""
        if not assessment:
            return None
        normalized = dict(assessment)
        for camel, snake in (
            ("score", "overall_score"),
            ("assessmentId", "assessment_id"),
            ("scoreAvailable", "score_available"),
            ("rubricVersion", "rubric_version"),
            ("requirementRevision", "requirement_revision"),
            ("modelVersion", "model_version"),
            ("inputFingerprint", "input_fingerprint"),
        ):
            if camel not in normalized and snake in normalized:
                normalized[camel] = normalized[snake]

        score = normalized.get("score")
        valid_score = (
            isinstance(score, (int, float, Decimal))
            and not isinstance(score, bool)
            and (not isinstance(score, Decimal) or score.is_finite())
            and 0 <= score <= 100
            and score == int(score)
        )
        source = normalized.get("source")
        # Old AI results omitted source, but carried substantive review content.
        # A bare number is not sufficient evidence of a completed AI review.
        legacy_review = source in (None, "") and any(
            normalized.get(field)
            for field in (
                "findings", "feedback", "scores", "summary",
                "detailedAnalysis", "detailed_analysis",
            )
        )
        available = (
            valid_score
            and (source == "ai" or legacy_review)
            and normalized.get("scoreAvailable", True) is True
            and normalized.get("score_available", True) is True
            and normalized.get("verdict") != "unavailable"
        )
        normalized["scoreAvailable"] = bool(available)
        normalized["score"] = int(score) if available and score is not None else None
        if "score_available" in normalized:
            normalized["score_available"] = normalized["scoreAvailable"]
        if "overall_score" in normalized:
            normalized["overall_score"] = normalized["score"]
        return normalized

    @staticmethod
    def _prepare_attempt_state(
        existing_attempt: Optional[AttemptResponse],
        last_assessment: Optional[Dict[str, Any]],
        reasoning_context: Optional[Dict[str, Any]],
        interview_session: Optional[Dict[str, Any]],
        addressed_finding_ids: Optional[List[str]],
        last_assessment_check: Optional[Dict[str, Any]] = None,
    ) -> PreparedAttemptState:
        existing_data = (
            existing_attempt.model_dump() if existing_attempt is not None else {}
        )
        assessment_count = existing_attempt.assessmentCount if existing_attempt else 0
        preserved_assessment = cast(
            Optional[Dict[str, Any]], existing_data.get("lastAssessment")
        )
        preserved_reasoning_context = DynamoDBService._preserve_attempt_context(
            reasoning_context, existing_data.get("reasoningContext")
        )
        preserved_interview_session = DynamoDBService._preserve_attempt_context(
            interview_session, existing_data.get("interviewSession")
        )

        incoming_assessment = DynamoDBService._normalize_attempt_assessment(
            last_assessment
        )
        incoming_check = DynamoDBService._normalize_attempt_assessment(
            last_assessment_check
        )
        preserved_check = cast(
            Optional[Dict[str, Any]], existing_data.get("lastAssessmentCheck")
        )
        assessment_count, preserved_assessment, preserved_check, new_reviews = (
            DynamoDBService._merge_attempt_reviews(
                assessment_count,
                preserved_assessment,
                preserved_check,
                incoming_assessment,
                incoming_check,
            )
        )

        preserved_addressed_finding_ids = list(
            addressed_finding_ids
            if addressed_finding_ids is not None
            else existing_data.get("addressedFindingIds", [])
        )
        assessment_history = list(existing_data.get("assessmentHistory", []))[-10:]
        assessment_history = DynamoDBService._append_attempt_history(
            assessment_history, new_reviews, preserved_addressed_finding_ids
        )
        return PreparedAttemptState(
            assessment_count=assessment_count,
            preserved_assessment=preserved_assessment,
            preserved_reasoning_context=preserved_reasoning_context,
            preserved_interview_session=preserved_interview_session,
            existing_data=existing_data,
            assessment_history=assessment_history,
            addressed_finding_ids=preserved_addressed_finding_ids,
            preserved_check=preserved_check,
        )

    @staticmethod
    def _preserve_attempt_context(
        incoming: Optional[Dict[str, Any]], existing: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        return convert_floats_to_decimal(incoming) if incoming is not None else existing

    @staticmethod
    def _merge_attempt_reviews(
        assessment_count: int,
        preserved_assessment: Optional[Dict[str, Any]],
        preserved_check: Optional[Dict[str, Any]],
        incoming_assessment: Optional[Dict[str, Any]],
        incoming_check: Optional[Dict[str, Any]],
    ) -> tuple[int, Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        previous_assessment = DynamoDBService._normalize_attempt_assessment(
            preserved_assessment
        )
        original_check = DynamoDBService._normalize_attempt_assessment(preserved_check)
        new_reviews: List[Dict[str, Any]] = []
        for review in (incoming_assessment, incoming_check):
            if review is None:
                continue
            if review.get("scoreAvailable"):
                if review != previous_assessment:
                    assessment_count += 1
                    new_reviews.append(review)
                    preserved_check = review
                elif preserved_check is None:
                    preserved_check = review
                preserved_assessment = review
                previous_assessment = review
            else:
                if review != original_check and review not in new_reviews:
                    new_reviews.append(review)
                preserved_check = review
        return assessment_count, preserved_assessment, preserved_check, new_reviews

    @staticmethod
    def _append_attempt_history(
        history: List[Dict[str, Any]],
        new_reviews: List[Dict[str, Any]],
        addressed_finding_ids: List[str],
    ) -> List[Dict[str, Any]]:
        for review in new_reviews:
            history.append(
                {
                    "id": str(review.get("assessmentId") or uuid4()),
                    "score": review["score"],
                    "scoreAvailable": review["scoreAvailable"],
                    "findingCount": len(review.get("findings", []) or review.get("feedback", []) or []),
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "source": review.get("source"),
                    "addressedFindingIds": addressed_finding_ids,
                    **{
                        field: review.get(field)
                        for field in (
                            "rubricVersion", "requirementRevision",
                            "modelVersion", "inputFingerprint",
                        )
                    },
                }
            )
            history = history[-10:]
        return history

    def _resolve_attempt_requirement_spec(
        self,
        problem_id: str,
        existing_attempt: Optional[AttemptResponse],
        supplied_spec: Optional[Dict[str, Any]],
        assessment: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Pin known approved context without upgrading historical attempts."""
        if existing_attempt and existing_attempt.problemRequirementSpec:
            return existing_attempt.problemRequirementSpec.model_dump()
        review = self._normalize_attempt_assessment(assessment)
        if existing_attempt and (review is None or not review.get("scoreAvailable") or not review.get("requirementRevision")):
            # New readers can send today's specification during autosave. That
            # alone must never relabel a legacy attempt or its old review.
            return None

        problem = self.get_problem_by_id(problem_id)
        if not problem or not problem.get("requirementSpec"):
            # Local/custom problems remain usable, but client content must not
            # masquerade as a server-approved catalog snapshot.
            return None
        approved = RequirementSpec.model_validate(
            convert_decimal_to_float(problem["requirementSpec"])
        )
        if supplied_spec is not None:
            supplied = RequirementSpec.model_validate(supplied_spec)
            if supplied.revision != approved.revision:
                raise ValueError("Problem requirement revision is not available")
        if review and review.get("requirementRevision") not in (None, approved.revision):
            # Never attach today's brief to an assessment of an older brief.
            return None
        return approved.model_dump()

    @staticmethod
    def _build_attempt_item(state: AttemptSaveState) -> Dict[str, Any]:
        request = state.request
        prepared = state.prepared
        item: Dict[str, Any] = {
            "userId": state.user_id,
            "problemId": request.problemId,
            "title": request.title,
            "difficulty": request.difficulty or "Medium",
            "category": request.category or "General",
            "nodes": convert_floats_to_decimal(request.nodes),
            "edges": convert_floats_to_decimal(request.edges),
            "elapsedTime": request.elapsedTime,
            "lastAssessment": prepared.preserved_assessment,
            "lastAssessmentCheck": prepared.preserved_check,
            "reasoningContext": prepared.preserved_reasoning_context,
            "interviewSession": prepared.preserved_interview_session,
            "assessmentCount": prepared.assessment_count,
            "assessmentHistory": convert_floats_to_decimal(prepared.assessment_history),
            "addressedFindingIds": prepared.addressed_finding_ids,
            "updatedAt": state.updated_at,
            "lastAttemptedAt": state.updated_at,
        }
        if state.problem_requirement_spec is not None:
            item["problemRequirementSpec"] = state.problem_requirement_spec

        if state.existing_attempt is None:
            item["createdAt"] = state.updated_at
        else:
            item["createdAt"] = state.existing_attempt.createdAt

        if state.existing_attempt and state.existing_attempt.isPublic:
            assessment = DynamoDBService._qualifying_attempt_assessment(
                {
                    "lastAssessment": prepared.preserved_assessment,
                    "lastAssessmentCheck": prepared.preserved_check,
                }
            )
            if assessment:
                item["leaderboardProblemId"] = request.problemId
                item["leaderboardScore"] = assessment["score"]

        return item

    @staticmethod
    def _build_attempt_response(
        state: AttemptSaveState, item: Dict[str, Any]
    ) -> AttemptResponse:
        request = state.request
        prepared = state.prepared
        reasoning_context = (
            request.reasoningContext.model_dump(exclude_none=True)
            if request.reasoningContext
            else prepared.existing_data.get("reasoningContext")
        )
        interview_session = (
            request.interviewSession.model_dump(exclude_none=True)
            if request.interviewSession
            else prepared.existing_data.get("interviewSession")
        )
        return AttemptResponse.model_validate(
            {
                "id": f"{state.user_id}#{request.problemId}",
                "userId": state.user_id,
                "problemId": request.problemId,
                "title": request.title,
                "difficulty": request.difficulty or "Medium",
                "category": request.category or "General",
                "nodes": request.nodes,
                "edges": request.edges,
                "elapsedTime": request.elapsedTime,
                "lastAssessment": convert_decimal_to_float(prepared.preserved_assessment),
                "lastAssessmentCheck": prepared.preserved_check,
                "problemRequirementSpec": state.problem_requirement_spec,
                "reasoningContext": reasoning_context,
                "interviewSession": interview_session,
                "assessmentCount": prepared.assessment_count,
                "assessmentHistory": prepared.assessment_history,
                "addressedFindingIds": prepared.addressed_finding_ids,
                "createdAt": item["createdAt"],
                "updatedAt": state.updated_at,
                "lastAttemptedAt": state.updated_at,
                "isPublic": state.existing_attempt.isPublic if state.existing_attempt else False,
                "publishedAt": state.existing_attempt.publishedAt if state.existing_attempt else None,
                "authorName": state.existing_attempt.authorName if state.existing_attempt else None,
                "authorPicture": state.existing_attempt.authorPicture if state.existing_attempt else None,
                "viewCount": state.existing_attempt.viewCount if state.existing_attempt else 0,
            }
        )

    @staticmethod
    def _attempt_update_condition(
        existing_attempt: Optional[AttemptResponse],
        names: Dict[str, str],
        values: Dict[str, Any],
    ) -> str:
        names["#condition_user"] = "userId"
        if existing_attempt is None:
            return "attribute_not_exists(#condition_user)"

        condition_parts = ["attribute_exists(#condition_user)"]
        names["#condition_updated"] = "updatedAt"
        if existing_attempt.updatedAt is None:
            condition_parts.append("attribute_not_exists(#condition_updated)")
        else:
            condition_parts.append("#condition_updated = :expected_updated")
            values[":expected_updated"] = existing_attempt.updatedAt

        names["#condition_public"] = "isPublic"
        values[":expected_public"] = existing_attempt.isPublic
        if existing_attempt.isPublic:
            condition_parts.append("#condition_public = :expected_public")
        else:
            condition_parts.append(
                "(attribute_not_exists(#condition_public) "
                "OR #condition_public = :expected_public)"
            )
        return " AND ".join(condition_parts)

    @staticmethod
    def _attempt_update_fields(
        item: Dict[str, Any],
    ) -> tuple[Dict[str, str], Dict[str, Any], str]:
        attributes = {
            key: value for key, value in item.items()
            if key not in ("userId", "problemId")
        }
        names = {f"#a{i}": key for i, key in enumerate(attributes)}
        values = {
            f":a{i}": convert_floats_to_decimal(value)
            for i, value in enumerate(attributes.values())
        }
        updates = []
        for i, key in enumerate(attributes):
            value = f":a{i}"
            if key in ("createdAt", "problemRequirementSpec"):
                value = f"if_not_exists(#a{i}, :a{i})"
            updates.append(f"#a{i} = {value}")

        remove_attributes = [
            key
            for key in ("leaderboardProblemId", "leaderboardScore")
            if key not in attributes
        ]
        remove_expression = ""
        if remove_attributes:
            for index, key in enumerate(remove_attributes):
                names[f"#remove{index}"] = key
            remove_expression = " REMOVE " + ", ".join(
                f"#remove{index}" for index in range(len(remove_attributes))
            )
        return names, values, "SET " + ", ".join(updates) + remove_expression

    def _attempt_update_request(
        self,
        user_id: str,
        problem_id: str,
        item: Dict[str, Any],
        existing_attempt: Optional[AttemptResponse],
    ) -> Dict[str, Any]:
        names, values, update_expression = self._attempt_update_fields(item)
        condition = self._attempt_update_condition(existing_attempt, names, values)
        return {
            "Key": {"userId": user_id, "problemId": problem_id},
            "UpdateExpression": update_expression,
            "ConditionExpression": condition,
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
            "ReturnValues": "ALL_NEW",
        }

    def create_or_update_attempt(
        self,
        user_id: str,
        request: AttemptCreate,
        _conflict_retries: int = 0,
    ) -> AttemptResponse:
        """Create or update a problem attempt (upsert operation)."""
        problem_id = request.problemId
        try:
            existing_attempt = self.get_attempt_by_problem(
                user_id, problem_id, consistent_read=True
            )
            now = datetime.now(timezone.utc).isoformat()
            prepared = self._prepare_attempt_state(
                existing_attempt,
                request.lastAssessment,
                request.reasoningContext.model_dump(exclude_none=True) if request.reasoningContext else None,
                request.interviewSession.model_dump(exclude_none=True) if request.interviewSession else None,
                request.addressedFindingIds,
                request.lastAssessmentCheck,
            )
            pinned_spec = self._resolve_attempt_requirement_spec(
                problem_id,
                existing_attempt,
                request.problemRequirementSpec.model_dump() if request.problemRequirementSpec else None,
                request.lastAssessmentCheck or request.lastAssessment,
            )
            state = AttemptSaveState(
                user_id=user_id,
                request=request,
                existing_attempt=existing_attempt,
                prepared=prepared,
                updated_at=now,
                problem_requirement_spec=pinned_spec,
            )
            item = self._build_attempt_item(state)

            update_request = self._attempt_update_request(
                user_id, problem_id, item, existing_attempt
            )
            try:
                saved = self.attempts_table.update_item(**update_request)
            except ClientError as error:
                is_conflict = (
                    error.response.get("Error", {}).get("Code")
                    == "ConditionalCheckFailedException"
                )
                if is_conflict and _conflict_retries < 2:
                    return self.create_or_update_attempt(
                        user_id=user_id,
                        request=request,
                        _conflict_retries=_conflict_retries + 1,
                    )
                raise
            if saved.get("Attributes"):
                saved_item = convert_decimal_to_float(saved["Attributes"])
                saved_item["id"] = f"{user_id}#{problem_id}"
                return AttemptResponse(**saved_item)
            return self._build_attempt_response(state, item)
        except ClientError as e:
            print(f"Error creating/updating attempt: {e}")
            raise

    def get_attempt_by_problem(
        self, user_id: str, problem_id: str, consistent_read: bool = False
    ) -> Optional[AttemptResponse]:
        """Get a user's attempt for a specific problem using direct key lookup."""
        try:
            response = self.attempts_table.get_item(
                Key={"userId": user_id, "problemId": problem_id},
                ConsistentRead=consistent_read,
            )

            item = response.get("Item")
            if item:
                item_float: Dict[str, Any] = convert_decimal_to_float(item)
                # Add composite ID for frontend compatibility
                item_float["id"] = f"{user_id}#{problem_id}"
                result = AttemptResponse(**item_float)
                return result

            return None
        except ClientError as e:
            print(f"Error getting attempt: {e}")
            return None

    def get_user_attempts(self, user_id: str) -> List[AttemptResponse]:
        """Get all attempts for a user using partition key query."""
        try:
            items: List[Dict[str, Any]] = []
            response = self.attempts_table.query(
                KeyConditionExpression=Key("userId").eq(user_id)
            )
            response_items = response.get("Items", [])
            items.extend(response_items)

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.attempts_table.query(
                    KeyConditionExpression=Key("userId").eq(user_id),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                response_items = response.get("Items", [])
                items.extend(response_items)

            # Convert Decimal back to float and add composite ID for frontend compatibility
            items_float = [convert_decimal_to_float(item) for item in items]
            for item in items_float:
                item["id"] = f"{item['userId']}#{item['problemId']}"
            return [AttemptResponse(**item) for item in items_float]
        except ClientError as e:
            print(f"Error querying attempts: {e}")
            return []

    def delete_attempt(self, user_id: str, problem_id: str) -> bool:
        """Delete a problem attempt using composite key."""
        try:
            self.attempts_table.delete_item(
                Key={"userId": user_id, "problemId": problem_id}
            )
            return True
        except ClientError:
            return False

    def _query_simulation_run_items(self, user_id: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        start_key = None
        while True:
            query_args: Dict[str, Any] = {
                "KeyConditionExpression": Key("userId").eq(user_id),
                "ConsistentRead": True,
                # Ask for one more than the supported maximum so an actually
                # overfull partition is detected even when DynamoDB paginates
                # responses at its 1 MiB response-size boundary.
                "Limit": 51 - len(items),
            }
            if start_key is not None:
                query_args["ExclusiveStartKey"] = start_key
            response = self.simulation_runs_table.query(**query_args)
            items.extend(response.get("Items", []))
            if len(items) > 50:
                raise RuntimeError("Simulation run storage exceeded the per-user bound")
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
        return [convert_decimal_to_float(item) for item in items]

    def get_simulation_runs(self, user_id: str, problem_id: str) -> List[Dict[str, Any]]:
        """Return only unexpired saved runs owned by this user for this exercise."""
        now = int(time.time())
        return sorted(
            (
                item for item in self._query_simulation_run_items(user_id)
                if item.get("problemId") == problem_id
                and int(item.get("expiresAt", 0)) > now
            ),
            key=lambda item: item.get("createdAt", ""),
            reverse=True,
        )

    def save_simulation_run(
        self,
        user_id: str,
        problem_id: str,
        snapshot: Dict[str, Any],
        ttl_seconds: int = 90 * 24 * 60 * 60,
        max_runs_per_user: int = 50,
    ) -> Dict[str, Any]:
        """Save an immutable private snapshot in one of a user's bounded slots."""
        now = int(time.time())
        created_at = datetime.now(timezone.utc).isoformat()
        run_id = uuid4().hex
        for _ in range(5):
            items = self._query_simulation_run_items(user_id)
            active = [item for item in items if int(item.get("expiresAt", 0)) > now]
            if len(active) >= max_runs_per_user:
                raise SimulationRunLimitReached(
                    "Delete a saved run before saving another one."
                )
            by_slot = {str(item["runSlot"]): item for item in items}
            slot_indexes = range(max_runs_per_user)
            empty_slots = [f"{index:02d}" for index in slot_indexes if f"{index:02d}" not in by_slot]
            if empty_slots:
                slot_suffix = empty_slots[0]
            else:
                expired = [item for item in items if int(item.get("expiresAt", 0)) <= now]
                if not expired:
                    raise SimulationRunLimitReached(
                        "Delete a saved run before saving another one."
                    )
                oldest = min(expired, key=lambda item: item.get("createdAt", ""))
                slot_suffix = str(oldest["runSlot"])

            slot_key = slot_suffix
            existing = by_slot.get(slot_key)
            item = {
                "userId": user_id,
                "runSlot": slot_key,
                "runId": run_id,
                "problemId": problem_id,
                "createdAt": created_at,
                "expiresAt": now + ttl_seconds,
                "snapshot": snapshot,
            }
            condition = (
                Attr("runId").not_exists()
                if existing is None
                else Attr("runId").eq(existing["runId"])
            )
            try:
                self.simulation_runs_table.put_item(
                    Item=convert_floats_to_decimal(item),
                    ConditionExpression=condition,
                )
                return item
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                    continue
                raise
        raise RuntimeError("Could not reserve a saved simulation run slot")

    def delete_simulation_run(self, user_id: str, run_id: str) -> bool:
        """Delete a saved run only when its owning user matches the partition key."""
        for item in self._query_simulation_run_items(user_id):
            if item.get("runId") != run_id:
                continue
            try:
                self.simulation_runs_table.delete_item(
                    Key={"userId": user_id, "runSlot": item["runSlot"]},
                    ConditionExpression=Attr("runId").eq(run_id),
                )
                return True
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                    return False
                raise
        return False

    # ------------------------------------------------------------------
    # Public sharing
    # ------------------------------------------------------------------

    @classmethod
    def _qualifying_attempt_assessment(
        cls, item: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        assessment = cls._normalize_attempt_assessment(item.get("lastAssessment"))
        if not assessment or not assessment.get("scoreAvailable"):
            return None
        latest_check = cls._normalize_attempt_assessment(item.get("lastAssessmentCheck"))
        if latest_check and not latest_check.get("scoreAvailable"):
            # The retained review describes an earlier submission; an outage
            # must not qualify the newly saved design as AI reviewed.
            return None
        return assessment

    def publish_attempt(
        self,
        user_id: str,
        problem_id: str,
        author_name: str,
        author_picture: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark an attempt as public and stamp author metadata."""
        try:
            existing = self.get_attempt_by_problem(
                user_id, problem_id, consistent_read=True
            )
            if not existing:
                return None
            qualifying_assessment = self._qualifying_attempt_assessment(
                existing.model_dump()
            )
            if qualifying_assessment is None:
                raise ValueError("A scored AI assessment is required to publish this attempt")

            now = datetime.now(timezone.utc).isoformat()
            check_condition = "#check = :check"
            if existing.lastAssessmentCheck is None:
                check_condition = "(attribute_not_exists(#check) OR #check = :check)"

            self.attempts_table.update_item(
                Key={"userId": user_id, "problemId": problem_id},
                UpdateExpression=(
                    "SET isPublic = :pub, publishedAt = :ts, "
                    "authorName = :name, authorPicture = :pic, "
                    "viewCount = if_not_exists(viewCount, :zero), "
                    "leaderboardProblemId = :leaderboard_problem, "
                    "leaderboardScore = :leaderboard_score"
                ),
                ConditionExpression=(
                    "attribute_exists(userId) AND attribute_exists(problemId) "
                    "AND #assessment = :assessment AND " + check_condition
                ),
                ExpressionAttributeNames={
                    "#assessment": "lastAssessment", "#check": "lastAssessmentCheck",
                },
                ExpressionAttributeValues={
                    ":pub": True,
                    ":ts": now,
                    ":name": author_name,
                    ":pic": author_picture or "",
                    ":leaderboard_problem": problem_id,
                    ":leaderboard_score": convert_floats_to_decimal(
                        qualifying_assessment["score"]
                    ),
                    DDB_ZERO_VALUE: 0,
                    ":assessment": convert_floats_to_decimal(existing.lastAssessment),
                    ":check": convert_floats_to_decimal(existing.lastAssessmentCheck),
                },
            )
            return {"publishedAt": now}
        except ClientError as e:
            print(f"Error publishing attempt: {e}")
            return None

    def unpublish_attempt(self, user_id: str, problem_id: str) -> bool:
        """Remove public visibility from an attempt."""
        try:
            self.attempts_table.update_item(
                Key={"userId": user_id, "problemId": problem_id},
                UpdateExpression=(
                    "SET isPublic = :f REMOVE leaderboardProblemId, leaderboardScore"
                ),
                ExpressionAttributeValues={":f": False},
            )
            return True
        except ClientError as e:
            print(f"Error unpublishing attempt: {e}")
            return False

    def get_public_solution(
        self, user_id: str, problem_id: str
    ) -> Optional[PublicSolutionResponse]:
        """Fetch a public solution and increment its view count atomically."""
        try:
            # Increment view count and return the updated item
            response = self.attempts_table.update_item(
                Key={"userId": user_id, "problemId": problem_id},
                UpdateExpression="ADD viewCount :inc",
                ConditionExpression="isPublic = :t",
                ExpressionAttributeValues={":inc": 1, ":t": True},
                ReturnValues="ALL_NEW",
            )
            item = response.get("Attributes")
            if not item:
                return None

            item_float: Dict[str, Any] = convert_decimal_to_float(item)
            attempt_id = f"{user_id}#{problem_id}"

            assessment = self._normalize_attempt_assessment(item_float.get("lastAssessment"))

            return PublicSolutionResponse(
                id=attempt_id,
                problemId=problem_id,
                title=item_float.get("title", ""),
                difficulty=item_float.get("difficulty"),
                category=item_float.get("category"),
                nodes=item_float.get("nodes", []),
                edges=item_float.get("edges", []),
                lastAssessment=assessment,
                lastAssessmentCheck=self._normalize_attempt_assessment(
                    item_float.get("lastAssessmentCheck")
                ),
                problemRequirementSpec=item_float.get("problemRequirementSpec"),
                authorName=item_float.get("authorName"),
                authorPicture=item_float.get("authorPicture"),
                publishedAt=item_float.get("publishedAt"),
                viewCount=int(item_float.get("viewCount", 0)),
                elapsedTime=int(item_float.get("elapsedTime", 0)),
            )
        except ClientError as e:
            # ConditionExpression failed → not public
            print(f"get_public_solution error (may not be public): {e}")
            return None

    def get_problem_leaderboard(
        self, problem_id: str, limit: int = 10
    ) -> List[LeaderboardEntry]:
        """Query indexed public solutions for a problem in score order."""
        try:
            entries: List[LeaderboardEntry] = []
            query: Dict[str, Any] = {
                "IndexName": "leaderboard-index",
                "KeyConditionExpression": Key("leaderboardProblemId").eq(problem_id),
                "ScanIndexForward": False,
                "Limit": max(1, min(limit, 100)),
            }
            while len(entries) < max(limit, 1):
                response = self.attempts_table.query(**query)
                for item in response.get("Items", []):
                    item_float = convert_decimal_to_float(item)
                    assessment = self._qualifying_attempt_assessment(item_float)
                    if assessment is None or not item_float.get("isPublic"):
                        continue
                    uid = item_float.get("userId", "")
                    pid = item_float.get("problemId", "")
                    entries.append(
                        LeaderboardEntry(
                            attemptId=f"{uid}#{pid}",
                            authorName=item_float.get("authorName"),
                            authorPicture=item_float.get("authorPicture"),
                            score=assessment["score"],
                            publishedAt=item_float.get("publishedAt"),
                            elapsedTime=int(item_float.get("elapsedTime", 0)),
                        )
                    )
                    if len(entries) >= limit:
                        break

                last_key = response.get("LastEvaluatedKey")
                if not last_key or len(entries) >= limit:
                    break
                query["ExclusiveStartKey"] = last_key
            return entries[:limit]
        except ClientError as e:
            print(f"Error fetching leaderboard: {e}")
            return []


    # ------------------------------------------------------------------
    # Free diagram publish / unpublish / public view
    # ------------------------------------------------------------------

    def publish_diagram(
        self,
        user_id: str,
        diagram_id: str,
        author_name: str,
        author_picture: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Publish an immutable snapshot of a free-design diagram."""
        try:
            diagram = self.get_diagram(user_id, diagram_id)
            if not diagram:
                return None

            # Multi-canvas graph data is canonical on canvas records. Publishing
            # continues to expose the primary canvas through the legacy snapshot.
            canvas_query: Dict[str, Any] = {
                "KeyConditionExpression": Key("userId").eq(user_id)
                & Key("id").begins_with(f"{diagram_id}#canvas#")
            }
            canvas_items: List[Dict[str, Any]] = []
            while True:
                canvas_response = self.diagrams_table.query(**canvas_query)
                canvas_items.extend(canvas_response.get("Items", []))
                last_key = canvas_response.get("LastEvaluatedKey")
                if not last_key:
                    break
                canvas_query["ExclusiveStartKey"] = last_key
            active_canvases = [
                item
                for item in canvas_items
                if item.get("recordType") == CANVAS_RECORD_TYPE
                and not item.get("deletedAt")
            ]
            if active_canvases:
                primary_item = min(
                    active_canvases, key=lambda item: int(item.get("order", 0))
                )
                primary_graph = convert_decimal_to_float(primary_item)
                diagram = diagram.model_copy(
                    update={
                        "nodes": primary_graph.get("nodes", []),
                        "edges": primary_graph.get("edges", []),
                        "nodeCount": len(primary_graph.get("nodes", [])),
                        "edgeCount": len(primary_graph.get("edges", [])),
                    }
                )

            now = datetime.now(timezone.utc).isoformat()
            snapshot_id = diagram.publicSnapshotId or str(uuid4())
            previous_snapshot = self.get_diagram(user_id, snapshot_id)
            family_id = diagram.familyId or diagram.id
            snapshot_item: Dict[str, Any] = {
                "id": snapshot_id,
                "userId": user_id,
                "title": diagram.title,
                "description": diagram.description,
                "nodes": convert_floats_to_decimal(diagram.nodes),
                "edges": convert_floats_to_decimal(diagram.edges),
                "nodeCount": diagram.nodeCount,
                "edgeCount": diagram.edgeCount,
                "reasoningContext": convert_floats_to_decimal(
                    diagram.reasoningContext
                )
                if diagram.reasoningContext is not None
                else None,
                "createdAt": previous_snapshot.createdAt if previous_snapshot else now,
                "updatedAt": now,
                "isPublic": True,
                "publishedAt": now,
                "viewCount": previous_snapshot.viewCount if previous_snapshot else 0,
                "collaborators": [],
                "recordType": "public_snapshot",
                "familyId": family_id,
                "sourceDiagramId": diagram.id,
                "authorName": author_name,
                "authorPicture": author_picture or "",
            }
            self.diagrams_table.put_item(Item=snapshot_item)
            self.diagrams_table.update_item(
                Key={"userId": user_id, "id": diagram_id},
                UpdateExpression=(
                    "SET isPublic = :pub, publishedAt = :ts, "
                    "publicSnapshotId = :snapshot, familyId = :family, "
                    "viewCount = :views"
                ),
                ExpressionAttributeValues={
                    ":pub": True,
                    ":ts": now,
                    ":snapshot": snapshot_id,
                    ":family": family_id,
                    ":views": snapshot_item["viewCount"],
                },
            )
            return {"publishedAt": now, "diagramId": snapshot_id}
        except ClientError as e:
            print(f"Error publishing diagram: {e}")
            return None

    def unpublish_diagram(self, user_id: str, diagram_id: str) -> bool:
        """Remove public visibility from a free-design diagram."""
        try:
            diagram = self.get_diagram(user_id, diagram_id)
            if not diagram:
                return False
            source_id = (
                diagram.sourceDiagramId
                if diagram.recordType == "public_snapshot" and diagram.sourceDiagramId
                else diagram.id
            )
            snapshot_id = (
                diagram.id
                if diagram.recordType == "public_snapshot"
                else diagram.publicSnapshotId
            )
            self.diagrams_table.update_item(
                Key={"userId": user_id, "id": source_id},
                UpdateExpression="SET isPublic = :f",
                ExpressionAttributeValues={":f": False},
            )
            if snapshot_id and snapshot_id != source_id:
                self.diagrams_table.update_item(
                    Key={"userId": user_id, "id": snapshot_id},
                    UpdateExpression="SET isPublic = :f",
                    ExpressionAttributeValues={":f": False},
                )
            return True
        except ClientError as e:
            print(f"Error unpublishing diagram: {e}")
            return False

    def get_public_diagram(self, diagram_id: str) -> Optional[PublicDiagramResponse]:
        """Scan for a public diagram by id and increment its view count."""
        try:
            # Scan for the diagram with matching id and isPublic = true
            response = self.diagrams_table.scan(
                FilterExpression="id = :did AND isPublic = :t",
                ExpressionAttributeValues={":did": diagram_id, ":t": True},
            )
            items = response.get("Items", [])

            # Handle pagination (small public dataset, so unlikely, but safe)
            while "LastEvaluatedKey" in response:
                response = self.diagrams_table.scan(
                    FilterExpression="id = :did AND isPublic = :t",
                    ExpressionAttributeValues={":did": diagram_id, ":t": True},
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            if not items:
                return None

            raw = convert_decimal_to_float(items[0])
            owner_user_id = raw.get("userId", "")

            # Keep old source URLs working after the source gains a snapshot.
            snapshot_id = raw.get("publicSnapshotId")
            if snapshot_id and raw.get("recordType") != "public_snapshot":
                snapshot_response = self.diagrams_table.get_item(
                    Key={"userId": owner_user_id, "id": snapshot_id}
                )
                snapshot_raw = snapshot_response.get("Item")
                if snapshot_raw and snapshot_raw.get("isPublic"):
                    raw = convert_decimal_to_float(snapshot_raw)
                    owner_user_id = raw.get("userId", owner_user_id)
                    diagram_id = raw.get("id", diagram_id)

            # Increment view count
            try:
                updated = self.diagrams_table.update_item(
                    Key={"userId": owner_user_id, "id": diagram_id},
                    UpdateExpression="ADD viewCount :inc",
                    ConditionExpression="isPublic = :t",
                    ExpressionAttributeValues={":inc": 1, ":t": True},
                    ReturnValues="ALL_NEW",
                )
                raw = convert_decimal_to_float(updated.get("Attributes", raw))
            except ClientError:
                pass  # view count increment is best-effort

            return PublicDiagramResponse(
                id=raw.get("id", diagram_id),
                title=raw.get("title", ""),
                description=raw.get("description"),
                nodes=raw.get("nodes", []),
                edges=raw.get("edges", []),
                canonicalDocument=raw.get("canonicalDocument"),
                authorName=raw.get("authorName"),
                authorPicture=raw.get("authorPicture"),
                publishedAt=raw.get("publishedAt"),
                viewCount=int(raw.get("viewCount", 0)),
                recordType=raw.get("recordType", "public_snapshot"),
                familyId=raw.get("familyId"),
                sourceDiagramId=raw.get("sourceDiagramId"),
            )
        except ClientError as e:
            print(f"get_public_diagram error: {e}")
            return None


    # Guided walkthrough operations

    def get_walkthrough_by_problem_id(
        self, problem_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a guided walkthrough by problem ID."""
        try:
            response = self.walkthroughs_table.get_item(Key={"problem_id": problem_id})
            item = response.get("Item")
            if item:
                return convert_decimal_to_float(item)
            return None
        except ClientError:
            return None


# Global DynamoDB service instance
dynamodb_service = DynamoDBService()
