"""DynamoDB service for managing users and diagrams."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, cast
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from mypy_boto3_dynamodb.service_resource import Table

from app.utils.config import get_settings
from app.models.auth_models import User
from app.models.diagram_models import Diagram, Collaborator, Permission, PublicDiagramResponse
from app.models.attempt_models import AttemptResponse, PublicSolutionResponse, LeaderboardEntry
from app.models.feedback_models import FeedbackCreate, FeedbackResponse

settings = get_settings()

DDB_ZERO_VALUE = ":zero"
DDB_UPDATED_VALUE = ":updated"
DDB_COLLABORATORS_VALUE = ":collaborators"
DDB_COLLABORATORS_UPDATE = (
    "SET collaborators = :collaborators, updatedAt = :updated"
)

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
        self.problems_table: Table = dynamodb.Table(settings.dynamodb_problems_table)
        self.attempts_table: Table = dynamodb.Table(settings.dynamodb_attempts_table)
        self.feedback_table: Table = dynamodb.Table(settings.dynamodb_feedback_table)
        self.walkthroughs_table: Table = dynamodb.Table(settings.dynamodb_walkthroughs_table)

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
                    "if_not_exists(verificationVersion, :zero) + :one, updatedAt = :updated"
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
                    "SET emailVerified = :verified, updatedAt = :updated "
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
                    "verificationSentAt = :sent, verificationVersion = :version, updatedAt = :updated"
                )
                values.update({
                    ":token": user.verificationTokenHash,
                    ":expires": user.verificationExpiresAt,
                    ":sent": user.verificationSentAt,
                })
            else:
                update_expression = (
                    "SET verificationVersion = :version, updatedAt = :updated "
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
                UpdateExpression="SET preferences = :prefs, updatedAt = :updated",
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

    def update_user_google_id(
        self, user_id: str, google_id: str, picture: Optional[str] = None
    ) -> Optional[User]:
        """Update user's Google ID and picture (for linking Google account to existing user)."""
        try:
            now = datetime.now(timezone.utc).isoformat()

            update_expression = "SET googleId = :google_id, updatedAt = :updated"
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
        return Diagram(
            id=diagram_id,
            userId=user_id,
            title=title,
            description=description,
            nodes=nodes,
            edges=edges,
            nodeCount=len(nodes),
            edgeCount=len(edges),
            reasoningContext=reasoning_context,
            createdAt=now,
            updatedAt=now,
            recordType="remix" if source_diagram_id else "canonical",
            familyId=family_id or diagram_id,
            sourceDiagramId=source_diagram_id,
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

            while response.get("LastEvaluatedKey"):
                response = self.diagrams_table.query(
                    **query_kwargs,
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

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
                "FilterExpression": Attr("recordType").not_exists()
                | Attr("recordType").ne("public_snapshot"),
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

    def get_diagram(self, user_id: str, diagram_id: str) -> Optional[Diagram]:
        """Get a specific diagram."""
        try:
            response = self.diagrams_table.get_item(
                Key={"userId": user_id, "id": diagram_id}
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

            update_expression = "SET updatedAt = :updated"
            expression_values: Dict[str, Any] = {DDB_UPDATED_VALUE: now}
            expression_names: Dict[str, str] = {}

            if title is not None:
                update_expression += ", title = :title"
                expression_values[":title"] = title

            if description is not None:
                update_expression += ", description = :description"
                expression_values[":description"] = description

            if nodes is not None:
                update_expression += ", #nodes = :nodes"
                # Convert floats to Decimal for DynamoDB
                expression_values[":nodes"] = convert_floats_to_decimal(nodes)
                expression_names["#nodes"] = "nodes"
                update_expression += ", nodeCount = :node_count"
                expression_values[":node_count"] = len(nodes)

            if edges is not None:
                update_expression += ", #edges = :edges"
                # Convert floats to Decimal for DynamoDB
                expression_values[":edges"] = convert_floats_to_decimal(edges)
                expression_names["#edges"] = "edges"
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

    def delete_diagram(self, user_id: str, diagram_id: str) -> bool:
        """Delete a diagram."""
        try:
            diagram = self.get_diagram(user_id, diagram_id)
            self.diagrams_table.delete_item(Key={"userId": user_id, "id": diagram_id})
            if diagram and diagram.publicSnapshotId:
                self.diagrams_table.delete_item(
                    Key={"userId": user_id, "id": diagram.publicSnapshotId}
                )
            return True
        except ClientError:
            return False

    # Sharing operations
    def share_diagram(
        self, diagram_id: str, owner_id: str, collaborator: Collaborator
    ) -> bool:
        """Share a diagram with a collaborator."""
        try:
            # Get the current diagram
            diagram = self.get_diagram(owner_id, diagram_id)
            if not diagram:
                return False

            # Check if collaborator already exists
            existing_collaborator = next(
                (c for c in diagram.collaborators if c.userId == collaborator.userId),
                None,
            )

            if existing_collaborator:
                # Update existing collaborator's permission
                existing_collaborator.permission = collaborator.permission
                existing_collaborator.addedAt = collaborator.addedAt
            else:
                # Add new collaborator
                diagram.collaborators.append(collaborator)

            # Update the diagram in DynamoDB
            self.diagrams_table.update_item(
                Key={"userId": owner_id, "id": diagram_id},
                UpdateExpression=DDB_COLLABORATORS_UPDATE,
                ExpressionAttributeValues={
                    DDB_COLLABORATORS_VALUE: [
                        convert_floats_to_decimal(c.model_dump())
                        for c in diagram.collaborators
                    ],
                    DDB_UPDATED_VALUE: datetime.now(timezone.utc).isoformat(),
                },
            )
            return True
        except ClientError:
            return False

    def remove_collaborator(
        self, diagram_id: str, owner_id: str, collaborator_user_id: str
    ) -> bool:
        """Remove a collaborator from a diagram."""
        try:
            # Get the current diagram
            diagram = self.get_diagram(owner_id, diagram_id)
            if not diagram:
                return False

            # Remove the collaborator
            diagram.collaborators = [
                c for c in diagram.collaborators if c.userId != collaborator_user_id
            ]

            # Update the diagram in DynamoDB
            self.diagrams_table.update_item(
                Key={"userId": owner_id, "id": diagram_id},
                UpdateExpression=DDB_COLLABORATORS_UPDATE,
                ExpressionAttributeValues={
                    DDB_COLLABORATORS_VALUE: [
                        convert_floats_to_decimal(c.model_dump())
                        for c in diagram.collaborators
                    ],
                    DDB_UPDATED_VALUE: datetime.now(timezone.utc).isoformat(),
                },
            )
            return True
        except ClientError:
            return False

    def update_collaborator_permission(
        self,
        diagram_id: str,
        owner_id: str,
        collaborator_user_id: str,
        permission: Permission,
    ) -> bool:
        """Update a collaborator's permission level."""
        try:
            # Get the current diagram
            diagram = self.get_diagram(owner_id, diagram_id)
            if not diagram:
                return False

            # Find and update the collaborator
            for collaborator in diagram.collaborators:
                if collaborator.userId == collaborator_user_id:
                    collaborator.permission = permission
                    break
            else:
                return False  # Collaborator not found

            # Update the diagram in DynamoDB
            self.diagrams_table.update_item(
                Key={"userId": owner_id, "id": diagram_id},
                UpdateExpression=DDB_COLLABORATORS_UPDATE,
                ExpressionAttributeValues={
                    DDB_COLLABORATORS_VALUE: [
                        convert_floats_to_decimal(c.model_dump())
                        for c in diagram.collaborators
                    ],
                    DDB_UPDATED_VALUE: datetime.now(timezone.utc).isoformat(),
                },
            )
            return True
        except ClientError:
            return False

    def get_diagram_collaborators(
        self, diagram_id: str, owner_id: str
    ) -> List[Collaborator]:
        """Get all collaborators for a diagram."""
        try:
            diagram = self.get_diagram(owner_id, diagram_id)
            return diagram.collaborators if diagram else []
        except ClientError:
            return []

    def check_collaborator_permission(
        self, diagram_id: str, user_id: str
    ) -> Optional[Permission]:
        """Check if a user has access to a diagram and return their permission level."""
        try:
            # First check if user is the owner
            diagram = self.get_diagram(user_id, diagram_id)
            if diagram:
                return Permission.EDIT  # Owner has edit permission

            # Check if user is a collaborator
            # We need to find the diagram by scanning or using a GSI
            # For now, we'll scan the table (not efficient for production)
            response = self.diagrams_table.scan()
            items = response.get("Items", [])

            for item in items:
                item_float = convert_decimal_to_float(item)
                if item_float.get("id") == diagram_id:
                    collaborators = item_float.get("collaborators", [])
                    for collab_data in collaborators:
                        if collab_data.get("userId") == user_id:
                            return Permission(collab_data.get("permission"))

            return None
        except ClientError:
            return None

    def get_shared_diagrams_for_user(self, user_id: str) -> List[Diagram]:
        """Get all full diagrams shared with a user."""
        try:
            shared_diagrams: List[Diagram] = []

            # Scan all diagrams to find those where user is a collaborator
            response = self.diagrams_table.scan()
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.diagrams_table.scan(
                    ExclusiveStartKey=response["LastEvaluatedKey"]
                )
                items.extend(response.get("Items", []))

            for item in items:
                item_float = convert_decimal_to_float(item)
                collaborators = item_float.get("collaborators", [])

                # Check if user is a collaborator
                for collab_data in collaborators:
                    if collab_data.get("userId") == user_id:
                        diagram = Diagram(**item_float)
                        shared_diagrams.append(diagram)
                        break

            return shared_diagrams
        except ClientError:
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
            shared_diagrams: List[Diagram] = []
            scan_kwargs = {
                "ProjectionExpression": DIAGRAM_SUMMARY_PROJECTION,
                "ExpressionAttributeNames": DIAGRAM_SUMMARY_NAMES,
            }
            response = self.diagrams_table.scan(**scan_kwargs)
            items = response.get("Items", [])

            while response.get("LastEvaluatedKey"):
                response = self.diagrams_table.scan(
                    **scan_kwargs,
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            for item in items:
                item_float = convert_decimal_to_float(item)
                collaborators = item_float.get("collaborators", [])
                if any(
                    collab_data.get("userId") == user_id
                    for collab_data in collaborators
                ):
                    shared_diagrams.append(Diagram(**item_float))

            return shared_diagrams
        except ClientError:
            return []

    def get_shared_diagram_summary_page_for_user(
        self,
        user_id: str,
        limit: int,
        exclusive_start_key: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[Diagram], Optional[Dict[str, Any]]]:
        """Get one projected page of shared diagram metadata.

        DynamoDB's scan limit applies before the collaborator filter, so keep
        scanning until this page is full or the table is exhausted.
        """
        try:
            shared_diagrams: List[Diagram] = []
            last_key = exclusive_start_key

            while len(shared_diagrams) < limit:
                scan_kwargs: Dict[str, Any] = {
                    "ProjectionExpression": DIAGRAM_SUMMARY_PROJECTION,
                    "ExpressionAttributeNames": DIAGRAM_SUMMARY_NAMES,
                    "Limit": max(limit - len(shared_diagrams), 1),
                }
                if last_key:
                    scan_kwargs["ExclusiveStartKey"] = last_key

                response = self.diagrams_table.scan(**scan_kwargs)
                for item in response.get("Items", []):
                    item_float = convert_decimal_to_float(item)
                    collaborators = item_float.get("collaborators", [])
                    if any(
                        collab_data.get("userId") == user_id
                        for collab_data in collaborators
                    ):
                        shared_diagrams.append(Diagram(**item_float))
                        if len(shared_diagrams) >= limit:
                            break

                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    return shared_diagrams, None

            return shared_diagrams, last_key
        except ClientError as e:
            print(f"Error scanning shared diagram summary page: {e}")
            return [], None

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
        try:
            scan_params: Dict[str, Any] = {
                "FilterExpression": Attr("slug").eq(slug),
            }
            while True:
                response = self.problems_table.scan(**scan_params)
                items = response.get("Items", [])
                if items:
                    return items[0]
                if "LastEvaluatedKey" not in response:
                    return None
                scan_params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        except ClientError:
            return None

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
    def _prepare_attempt_state(
        existing_attempt: Optional[AttemptResponse],
        last_assessment: Optional[Dict[str, Any]],
        reasoning_context: Optional[Dict[str, Any]],
        interview_session: Optional[Dict[str, Any]],
        addressed_finding_ids: Optional[List[str]],
    ) -> tuple[
        int,
        Optional[Dict[str, Any]],
        Optional[Dict[str, Any]],
        Optional[Dict[str, Any]],
        Dict[str, Any],
        List[Dict[str, Any]],
        List[str],
    ]:
        existing_data = (
            existing_attempt.model_dump() if existing_attempt is not None else {}
        )
        assessment_count = existing_attempt.assessmentCount if existing_attempt else 0
        preserved_assessment = cast(
            Optional[Dict[str, Any]], existing_data.get("lastAssessment")
        )

        if reasoning_context is not None:
            preserved_reasoning_context = convert_floats_to_decimal(
                reasoning_context
            )
        else:
            preserved_reasoning_context = existing_data.get("reasoningContext")

        if interview_session is not None:
            preserved_interview_session = convert_floats_to_decimal(
                interview_session
            )
        else:
            preserved_interview_session = existing_data.get("interviewSession")

        if last_assessment:
            assessment_count += 1
            preserved_assessment = convert_floats_to_decimal(last_assessment)

        preserved_addressed_finding_ids = list(
            addressed_finding_ids
            if addressed_finding_ids is not None
            else existing_data.get("addressedFindingIds", [])
        )
        assessment_history = list(existing_data.get("assessmentHistory", []))
        if last_assessment:
            assessment_history.append(
                {
                    "id": str(last_assessment.get("assessmentId") or f"assessment-{assessment_count}"),
                    "score": int(last_assessment.get("score", 0)),
                    "findingCount": len(last_assessment.get("findings", []) or last_assessment.get("feedback", []) or []),
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "source": last_assessment.get("source"),
                    "addressedFindingIds": preserved_addressed_finding_ids,
                }
            )
            assessment_history = assessment_history[-10:]

        return (
            assessment_count,
            preserved_assessment,
            preserved_reasoning_context,
            preserved_interview_session,
            existing_data,
            assessment_history,
            preserved_addressed_finding_ids,
        )

    @staticmethod
    def _build_attempt_item(
        user_id: str,
        problem_id: str,
        title: str,
        difficulty: Optional[str],
        category: Optional[str],
        nodes: List[Any],
        edges: List[Any],
        elapsed_time: int,
        preserved_assessment: Optional[Dict[str, Any]],
        preserved_reasoning_context: Optional[Dict[str, Any]],
        preserved_interview_session: Optional[Dict[str, Any]],
        assessment_count: int,
        assessment_history: List[Dict[str, Any]],
        addressed_finding_ids: List[str],
        now: str,
        existing_attempt: Optional[AttemptResponse],
    ) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "userId": user_id,
            "problemId": problem_id,
            "title": title,
            "difficulty": difficulty or "Medium",
            "category": category or "General",
            "nodes": convert_floats_to_decimal(nodes),
            "edges": convert_floats_to_decimal(edges),
            "elapsedTime": elapsed_time,
            "lastAssessment": preserved_assessment,
            "reasoningContext": preserved_reasoning_context,
            "interviewSession": preserved_interview_session,
            "assessmentCount": assessment_count,
            "assessmentHistory": convert_floats_to_decimal(assessment_history),
            "addressedFindingIds": addressed_finding_ids,
            "updatedAt": now,
            "lastAttemptedAt": now,
        }

        if existing_attempt is None:
            item["createdAt"] = now
        else:
            item["createdAt"] = existing_attempt.createdAt
            item.update(
                {
                    "isPublic": existing_attempt.isPublic,
                    "publishedAt": existing_attempt.publishedAt,
                    "authorName": existing_attempt.authorName,
                    "authorPicture": existing_attempt.authorPicture,
                    "viewCount": existing_attempt.viewCount,
                }
            )

        return item

    @staticmethod
    def _build_attempt_response(
        user_id: str,
        problem_id: str,
        title: str,
        difficulty: Optional[str],
        category: Optional[str],
        nodes: List[Any],
        edges: List[Any],
        elapsed_time: int,
        last_assessment: Optional[Dict[str, Any]],
        reasoning_context: Optional[Dict[str, Any]],
        interview_session: Optional[Dict[str, Any]],
        assessment_count: int,
        assessment_history: List[Dict[str, Any]],
        addressed_finding_ids: List[str],
        item: Dict[str, Any],
        now: str,
        existing_attempt: Optional[AttemptResponse],
    ) -> AttemptResponse:
        return AttemptResponse(
            id=f"{user_id}#{problem_id}",
            userId=user_id,
            problemId=problem_id,
            title=title,
            difficulty=difficulty or "Medium",
            category=category or "General",
            nodes=nodes,
            edges=edges,
            elapsedTime=elapsed_time,
            lastAssessment=last_assessment,
            reasoningContext=reasoning_context,
            interviewSession=interview_session,
            assessmentCount=assessment_count,
            assessmentHistory=assessment_history,
            addressedFindingIds=addressed_finding_ids,
            createdAt=item["createdAt"],
            updatedAt=now,
            lastAttemptedAt=now,
            isPublic=existing_attempt.isPublic if existing_attempt else False,
            publishedAt=existing_attempt.publishedAt if existing_attempt else None,
            authorName=existing_attempt.authorName if existing_attempt else None,
            authorPicture=existing_attempt.authorPicture if existing_attempt else None,
            viewCount=existing_attempt.viewCount if existing_attempt else 0,
        )

    def create_or_update_attempt(
        self,
        user_id: str,
        problem_id: str,
        title: str,
        difficulty: Optional[str],
        category: Optional[str],
        nodes: List[Any],
        edges: List[Any],
        elapsed_time: int = 0,
        last_assessment: Optional[Dict[str, Any]] = None,
        reasoning_context: Optional[Dict[str, Any]] = None,
        interview_session: Optional[Dict[str, Any]] = None,
        addressed_finding_ids: Optional[List[str]] = None,
    ) -> AttemptResponse:
        """Create or update a problem attempt (upsert operation)."""
        try:
            existing_attempt = self.get_attempt_by_problem(user_id, problem_id)
            now = datetime.now(timezone.utc).isoformat()
            (
                assessment_count,
                preserved_assessment,
                preserved_reasoning_context,
                preserved_interview_session,
                existing_data,
                assessment_history,
                preserved_addressed_finding_ids,
            ) = self._prepare_attempt_state(
                existing_attempt,
                last_assessment,
                reasoning_context,
                interview_session,
                addressed_finding_ids,
            )
            item = self._build_attempt_item(
                user_id,
                problem_id,
                title,
                difficulty,
                category,
                nodes,
                edges,
                elapsed_time,
                preserved_assessment,
                preserved_reasoning_context,
                preserved_interview_session,
                assessment_count,
                assessment_history,
                preserved_addressed_finding_ids,
                now,
                existing_attempt,
            )

            self.attempts_table.put_item(Item=convert_floats_to_decimal(item))
            response_reasoning_context = reasoning_context
            if response_reasoning_context is None:
                response_reasoning_context = existing_data.get("reasoningContext")
            response_interview_session = interview_session
            if response_interview_session is None:
                response_interview_session = existing_data.get("interviewSession")

            return self._build_attempt_response(
                user_id,
                problem_id,
                title,
                difficulty,
                category,
                nodes,
                edges,
                elapsed_time,
                last_assessment,
                response_reasoning_context,
                response_interview_session,
                assessment_count,
                assessment_history,
                preserved_addressed_finding_ids,
                item,
                now,
                existing_attempt,
            )
        except ClientError as e:
            print(f"Error creating/updating attempt: {e}")
            raise

    def get_attempt_by_problem(
        self, user_id: str, problem_id: str
    ) -> Optional[AttemptResponse]:
        """Get a user's attempt for a specific problem using direct key lookup."""
        try:
            response = self.attempts_table.get_item(
                Key={"userId": user_id, "problemId": problem_id}
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

    # ------------------------------------------------------------------
    # Public sharing
    # ------------------------------------------------------------------

    def publish_attempt(
        self,
        user_id: str,
        problem_id: str,
        author_name: str,
        author_picture: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark an attempt as public and stamp author metadata."""
        try:
            existing = self.get_attempt_by_problem(user_id, problem_id)
            if not existing:
                return None

            now = datetime.now(timezone.utc).isoformat()

            self.attempts_table.update_item(
                Key={"userId": user_id, "problemId": problem_id},
                UpdateExpression=(
                    "SET isPublic = :pub, publishedAt = :ts, "
                    "authorName = :name, authorPicture = :pic, "
                    "viewCount = if_not_exists(viewCount, :zero)"
                ),
                ExpressionAttributeValues={
                    ":pub": True,
                    ":ts": now,
                    ":name": author_name,
                    ":pic": author_picture or "",
                    DDB_ZERO_VALUE: 0,
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
                UpdateExpression="SET isPublic = :f",
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

            assessment = item_float.get("lastAssessment")

            return PublicSolutionResponse(
                id=attempt_id,
                problemId=problem_id,
                title=item_float.get("title", ""),
                difficulty=item_float.get("difficulty"),
                category=item_float.get("category"),
                nodes=item_float.get("nodes", []),
                edges=item_float.get("edges", []),
                lastAssessment=assessment,
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
        """Scan for top public solutions for a problem (sorted by score desc)."""
        try:
            # Scan with filter — small dataset per problem, acceptable cost
            response = self.attempts_table.scan(
                FilterExpression=(
                    "problemId = :pid AND isPublic = :t"
                ),
                ExpressionAttributeValues={
                    ":pid": problem_id,
                    ":t": True,
                },
            )
            items = response.get("Items", [])

            entries: List[LeaderboardEntry] = []
            for item in items:
                item_float = convert_decimal_to_float(item)
                assessment = cast(
                    Dict[str, Any], item_float.get("lastAssessment") or {}
                )
                score = int(assessment.get("score", 0))
                uid = item_float.get("userId", "")
                pid = item_float.get("problemId", "")
                entries.append(
                    LeaderboardEntry(
                        attemptId=f"{uid}#{pid}",
                        authorName=item_float.get("authorName"),
                        authorPicture=item_float.get("authorPicture"),
                        score=score,
                        publishedAt=item_float.get("publishedAt"),
                        elapsedTime=int(item_float.get("elapsedTime", 0)),
                    )
                )

            # Sort by score descending, return top N
            entries.sort(key=lambda e: e.score, reverse=True)
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
