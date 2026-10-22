"""
Components Router
API endpoints for component management
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.components_service import components_service


router = APIRouter(prefix="/api/components", tags=["components"])
logger = logging.getLogger(__name__)


class ComponentsResponse(BaseModel):
    """Response model for component queries"""

    items: List[Dict[str, Any]]
    count: int
    lastEvaluatedKey: Optional[Dict[str, Any]] = None


class UsageResponse(BaseModel):
    """Response model for usage tracking"""

    success: bool
    usageCount: int
    message: str


class ProvidersResponse(BaseModel):
    """Response model for providers list"""

    providers: list[str]
    count: int


class CategoriesResponse(BaseModel):
    """Response model for categories list"""

    categories: list[str]
    count: int


class ComponentBatchRequest(BaseModel):
    ids: List[str] = Field(..., min_length=1, max_length=100)
    minimal: bool = False


def _decoded_key(encoded_key: Optional[str]) -> Optional[Dict[str, Any]]:
    return _decode_pagination_key(encoded_key) if encoded_key else None


def _fetch_components(
    provider: Optional[str],
    category: Optional[str],
    limit: int,
    last_evaluated_key: Optional[str],
) -> Dict[str, Any]:
    pagination_key = _decoded_key(last_evaluated_key)
    if provider:
        return components_service.get_components_by_provider(
            provider=provider,
            category=category,
            limit=limit,
            last_evaluated_key=pagination_key,
        )
    if category:
        return components_service.get_components_by_category(
            category=category,
            limit=limit,
            last_evaluated_key=pagination_key,
        )
    return components_service.get_all_components(
        limit=limit,
        last_evaluated_key=pagination_key,
    )


@router.get(
    "",
    response_model=ComponentsResponse,
    responses={500: {"description": "Failed to fetch components."}},
)
async def get_components(
    provider: Optional[str] = Query(
        None, description="Filter by provider (aws, azure, gcp, etc.)"
    ),
    category: Optional[str] = Query(
        None, description="Filter by category (storage, compute, etc.)"
    ),
    limit: int = Query(
        100, ge=1, le=500, description="Maximum number of items to return"
    ),
    last_evaluated_key: Optional[str] = Query(
        None, description="Pagination key (base64 encoded)"
    ),
    minimal: bool = Query(
        False,
        description="Return minimal fields only (id, provider, label, description, group, iconUrl, tags)",
    ),
):
    """
    Get components with optional filtering by provider and/or category

    Examples:
    - GET /api/components - Get all components
    - GET /api/components?provider=aws - Get all AWS components
    - GET /api/components?category=storage - Get all storage components
    - GET /api/components?provider=azure&category=compute - Get Azure compute components
    """
    try:
        result = _fetch_components(provider, category, limit, last_evaluated_key)

        # Filter to minimal fields if requested
        items = result["items"]
        if minimal:
            items = [
                {
                    "id": item["id"],
                    "provider": item.get("provider", ""),
                    "label": item.get("label", ""),
                    "description": item.get("description", ""),
                    "group": item.get("group", ""),
                    "iconUrl": item.get("iconUrl", ""),
                    "tags": item.get("tags", []),
                    "nodeType": item.get("nodeType", "custom"),
                }
                for item in items
            ]

        return ComponentsResponse(
            items=items,
            count=len(items),
            lastEvaluatedKey=result.get("lastEvaluatedKey"),
        )

    except Exception as exc:
        logger.exception("Error in get_components")
        raise HTTPException(
            status_code=500, detail="Error fetching components"
        ) from exc


@router.get(
    "/search",
    response_model=ComponentsResponse,
    responses={500: {"description": "Failed to search components."}},
)
async def search_components(
    search: str = Query(..., min_length=1, description="Search term"),
    provider: Optional[str] = Query(None, description="Filter by provider"),
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(
        100, ge=1, le=500, description="Maximum number of items to return"
    ),
):
    """
    Search components by name, description, or tags

    Examples:
    - GET /api/components/search?search=s3 - Search for "s3"
    - GET /api/components/search?search=storage&provider=aws - Search AWS storage
    """
    try:
        result = components_service.search_components(
            search_term=search, provider=provider, category=category, limit=limit
        )

        return ComponentsResponse(items=result["items"], count=result["count"])

    except Exception as exc:
        logger.exception("Error in search_components")
        raise HTTPException(
            status_code=500, detail="Error searching components"
        ) from exc


@router.get(
    "/providers",
    response_model=ProvidersResponse,
    responses={500: {"description": "Failed to fetch providers."}},
)
async def get_providers():
    """
    Get list of all available providers

    Returns:
        List of provider names (aws, azure, gcp, kubernetes, etc.)
    """
    try:
        providers = components_service.get_providers()

        return ProvidersResponse(providers=providers, count=len(providers))

    except Exception as exc:
        logger.exception("Error in get_providers")
        raise HTTPException(
            status_code=500, detail="Error fetching providers"
        ) from exc


@router.get(
    "/categories",
    response_model=CategoriesResponse,
    responses={500: {"description": "Failed to fetch categories."}},
)
async def get_categories():
    """
    Get list of all available categories

    Returns:
        List of category names (storage, compute, database, etc.)
    """
    try:
        categories = components_service.get_categories()

        return CategoriesResponse(categories=categories, count=len(categories))

    except Exception as exc:
        logger.exception("Error in get_categories")
        raise HTTPException(
            status_code=500, detail="Error fetching categories"
        ) from exc


@router.post(
    "/batch/by-ids",
    response_model=ComponentsResponse,
    responses={500: {"description": "Error fetching components."}},
)
async def get_components_by_ids(request: ComponentBatchRequest):
    """Fetch up to 100 component records with one DynamoDB batch request."""
    try:
        items = components_service.get_components_by_ids(
            request.ids, minimal=request.minimal
        )
        return ComponentsResponse(items=items, count=len(items))
    except Exception as exc:
        logger.exception("Error fetching components by ID")
        raise HTTPException(
            status_code=500, detail="Error fetching components"
        ) from exc


@router.get(
    "/{component_id}",
    responses={
        404: {"description": "Component not found."},
        500: {"description": "Failed to fetch component."},
    },
)
async def get_component(component_id: str):
    """
    Get a specific component by ID

    Args:
        component_id: Component ID

    Returns:
        Component data
    """
    try:
        component = components_service.get_component_by_id(component_id)

        if not component:
            raise HTTPException(
                status_code=404, detail=f"Component '{component_id}' not found"
            )

        return component

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error in get_component")
        raise HTTPException(
            status_code=500, detail="Error fetching component"
        ) from exc


@router.post(
    "/{component_id}/usage",
    response_model=UsageResponse,
    responses={
        404: {"description": "Component not found."},
        500: {"description": "Failed to track component usage."},
    },
)
async def track_usage(component_id: str):
    """
    Track component usage (increment usage count)

    Args:
        component_id: Component ID

    Returns:
        Updated usage count
    """
    try:
        # First check if component exists
        component = components_service.get_component_by_id(component_id)
        if not component:
            raise HTTPException(
                status_code=404, detail=f"Component '{component_id}' not found"
            )

        # Increment usage count
        updated_component = components_service.increment_usage_count(component_id)

        return UsageResponse(
            success=True,
            usageCount=updated_component.get("usageCount", 1),
            message="Usage tracked successfully",
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error in track_usage")
        raise HTTPException(
            status_code=500, detail="Error tracking usage"
        ) from exc


def _decode_pagination_key(encoded_key: str) -> Dict[str, Any]:
    """
    Decode base64 encoded pagination key

    Args:
        encoded_key: Base64 encoded JSON string

    Returns:
        Decoded dictionary
    """
    import base64
    import json

    try:
        decoded = base64.b64decode(encoded_key).decode("utf-8")
        return json.loads(decoded)
    except ValueError as exc:
        logger.warning("Invalid pagination key: %s", exc)
        return {}
