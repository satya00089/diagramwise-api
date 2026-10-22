"""
Components Service
Handles DynamoDB operations for component management
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import threading
import time
import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource
from boto3.dynamodb.conditions import Key, Attr
from app.utils.config import get_settings

settings = get_settings()


class ComponentsService:
    """Service for managing components in DynamoDB"""

    _catalog_cache_ttl_seconds = 300

    def __init__(self):
        """Initialize DynamoDB client and table"""
        self.dynamodb: DynamoDBServiceResource = boto3.resource(  # pyright: ignore[reportUnknownMemberType]
            "dynamodb",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        self.table_name = settings.components_table_name
        self.table = self.dynamodb.Table(self.table_name)
        self._catalog_cache: tuple[float, List[Dict[str, Any]]] | None = None
        self._catalog_cache_lock = threading.Lock()

    def _get_active_catalog(self) -> List[Dict[str, Any]]:
        """Cache the small active catalog used by search and metadata endpoints."""
        now = time.monotonic()
        cached = self._catalog_cache
        if cached and now - cached[0] < self._catalog_cache_ttl_seconds:
            return cached[1]

        with self._catalog_cache_lock:
            now = time.monotonic()
            cached = self._catalog_cache
            if cached and now - cached[0] < self._catalog_cache_ttl_seconds:
                return cached[1]

            items: List[Dict[str, Any]] = []
            scan_params: Dict[str, Any] = {
                "FilterExpression": Attr("isActive").eq(True),
            }
            while True:
                response = self.table.scan(**scan_params)
                items.extend(response.get("Items", []))
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
                scan_params["ExclusiveStartKey"] = last_key

            self._catalog_cache = (time.monotonic(), items)
            return items

    def get_components_by_provider(
        self,
        provider: str,
        category: Optional[str] = None,
        limit: int = 100,
        last_evaluated_key: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Get components filtered by provider and optionally by category

        Args:
            provider: Provider name (aws, azure, gcp, kubernetes, etc.)
            category: Optional category filter (storage, compute, etc.)
            limit: Maximum number of items to return
            last_evaluated_key: Pagination key

        Returns:
            Dict with items and pagination info
        """
        try:
            # Build query parameters
            query_params: Dict[str, Any] = {
                "IndexName": "ProviderIndex",
                "KeyConditionExpression": Key("provider").eq(provider),
                "Limit": limit,
                "FilterExpression": Attr("isActive").eq(True),
            }

            # Add category filter if provided
            if category:
                query_params["FilterExpression"] = query_params[
                    "FilterExpression"
                ] & Attr("category").eq(category)

            # Add pagination if provided
            if last_evaluated_key:
                query_params["ExclusiveStartKey"] = last_evaluated_key

            # Execute query
            response = self.table.query(**query_params)

            return {
                "items": response.get("Items", []),
                "lastEvaluatedKey": response.get("LastEvaluatedKey"),
                "count": response.get("Count", 0),
            }

        except Exception as e:
            print(f"Error querying components by provider: {e}")
            raise

    def get_components_by_category(
        self,
        category: str,
        provider: Optional[str] = None,
        limit: int = 100,
        last_evaluated_key: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Get components filtered by category and optionally by provider

        Args:
            category: Category name (storage, compute, database, etc.)
            provider: Optional provider filter
            limit: Maximum number of items to return
            last_evaluated_key: Pagination key

        Returns:
            Dict with items and pagination info
        """
        try:
            # Build query parameters
            query_params: Dict[str, Any] = {
                "IndexName": "CategoryIndex",
                "KeyConditionExpression": Key("category").eq(category),
                "Limit": limit,
                "FilterExpression": Attr("isActive").eq(True),
            }

            # Add provider filter if provided
            if provider:
                query_params["FilterExpression"] = query_params[
                    "FilterExpression"
                ] & Attr("provider").eq(provider)

            # Add pagination if provided
            if last_evaluated_key:
                query_params["ExclusiveStartKey"] = last_evaluated_key

            # Execute query
            response = self.table.query(**query_params)

            return {
                "items": response.get("Items", []),
                "lastEvaluatedKey": response.get("LastEvaluatedKey"),
                "count": response.get("Count", 0),
            }

        except Exception as e:
            print(f"Error querying components by category: {e}")
            raise

    def search_components(
        self,
        search_term: str,
        provider: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Search components by name, displayName, description, or tags

        Args:
            search_term: Search query
            provider: Optional provider filter
            category: Optional category filter
            limit: Maximum number of items to return

        Returns:
            Dict with matching items
        """
        try:
            term = search_term.casefold()

            def matches(value: Any) -> bool:
                if isinstance(value, str):
                    return term in value.casefold()
                if isinstance(value, list):
                    return any(term in str(item).casefold() for item in value)
                return False

            matching_items = []
            for item in self._get_active_catalog():
                if provider and str(item.get("provider", "")).casefold() != provider.casefold():
                    continue
                if category and str(item.get("category", "")).casefold() != category.casefold():
                    continue
                if any(
                    matches(item.get(field))
                    for field in ("name", "displayName", "description", "tags")
                ):
                    matching_items.append(item)

            return {"items": matching_items[:limit], "count": min(len(matching_items), limit)}

        except Exception as e:
            print(f"Error searching components: {e}")
            raise

    def get_component_by_id(self, component_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single component by ID

        Args:
            component_id: Component ID (format: {platform}-{component-name})

        Returns:
            Component data or None if not found
        """
        try:
            # Use composite key (platform + id) for get_item
            response = self.table.get_item(
                Key=self._component_key(component_id)
            )
            return response.get("Item")

        except Exception as e:
            print(f"Error getting component by ID: {e}")
            raise

    @staticmethod
    def _component_key(component_id: str) -> Dict[str, str]:
        """Build the component table key from its provider-prefixed ID."""
        platform_prefix = (
            component_id.split("-")[0].lower() if "-" in component_id else ""
        )
        platform_map = {
            "aws": "AWS",
            "azure": "Azure",
            "gcp": "GCP",
            "kubernetes": "Kubernetes",
            "k8s": "Kubernetes",
        }
        platform = platform_map.get(platform_prefix, platform_prefix.capitalize())
        return {"platform": platform, "id": component_id}

    def get_components_by_ids(
        self, component_ids: List[str], minimal: bool = False
    ) -> List[Dict[str, Any]]:
        """Fetch component records in DynamoDB batches, preserving request order."""
        ids = list(dict.fromkeys(component_ids))
        if not ids:
            return []
        if len(ids) > 100:
            raise ValueError("At most 100 component IDs can be fetched at once")

        serializer = TypeSerializer()
        deserializer = TypeDeserializer()
        keys = [self._component_key(component_id) for component_id in ids]
        request: Dict[str, Any] = {
            "Keys": [
                {name: serializer.serialize(value) for name, value in key.items()}
                for key in keys
            ]
        }
        if minimal:
            request["ProjectionExpression"] = "#id, #provider, #label, #description, #group, #icon, #tags, #node_type"
            request["ExpressionAttributeNames"] = {
                "#id": "id",
                "#provider": "provider",
                "#label": "label",
                "#description": "description",
                "#group": "group",
                "#icon": "iconUrl",
                "#tags": "tags",
                "#node_type": "nodeType",
            }

        client = self.table.meta.client
        pending: Dict[str, Any] = {self.table_name: request}
        records: List[Dict[str, Any]] = []
        attempts = 0
        while pending:
            response = client.batch_get_item(RequestItems=pending)
            records.extend(
                {
                    name: deserializer.deserialize(value)
                    for name, value in item.items()
                }
                for item in response.get("Responses", {}).get(self.table_name, [])
            )
            pending = response.get("UnprocessedKeys", {})
            if pending:
                attempts += 1
                if attempts >= 5:
                    raise RuntimeError("DynamoDB left component keys unprocessed")
                time.sleep(0.05 * (2 ** (attempts - 1)))

        by_id = {str(item["id"]): item for item in records if item.get("id")}
        return [by_id[component_id] for component_id in ids if component_id in by_id]

    def get_all_components(
        self, limit: int = 100, last_evaluated_key: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get all active components

        Args:
            limit: Maximum number of items to return
            last_evaluated_key: Pagination key

        Returns:
            Dict with items and pagination info
        """
        try:
            scan_params: Dict[str, Any] = {
                "Limit": limit,
                "FilterExpression": Attr("isActive").eq(True),
            }

            if last_evaluated_key:
                scan_params["ExclusiveStartKey"] = last_evaluated_key

            response = self.table.scan(**scan_params)

            return {
                "items": response.get("Items", []),
                "lastEvaluatedKey": response.get("LastEvaluatedKey"),
                "count": response.get("Count", 0),
            }

        except Exception as e:
            print(f"Error getting all components: {e}")
            raise

    def increment_usage_count(self, component_id: str) -> Dict[str, Any]:
        """
        Increment the usage count for a component

        Args:
            component_id: Component ID (format: {platform}-{component-name})

        Returns:
            Updated component data
        """
        try:
            # Extract platform from component ID
            platform_prefix = (
                component_id.split("-")[0].lower() if "-" in component_id else ""
            )

            # Map platform prefix to platform name
            platform_map = {
                "aws": "AWS",
                "azure": "Azure",
                "gcp": "GCP",
                "kubernetes": "Kubernetes",
                "k8s": "Kubernetes",
            }

            platform = platform_map.get(platform_prefix, platform_prefix.capitalize())

            response = self.table.update_item(
                Key={"platform": platform, "id": component_id},
                UpdateExpression="SET usageCount = if_not_exists(usageCount, :zero) + :inc, updatedAt = :timestamp",
                ExpressionAttributeValues={
                    ":inc": 1,
                    ":zero": 0,
                    ":timestamp": datetime.now(timezone.utc).isoformat(),
                },
                ReturnValues="ALL_NEW",
            )
            return response.get("Attributes", {})

        except Exception as e:
            print(f"Error incrementing usage count: {e}")
            raise

    def get_providers(self) -> List[str]:
        """
        Get list of unique providers

        Returns:
            List of provider names
        """
        try:
            return sorted(
                {
                    str(item["provider"])
                    for item in self._get_active_catalog()
                    if item.get("provider")
                }
            )

        except Exception as e:
            print(f"Error getting providers: {e}")
            raise

    def get_categories(self) -> List[str]:
        """
        Get list of unique categories

        Returns:
            List of category names
        """
        try:
            return sorted(
                {
                    str(item["category"])
                    for item in self._get_active_catalog()
                    if item.get("category")
                }
            )

        except Exception as e:
            print(f"Error getting categories: {e}")
            raise


# Singleton instance
components_service = ComponentsService()
